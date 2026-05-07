const API_BASE = window.location.origin;

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

const LOGIN_REASON_MESSAGES = {
  'auth-required': 'Please sign in to continue.',
  'session-expired': 'Your session expired. Please sign in again.',
  'appeals-login-required': 'Please sign in to access Appeals.',
  'admin-login-required': 'Please sign in to access Admin tools.',
  'admin-forbidden': 'This account is signed in, but does not have admin permission.',
  'logged-out': 'You have been logged out successfully.',
};

function getSafeNextPath() {
  const next = new URLSearchParams(window.location.search).get('next');
  if (!next) return 'index.html';
  if (/^https?:\/\//i.test(next) || next.startsWith('//')) return 'index.html';
  return next;
}

// Check if already logged in
document.addEventListener('DOMContentLoaded', () => {
  const reason = new URLSearchParams(window.location.search).get('reason');
  const reasonMessage = LOGIN_REASON_MESSAGES[reason || ''];
  if (reasonMessage) {
    const errorAlert = document.getElementById('error-alert');
    errorAlert.textContent = reasonMessage;
    errorAlert.classList.add('visible');
  }

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
        // Already logged in, continue to intended destination
        window.location.href = getSafeNextPath();
      } else {
        // Token expired, clear it
        if (typeof Auth.clearSession === 'function') {
          Auth.clearSession();
        } else {
          localStorage.removeItem('access_token');
          localStorage.removeItem('user');
        }
      }
    })
    .catch(() => {
      // Error checking, clear token
      if (typeof Auth.clearSession === 'function') {
        Auth.clearSession();
      } else {
        localStorage.removeItem('access_token');
        localStorage.removeItem('user');
      }
    });
  }
});

// Handle form submission
document.getElementById('login-form').addEventListener('submit', async (e) => {
  e.preventDefault();

  const submitBtn = document.getElementById('submit-btn');
  const errorAlert = document.getElementById('error-alert');
  const successAlert = document.getElementById('success-alert');

  // Clear previous alerts
  errorAlert.classList.remove('visible');
  successAlert.classList.remove('visible');

  // Show loading state
  submitBtn.disabled = true;
  submitBtn.innerHTML = '<span class="loading-spinner"></span>Signing in...';

  const email = document.getElementById('email').value.trim();
  const password = document.getElementById('password').value;

  try {
    const csrfToken = syncCsrfToken();
    const response = await fetch(`${API_BASE}/api/auth/login`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-CSRF-Token': csrfToken
      },
      body: JSON.stringify({ email, password })
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
      successAlert.textContent = 'Login successful! Redirecting...';
      successAlert.classList.add('visible');

      // Redirect to the originally requested page, if present
      setTimeout(() => {
        window.location.href = getSafeNextPath();
      }, 1000);
    } else {
      // Show error
      errorAlert.textContent = data.error || 'Login failed. Please try again.';
      errorAlert.classList.add('visible');
      document.getElementById('email').setAttribute('aria-invalid', 'true');
      document.getElementById('password').setAttribute('aria-invalid', 'true');
      submitBtn.disabled = false;
      submitBtn.textContent = 'Sign In';
    }
  } catch (error) {
    console.error('Login error:', error);
    errorAlert.textContent = 'Network error. Please try again.';
    errorAlert.classList.add('visible');
    submitBtn.disabled = false;
    submitBtn.textContent = 'Sign In';
  }
});
