// Keep dashboard content hidden until FastAPI verifies the Clerk session and
// resolves the session subject to a linked application profile.
document.documentElement.style.visibility = 'hidden';

const portalSignInPage = () => document.body.dataset.portal === 'mentor'
    ? 'mentor_auth.html'
    : 'auth.html';

const showSessionError = (message) => {
    document.documentElement.style.visibility = '';
    const panel = document.createElement('main');
    panel.setAttribute('role', 'alert');
    panel.style.cssText = 'max-width:36rem;margin:15vh auto;padding:2rem;font:16px/1.5 system-ui;text-align:center;background:white;border-radius:16px;color:#1f2937;box-shadow:0 12px 40px #1f293733';
    panel.innerHTML = '<h1>Portal unavailable</h1>';
    const detail = document.createElement('p');
    detail.textContent = message;
    panel.append(detail);
    const reload = document.createElement('button');
    reload.type = 'button';
    reload.textContent = 'Try again';
    reload.style.cssText = 'padding:.7rem 1.2rem;border:0;border-radius:8px;background:#6758ef;color:#fff;cursor:pointer';
    reload.addEventListener('click', () => window.location.reload());
    panel.append(reload);
    document.body.replaceChildren(panel);
};

window.projectGuardSessionReady = (async () => {
    let clerk;
    try {
        clerk = await window.projectGuardClerkReady;
        if (!clerk.isSignedIn) {
            window.location.replace(portalSignInPage());
            return null;
        }

        const token = await clerk.session?.getToken();
        if (!token) throw new Error('Clerk did not provide a session token.');

        const response = await window.projectGuardApiFetch(`${window.projectGuardApiBaseUrl}/api/me`, {
            headers: { Authorization: `Bearer ${token}` },
        });
        const profile = await response.json().catch(() => ({}));
        if (response.status === 401 || response.status === 403) {
            await clerk.signOut();
            window.location.replace(portalSignInPage());
            return null;
        }
        if (!response.ok) {
            throw new Error(profile.detail || 'The server could not verify your application profile.');
        }

        const expectedRole = document.body.dataset.portal;
        if (profile.role !== expectedRole) {
            window.location.replace(profile.role === 'mentor' ? 'mentor_index.html' : 'index.html');
            return null;
        }

        window.projectGuardProfile = profile;
        document.documentElement.style.visibility = '';
        return clerk;
    } catch (error) {
        console.error('Could not verify Clerk session with FastAPI:', error);
        showSessionError('We could not verify your Clerk session with the server. Check that the API is running, then try again.');
        return null;
    }
})();
