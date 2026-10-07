document.addEventListener('DOMContentLoaded', async () => {
    const isMentor = document.body.dataset.portal === 'mentor';
    const loginForm = document.getElementById('login-form');
    const signupForm = document.getElementById('signup-form');
    const authTitle = document.getElementById('auth-title');
    const authSubtitle = document.getElementById('auth-subtitle');
    const showSignup = document.getElementById('show-signup');
    const showLogin = document.getElementById('show-login');
    document.querySelectorAll('[data-password-toggle]').forEach((toggle) => {
        toggle.addEventListener('click', () => {
            const input = document.getElementById(toggle.dataset.passwordToggle);
            const showing = input.type === 'password';
            input.type = showing ? 'text' : 'password';
            toggle.setAttribute('aria-pressed', String(showing));
            toggle.setAttribute('aria-label', showing ? 'Hide password' : 'Show password');
            toggle.querySelector('i').className = showing ? 'ph ph-eye-slash' : 'ph ph-eye';
        });
    });
    const destination = isMentor ? 'mentor_index.html' : 'index.html';
    const returnTo = new URLSearchParams(window.location.search).get('redirect_url');
    const targetPage = returnTo === destination ? returnTo : destination;
    let completingEnrollment = false;
    let currentSignupPassword = null;
    const showEnrollment = () => {
        completingEnrollment = true;
        loginForm.style.display = 'none';
        signupForm.style.display = 'block';
        authTitle.textContent = 'Complete enrollment';
        authSubtitle.textContent = 'Correct your enrollment details. Leave password blank to keep it, or enter a new password.';
        document.getElementById('current-password-group').hidden = false;
        for (const id of ['signup-pass', isMentor ? 'signup-confirm-pass' : 'confirm-pass']) {
            const input = document.getElementById(id);
            input.required = false;
            input.closest('.form-group').style.display = '';
            input.value = '';
        }
        signupForm.querySelector('button[type=submit] span').textContent = 'Complete enrollment';
    };
    const expectedRole = isMentor ? 'mentor' : 'student';
    const showAuthError = (form, message) => {
        let error = form.querySelector('[role="alert"]');
        if (!error) {
            error = document.createElement('p');
            error.setAttribute('role', 'alert');
            error.className = 'upload-error';
            form.insertBefore(error, form.querySelector('.auth-switch'));
        }
        error.textContent = message;
    };

    const clerkErrorMessage = (error) => {
        const messages = error?.errors?.map((item) => item.longMessage || item.message).filter(Boolean);
        return messages?.join('\n') || error?.message || 'Authentication failed. Please try again.';
    };

    const formatClerkFields = (fields) => fields
        .map((field) => ({
            email_address: 'email address',
            phone_number: 'phone number',
            first_name: 'first name',
            last_name: 'last name',
        })[field] || field.replaceAll('_', ' '))
        .join(', ');

    const linkProfileToPostgres = async (clerk, profile) => {
        const token = await clerk.session?.getToken();
        if (!token) {
            throw new Error('Clerk signed you in, but no session token was available to save your profile.');
        }

        const response = await window.projectGuardApiFetch(`${window.projectGuardApiBaseUrl}/api/profile/link`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                Authorization: `Bearer ${token}`,
            },
            body: JSON.stringify(profile),
        });
        const result = await response.json().catch(() => ({}));
        if (!response.ok) {
            const error = new Error(result.detail || 'Could not save your application profile.');
            error.status = response.status;
            throw error;
        }
        return result;
    };

    const getLinkedProfile = async (clerk) => {
        const response = await window.projectGuardApiFetch(`${window.projectGuardApiBaseUrl}/api/me`);
        const profile = await response.json().catch(() => ({}));
        if (!response.ok) {
            const error = new Error(profile.detail || 'Could not verify your Project Guard profile.');
            error.status = response.status;
            if (response.status === 401) {
                await clerk.signOut();
            }
            throw error;
        }
        if (!['student', 'mentor'].includes(profile.role)) {
            throw new Error('The server returned an invalid Project Guard profile.');
        }
        return profile;
    };

    const requirePortalRole = async (clerk, profile) => {
        if (profile.role !== expectedRole) {
            await clerk.signOut();
            const error = new Error(`This account is linked as a ${profile.role}. Please sign in through the ${profile.role} portal.`);
            error.portalRoleMismatch = true;
            throw error;
        }
        return profile;
    };

    const setBusy = (form, busy, label) => {
        const button = form.querySelector('button[type="submit"]');
        if (!button) return;
        button.disabled = busy;
        const span = button.querySelector('span');
        if (span) {
            if (busy) {
                button.dataset.originalLabel = span.textContent;
                span.textContent = label;
            } else if (button.dataset.originalLabel) {
                span.textContent = button.dataset.originalLabel;
                delete button.dataset.originalLabel;
            }
        }
    };

    const blockSubmitUntilReady = (event) => event.preventDefault();
    for (const form of [loginForm, signupForm]) {
        form.addEventListener('submit', blockSubmitUntilReady);
        setBusy(form, true, 'Connecting...');
    }

    showSignup.addEventListener('click', (event) => {
        event.preventDefault();
        loginForm.style.display = 'none';
        signupForm.style.display = 'block';
        authTitle.textContent = 'Create Account';
        authSubtitle.textContent = isMentor ? 'Enter your details to register' : 'Register your team to get started';
    });

    showLogin.addEventListener('click', (event) => {
        event.preventDefault();
        signupForm.style.display = 'none';
        loginForm.style.display = 'block';
        authTitle.textContent = 'Welcome Back';
        authSubtitle.textContent = 'Please Enter your details to continue';
    });

    try {
        const clerk = await window.projectGuardClerkReady;
        const sessionNotice = document.createElement('p');
        sessionNotice.className = 'active-session-notice';
        sessionNotice.setAttribute('role', 'status');
        const sessionLabel = document.createElement('span');
        const switchAccount = document.createElement('button');
        switchAccount.type = 'button';
        switchAccount.textContent = 'Logout';
        switchAccount.className = 'session-logout';
        switchAccount.addEventListener('click', async () => {
            switchAccount.disabled = true;
            try {
                await clerk.signOut();
                window.location.reload();
            } catch (error) {
                showAuthError(signupForm, clerkErrorMessage(error));
                switchAccount.disabled = false;
            }
        });
        sessionNotice.append(sessionLabel, switchAccount);
        loginForm.insertBefore(sessionNotice, loginForm.querySelector('.auth-switch'));
        const updateSessionNotice = () => {
            sessionNotice.hidden = !clerk.session;
            sessionLabel.textContent = 'You have an active session. Log out to use another account.';
        };
        updateSessionNotice();
        if (clerk.session) {
            try {
                await requirePortalRole(clerk, await getLinkedProfile(clerk));
                window.location.replace(targetPage);
                return;
            } catch (error) {
                if (error.portalRoleMismatch) {
                    showAuthError(loginForm, error.message);
                } else if (error.status === 403 && clerk.session) {
                    showEnrollment();
                } else if (error.status === 401 || error.status === 403) {
                    showAuthError(loginForm, error.message);
                } else {
                    throw error;
                }
            }
        }

        for (const form of [loginForm, signupForm]) {
            form.removeEventListener('submit', blockSubmitUntilReady);
            setBusy(form, false);
        }

        loginForm.addEventListener('submit', async (event) => {
            event.preventDefault();
            setBusy(loginForm, true, 'Logging in...');
            try {
                const identifier = document.getElementById('login-roll').value.trim();
                const password = document.getElementById('login-pass').value;
                const attempt = await clerk.client.signIn.create({
                    identifier,
                    password,
                    strategy: 'password',
                });
                if (attempt.status !== 'complete') {
                    const missing = attempt.supportedSecondFactors?.map((factor) => factor.strategy).join(', ');
                    throw new Error(missing
                        ? `Clerk requires another sign-in step: ${missing}.`
                        : `Clerk sign-in needs another step (${attempt.status}).`);
                }
                await clerk.setActive({ session: attempt.createdSessionId });
                await requirePortalRole(clerk, await getLinkedProfile(clerk));
                window.location.assign(targetPage);
            } catch (error) {
                if (error.status === 403 && clerk.session) {
                    showEnrollment();
                } else if (error.portalRoleMismatch) {
                    showAuthError(loginForm, error.message);
                } else {
                    showAuthError(loginForm, clerkErrorMessage(error));
                }
                setBusy(loginForm, false);
            }
        });

        signupForm.addEventListener('submit', async (event) => {
            event.preventDefault();
            const password = document.getElementById('signup-pass').value;
            const confirmPassword = document.getElementById(isMentor ? 'signup-confirm-pass' : 'confirm-pass').value;
            if (password !== confirmPassword) {
                showAuthError(signupForm, 'Passwords do not match.');
                return;
            }

            setBusy(signupForm, true, 'Creating account...');
            try {
                const username = isMentor
                    ? document.getElementById('signup-id').value.trim()
                    : document.getElementById('roll-1').value.trim();
                const studentYear = isMentor ? null : document.getElementById('year').value.trim();
                updateSessionNotice();
                if (clerk.session && clerk.user?.username && clerk.user.username.toLowerCase() !== username.toLowerCase()) {
                    throw new Error('You have an active session for another account. Open Login and click Logout before creating this account.');
                }
                const recoveringSession = Boolean(clerk.session);
                const attempt = recoveringSession
                    ? { status: 'complete' }
                    : await clerk.client.signUp.create({ username, password });
                if (attempt.status !== 'complete') {
                    const missingFields = attempt.missingFields?.length
                        ? formatClerkFields(attempt.missingFields)
                        : '';
                    const unverifiedFields = attempt.unverifiedFields?.length
                        ? formatClerkFields(attempt.unverifiedFields)
                        : '';
                    const missing = [missingFields && `missing ${missingFields}`, unverifiedFields && `unverified ${unverifiedFields}`]
                        .filter(Boolean)
                        .join('; ');
                    throw new Error(missing
                        ? `Clerk sign-up is not complete: ${missing}. This form collects a username and password only. To keep it that way, make email optional in this Clerk application's sign-up requirements.`
                        : `Clerk sign-up needs another step (${attempt.status}).`);
                }
                if (attempt.createdSessionId) {
                    await clerk.setActive({ session: attempt.createdSessionId });
                    currentSignupPassword = password;
                }
                updateSessionNotice();
                if (recoveringSession && password) {
                    const currentPassword = document.getElementById('enrollment-current-password').value || currentSignupPassword;
                    if (clerk.user.hasPassword && !currentPassword) throw new Error('Enter your current password to choose a new password.');
                    await clerk.user.updatePassword({ newPassword: password, ...(currentPassword ? { currentPassword } : {}) });
                    currentSignupPassword = password;
                    document.getElementById('enrollment-current-password').value = '';
                }
                await linkProfileToPostgres(clerk, isMentor
                    ? { role: 'mentor', mentor_name: username, enrollment_code: document.getElementById('enrollment-code').value.trim() }
                    : { role: 'student', roll_no: username, year: studentYear, enrollment_code: document.getElementById('enrollment-code').value.trim() });
                window.location.assign(targetPage);
            } catch (error) {
                updateSessionNotice();
                const detail = clerkErrorMessage(error);
                const profileConflict = error.status === 409 && /PostgreSQL|already linked|already exists/i.test(detail);
                if (clerk.session) showEnrollment();
                showAuthError(signupForm, profileConflict
                    ? `${detail} If this is your existing test account, ask an administrator to link the PostgreSQL profile to your Clerk user. For a stale test-only profile, an administrator must confirm and remove the row before you retry.`
                    : detail);
                setBusy(signupForm, false);
            }
        });
    } catch (error) {
        console.error('Could not initialize Clerk:', error);
        authSubtitle.textContent = 'Sign-in could not finish loading. Refresh the page to retry.';
        const detail = error?.message || 'Unknown Clerk initialization error.';
        for (const form of [loginForm, signupForm]) {
            setBusy(form, false);
            form.querySelectorAll('button[type="submit"]').forEach((button) => {
                button.disabled = true;
            });
            showAuthError(form, `Sign-in initialization failed: ${detail}`);
        }
    }
});
