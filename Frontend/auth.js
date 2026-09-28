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
        authSubtitle.textContent = 'Register your team to get started';
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
        
        span.textContent = 'Logging in...';
        btn.disabled = true;

        const rollNo = document.getElementById('login-roll').value.trim();
        const password = document.getElementById('login-pass').value;

        try {
            const response = await fetch('http://localhost:8000/login', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({
                    roll_no: rollNo,
                    password: password
                })
            });

            const data = await response.json();

            if (response.ok) {
                // Store login info in localStorage
                localStorage.setItem('loggedInUser', rollNo);
                localStorage.removeItem('loggedInTeam'); // Clear any legacy data
                window.location.href = 'index.html';
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
        
        const password = document.getElementById('signup-pass').value;
        const confirmPass = document.getElementById('confirm-pass').value;

        // Validate passwords match
        if (password !== confirmPass) {
            alert('Passwords do not match!');
            return;
        }

        span.textContent = 'Creating account...';
        btn.disabled = true;

        const formData = {
            roll_no: document.getElementById('roll-1').value.trim(),
            year: document.getElementById('year').value.trim(),
            password: password
        };

        try {
            const response = await fetch('http://localhost:8000/signup', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify(formData)
            });

            const data = await response.json();

            if (response.ok) {
                alert('Account created successfully! You can now login.');
                showLogin.click();
            } else {
                alert(data.detail || 'Signup failed');
            }
        } catch (error) {
            console.error('Signup error:', error);
            alert('Network error. Please try again.');
        }

        span.textContent = 'Create Account';
        btn.disabled = false;
    });
});
