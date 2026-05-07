const API_BASE = window.location.origin;

function getSafeNextPath() {
  const next = new URLSearchParams(window.location.search).get('next');
  if (!next) return 'index.html';
  if (/^https?:\/\//i.test(next) || next.startsWith('//')) return 'index.html';
  return next;
}

function syncCsrfToken() {
  if (typeof BDA !== 'undefined' && typeof BDA.syncCsrfTokenFromCookie === 'function') {
    return BDA.syncCsrfTokenFromCookie();
  }

  const match = document.cookie.match(/(?:^|;\s*)csrf_token=([^;]+)/);
  const input = document.getElementById('csrf_token');
  const token = match ? decodeURIComponent(match[1]) : '';
  if (match) {
    if (input) input.value = token;
  }

  return token || (input ? input.value : '');
}

syncCsrfToken();

// Check if already logged in
document.addEventListener('DOMContentLoaded', () => {
  const token = localStorage.getItem('access_token');
  if (token) {
    // Verify token is still valid
    fetch(`${API_BASE}/api/auth/me`, {
      headers: {
        'Authorization': `Bearer ${token}`
      }
    })
    .then(res => {
      if (res.ok) {
        // Already logged in, redirect to requested page if available
        window.location.href = getSafeNextPath();
      } else if (typeof Auth.clearSession === 'function') {
        Auth.clearSession();
      }
    })
    .catch(() => {
      if (typeof Auth.clearSession === 'function') {
        Auth.clearSession();
      }
    });
  }
});

// Password validation
const passwordInput = document.getElementById('password');
const confirmInput = document.getElementById('confirm_password');

passwordInput.addEventListener('input', validatePassword);
confirmInput.addEventListener('input', validatePassword);

function validatePassword() {
  const password = passwordInput.value;
  const confirm = confirmInput.value;

  // Check requirements
  document.getElementById('req-length').className = password.length >= 8 ? 'met' : 'unmet';
  document.getElementById('req-upper').className = /[A-Z]/.test(password) ? 'met' : 'unmet';
  document.getElementById('req-lower').className = /[a-z]/.test(password) ? 'met' : 'unmet';
  document.getElementById('req-number').className = /\d/.test(password) ? 'met' : 'unmet';

  // Check match
  if (confirm && password !== confirm) {
    confirmInput.classList.add('error');
  } else {
    confirmInput.classList.remove('error');
  }
}

// Handle form submission
document.getElementById('register-form').addEventListener('submit', async (e) => {
  e.preventDefault();

  const submitBtn = document.getElementById('submit-btn');
  const errorAlert = document.getElementById('error-alert');
  const successAlert = document.getElementById('success-alert');

  // Clear previous alerts
  errorAlert.classList.remove('visible');
  successAlert.classList.remove('visible');

  // Get values
  const display_name = document.getElementById('display_name').value.trim();
  const email = document.getElementById('email').value.trim();
  const password = passwordInput.value;
  const confirm_password = confirmInput.value;

  function markInvalid() {
    document.getElementById('display_name').setAttribute('aria-invalid', 'true');
    document.getElementById('email').setAttribute('aria-invalid', 'true');
    document.getElementById('password').setAttribute('aria-invalid', 'true');
    document.getElementById('confirm_password').setAttribute('aria-invalid', 'true');
  }

  // Client-side validation
  if (password !== confirm_password) {
    errorAlert.textContent = 'Passwords do not match.';
    errorAlert.classList.add('visible');
    confirmInput.classList.add('error');
    markInvalid();
    return;
  }

  if (password.length < 8) {
    errorAlert.textContent = 'Password must be at least 8 characters long.';
    errorAlert.classList.add('visible');
    markInvalid();
    return;
  }

  if (!/[A-Z]/.test(password) || !/[a-z]/.test(password) || !/\d/.test(password)) {
    errorAlert.textContent = 'Password does not meet all requirements.';
    errorAlert.classList.add('visible');
    markInvalid();
    return;
  }

  // Show loading state
  submitBtn.disabled = true;
  submitBtn.innerHTML = '<span class="loading-spinner"></span>Creating account...';

  try {
    const csrfToken = syncCsrfToken();
    const response = await fetch(`${API_BASE}/api/auth/register`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-CSRF-Token': csrfToken
      },
      body: JSON.stringify({ display_name, email, password })
    });

    const data = await response.json();

    if (response.ok) {
      // Save token and user info
      localStorage.setItem('access_token', data.access_token);
      localStorage.setItem('user', JSON.stringify({
        user_id: data.user_id,
        email: data.email,
        display_name: data.display_name,
        is_admin: data.is_admin
      }));

      // Show success message
      successAlert.textContent = 'Account created successfully! Redirecting...';
      successAlert.classList.add('visible');

      // Redirect to requested page if available
      setTimeout(() => {
        window.location.href = getSafeNextPath();
      }, 1500);
    } else {
      // Show error
      errorAlert.textContent = data.error || 'Registration failed. Please try again.';
      errorAlert.classList.add('visible');
      markInvalid();
      submitBtn.disabled = false;
      submitBtn.textContent = 'Create Account';
    }
  } catch (error) {
    console.error('Registration error:', error);
    errorAlert.textContent = 'Network error. Please try again.';
    errorAlert.classList.add('visible');
    markInvalid();
    submitBtn.disabled = false;
    submitBtn.textContent = 'Create Account';
  }
});
