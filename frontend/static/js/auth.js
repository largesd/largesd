/**
 * Authentication utilities for Blind Debate Adjudicator
 */

const Auth = {
  TOKEN_KEY: 'access_token',
  USER_KEY: 'user',
  ACTIVE_DEBATE_KEY: 'bda_active_debate_id',
  PENDING_POSTS_KEY: 'bda_pending_posts',
  _userMenuDismissBound: false,

  /**
   * Get the stored access token
   */
  getToken() {
    return localStorage.getItem(this.TOKEN_KEY);
  },

  /**
   * Get the stored user info
   */
  getUser() {
    const userJson = localStorage.getItem(this.USER_KEY);
    if (!userJson) return null;

    try {
      return JSON.parse(userJson);
    } catch (error) {
      console.warn('Stored user payload is invalid JSON. Clearing stale auth user state.', error);
      localStorage.removeItem(this.USER_KEY);
      return null;
    }
  },

  /**
   * Check if user is logged in
   */
  isLoggedIn() {
    return !!this.getToken();
  },

  /**
   * Check if the current user is an admin
   */
  isAdmin() {
    const user = this.getUser();
    return !!(user && user.is_admin);
  },

  /**
   * Clear auth and session-related local state
   */
  clearSession() {
    localStorage.removeItem(this.TOKEN_KEY);
    localStorage.removeItem(this.USER_KEY);
    localStorage.removeItem(this.ACTIVE_DEBATE_KEY);
    localStorage.removeItem(this.PENDING_POSTS_KEY);
  },

  /**
   * Build a login redirect URL that preserves current page intent
   */
  buildLoginRedirectUrl(reason = 'auth-required', nextOverride = null) {
    const currentPath = window.location.pathname || '/index.html';
    const normalizedCurrent = currentPath.startsWith('/') ? currentPath : `/${currentPath}`;
    const onAuthPage = normalizedCurrent.endsWith('/login.html') || normalizedCurrent.endsWith('/register.html');
    const computedReturnTo = onAuthPage
      ? '/index.html'
      : `${normalizedCurrent}${window.location.search || ''}${window.location.hash || ''}`;
    const returnTo = typeof nextOverride === 'string' && nextOverride.trim()
      ? nextOverride
      : computedReturnTo;

    const params = new URLSearchParams();
    if (reason) params.set('reason', reason);
    if (returnTo) params.set('next', returnTo);
    return `login.html?${params.toString()}`;
  },

  /**
   * Redirect to login with context about why
   */
  redirectToLogin(reason = 'auth-required', nextOverride = null) {
    window.location.href = this.buildLoginRedirectUrl(reason, nextOverride);
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

    // Clear local storage + debate context and redirect
    this.clearSession();
    this.redirectToLogin('logged-out');
  },

  /**
   * Update navigation to show user info or login link.
   * Phase 3: public blind mode — show generic session indicator, never identity strings.
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
      // Show generic session indicator (no display_name/email on public surfaces)
      const userDiv = document.createElement('div');
      userDiv.className = 'auth-link';
      userDiv.style.cssText = 'position:relative;display:inline-block;margin-left:8px';
      userDiv.innerHTML = `
        <button class="auth-menu-btn" type="button" data-action="toggle-user-menu" aria-label="Account menu" aria-haspopup="menu" aria-expanded="false" aria-controls="user-menu">
          <span>Account</span>
          <span class="text-10">▼</span>
        </button>
        <div id="user-menu" class="user-menu">
          <div class="user-menu-header">
            <div class="text-11-muted">Signed in</div>
          </div>
          <a href="#" class="user-menu-link" data-action="logout">Logout</a>
        </div>
      `;
      nav.appendChild(userDiv);
      userDiv.querySelector('[data-action="toggle-user-menu"]').addEventListener('click', () => this.toggleUserMenu());
      userDiv.querySelector('[data-action="logout"]').addEventListener('click', (e) => { e.preventDefault(); this.logout(); });

      // Close menu when clicking outside
      if (!this._userMenuDismissBound) {
        document.addEventListener('click', (e) => {
          const menu = document.getElementById('user-menu');
          const btn = e.target.closest('.auth-link button');
          if (menu && !btn && !e.target.closest('#user-menu')) {
            menu.style.display = 'none';
            const toggle = document.querySelector('.auth-link .auth-menu-btn');
            if (toggle) toggle.setAttribute('aria-expanded', 'false');
          }
        });
        this._userMenuDismissBound = true;
      }
    } else {
      // Show login link
      const loginLink = document.createElement('a');
      loginLink.className = 'auth-link';
      loginLink.href = 'login.html';
      loginLink.textContent = 'Login';
      nav.appendChild(loginLink);
    }

    if (window.BDA && typeof window.BDA.normalizeNavigation === 'function') {
      window.BDA.normalizeNavigation();
    }
  },

  /**
   * Toggle user menu dropdown
   */
  toggleUserMenu() {
    const menu = document.getElementById('user-menu');
    const toggle = document.querySelector('.auth-link .auth-menu-btn');
    if (menu) {
      const isOpen = menu.style.display !== 'none';
      menu.style.display = isOpen ? 'none' : 'block';
      if (toggle) {
        toggle.setAttribute('aria-expanded', String(!isOpen));
      }
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
    const {
      suppressAuthRedirect = false,
      ...fetchOptions
    } = options;
    const token = this.getToken();

    const headers = {
      'Content-Type': 'application/json',
      ...fetchOptions.headers
    };

    if (token) {
      headers['Authorization'] = `Bearer ${token}`;
    }

    const response = await fetch(url, {
      ...fetchOptions,
      headers
    });

    // If unauthorized, clear token and redirect to login
    if (response.status === 401) {
      this.clearSession();
      if (!suppressAuthRedirect) {
        this.redirectToLogin('session-expired');
      }
      return null;
    }

    return response;
  },

  /**
   * Verify the current session with the backend.
   * @returns {Promise<{ok: boolean, reason?: string, user?: object}>}
   */
  async verifySession() {
    const token = this.getToken();
    if (!token) {
      return { ok: false, reason: 'missing-token' };
    }

    try {
      const response = await this.fetch('/api/auth/me', {
        suppressAuthRedirect: true
      });

      if (response === null) {
        // 401 happened; Auth.fetch already cleared session
        return { ok: false, reason: 'expired' };
      }

      if (!response.ok) {
        return { ok: false, reason: 'network-error' };
      }

      const user = await response.json();
      localStorage.setItem(this.USER_KEY, JSON.stringify(user));
      return { ok: true, user };
    } catch (err) {
      return { ok: false, reason: 'network-error' };
    }
  }
};

// Initialize auth on page load
document.addEventListener('DOMContentLoaded', () => {
  Auth.updateNavigation();
});

// Make Auth available globally
window.Auth = Auth;
