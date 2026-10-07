// Keep dashboard content hidden until FastAPI verifies the Clerk session and
// resolves the session subject to a linked application profile.
document.documentElement.style.visibility = 'hidden';

const portalSignInPage = () => document.body.dataset.portal === 'mentor'
    ? 'mentor_auth.html'
    : 'auth.html';
const portalDestination = () => document.body.dataset.portal === 'mentor'
    ? 'mentor_index.html'
    : 'index.html';

const getSettledSessionToken = async (clerk) => {
    // Treat the active session/token as the source of truth. `isSignedIn` is a
    // convenience state flag and can briefly lag session restoration after a
    // redirect, so it must not prevent a token request.
    for (let attempt = 0; attempt < 30; attempt += 1) {
        const session = clerk.session;
        if (session && typeof session.getToken === 'function') {
            try {
                const token = await session.getToken();
                if (token) return token;
            } catch (error) {
                if (attempt === 29) throw error;
            }
        }
        await new Promise(resolve => setTimeout(resolve, 100));
    }
    return null;
};

const showSessionError = (message, actionLabel, action) => {
    document.documentElement.style.visibility = '';
    const panel = document.createElement('main');
    panel.setAttribute('role', 'alert');
    panel.style.cssText = 'max-width:36rem;margin:15vh auto;padding:2rem;font:16px/1.5 system-ui;text-align:center;background:white;border-radius:16px;color:#1f2937;box-shadow:0 12px 40px #1f293733';
    panel.innerHTML = '<h1>Portal unavailable</h1>';
    const detail = document.createElement('p');
    detail.textContent = message;
    panel.append(detail);
    if (actionLabel && action) {
        const button = document.createElement('button');
        button.type = 'button';
        button.textContent = actionLabel;
        button.style.cssText = 'padding:.7rem 1.2rem;border:0;border-radius:8px;background:#6758ef;color:#fff;cursor:pointer';
        button.addEventListener('click', action);
        panel.append(button);
    }
    document.body.replaceChildren(panel);
};

window.projectGuardSessionReady = (async () => {
    let clerk;
    try {
        clerk = await window.projectGuardClerkReady;
        const token = await getSettledSessionToken(clerk);
        if (!token) {
            console.error('No active Clerk session token on portal origin:', {
                origin: window.location.origin,
                clerkStatus: clerk.status,
                isSignedIn: clerk.isSignedIn,
                hasSession: Boolean(clerk.session),
            });
            showSessionError(
                'Clerk has no active session on this portal. Sign in again here. If you signed in on a different domain, that domain must be configured as a Clerk satellite.',
                'Sign in',
                () => {
                    const signInUrl = new URL(portalSignInPage(), window.location.href);
                    signInUrl.searchParams.set('redirect_url', portalDestination());
                    window.location.assign(signInUrl);
                },
            );
            return null;
        }

        const response = await window.projectGuardApiFetch(`${window.projectGuardApiBaseUrl}/api/me`, {
            headers: { Authorization: `Bearer ${token}` },
        });
        const profile = await response.json().catch(() => ({}));
        if (response.status === 401 || response.status === 403) {
            showSessionError(
                profile.detail || 'FastAPI rejected this Clerk session or could not find its linked application profile.',
                'Sign in again',
                async () => {
                    try {
                        await clerk.signOut();
                    } finally {
                        window.location.assign(portalSignInPage());
                    }
                },
            );
            return null;
        }
        if (!response.ok) {
            throw new Error(profile.detail || 'The server could not verify your application profile.');
        }

        const expectedRole = document.body.dataset.portal || 'student';
        if (profile.role !== expectedRole) {
            const correctPortal = profile.role === 'mentor' ? 'mentor_index.html' : 'index.html';
            showSessionError(
                `This account is linked as a ${profile.role} and cannot open the ${expectedRole} portal.`,
                'Open matching portal',
                () => window.location.assign(correctPortal),
            );
            return null;
        }

        window.projectGuardProfile = profile;
        document.documentElement.style.visibility = '';
        return clerk;
    } catch (error) {
        console.error('Could not verify Clerk session with FastAPI:', error);
        showSessionError(error.message || 'We could not verify your Clerk session with the server. Check the API connection and try again.');
        return null;
    }
})();
