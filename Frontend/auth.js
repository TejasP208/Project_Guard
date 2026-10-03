document.addEventListener('DOMContentLoaded', async () => {
    const isMentor = document.body.dataset.portal === 'mentor';
    const loginForm = document.getElementById('login-form');
    const signupForm = document.getElementById('signup-form');
    const authTitle = document.getElementById('auth-title');
    const authSubtitle = document.getElementById('auth-subtitle');
    const showSignup = document.getElementById('show-signup');
    const showLogin = document.getElementById('show-login');
    const destination = isMentor ? 'mentor_index.html' : 'index.html';

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
            throw new Error(result.detail || 'Could not save your application profile.');
        }
        return result;
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
        if (clerk.isSignedIn) {
            window.location.replace(destination);
            return;
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
                window.location.assign(destination);
            } catch (error) {
                showAuthError(loginForm, clerkErrorMessage(error));
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
                const attempt = await clerk.client.signUp.create({ username, password });
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
                await clerk.setActive({ session: attempt.createdSessionId });
                await linkProfileToPostgres(clerk, isMentor
                    ? { role: 'mentor', mentor_name: username }
                    : { role: 'student', roll_no: username, year: studentYear });
                window.location.assign(destination);
            } catch (error) {
                showAuthError(signupForm, clerkErrorMessage(error));
                setBusy(signupForm, false);
            }
        });
    } catch (error) {
        console.error('Could not initialize Clerk:', error);
        authSubtitle.textContent = 'Sign-in is temporarily unavailable. Please refresh and try again.';
        for (const form of [loginForm, signupForm]) {
            setBusy(form, false);
            form.querySelectorAll('button[type="submit"]').forEach((button) => {
                button.disabled = true;
            });
            showAuthError(form, 'Could not connect to Clerk. Check that the FastAPI server is running and refresh this page.');
        }
    }
});
