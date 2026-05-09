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
    this.injectSharedHelpPanel().finally(() => this.setupHelpPanel());
    this.setupBackToTop();
    this.setupTooltips();
    this.setupMobileState();
    this.setupTableScroll();
    this.setupTableLabels();
    this.normalizeNavigation();
    this.setupNavigationDismiss();
    this.setupNavigationResize();
    this.setupActionDelegation();
    Auth.updateNavigation();
  },

  /**
   * Action delegation registry for data-action buttons
   */
  _actionRegistry: {},
  registerAction(name, handler) {
    this._actionRegistry[name] = handler;
  },

  /**
   * Setup universal data-action event delegation
   */
  setupActionDelegation() {
    document.addEventListener('click', (e) => {
      const trigger = e.target.closest('[data-action]');
      if (!trigger) return;
      const action = trigger.dataset.action;
      if (!action) return;

      // Universal actions
      if (action === 'scroll-top') {
        e.preventDefault();
        window.scrollTo({ top: 0, behavior: 'smooth' });
        return;
      }
      if (action === 'toggle-help') {
        e.preventDefault();
        if (typeof BDA !== 'undefined' && BDA.toggleHelp) {
          BDA.toggleHelp();
        } else if (typeof toggleHelp === 'function') {
          toggleHelp();
        }
        return;
      }

      // Page-registered actions
      if (this._actionRegistry[action]) {
        e.preventDefault();
        this._actionRegistry[action](trigger, e);
      }
    });
  },

  /**
   * Inject shared help panel markup for pages using a placeholder
   */
  async injectSharedHelpPanel() {
    const placeholder = document.getElementById('shared-help-panel');
    const existingPanel = document.getElementById('helpPanel');
    if (!placeholder || existingPanel) return;

    const panelName = placeholder.dataset.panel || 'help-panel';
    const safePanelName = panelName.replace(/[^a-z0-9-]/gi, '');

    try {
      const response = await fetch(`components/${safePanelName}.html`);
      if (!response.ok) {
        placeholder.outerHTML = this.getFallbackHelpPanelMarkup(safePanelName);
        return;
      }
      placeholder.outerHTML = await response.text();
    } catch (error) {
      console.warn('Failed to load shared help panel from components folder; using fallback markup.', error);
      placeholder.outerHTML = this.getFallbackHelpPanelMarkup(safePanelName);
    }
  },

  /**
   * Generic shared component injector.
   * Usage: <div id="shared-footer" data-component="site-footer"></div>
   */
  async injectSharedComponent(placeholderId) {
    const placeholder = document.getElementById(placeholderId);
    if (!placeholder) return;
    const componentName = placeholder.dataset.component;
    if (!componentName) return;
    const safeName = componentName.replace(/[^a-z0-9-]/gi, '');
    try {
      const response = await fetch(`components/${safeName}.html`);
      if (response.ok) {
        placeholder.outerHTML = await response.text();
      }
    } catch (error) {
      console.warn(`Failed to load shared component ${safeName}:`, error);
    }
  },

  /**
   * Fallback help panel markup for file:// previews where fetch() can fail
   */
  getFallbackHelpPanelMarkup(panelName) {
    const commonHeader = `
<div class="help-overlay"></div>
<div class="help-panel" id="helpPanel">
  <div class="help-panel-header">
    <h3>Glossary & Help</h3>
    <button class="close-help" aria-label="Close help">x</button>
  </div>
  <div class="help-panel-body">
`;
    const commonFooter = `
    <hr />
    <p class="help-panel-footer">For full specification, see <a href="about.html">About</a> page.</p>
  </div>
</div>`;

    if (panelName === 'help-panel-admin') {
      return `${commonHeader}
    <p class="help-panel-desc">Administrative terms for moderation configuration.</p>
    <div class="glossary-term">Modulation Template</div>
    <div class="glossary-def">Versioned moderation rule set for allow or block decisions.</div>
    <div class="glossary-term">PII</div>
    <div class="glossary-def">Personally identifiable information such as emails, phone numbers, and addresses.</div>
    <div class="glossary-term">Snapshot Audit</div>
    <div class="glossary-def">Immutable record of moderation outcomes, including block reason counts.</div>
${commonFooter}`;
    }

    if (panelName === 'help-panel-posting') {
      return `${commonHeader}
    <p class="help-panel-desc">Key terms for posting and debate structure.</p>
    <div class="glossary-term">Argument Unit</div>
    <div class="glossary-def">Structured contribution made from factual premises and inference.</div>
    <div class="glossary-term">Canonical FACT</div>
    <div class="glossary-def">Deduplicated atomic fact used in scoring and auditing.</div>
    <div class="glossary-term">Coverage</div>
    <div class="glossary-def">How effectively one side addresses opposing arguments.</div>
${commonFooter}`;
    }

    return `${commonHeader}
    <p class="help-panel-desc">Key terms and metrics used throughout the system.</p>
    <div class="glossary-term">CI(D)</div>
    <div class="glossary-def">Confidence interval of D (FOR minus AGAINST). If it crosses zero, verdict remains NO VERDICT.</div>
    <div class="glossary-term">D = FOR - AGAINST</div>
    <div class="glossary-def">Margin between overall FOR and AGAINST scores.</div>
    <div class="glossary-term">Q_t,s</div>
    <div class="glossary-def">Geometric mean of factuality, reasoning, and coverage.</div>
    <div class="glossary-term">Rel_t</div>
    <div class="glossary-def">Topic relevance weight from claim-producing content mass.</div>
${commonFooter}`;
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
   * Sync the double-submit CSRF token from the readable cookie into any form field.
   */
  syncCsrfTokenFromCookie() {
    const match = document.cookie.match(/(?:^|;\s*)csrf_token=([^;]+)/);
    const csrfInput = document.getElementById('csrf_token');
    const cookieToken = match ? decodeURIComponent(match[1]) : '';

    if (csrfInput && cookieToken) {
      csrfInput.value = cookieToken;
    }

    return cookieToken || (csrfInput ? csrfInput.value : '');
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
    const {
      suppressAuthRedirect = false,
      ...fetchOptions
    } = options;
    const url = `${this.API_BASE}${endpoint}`;
    const headers = {
      'Content-Type': 'application/json',
      ...fetchOptions.headers
    };

    // Add auth token if available
    const token = Auth.getToken();
    if (token) {
      headers['Authorization'] = `Bearer ${token}`;
    }

    // Add CSRF token for double-submit cookie pattern
    const csrfToken = this.syncCsrfTokenFromCookie();
    if (csrfToken && !headers['X-CSRF-Token']) {
      headers['X-CSRF-Token'] = csrfToken;
    }

    const debateId = this.getActiveDebateId();
    if (debateId && !headers['X-Debate-ID']) {
      headers['X-Debate-ID'] = debateId;
    }

    try {
      this.state.isLoading = true;
      const response = await fetch(url, {
        ...fetchOptions,
        headers
      });

      const contentType = response.headers.get('content-type') || '';
      let data = {};
      if (contentType.includes('application/json')) {
        data = await response.json();
      } else {
        const textBody = await response.text();
        data = textBody ? { error: textBody } : {};
      }

      if (response.status === 401) {
        if (typeof Auth.clearSession === 'function') {
          Auth.clearSession();
        } else {
          localStorage.removeItem('access_token');
          localStorage.removeItem('user');
          localStorage.removeItem('bda_active_debate_id');
          localStorage.removeItem('bda_pending_posts');
        }
        if (!suppressAuthRedirect) {
          if (typeof Auth.redirectToLogin === 'function') {
            Auth.redirectToLogin('session-expired');
          } else {
            window.location.href = 'login.html';
          }
          return null;
        }
      }

      if (response.status === 429) {
        const retryAfter = data.retry_after || response.headers.get('Retry-After') || 'a moment';
        const error = new Error(
          data.error || `Too many requests. Please retry in ${retryAfter} second(s).`
        );
        error.status = 429;
        error.code = 'RATE_LIMITED';
        error.retry_after = retryAfter;
        error.payload = data;
        throw error;
      }

      if (!response.ok && response.status !== 202) {
        const error = new Error(data.error || `HTTP ${response.status}`);
        error.status = response.status;
        error.code = data.code || null;
        error.payload = data;
        throw error;
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
  async loadDebate(options = {}) {
    try {
      const data = await this.api('/api/debate', options);
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
  async loadSnapshot(options = {}) {
    try {
      const data = await this.api('/api/debate/snapshot', options);
      this.state.currentSnapshot = data.has_snapshot ? data : null;
      return data;
    } catch (error) {
      console.error('Error loading snapshot:', error);
      this.state.currentSnapshot = null;
      return null;
    }
  },

  /**
   * Poll a snapshot job until it completes or fails.
   * @param {string} jobId
   * @param {Object} options
   * @param {number} options.intervalMs - polling interval in ms (default 2000)
   * @param {number} options.maxPolls - maximum number of polls (default 150 = 5 min)
   * @param {Function} options.onProgress - callback(job) for status updates
   */
  async pollSnapshotJob(jobId, options = {}) {
    const {
      intervalMs = 2000,
      maxPolls = 150,
      onProgress = null,
    } = options;

    for (let i = 0; i < maxPolls; i++) {
      const job = await this.api(`/api/debate/snapshot-jobs/${encodeURIComponent(jobId)}`, {
        method: 'GET',
        preferLiveApi: true,
      });

      if (onProgress && typeof onProgress === 'function') {
        onProgress(job);
      }

      if (job.status === 'completed') {
        return job;
      }
      if (job.status === 'failed') {
        const error = new Error(job.error || 'Snapshot generation failed');
        error.jobId = jobId;
        error.job = job;
        throw error;
      }

      await new Promise((resolve) => setTimeout(resolve, intervalMs));
    }

    const timeoutError = new Error('Snapshot generation timed out');
    timeoutError.jobId = jobId;
    throw timeoutError;
  },

  /**
   * Generate a new snapshot asynchronously.
   * POSTs to /api/debate/snapshot, then polls the job until complete.
   * @param {Object} options
   * @param {string} options.triggerType - e.g. 'activity', 'scheduled', 'manual'
   * @param {Function} options.onProgress - callback(job) for status updates
   */
  async generateSnapshot(options = {}) {
    const { triggerType = 'manual', onProgress = null } = options;

    // Step 1: enqueue snapshot generation
    const enqueueData = await this.api('/api/debate/snapshot', {
      method: 'POST',
      body: JSON.stringify({ trigger_type: triggerType }),
      preferLiveApi: true,
    });

    if (!enqueueData || !enqueueData.job_id) {
      throw new Error('Snapshot enqueue failed: no job_id returned');
    }

    // Step 2: poll until complete
    const job = await this.pollSnapshotJob(enqueueData.job_id, {
      onProgress,
    });

    // Step 3: reload the current snapshot to get full data
    const snapshotData = await this.loadSnapshot({ preferLiveApi: true });
    return {
      job,
      snapshot: snapshotData,
    };
  },

  /**
   * Load debates visible to the current viewer
   */
  async loadDebates(options = {}) {
    try {
      const data = await this.api('/api/debates', options);
      return data.debates || [];
    } catch (error) {
      console.error('Error loading debates:', error);
      return [];
    }
  },

  /**
   * Update state strip display
   */
  getVerdictTone(verdict) {
    if (verdict === 'FOR') return 'good';
    if (verdict === 'AGAINST') return 'bad';
    return 'warn';
  },

  updateStateStrip(data) {
    const verdict = data?.verdict || 'NO VERDICT';
    const verdictTone = this.getVerdictTone(verdict);
    const confidence = data?.confidence !== null && data?.confidence !== undefined
      ? data.confidence.toFixed(2)
      : '-';
    const snapshotId = data?.snapshot_id || '-';

    // Desktop
    const verdictEl = document.getElementById('header-verdict') || document.getElementById('verdict-display');
    const confidenceEl = document.getElementById('header-confidence') || document.getElementById('confidence-display');
    const snapshotEl = document.getElementById('header-snapshot') || document.getElementById('snapshot-display');

    if (verdictEl) {
      verdictEl.textContent = verdict;
      verdictEl.className = 'state-value verdict-neutral' +
        (verdict === 'FOR' ? ' good' : verdict === 'AGAINST' ? ' bad' : '');
      const verdictItem = verdictEl.closest('.state-item');
      if (verdictItem) verdictItem.dataset.stateTone = verdictTone;
    }
    if (confidenceEl) confidenceEl.textContent = confidence;
    if (snapshotEl) {
      snapshotEl.textContent = snapshotId;
      snapshotEl.title = snapshotId;
    }

    // Mobile
    const verdictMobile = document.getElementById('verdict-mobile');
    const confidenceMobile = document.getElementById('confidence-mobile');
    if (verdictMobile) {
      verdictMobile.textContent = verdict;
      const verdictCompact = verdictMobile.closest('.state-compact');
      if (verdictCompact) verdictCompact.dataset.stateTone = verdictTone;
    }
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
    const helpBtns = document.querySelectorAll('.help-btn[aria-controls="helpPanel"], [data-help-toggle="true"]');
    const helpOverlay = document.querySelector('.help-overlay');
    const closeHelpBtns = document.querySelectorAll('.close-help');

    helpBtns.forEach((helpBtn) => {
      if (helpBtn.dataset.helpBound === 'true') return;
      helpBtn.addEventListener('click', () => this.toggleHelp());
      helpBtn.dataset.helpBound = 'true';
    });
    if (helpOverlay && helpOverlay.dataset.helpBound !== 'true') {
      helpOverlay.addEventListener('click', () => this.toggleHelp());
      helpOverlay.dataset.helpBound = 'true';
    }
    closeHelpBtns.forEach((closeHelpBtn) => {
      if (closeHelpBtn.dataset.helpBound === 'true') return;
      closeHelpBtn.addEventListener('click', () => this.toggleHelp());
      closeHelpBtn.dataset.helpBound = 'true';
    });

    if (!this._helpEscapeBound) {
      document.addEventListener('keydown', (event) => {
        if (event.key !== 'Escape') return;
        const panel = document.getElementById('helpPanel');
        if (panel && panel.classList.contains('open')) {
          this.toggleHelp();
        }
      });
      this._helpEscapeBound = true;
    }
  },

  /**
   * Toggle help panel
   */
  toggleHelp() {
    const panel = document.getElementById('helpPanel');
    const overlay = document.querySelector('.help-overlay');
    const helpButtons = document.querySelectorAll('.help-btn[aria-controls="helpPanel"], [data-help-toggle="true"]');
    if (!panel || !overlay) return;

    const shouldOpen = !panel.classList.contains('open');
    panel.classList.toggle('open', shouldOpen);
    overlay.classList.toggle('visible', shouldOpen);
    panel.setAttribute('aria-hidden', String(!shouldOpen));
    overlay.setAttribute('aria-hidden', String(!shouldOpen));

    if (shouldOpen) {
      panel.removeAttribute('inert');
      this._helpTrigger = document.activeElement;
      this._trapFocus(panel);
      const firstFocusable = panel.querySelector('button, a, input, textarea, select, [tabindex]:not([tabindex="-1"])');
      if (firstFocusable) firstFocusable.focus();
    } else {
      panel.setAttribute('inert', '');
      if (this._helpTrigger && this._helpTrigger.focus) {
        this._helpTrigger.focus();
      }
      this._untrapFocus();
    }

    helpButtons.forEach((button) => {
      button.setAttribute('aria-expanded', String(shouldOpen));
    });
  },

  _trapFocus(container) {
    this._focusTrapHandler = (e) => {
      if (e.key !== 'Tab') return;
      const focusables = Array.from(container.querySelectorAll('button, a, input, textarea, select, [tabindex]:not([tabindex="-1"])'))
        .filter(el => !el.disabled && el.offsetParent !== null);
      if (focusables.length === 0) return;
      const first = focusables[0];
      const last = focusables[focusables.length - 1];
      if (e.shiftKey) {
        if (document.activeElement === first) {
          e.preventDefault();
          last.focus();
        }
      } else {
        if (document.activeElement === last) {
          e.preventDefault();
          first.focus();
        }
      }
    };
    container.addEventListener('keydown', this._focusTrapHandler);
  },

  _untrapFocus() {
    const panel = document.getElementById('helpPanel');
    if (panel && this._focusTrapHandler) {
      panel.removeEventListener('keydown', this._focusTrapHandler);
      this._focusTrapHandler = null;
    }
  },

  /**
   * Setup mobile state strip
   */
  setupMobileState() {
    const desktop = document.getElementById('state-wrap-desktop');
    const mobile = document.getElementById('state-wrap-mobile');
    const stateWraps = document.querySelectorAll('.state-wrap');

    if (!desktop && !mobile && stateWraps.length < 2) return;

    const applyLayout = () => {
      const isMobile = window.innerWidth <= 640;

      if (desktop && mobile) {
        desktop.style.display = isMobile ? 'none' : 'grid';
        mobile.style.display = isMobile ? 'grid' : 'none';
        return;
      }

      if (stateWraps.length >= 2) {
        stateWraps[0].style.display = isMobile ? 'none' : 'grid';
        stateWraps[1].style.display = isMobile ? 'grid' : 'none';
      }
    };

    applyLayout();
    window.addEventListener('resize', this.debounce(applyLayout, 120));
  },

  /**
   * Auto-populate data-label attributes on table cells based on header text.
   * Runs on all .table elements and watches for dynamic updates.
   */
  setupTableLabels() {
    const hydrateTable = (table) => {
      const thead = table.querySelector('thead');
      const headers = thead
        ? Array.from(thead.querySelectorAll('th')).map(th => th.textContent.trim())
        : [];

      table.querySelectorAll('tr').forEach(tr => {
        const tds = Array.from(tr.querySelectorAll('td'));
        const rowTh = tr.querySelector('th');

        tds.forEach((td, index) => {
          if (td.hasAttribute('data-label')) return;
          if (td.hasAttribute('colspan')) return;

          if (headers[index]) {
            td.setAttribute('data-label', headers[index]);
          } else if (rowTh) {
            td.setAttribute('data-label', rowTh.textContent.trim());
          }
        });
      });
    };

    document.querySelectorAll('.table').forEach(hydrateTable);

    const observer = new MutationObserver((mutations) => {
      const tablesToHydrate = new Set();

      mutations.forEach((mutation) => {
        mutation.addedNodes.forEach((node) => {
          if (node.nodeType !== Node.ELEMENT_NODE) return;

          // Direct table additions
          if (node.matches && node.matches('.table')) {
            tablesToHydrate.add(node);
          }

          // Tables within added subtree
          if (node.querySelectorAll) {
            node.querySelectorAll('.table').forEach(t => tablesToHydrate.add(t));
          }

          // Added nodes inside existing tables
          if (node.closest) {
            const parentTable = node.closest('.table');
            if (parentTable) {
              tablesToHydrate.add(parentTable);
            }
          }
        });
      });

      tablesToHydrate.forEach(hydrateTable);
    });

    observer.observe(document.body, { childList: true, subtree: true });
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
   * Normalize nav links and move overflow into the More disclosure.
   */
  normalizeNavigation() {
    const nav = document.querySelector('.navlinks');
    if (!nav) return;

    // Flatten any existing More menu so we can rebuild it in a consistent position.
    Array.from(nav.querySelectorAll('.nav-more')).forEach((details) => {
      const menuLinks = Array.from(details.querySelectorAll('.nav-more-menu > a'));
      menuLinks.forEach((link) => nav.insertBefore(link, details));
      details.remove();
    });

    // Remove admin link for non-admins before normalizing
    const isAdmin = (typeof Auth !== 'undefined' && typeof Auth.isAdmin === 'function') ? Auth.isAdmin() : false;
    if (!isAdmin) {
      Array.from(nav.children).forEach((child) => {
        if (child.tagName === 'A') {
          const href = (child.getAttribute('href') || '').split('?')[0].split('#')[0].split('/').pop();
          if (href === 'admin.html') {
            child.remove();
          }
        }
      });
    }

    let allLinks = Array.from(nav.children).filter((element) => {
      return element.tagName === 'A' && !element.classList.contains('auth-link');
    });

    const navOrder = [
      'index.html',
      'propose.html',
      'new_debate.html',
      'snapshot.html',
      'verdict.html',
      'topics.html',
      'audits.html',
      'dossier.html',
      'governance.html',
      'appeals.html',
      'admin.html',
      'about.html'
    ];
    const alwaysInMore = new Set(['governance.html', 'appeals.html', 'admin.html', 'about.html']);
    const navLabels = {
      'index.html': 'Home',
      'propose.html': 'Propose',
      'new_debate.html': 'Post Argument',
      'snapshot.html': 'Snapshot',
      'verdict.html': 'Verdict',
      'topics.html': 'Topics',
      'audits.html': 'Audits',
      'dossier.html': 'Dossier',
      'governance.html': 'Governance',
      'appeals.html': 'Appeals',
      'admin.html': 'Admin',
      'about.html': 'About'
    };
    const rankMap = new Map(navOrder.map((item, index) => [item, index]));
    const hrefKey = (link) => {
      const href = link.getAttribute('href') || '';
      return href.split('?')[0].split('#')[0].split('/').pop();
    };
    const currentPage = (window.location.pathname.split('/').pop() || 'index.html');

    const existingHrefs = new Set(allLinks.map((link) => hrefKey(link)));
    const insertionPointForMissing = nav.querySelector('.help-btn, [data-help-toggle="true"], .auth-link');
    navOrder.forEach((href) => {
      if (existingHrefs.has(href)) return;
      // Hide admin link for non-admins
      if (href === 'admin.html' && !isAdmin) return;
      const link = document.createElement('a');
      link.href = href;
      link.textContent = navLabels[href] || href;
      if (href === currentPage) {
        link.classList.add('active');
        link.setAttribute('aria-current', 'page');
      }
      nav.insertBefore(link, insertionPointForMissing || null);
      existingHrefs.add(href);
    });
    allLinks = Array.from(nav.children).filter((element) => {
      return element.tagName === 'A' && !element.classList.contains('auth-link');
    });

    // Evidence is now a tab within Audits; drop standalone nav links.
    allLinks.forEach((link) => {
      if (hrefKey(link) === 'evidence.html') {
        link.remove();
      }
    });
    allLinks = Array.from(nav.children).filter((element) => {
      return element.tagName === 'A' && !element.classList.contains('auth-link');
    });

    // Keep nav order consistent with index across all pages.
    allLinks.sort((a, b) => {
      const aRank = rankMap.has(hrefKey(a)) ? rankMap.get(hrefKey(a)) : 999;
      const bRank = rankMap.has(hrefKey(b)) ? rankMap.get(hrefKey(b)) : 999;
      return aRank - bRank;
    });

    const insertionPoint = nav.querySelector('.help-btn, [data-help-toggle="true"], .auth-link');
    allLinks.forEach((link) => nav.insertBefore(link, insertionPoint || null));

    // Keep top-level label consistent with index.
    allLinks.forEach((link) => {
      if (hrefKey(link) === 'new_debate.html') {
        link.textContent = 'Post Argument';
      }
    });

    if (allLinks.length === 0) return;

    const details = document.createElement('details');
    details.className = 'nav-more';
    details.dataset.generated = 'true';

    const summary = document.createElement('summary');
    summary.textContent = 'More';

    const menu = document.createElement('div');
    menu.className = 'nav-more-menu';

    details.appendChild(summary);
    details.appendChild(menu);

    const menuInsertionPoint = nav.querySelector('.help-btn, [data-help-toggle="true"], .auth-link');
    nav.insertBefore(details, menuInsertionPoint || null);

    const overflowLinks = [];
    const moveToOverflow = (link) => {
      if (!link) return;
      overflowLinks.push(link);
      menu.appendChild(link);
    };

    allLinks.forEach((link) => {
      if (alwaysInMore.has(hrefKey(link))) {
        moveToOverflow(link);
      }
    });

    const getVisibleLinks = () => {
      return Array.from(nav.children).filter((element) => {
        return element.tagName === 'A' && !element.classList.contains('auth-link');
      });
    };

    while (nav.scrollWidth > nav.clientWidth) {
      const visibleLinks = getVisibleLinks();
      if (visibleLinks.length <= 1) break;

      const movableLinks = visibleLinks.filter((link) => hrefKey(link) !== currentPage);
      const linkToMove = movableLinks[movableLinks.length - 1] || visibleLinks[visibleLinks.length - 1];
      if (!linkToMove) break;
      overflowLinks.unshift(linkToMove);
      menu.prepend(linkToMove);
    }

    if (overflowLinks.length === 0) {
      details.remove();
      if (this.syncNavigationWrapState()) {
        this.scheduleNavigationRebalance();
      }
      return;
    }

    const hasActiveOverflowLink = overflowLinks.some((link) => {
      return link.classList.contains('active') || link.getAttribute('aria-current') === 'page';
    });
    summary.classList.toggle('active', hasActiveOverflowLink);
    if (this.syncNavigationWrapState()) {
      this.scheduleNavigationRebalance();
    }
  },

  /**
   * Toggle a class when the header wraps so CSS can left-align the second row.
   */
  syncNavigationWrapState() {
    const navShell = document.querySelector('.nav');
    const brand = navShell?.querySelector('.brand');
    const links = navShell?.querySelector('.navlinks');
    if (!navShell || !brand || !links) return;

    const brandBox = brand.getBoundingClientRect();
    const linksBox = links.getBoundingClientRect();
    const wrapped = linksBox.top >= brandBox.bottom - 2;
    const changed = navShell.classList.contains('nav-is-wrapped') !== wrapped;
    navShell.classList.toggle('nav-is-wrapped', wrapped);
    return changed;
  },

  /**
   * Run one follow-up nav normalization after wrap state changes.
   */
  scheduleNavigationRebalance() {
    if (this._navWrapSyncPending) return;
    this._navWrapSyncPending = true;
    requestAnimationFrame(() => {
      this._navWrapSyncPending = false;
      this.normalizeNavigation();
    });
  },

  /**
   * Close More menu when clicking outside nav
   */
  setupNavigationDismiss() {
    if (this._dismissNavBound) return;

    document.addEventListener('click', (event) => {
      document.querySelectorAll('.nav-more').forEach((menu) => {
        if (!menu.contains(event.target)) {
          menu.removeAttribute('open');
        }
      });
    });

    this._dismissNavBound = true;
  },

  /**
   * Rebalance visible nav links as viewport size changes.
   */
  setupNavigationResize() {
    if (this._navResizeBound) return;

    const rebalance = this.debounce(() => this.normalizeNavigation(), 120);
    window.addEventListener('resize', rebalance);
    if (document.fonts && document.fonts.ready) {
      document.fonts.ready.then(() => rebalance());
    }
    this._navResizeBound = true;
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
  },

  /**
   * Set button busy state with spinner.
   * Replaces button content with a spinner + label while busy.
   */
  setButtonBusy(button, isBusy, busyLabel) {
    if (!button) return;
    if (!button.dataset.defaultLabel) {
      button.dataset.defaultLabel = button.textContent.trim();
    }
    button.disabled = isBusy;
    button.setAttribute('aria-busy', String(isBusy));
    if (isBusy) {
      const label = this.escapeHtml(busyLabel || 'Processing...');
      button.innerHTML = `<span class="spinner" aria-label="Loading" role="status"></span> ${label}`;
    } else {
      button.textContent = button.dataset.defaultLabel;
    }
  },

  /**
   * Show an inline error message with an optional retry button.
   * WARNING: This replaces container.innerHTML. Do not pass containers
   * that contain form inputs you need to preserve.
   * @param {HTMLElement} container - Element to display error inside
   * @param {string} message - Error message
   * @param {Function|null} retryCallback - Called when retry button is clicked
   */
  showInlineError(container, message, retryCallback = null) {
    if (!container) return;
    const requestId = container.dataset.requestId || '';
    const safeMessage = this.escapeHtml(message || 'Something went wrong. Please try again.');
    const retryHtml = retryCallback
      ? `<button type="button" class="retry-btn" data-retry="true">Retry</button>`
      : '';
    container.innerHTML = `<div class="inline-error"><span>${safeMessage}</span>${retryHtml}</div>`;
    if (retryCallback) {
      const retryBtn = container.querySelector('[data-retry="true"]');
      if (retryBtn) {
        retryBtn.addEventListener('click', (e) => {
          e.preventDefault();
          retryCallback();
        });
      }
    }
    if (requestId) {
      console.error(`[request_id: ${requestId}]`, message);
    } else {
      console.error(message);
    }
  },

  /**
   * Clear an inline error from a container.
   */
  clearInlineError(container) {
    if (!container) return;
    const errorEl = container.querySelector('.inline-error');
    if (errorEl) errorEl.remove();
  },

  /**
   * Replace an element's children with skeleton placeholders.
   * @param {HTMLElement} element
   * @param {number} rows - number of skeleton bars
   */
  showSkeleton(element, rows = 1) {
    if (!element) return;
    element.dataset.originalContent = element.innerHTML;
    let html = '';
    for (let i = 0; i < rows; i++) {
      html += '<span class="skeleton skeleton-text-md"></span>';
    }
    element.innerHTML = html;
  },

  /**
   * Restore original content from skeleton state.
   */
  hideSkeleton(element) {
    if (!element) return;
    if (element.dataset.originalContent !== undefined) {
      element.innerHTML = element.dataset.originalContent;
      delete element.dataset.originalContent;
    }
  }
};

// Initialize on DOM ready
document.addEventListener('DOMContentLoaded', () => {
  BDA.init();
});

// Make available globally
window.BDA = BDA;

/**
 * DebateSelector — shared component for explicit debate selection
 * Works in both API mode and DataBridge/GitHub mode.
 */
const DebateSelector = {
  async init(containerId, options = {}) {
    const container = document.getElementById(containerId);
    if (!container) return;
    this.container = container;
    this.onSelect = options.onSelect || (() => {});
    this.allowActivate = options.allowActivate !== false;
    await this.render();
  },

  async fetchDebates() {
    // Try API first
    try {
      const data = await BDA.api('/api/debates', {
        preferLiveApi: true,
        suppressAuthRedirect: true,
      });
      if (data && data.debates && data.debates.length > 0) {
        return data.debates.map(d => ({
          debate_id: d.debate_id,
          motion: d.resolution || d.motion || 'Untitled',
          debate_frame: d.debate_frame || '',
        }));
      }
    } catch (e) {
      // Fall through to DataBridge
    }
    // DataBridge fallback
    if (typeof DataBridge !== 'undefined') {
      DataBridge.loadConfig();
      if (DataBridge.isConfigured()) {
        await DataBridge.ensureData();
        const d = DataBridge.getDebate();
        if (d && d.has_debate) {
          return [{
            debate_id: d.debate_id,
            motion: d.resolution || d.motion || 'Untitled',
            debate_frame: d.debate_frame || '',
          }];
        }
      }
    }
    return [];
  },

  async render() {
    const debates = await this.fetchDebates();
    const activeId = BDA.getActiveDebateId();

    if (debates.length === 0) {
      this.container.innerHTML = `
        <div class="callout soft">
          <p>No debates available. <a href="propose.html">Propose a debate</a> or ask an admin to create one.</p>
        </div>
      `;
      return;
    }

    const optionsHtml = debates.map(d => {
      const selected = d.debate_id === activeId ? ' selected' : '';
      return `<option value="${BDA.escapeHtml(d.debate_id)}"${selected}>${BDA.escapeHtml(d.motion)}</option>`;
    }).join('');

    this.container.innerHTML = `
      <div class="form-group form-group-no-margin">
        <label for="debate-selector-select">Select Active Debate</label>
        <div class="row row-gap-sm-items-end">
          <select id="debate-selector-select" class="debate-selector-select select-wide">
            ${optionsHtml}
          </select>
          ${this.allowActivate ? `<button class="button" id="debate-selector-activate" data-action="activate-debate">Activate</button>` : ''}
        </div>
      </div>
    `;
    const activateBtn = this.container.querySelector('#debate-selector-activate');
    if (activateBtn) {
      activateBtn.addEventListener('click', () => this.activate());
    }
  },

  async activate() {
    const select = document.getElementById('debate-selector-select');
    if (!select) return;
    const debateId = select.value;
    if (!debateId) return;

    try {
      await BDA.api(`/api/debate/${encodeURIComponent(debateId)}/activate`, {
        method: 'POST',
        suppressAuthRedirect: true,
      });
      BDA.setActiveDebateId(debateId);
      BDA.showStatus('Debate activated.');
      this.onSelect(debateId);
    } catch (error) {
      // If API fails (e.g., no auth in GitHub mode), just set locally
      BDA.setActiveDebateId(debateId);
      BDA.showStatus('Debate selected.');
      this.onSelect(debateId);
    }
  },
};

window.DebateSelector = DebateSelector;
