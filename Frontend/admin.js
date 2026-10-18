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
            const response = await window.projectGuardApiFetch(`${window.projectGuardApiBaseUrl}/api/admin${path}`, options);
            const body = await response.json().catch(() => ({}));
            if (!response.ok) throw new Error(body.detail || 'Could not complete the request.');
            return body;
        };
        let selectedRole = 'student';
        let records = [];
        let accounts = [];
        let codeClearTimer;
        const clearIssuedCode = () => {
            clearTimeout(codeClearTimer);
            document.getElementById('code').textContent = '';
            document.getElementById('issued').hidden = true;
        };
        const renderEnrollments = () => {
            const rows = document.getElementById('rows');
            rows.replaceChildren();
            const visible = records.filter(record => record.role === selectedRole);
            visible.forEach(record => {
                const row = document.createElement('tr');
                const expired = record.expires_at * 1000 <= Date.now();
                const status = record.used_at ? 'Used' : record.revoked_at ? 'Revoked' : expired ? 'Expired' : 'Available';
                const verificationLabels = {
                    official_roster: 'Official records',
                    institutional_contact: 'Institutional contact',
                    in_person: 'In person with ID'
                };
                for (const value of [record.id, record.role, record.roll_no, record.year,
                    new Date(record.expires_at * 1000).toLocaleString(), status,
                    record.issued_by_clerk_user_id || 'Legacy',
                    verificationLabels[record.verification_method] || 'Not recorded']) {
                    const cell = document.createElement('td'); cell.textContent = String(value); row.append(cell);
                }
                const action = document.createElement('td');
                if (status === 'Available') {
                    const button = document.createElement('button'); button.textContent = 'Revoke';
                    button.onclick = async () => {
                        button.disabled = true;
                        try { await request(`/enrollments/${record.id}/revoke`, { method: 'POST' }); await refresh(); }
                        catch (error) { report(error); button.disabled = false; }
                    };
                    action.append(button);
                }
                row.append(action); rows.append(row);
            });
            if (!visible.length) {
                const row = document.createElement('tr');
                const cell = document.createElement('td'); cell.colSpan = 9;
                cell.textContent = `No ${selectedRole} enrollment codes found.`; row.append(cell); rows.append(row);
            }
        };
        const refresh = async () => {
            records = await request('/enrollments');
            renderEnrollments();
        };
        await refresh(); // Server authorization succeeds before showing admin controls.
        document.getElementById('admin').hidden = false;
        const roleSelect = document.getElementById('enrollment-role');
        roleSelect.onchange = () => {
            const mentor = roleSelect.value === 'mentor';
            document.getElementById('identifier-label').textContent = mentor ? 'Mentor name' : 'Roll number';
            document.getElementById('year-field').hidden = mentor;
            document.querySelector('[name=year]').required = !mentor;
        };
        roleSelect.onchange();
        const renderAccounts = () => {
            const rows = document.getElementById('accounts');
            rows.replaceChildren();
            const visible = accounts.filter(account => account.role === selectedRole);
            visible.forEach(account => {
                const row = document.createElement('tr');
                for (const value of [account.role, account.identifier]) {
                    const cell = document.createElement('td'); cell.textContent = value; row.append(cell);
                }
                const cell = document.createElement('td');
                const button = document.createElement('button'); button.textContent = 'Delete account';
                button.onclick = async () => {
                    if (!await window.projectGuardFeedback.confirm(`Delete ${account.role} account ${account.identifier}? This permanently removes the login and profile.`, {
                        title: 'Delete account', confirmLabel: 'Delete account'
                    })) return;
                    button.disabled = true;
                    try {
                        await request(`/accounts/${account.role}/${account.id}`, { method: 'DELETE' });
                        message.textContent = 'Account deleted.';
                        await refreshAccounts();
                    } catch (error) { report(error); button.disabled = false; }
                };
                cell.append(button); row.append(cell); rows.append(row);
            });
            if (!visible.length) {
                const row = document.createElement('tr');
                const cell = document.createElement('td'); cell.colSpan = 3;
                cell.textContent = `No ${selectedRole} accounts found.`; row.append(cell); rows.append(row);
            }
        };
        const refreshAccounts = async () => {
            accounts = await request('/accounts');
            renderAccounts();
        };
        document.querySelectorAll('[data-portal-role]').forEach(button => {
            button.onclick = () => {
                selectedRole = button.dataset.portalRole;
                roleSelect.value = selectedRole;
                roleSelect.onchange();
                document.querySelectorAll('[data-portal-role]').forEach(item => item.setAttribute('aria-pressed', String(item === button)));
                document.getElementById('portal-summary').textContent = `Manage ${selectedRole} accounts and enrollment codes.`;
                const label = selectedRole === 'mentor' ? 'Mentor' : 'Student';
                document.getElementById('issue-title').textContent = `Create ${selectedRole} enrollment code`;
                document.getElementById('enrollments-title').textContent = `${label} enrollment codes`;
                document.getElementById('accounts-title').textContent = `${label} accounts`;
                clearIssuedCode();
                document.querySelector('[name=roll_no]').value = '';
                document.querySelector('[name=year]').value = '';
                message.textContent = '';
                renderEnrollments();
                renderAccounts();
            };
        });
        document.getElementById('refresh-accounts').onclick = () => refreshAccounts().catch(report);
        await refreshAccounts();
        document.getElementById('refresh').onclick = () => refresh().catch(report);
        document.getElementById('issue').onsubmit = async event => {
            event.preventDefault();
            const button = event.target.querySelector('button'); button.disabled = true;
            clearIssuedCode();
            message.textContent = '';
            try {
                const fields = new FormData(event.target);
                const grant = await request('/enrollments', { method: 'POST', headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ role: fields.get('role'), roll_no: fields.get('roll_no'),
                        year: roleSelect.value === 'mentor' ? '' : fields.get('year'),
                        expires_hours: Number(fields.get('expires_hours')),
                        verification_method: fields.get('verification_method'),
                        recipient_verified: fields.get('recipient_verified') === 'on' }) });
                document.getElementById('code').textContent = grant.code;
                document.getElementById('issued').hidden = false;
                codeClearTimer = setTimeout(() => {
                    clearIssuedCode();
                    message.textContent = 'The enrollment code was hidden after five minutes. Issue a new code if needed.';
                }, 5 * 60 * 1000);
                await refresh();
            } catch (error) { report(error); }
            finally {
                button.disabled = false;
                event.target.elements.recipient_verified.checked = false;
            }
        };
        document.getElementById('copy').onclick = async () => {
            if (!document.getElementById('code').textContent) {
                message.textContent = 'The enrollment code is no longer displayed.';
                return;
            }
            try { await navigator.clipboard.writeText(document.getElementById('code').textContent); message.textContent = 'Code copied.'; }
            catch { message.textContent = 'Select the code and copy it manually.'; }
        };
    } catch (error) { report(error); }
});
