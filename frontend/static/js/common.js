/**
 * Shared utilities for Blind Debate Adjudicator
 * Centralizes common functionality across all pages
 */

const BDA = {
  // API Configuration
  API_BASE: window.location.origin,
  
  /**
   * State management
   */
  state: {
    currentDebate: null,
    currentSnapshot: null,
    pendingPosts: [],
    isLoading: false,
    activeDebateId: null
  },
  
  /**
   * Initialize the application
   */
  init() {
    this.hydrateDebateContext();
    this.loadPendingPosts();
    this.setupBackToTop();
    this.setupTooltips();
    this.setupHelpPanel();
    this.setupMobileState();
    this.setupTableScroll();
    Auth.updateNavigation();
  },

  /**
   * Sync active debate context from URL/localStorage
   */
  hydrateDebateContext() {
    const params = new URLSearchParams(window.location.search);
    const debateIdFromUrl = params.get('debate_id');
    const debateIdFromStorage = localStorage.getItem('bda_active_debate_id');

    if (debateIdFromUrl) {
      this.setActiveDebateId(debateIdFromUrl);
      return;
    }

    if (debateIdFromStorage) {
      this.state.activeDebateId = debateIdFromStorage;
    }
  },

  /**
   * Persist the active debate for cross-page browsing
   */
  setActiveDebateId(debateId) {
    if (!debateId) return;
    this.state.activeDebateId = debateId;
    localStorage.setItem('bda_active_debate_id', debateId);
  },

  /**
   * Clear active debate context
   */
  clearActiveDebateId() {
    this.state.activeDebateId = null;
    localStorage.removeItem('bda_active_debate_id');
  },

  /**
   * Get active debate id from in-memory state or localStorage
   */
  getActiveDebateId() {
    return this.state.activeDebateId || localStorage.getItem('bda_active_debate_id');
  },
  
  /**
   * Load pending posts from localStorage
   */
  loadPendingPosts() {
    try {
      const saved = localStorage.getItem('bda_pending_posts');
      if (saved) {
        this.state.pendingPosts = JSON.parse(saved);
      }
    } catch (e) {
      console.warn('Failed to load pending posts:', e);
      this.state.pendingPosts = [];
    }
  },
  
  /**
   * Save pending posts to localStorage
   */
  savePendingPosts() {
    try {
      localStorage.setItem('bda_pending_posts', JSON.stringify(this.state.pendingPosts));
    } catch (e) {
      console.warn('Failed to save pending posts:', e);
    }
  },
  
  /**
   * Add a pending post
   */
  addPendingPost(post) {
    this.state.pendingPosts.push({
      ...post,
      timestamp: new Date().toISOString()
    });
    this.savePendingPosts();
  },
  
  /**
   * Clear all pending posts
   */
  clearPendingPosts() {
    this.state.pendingPosts = [];
    localStorage.removeItem('bda_pending_posts');
  },
  
  /**
   * Remove a specific pending post
   */
  removePendingPost(postId) {
    this.state.pendingPosts = this.state.pendingPosts.filter(p => p.id !== postId);
    this.savePendingPosts();
  },
  
  /**
   * API Request helper with error handling
   */
  async api(endpoint, options = {}) {
    const url = `${this.API_BASE}${endpoint}`;
    const headers = {
      'Content-Type': 'application/json',
      ...options.headers
    };
    
    // Add auth token if available
    const token = Auth.getToken();
    if (token) {
      headers['Authorization'] = `Bearer ${token}`;
    }

    const debateId = this.getActiveDebateId();
    if (debateId && !headers['X-Debate-ID']) {
      headers['X-Debate-ID'] = debateId;
    }
    
    try {
      this.state.isLoading = true;
      const response = await fetch(url, {
        ...options,
        headers
      });
      
      // Handle auth errors
      if (response.status === 401) {
        localStorage.removeItem('access_token');
        localStorage.removeItem('user');
        window.location.href = 'login.html';
        return null;
      }
      
      const data = await response.json();
      
      if (!response.ok) {
        throw new Error(data.error || `HTTP ${response.status}`);
      }
      
      return data;
    } catch (error) {
      console.error('API Error:', error);
      throw error;
    } finally {
      this.state.isLoading = false;
    }
  },
  
  /**
   * Load current debate info
   */
  async loadDebate() {
    try {
      const data = await this.api('/api/debate');
      this.state.currentDebate = data.has_debate ? data : null;
      if (data?.debate_id) {
        this.setActiveDebateId(data.debate_id);
      }
      return data;
    } catch (error) {
      console.error('Error loading debate:', error);
      this.state.currentDebate = null;
      return { has_debate: false };
    }
  },
  
  /**
   * Load current snapshot
   */
  async loadSnapshot() {
    try {
      const data = await this.api('/api/debate/snapshot');
      this.state.currentSnapshot = data.has_snapshot ? data : null;
      return data;
    } catch (error) {
      console.error('Error loading snapshot:', error);
      this.state.currentSnapshot = null;
      return null;
    }
  },

  /**
   * Load debates visible to the current viewer
   */
  async loadDebates() {
    try {
      const data = await this.api('/api/debates');
      return data.debates || [];
    } catch (error) {
      console.error('Error loading debates:', error);
      return [];
    }
  },
  
  /**
   * Update state strip display
   */
  updateStateStrip(data) {
    const verdict = data?.verdict || 'NO VERDICT';
    const confidence = data?.confidence !== null && data?.confidence !== undefined 
      ? data.confidence.toFixed(2) 
      : '-';
    const snapshotId = data?.snapshot_id || '-';
    const timestamp = data?.timestamp 
      ? new Date(data.timestamp).toLocaleString() 
      : '-';
    
    // Desktop
    const verdictEl = document.getElementById('header-verdict') || document.getElementById('verdict-display');
    const confidenceEl = document.getElementById('header-confidence') || document.getElementById('confidence-display');
    const snapshotEl = document.getElementById('header-snapshot') || document.getElementById('snapshot-display');
    const updatedEl = document.getElementById('header-updated') || document.getElementById('updated-display');
    
    if (verdictEl) {
      verdictEl.textContent = verdict;
      verdictEl.className = 'state-value verdict-neutral' + 
        (verdict === 'FOR' ? ' good' : verdict === 'AGAINST' ? ' bad' : '');
    }
    if (confidenceEl) confidenceEl.textContent = confidence;
    if (snapshotEl) {
      snapshotEl.textContent = snapshotId;
      snapshotEl.title = snapshotId;
    }
    if (updatedEl) updatedEl.textContent = timestamp;
    
    // Mobile
    const verdictMobile = document.getElementById('verdict-mobile');
    const confidenceMobile = document.getElementById('confidence-mobile');
    if (verdictMobile) verdictMobile.textContent = verdict;
    if (confidenceMobile) confidenceMobile.textContent = confidence;
  },
  
  /**
   * Show status message
   */
  showStatus(message, isError = false, duration = 5000) {
    const statusEl = document.getElementById('status-message');
    if (!statusEl) return;
    
    statusEl.textContent = message;
    statusEl.className = 'status-message ' + (isError ? 'post-error' : 'post-success');
    statusEl.style.display = 'block';
    
    if (duration > 0) {
      setTimeout(() => {
        statusEl.style.display = 'none';
      }, duration);
    }
  },
  
  /**
   * Setup back to top button
   */
  setupBackToTop() {
    const backToTop = document.querySelector('.back-to-top');
    if (!backToTop) return;
    
    window.addEventListener('scroll', () => {
      if (window.scrollY > 300) {
        backToTop.classList.add('visible');
      } else {
        backToTop.classList.remove('visible');
      }
    });
  },
  
  /**
   * Setup tooltip system
   */
  setupTooltips() {
    // Remove existing tooltip popup if any
    const existing = document.querySelector('.tooltip-popup');
    if (existing) existing.remove();
    
    // Create new tooltip popup
    const tooltipPopup = document.createElement('div');
    tooltipPopup.className = 'tooltip-popup';
    document.body.appendChild(tooltipPopup);
    
    // Add event listeners to all tooltips
    document.querySelectorAll('.tooltip').forEach(el => {
      el.addEventListener('mouseenter', (e) => {
        const text = el.getAttribute('data-tooltip');
        if (!text) return;
        
        tooltipPopup.textContent = text;
        tooltipPopup.classList.add('visible');
        
        const rect = el.getBoundingClientRect();
        const popupRect = tooltipPopup.getBoundingClientRect();
        
        let top = rect.top - popupRect.height - 8;
        let left = rect.left + (rect.width / 2) - (popupRect.width / 2);
        
        // Clamp to viewport
        left = Math.max(10, Math.min(left, window.innerWidth - popupRect.width - 10));
        if (top < 10) top = rect.bottom + 8;
        
        tooltipPopup.style.top = top + 'px';
        tooltipPopup.style.left = left + 'px';
      });
      
      el.addEventListener('mouseleave', () => {
        tooltipPopup.classList.remove('visible');
      });
    });
  },
  
  /**
   * Setup help panel
   */
  setupHelpPanel() {
    const helpBtn = document.querySelector('.help-btn');
    const helpOverlay = document.querySelector('.help-overlay');
    const closeHelpBtn = document.querySelector('.close-help');
    
    if (helpBtn) {
      helpBtn.addEventListener('click', () => this.toggleHelp());
    }
    if (helpOverlay) {
      helpOverlay.addEventListener('click', () => this.toggleHelp());
    }
    if (closeHelpBtn) {
      closeHelpBtn.addEventListener('click', () => this.toggleHelp());
    }
  },
  
  /**
   * Toggle help panel
   */
  toggleHelp() {
    const panel = document.getElementById('helpPanel');
    const overlay = document.querySelector('.help-overlay');
    
    if (panel) panel.classList.toggle('open');
    if (overlay) overlay.classList.toggle('visible');
  },
  
  /**
   * Setup mobile state strip
   */
  setupMobileState() {
    if (window.innerWidth <= 640) {
      const stateWraps = document.querySelectorAll('.state-wrap');
      if (stateWraps.length >= 2) {
        stateWraps[0].style.display = 'none';
        stateWraps[1].style.display = 'grid';
      }
    }
  },
  
  /**
   * Setup table scroll indicators
   */
  setupTableScroll() {
    document.querySelectorAll('.table-wrap').forEach(wrap => {
      wrap.classList.add('scrollable');
      
      const updateFade = () => {
        const isScrollable = wrap.scrollWidth > wrap.clientWidth;
        const isAtEnd = wrap.scrollLeft + wrap.clientWidth >= wrap.scrollWidth - 10;
        wrap.classList.toggle('show-fade', isScrollable && !isAtEnd);
      };
      
      wrap.addEventListener('scroll', updateFade);
      updateFade(); // Initial check
    });
  },
  
  /**
   * Format number with fixed decimals
   */
  formatNumber(num, decimals = 2) {
    if (num === null || num === undefined || isNaN(num)) return '-';
    return num.toFixed(decimals);
  },

  /**
   * Format timestamps consistently
   */
  formatDateTime(value) {
    if (!value) return '-';
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return String(value);
    return date.toLocaleString();
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
   * Debounce function calls
   */
  debounce(func, wait) {
    let timeout;
    return function executedFunction(...args) {
      const later = () => {
        clearTimeout(timeout);
        func(...args);
      };
      clearTimeout(timeout);
      timeout = setTimeout(later, wait);
    };
  }
};

// Initialize on DOM ready
document.addEventListener('DOMContentLoaded', () => {
  BDA.init();
});

// Make available globally
window.BDA = BDA;
