/**
 * Authentication utilities for Blind Debate Adjudicator
 */

const Auth = {
  /**
   * Get the stored access token
   */
  getToken() {
    return localStorage.getItem('access_token');
  },

  /**
   * Get the stored user info
   */
  getUser() {
    const userJson = localStorage.getItem('user');
    return userJson ? JSON.parse(userJson) : null;
  },

  /**
   * Check if user is logged in
   */
  isLoggedIn() {
    return !!this.getToken();
  },

  /**
   * Log out the user
   */
  logout() {
    // Call logout endpoint if available
    const token = this.getToken();
    if (token) {
      fetch('/api/auth/logout', {
        method: 'POST',
        headers: {
          'Authorization': `Bearer ${token}`
        }
      }).catch(() => {}); // Ignore errors
    }
    
    // Clear local storage
    localStorage.removeItem('access_token');
    localStorage.removeItem('user');
    
    // Redirect to login
    window.location.href = 'login.html';
  },

  /**
   * Update navigation to show user info or login link
   */
  updateNavigation() {
    const nav = document.querySelector('.navlinks');
    if (!nav) return;
    
    const user = this.getUser();
    const existingAuthLink = nav.querySelector('.auth-link');
    
    if (existingAuthLink) {
      existingAuthLink.remove();
    }
    
    if (user) {
      // Show user dropdown
      const userDiv = document.createElement('div');
      userDiv.className = 'auth-link';
      userDiv.style.cssText = 'position:relative;display:inline-block;margin-left:8px';
      userDiv.innerHTML = `
        <button class="help-btn" onclick="Auth.toggleUserMenu()" style="display:flex;align-items:center;gap:8px">
          <span>${this.escapeHtml(user.display_name)}</span>
          <span style="font-size:10px">▼</span>
        </button>
        <div id="user-menu" style="display:none;position:absolute;right:0;top:100%;margin-top:8px;background:var(--panel);border:1px solid var(--line);border-radius:8px;padding:8px 0;min-width:160px;z-index:100">
          <div style="padding:8px 16px;border-bottom:1px solid var(--line)">
            <div style="font-size:13px;font-weight:600">${this.escapeHtml(user.display_name)}</div>
            <div style="font-size:11px;color:var(--muted)">${this.escapeHtml(user.email)}</div>
          </div>
          <a href="#" onclick="Auth.logout();return false;" style="display:block;padding:10px 16px;color:var(--bad);font-size:13px;text-decoration:none">Logout</a>
        </div>
      `;
      nav.appendChild(userDiv);
      
      // Close menu when clicking outside
      document.addEventListener('click', (e) => {
        const menu = document.getElementById('user-menu');
        const btn = e.target.closest('.auth-link button');
        if (menu && !btn && !e.target.closest('#user-menu')) {
          menu.style.display = 'none';
        }
      });
    } else {
      // Show login link
      const loginLink = document.createElement('a');
      loginLink.className = 'auth-link';
      loginLink.href = 'login.html';
      loginLink.textContent = 'Login';
      nav.appendChild(loginLink);
    }
  },

  /**
   * Toggle user menu dropdown
   */
  toggleUserMenu() {
    const menu = document.getElementById('user-menu');
    if (menu) {
      menu.style.display = menu.style.display === 'none' ? 'block' : 'none';
    }
  },

  /**
   * Escape HTML to prevent XSS
   */
  escapeHtml(text) {
    if (!text) return '';
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
  },

  /**
   * Make an authenticated API request
   */
  async fetch(url, options = {}) {
    const token = this.getToken();
    
    const headers = {
      'Content-Type': 'application/json',
      ...options.headers
    };
    
    if (token) {
      headers['Authorization'] = `Bearer ${token}`;
    }
    
    const response = await fetch(url, {
      ...options,
      headers
    });
    
    // If unauthorized, clear token and redirect to login
    if (response.status === 401) {
      localStorage.removeItem('access_token');
      localStorage.removeItem('user');
      window.location.href = 'login.html';
      return null;
    }
    
    return response;
  }
};

// Initialize auth on page load
document.addEventListener('DOMContentLoaded', () => {
  Auth.updateNavigation();
});

// Make Auth available globally
window.Auth = Auth;
