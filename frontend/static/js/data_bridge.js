/**
 * Data Bridge — GitHub-centric data layer for Blind Debate Adjudicator
 *
 * Replaces localhost API calls with:
 * 1. Config-driven GitHub raw URL fetching
 * 2. localStorage-based JSON caching
 * 3. Offline-capable rendering
 * 4. mailto: link generation for email submission
 */

const DataBridge = {
  CONFIG_KEY: 'bda_github_config',
  CACHE_KEY: 'bda_cached_results',
  CACHE_TIMESTAMP_KEY: 'bda_cache_timestamp',

  config: null,
  cache: null,
  isLoading: false,
  lastError: null,

  /**
   * Initialize and check configuration.
   * If not configured, redirect to setup.html (unless already on setup).
   */
  init() {
    this.loadConfig();
    const onSetup = window.location.pathname.endsWith('setup.html');
    if (!this.isConfigured() && !onSetup) {
      window.location.href = 'setup.html';
      return false;
    }
    this.loadCache();
    return true;
  },

  // ===================================================================
  // Configuration
  // ===================================================================

  loadConfig() {
    try {
      const raw = localStorage.getItem(this.CONFIG_KEY);
      if (raw) {
        this.config = JSON.parse(raw);
      }
    } catch (e) {
      console.warn('Failed to load config:', e);
      this.config = null;
    }
  },

  saveConfig(githubUrl, destEmail) {
    this.config = {
      githubUrl: githubUrl.trim(),
      destEmail: destEmail.trim(),
      configuredAt: new Date().toISOString(),
    };
    localStorage.setItem(this.CONFIG_KEY, JSON.stringify(this.config));
  },

  clearConfig() {
    this.config = null;
    localStorage.removeItem(this.CONFIG_KEY);
    localStorage.removeItem(this.CACHE_KEY);
    localStorage.removeItem(this.CACHE_TIMESTAMP_KEY);
    localStorage.removeItem('bda_active_debate_id');
  },

  isConfigured() {
    return !!(this.config && this.config.githubUrl && this.config.destEmail);
  },

  getGithubUrl() {
    return this.config?.githubUrl || '';
  },

  getDestEmail() {
    return this.config?.destEmail || '';
  },

  // ===================================================================
  // Cache
  // ===================================================================

  loadCache() {
    try {
      const raw = localStorage.getItem(this.CACHE_KEY);
      if (raw) {
        this.cache = JSON.parse(raw);
      }
    } catch (e) {
      console.warn('Failed to load cache:', e);
      this.cache = null;
    }
  },

  saveCache(data) {
    this.cache = data;
    try {
      localStorage.setItem(this.CACHE_KEY, JSON.stringify(data));
      localStorage.setItem(this.CACHE_TIMESTAMP_KEY, new Date().toISOString());
    } catch (e) {
      console.warn('Failed to save cache:', e);
    }
  },

  getCacheTimestamp() {
    return localStorage.getItem(this.CACHE_TIMESTAMP_KEY);
  },

  hasCache() {
    return this.cache !== null;
  },

  // ===================================================================
  // GitHub Fetch
  // ===================================================================

  async refreshFromGitHub() {
    if (!this.isConfigured()) {
      throw new Error('GitHub URL not configured');
    }

    const url = this.getGithubUrl();
    this.isLoading = true;
    this.lastError = null;

    try {
      const response = await fetch(url, {
        method: 'GET',
        cache: 'no-store',
      });

      if (!response.ok) {
        throw new Error(`GitHub fetch failed: HTTP ${response.status}`);
      }

      const data = await response.json();
      this.saveCache(data);
      this.isLoading = false;
      return data;
    } catch (error) {
      this.lastError = error.message || String(error);
      this.isLoading = false;
      throw error;
    }
  },

  /**
   * Ensure cache is loaded. If empty, attempt a refresh.
   */
  async ensureData() {
    if (this.hasCache()) {
      return this.cache;
    }
    return this.refreshFromGitHub();
  },

  // ===================================================================
  // Data Accessors (mirror existing API shapes)
  // ===================================================================

  getDebates() {
    const d = this.getDebate();
    if (!d.has_debate) {
      return { debates: [] };
    }
    return {
      debates: [{
        debate_id: d.debate_id,
        resolution: d.resolution,
        scope: d.scope,
        motion: d.motion,
        debate_frame: d.debate_frame,
        created_at: d.created_at,
        has_snapshot: d.has_snapshot,
      }]
    };
  },

  getDebate() {
    const data = this.cache;
    if (!data || !data.debate) {
      return { has_debate: false };
    }
    const snap = data.snapshot || {};
    const debate = data.debate;
    // Normalized shape: always expose debate_id, motion (with fallback), debate_frame
    const motion = debate.motion || debate.resolution || 'Untitled';
    return {
      has_debate: true,
      has_snapshot: !!snap.snapshot_id,
      debate_id: debate.debate_id,
      resolution: debate.resolution || motion,
      scope: debate.scope || '',
      motion: motion,
      debate_frame: debate.debate_frame || debate.frame_summary || '',
      created_at: debate.created_at,
      current_snapshot_id: debate.current_snapshot_id,
      snapshot_id: snap.snapshot_id,
      timestamp: snap.timestamp,
      trigger_type: snap.trigger_type,
      template_name: snap.template_name,
      template_version: snap.template_version,
      allowed_count: snap.allowed_count || 0,
      blocked_count: snap.blocked_count || 0,
      block_reasons: snap.block_reasons || {},
      borderline_rate: snap.borderline_rate || 0,
      suppression_policy: snap.suppression_policy || { k: 5, affected_buckets: [], affected_bucket_count: 0 },
      status: snap.status || 'valid',
      overall_for: snap.overall_for,
      overall_against: snap.overall_against,
      margin_d: snap.margin_d,
      ci_d: snap.ci_d,
      confidence: snap.confidence,
      verdict: snap.verdict || 'NO VERDICT',
    };
  },

  getSnapshot() {
    const data = this.cache;
    if (!data || !data.snapshot || !data.snapshot.snapshot_id) {
      return { has_snapshot: false };
    }
    return {
      has_snapshot: true,
      ...data.snapshot,
    };
  },

  getTopics() {
    const data = this.cache;
    if (!data || !data.topics) {
      return { topics: [] };
    }
    return { topics: data.topics };
  },

  getTopicDetail(topicId) {
    const data = this.cache;
    if (!data || !data.topic_details || !data.topic_details[topicId]) {
      return null;
    }
    return data.topic_details[topicId];
  },

  getVerdict() {
    const data = this.cache;
    if (!data || !data.verdict) {
      return {
        snapshot_id: null,
        overall_for: null,
        overall_against: null,
        margin_d: null,
        ci_d: null,
        confidence: null,
        verdict: 'NO VERDICT',
        topic_contributions: [],
      };
    }
    return data.verdict;
  },

  getAudits() {
    const data = this.cache;
    if (!data || !data.audits) {
      return {
        snapshot_id: null,
        timestamp: null,
        verdict: 'NO VERDICT',
        confidence: 0,
        topic_geometry: [],
        extraction_stability: {
          fact_overlap: {},
          argument_overlap: {},
          mismatches: [],
          num_runs: 0,
          stability_score: 0,
        },
        evaluator_disagreement: {
          reasoning_iqr_median: 0,
          coverage_iqr_median: 0,
          overall_iqr: 0,
        },
        label_symmetry: {
          median_delta_d: 0,
          abs_delta_d: 0,
          original_d: 0,
          swapped_d: 0,
          topic_deltas: {},
          interpretation: '',
        },
        relevance_sensitivity: {},
      };
    }
    return data.audits;
  },

  getDecisionDossier() {
    const data = this.cache;
    if (!data || !data.decision_dossier) {
      return {
        snapshot_id: data?.snapshot?.snapshot_id || null,
        verdict: data?.snapshot?.verdict || 'NO VERDICT',
        confidence: data?.snapshot?.confidence || 0,
        evidence_gaps: {},
        selection_diagnostics: {},
      };
    }
    return data.decision_dossier;
  },

  getEvidenceTargets() {
    const data = this.cache;
    if (!data || !data.evidence_targets) {
      return { gaps: [], targets: [] };
    }
    return data.evidence_targets;
  },

  getSnapshotHistory() {
    const data = this.cache;
    if (!data || !data.snapshot_history) {
      return { debate_id: null, snapshot_count: 0, snapshots: [] };
    }
    return data.snapshot_history;
  },

  getSnapshotDiff() {
    const data = this.cache;
    if (!data || !data.snapshot_diff) {
      return null;
    }
    return data.snapshot_diff;
  },

  getModulation() {
    const data = this.cache;
    if (!data || !data.modulation) {
      return {
        template_name: null,
        template_version: null,
        allowed_count: 0,
        blocked_count: 0,
      };
    }
    return data.modulation;
  },

  getPosts() {
    const data = this.cache;
    if (!data || !data.posts) {
      return { posts: [] };
    }
    return { posts: data.posts };
  },

  getFrame() {
    const data = this.cache;
    if (!data || !data.frame) {
      return null;
    }
    return data.frame;
  },

  getGovernanceFrames() {
    const data = this.cache;
    if (!data || !data.frame) {
      return { active_frame: null, frames: [], mode: 'single', review_schedule: [] };
    }
    return data.frame.active_frame ? data.frame : { active_frame: data.frame, frames: [data.frame], mode: data.frame.frame_mode || 'single', review_schedule: [] };
  },

  getFramePetitions() {
    const data = this.cache;
    return { petitions: data?.frame_petitions || [] };
  },

  // ===================================================================
  // Email Submission
  // ===================================================================

  /**
   * Build a mailto: link for submitting a post via email.
   */
  buildMailtoLink(debateId, resolution, side, topicId, facts, inference, counterArguments) {
    const destEmail = this.getDestEmail();
    if (!destEmail) {
      return null;
    }

    const cleanDebateId = (debateId || '').trim();
    const cleanResolution = (resolution || '').trim();
    if (!cleanDebateId || cleanDebateId === 'null' || cleanDebateId === 'undefined') {
      return null;
    }
    if (!cleanResolution || cleanResolution.toLowerCase() === 'untitled') {
      return null;
    }

    const parser = {
      buildEmailBody(debate_id, resolution, side, topic_id, facts, inference, counter_arguments) {
        const submissionId = self.crypto?.randomUUID
          ? self.crypto.randomUUID()
          : 'sub-' + Date.now();
        const submittedAt = new Date().toISOString();
        const lines = [
          'BDA Submission v1',
          `Debate-ID: ${debate_id}`,
          `Resolution: ${resolution}`,
          `Submission-ID: ${submissionId}`,
          `Submitted-At: ${submittedAt}`,
          `Position: ${side}`,
          `Topic-Area: ${topic_id}`,
          '',
          'Facts:',
          facts,
          '',
          'Inference:',
          inference,
        ];
        if (counter_arguments) {
          lines.push('', 'Counter-Arguments:', counter_arguments);
        }
        return lines.join('\n');
      }
    };

    const body = parser.buildEmailBody(
      cleanDebateId, cleanResolution, side, topicId, facts, inference, counterArguments
    );

    const subject = encodeURIComponent(`BDA Submission — ${side} — ${cleanDebateId}`);
    const encodedBody = encodeURIComponent(body);
    return `mailto:${destEmail}?subject=${subject}&body=${encodedBody}`;
  },

  // ===================================================================
  // UI Helpers
  // ===================================================================

  formatCacheAge() {
    const ts = this.getCacheTimestamp();
    if (!ts) return 'Never';
    const then = new Date(ts);
    const now = new Date();
    const diffMs = now - then;
    const diffSec = Math.floor(diffMs / 1000);
    if (diffSec < 60) return `${diffSec}s ago`;
    const diffMin = Math.floor(diffSec / 60);
    if (diffMin < 60) return `${diffMin}m ago`;
    const diffHr = Math.floor(diffMin / 60);
    if (diffHr < 24) return `${diffHr}h ago`;
    const diffDay = Math.floor(diffHr / 24);
    return `${diffDay}d ago`;
  },

  showOfflineBanner() {
    const banner = document.getElementById('offline-banner');
    if (banner) {
      banner.style.display = 'block';
    }
  },

  hideOfflineBanner() {
    const banner = document.getElementById('offline-banner');
    if (banner) {
      banner.style.display = 'none';
    }
  },
};

