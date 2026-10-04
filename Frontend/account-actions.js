document.addEventListener('DOMContentLoaded', () => {
    const logoutButton = document.getElementById('logout-btn');
    if (!logoutButton) return;

    const isMentor = document.body.dataset.portal === 'mentor';
    const signInPage = isMentor ? 'mentor_auth.html' : 'auth.html';
    const dialog = document.createElement('div');
    dialog.className = 'account-actions-overlay';
    dialog.hidden = true;
    dialog.innerHTML = `
        <section class="account-actions-dialog" role="dialog" aria-modal="true" aria-labelledby="account-actions-title">
            <h2 id="account-actions-title">Leave ProjectGuard?</h2>
            <p>Logout keeps your account. Delete account removes your login profile and Clerk account, while your team and roster records remain.</p>
            <p class="account-actions-error" role="alert" hidden></p>
            <div class="account-actions-buttons">
                <button type="button" class="btn account-actions-cancel">Cancel</button>
                <button type="button" class="btn btn-primary account-actions-logout">Logout</button>
                <button type="button" class="btn account-actions-delete">Delete account</button>
            </div>
        </section>`;
    document.body.append(dialog);

    const close = () => { dialog.hidden = true; };
    const showError = (message) => {
        const error = dialog.querySelector('.account-actions-error');
        error.textContent = message;
        error.hidden = false;
    };
    const setBusy = (busy) => dialog.querySelectorAll('button').forEach((button) => { button.disabled = busy; });

    logoutButton.addEventListener('click', (event) => {
        event.preventDefault();
        dialog.querySelector('.account-actions-error').hidden = true;
        dialog.hidden = false;
        dialog.querySelector('.account-actions-cancel').focus();
    });
    dialog.querySelector('.account-actions-cancel').addEventListener('click', close);
    dialog.addEventListener('click', (event) => { if (event.target === dialog) close(); });
    dialog.querySelector('.account-actions-logout').addEventListener('click', async () => {
        setBusy(true);
        try {
            const clerk = await window.projectGuardClerkReady;
            await clerk.signOut();
            window.location.replace(signInPage);
        } catch (error) {
            showError(error.message || 'Could not log out. Please try again.');
            setBusy(false);
        }
    });
    dialog.querySelector('.account-actions-delete').addEventListener('click', async () => {
        setBusy(true);
        try {
            const response = await window.projectGuardApiFetch(`${window.projectGuardApiBaseUrl}/api/account`, { method: 'DELETE' });
            const result = await response.json().catch(() => ({}));
            if (!response.ok) throw new Error(result.detail || 'Could not delete the account.');
            localStorage.removeItem(isMentor ? 'mentorName' : 'studentName');
            localStorage.removeItem(isMentor ? 'mentorPic' : 'studentPic');
            window.location.replace(signInPage);
        } catch (error) {
            showError(error.message || 'Could not delete the account. Please try again.');
            setBusy(false);
        }
    });
});
