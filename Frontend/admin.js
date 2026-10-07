document.addEventListener('DOMContentLoaded', async () => {
    const message = document.getElementById('message');
    const report = error => { message.textContent = error.message || 'Request failed.'; };
    try {
        const clerk = await window.projectGuardClerkReady;
        if (!clerk.session) {
            clerk.mountSignIn(document.getElementById('signin'), { forceRedirectUrl: window.location.href });
            return;
        }
        document.getElementById('signout').hidden = false;
        document.getElementById('signout').onclick = async () => { await clerk.signOut(); window.location.reload(); };
        const request = async (path, options = {}) => {
            const response = await window.projectGuardApiFetch(`${window.projectGuardApiBaseUrl}/api/admin/enrollments${path}`, options);
            const body = await response.json().catch(() => ({}));
            if (!response.ok) throw new Error(body.detail || 'Could not complete the request.');
            return body;
        };
        const refresh = async () => {
            const records = await request('');
            const rows = document.getElementById('rows');
            rows.replaceChildren();
            records.forEach(record => {
                const row = document.createElement('tr');
                const expired = record.expires_at * 1000 <= Date.now();
                const status = record.used_at ? 'Used' : record.revoked_at ? 'Revoked' : expired ? 'Expired' : 'Available';
                for (const value of [record.id, record.roll_no, record.year, new Date(record.expires_at * 1000).toLocaleString(), status]) {
                    const cell = document.createElement('td'); cell.textContent = String(value); row.append(cell);
                }
                const action = document.createElement('td');
                if (status === 'Available') {
                    const button = document.createElement('button'); button.textContent = 'Revoke';
                    button.onclick = async () => {
                        button.disabled = true;
                        try { await request(`/${record.id}/revoke`, { method: 'POST' }); await refresh(); }
                        catch (error) { report(error); button.disabled = false; }
                    };
                    action.append(button);
                }
                row.append(action); rows.append(row);
            });
        };
        await refresh(); // Server authorization succeeds before showing admin controls.
        document.getElementById('admin').hidden = false;
        document.getElementById('refresh').onclick = () => refresh().catch(report);
        document.getElementById('issue').onsubmit = async event => {
            event.preventDefault();
            const button = event.target.querySelector('button'); button.disabled = true;
            document.getElementById('issued').hidden = true;
            document.getElementById('code').textContent = '';
            message.textContent = '';
            try {
                const fields = new FormData(event.target);
                const grant = await request('', { method: 'POST', headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ roll_no: fields.get('roll_no'), year: fields.get('year'), expires_hours: Number(fields.get('expires_hours')) }) });
                document.getElementById('code').textContent = grant.code;
                document.getElementById('issued').hidden = false;
                await refresh();
            } catch (error) { report(error); }
            finally { button.disabled = false; }
        };
        document.getElementById('copy').onclick = async () => {
            try { await navigator.clipboard.writeText(document.getElementById('code').textContent); message.textContent = 'Code copied.'; }
            catch { message.textContent = 'Select the code and copy it manually.'; }
        };
    } catch (error) { report(error); }
});