// ===================================================================
// Monkey-patch BDA.api() for hard cutover to GitHub mode
// ===================================================================

(function patchBDA() {
  // Wait until BDA is available
  function applyPatch() {
    if (typeof BDA === 'undefined' || !BDA.api) {
      setTimeout(applyPatch, 50);
      return;
    }

    const originalApi = BDA.api.bind(BDA);
    const originalLoadDebate = BDA.loadDebate.bind(BDA);
    const originalLoadSnapshot = BDA.loadSnapshot.bind(BDA);
    const originalLoadDebates = BDA.loadDebates.bind(BDA);

    BDA.api = async function(endpoint, options = {}) {
      DataBridge.loadConfig();
      if (!DataBridge.isConfigured()) {
        return originalApi(endpoint, options);
      }

      // Ensure cache is loaded
      if (!DataBridge.hasCache()) {
        try {
          await DataBridge.refreshFromGitHub();
        } catch (e) {
          console.warn('DataBridge fetch failed, falling back to cache:', e);
        }
      }

      // Map endpoints to cached data
      if (endpoint === '/api/debate' || endpoint.startsWith('/api/debate?')) {
        return DataBridge.getDebate();
      }
      if (endpoint === '/api/debate/snapshot') {
        return DataBridge.getSnapshot();
      }
      if (endpoint === '/api/debates') {
        return DataBridge.getDebates();
      }
      if (endpoint === '/api/debate/topics') {
        return DataBridge.getTopics();
      }
      if (endpoint === '/api/debate/verdict') {
        return DataBridge.getVerdict();
      }
      if (endpoint === '/api/debate/audits') {
        return DataBridge.getAudits();
      }
      if (endpoint === '/api/debate/decision-dossier') {
        return DataBridge.getDecisionDossier();
      }
      if (endpoint === '/api/governance/frames') {
        return DataBridge.getGovernanceFrames();
      }
      if (endpoint.includes('/frame-petitions')) {
        return DataBridge.getFramePetitions();
      }
      if (endpoint === '/api/debate/evidence-targets') {
        return DataBridge.getEvidenceTargets();
      }
      if (endpoint === '/api/debate/snapshot-history') {
        return DataBridge.getSnapshotHistory();
      }
      if (endpoint === '/api/debate/snapshot-diff') {
        return DataBridge.getSnapshotDiff() || {};
      }
      if (endpoint === '/api/debate/posts') {
        if (options.method === 'POST') {
          // In hard cutover, POSTs should go through email
          throw new Error('Use email submission in GitHub mode.');
        }
        return DataBridge.getPosts();
      }
      if (endpoint.startsWith('/api/debate/topics/')) {
        const topicId = endpoint.split('/').pop();
        return DataBridge.getTopicDetail(topicId);
      }

      // Fallback for unmapped endpoints
      console.warn('DataBridge: unmapped endpoint, falling back to API:', endpoint);
      return originalApi(endpoint, options);
    };

    BDA.loadDebate = async function() {
      DataBridge.loadConfig();
      if (DataBridge.isConfigured()) {
        await DataBridge.ensureData();
        const d = DataBridge.getDebate();
        BDA.state.currentDebate = d.has_debate ? d : null;
        if (d.debate_id) BDA.setActiveDebateId(d.debate_id);
        return d;
      }
      return originalLoadDebate();
    };

    BDA.loadSnapshot = async function() {
      DataBridge.loadConfig();
      if (DataBridge.isConfigured()) {
        await DataBridge.ensureData();
        const s = DataBridge.getSnapshot();
        BDA.state.currentSnapshot = s.has_snapshot ? s : null;
        return s;
      }
      return originalLoadSnapshot();
    };

    BDA.loadDebates = async function() {
      DataBridge.loadConfig();
      if (DataBridge.isConfigured()) {
        await DataBridge.ensureData();
        const d = DataBridge.getDebate();
        return {
          debates: d.has_debate ? [{
            debate_id: d.debate_id,
            resolution: d.resolution,
            scope: d.scope,
            created_at: d.created_at,
            has_snapshot: d.has_snapshot,
          }] : []
        };
      }
      return originalLoadDebates();
    };
  }

  applyPatch();
})();

// Auto-redirect unconfigured users to setup
(function autoRedirect() {
  const path = window.location.pathname;
  const skipPages = ['setup.html', 'login.html', 'register.html', 'about.html', 'index.html'];
  if (skipPages.some(p => path.endsWith(p))) return;
  DataBridge.loadConfig();
  if (!DataBridge.isConfigured()) {
    window.location.href = 'setup.html';
  }
})();

// Make available globally
window.DataBridge = DataBridge;
