document.addEventListener('DOMContentLoaded', () => {
    const loginForm = document.getElementById('login-form');
    const signupForm = document.getElementById('signup-form');
    const authTitle = document.getElementById('auth-title');
    const authSubtitle = document.getElementById('auth-subtitle');
    const showSignup = document.getElementById('show-signup');
    const showLogin = document.getElementById('show-login');

    // Switch to Signup
    showSignup.addEventListener('click', (e) => {
        e.preventDefault();
        loginForm.style.display = 'none';
        signupForm.style.display = 'block';
        authTitle.textContent = 'Create Account';
        authSubtitle.textContent = 'Enter your details to register';
    });

    // Switch to Login
    showLogin.addEventListener('click', (e) => {
        e.preventDefault();
        signupForm.style.display = 'none';
        loginForm.style.display = 'block';
        authTitle.textContent = 'Welcome Back';
        authSubtitle.textContent = 'Please Enter your details to continue';
    });

    // Handle Login 
    loginForm.addEventListener('submit', async (e) => {
        e.preventDefault();
        const btn = loginForm.querySelector('button');
        const span = btn.querySelector('span');
        const originalText = span.textContent;
        
        const username = document.getElementById('login-roll').value.trim();
        const password = document.getElementById('login-pass').value;

        span.textContent = 'Logging in...';
        btn.disabled = true;

        try {
            const response = await fetch('http://localhost:8000/mentor/login', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({
                    username: username,
                    password: password
                })
            });

            const data = await response.json();

            if (response.ok) {
                // Store mentor session
                localStorage.setItem('mentorUser', data.username);
                window.location.href = 'mentor_index.html';
            } else {
                alert(data.detail || 'Login failed');
                span.textContent = originalText;
                btn.disabled = false;
            }
        } catch (error) {
            console.error('Login error:', error);
            alert('Network error. Please try again.');
            span.textContent = originalText;
            btn.disabled = false;
        }
    });

    // Handle Signup 
    signupForm.addEventListener('submit', async (e) => {
        e.preventDefault();
        const btn = signupForm.querySelector('button');
        const span = btn.querySelector('span');
        const originalText = span.textContent;

        const username = document.getElementById('signup-id').value.trim();
        const password = document.getElementById('signup-pass').value;
        const confirmPassword = document.getElementById('signup-confirm-pass').value;

        if (password !== confirmPassword) {
            alert('Passwords do not match!');
            return;
        }

        span.textContent = 'Creating account...';
        btn.disabled = true;

        try {
            const response = await fetch('http://localhost:8000/mentor/signup', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({
                    username: username,
                    password: password
                })
            });

            const data = await response.json();

            if (response.ok) {
                alert('Account created successfully! You can now login.');
                document.getElementById('login-roll').value = username;
                showLogin.click();
            } else {
                alert(data.detail || 'Signup failed');
            }
        } catch (error) {
            console.error('Signup error:', error);
            alert('Network error. Please try again.');
        }

        span.textContent = originalText;
        btn.disabled = false;
    });
});
