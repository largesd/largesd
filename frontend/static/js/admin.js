    (function gateAdminRouteBeforePaint() {
      const root = document.documentElement;
      root.classList.add('route-auth-pending');
      root.setAttribute('aria-busy', 'true');
      try {
        const token = localStorage.getItem('access_token');
        const userJson = localStorage.getItem('user');
        const user = userJson ? JSON.parse(userJson) : null;
        if (!token || !user || !user.is_admin) {
          const next = `${window.location.pathname || '/admin.html'}${window.location.search || ''}${window.location.hash || ''}`;
          const params = new URLSearchParams();
          params.set('reason', 'admin-login-required');
          params.set('next', next);
          window.location.replace(`login.html?${params.toString()}`);
        }
      } catch (error) {
        window.location.replace('login.html?reason=admin-login-required');
      }
    })();

  const AdminState = {
    currentTemplate: null,
    history: [],
    availableBases: [],
    currentWorkspace: 'policy',
    hasLiveData: false,
  };

  BDA.registerAction('save-draft', saveDraft);
  BDA.registerAction('apply-template', applyTemplate);
  BDA.registerAction('cancel-proposal-decision', cancelProposalDecision);
  BDA.registerAction('confirm-proposal-decision', confirmProposalDecision);
  BDA.registerAction('accept-proposal', (el) => acceptProposal(el.dataset.proposalId));
  BDA.registerAction('show-reject-panel', (el) => showRejectPanel(el.dataset.proposalId));
  BDA.registerAction('open-fact-check-audit', (el) => openFactCheckAudit(el.dataset.premiseId));

  const WORKSPACE_ORDER = ['policy', 'review', 'audit', 'frames', 'hr'];
  const WORKSPACE_HASH_MAP = {
    'workspace-policy': 'policy',
    'workspace-review': 'review',
    'workspace-audit': 'audit',
    'workspace-frames': 'frames',
    'workspace-hr': 'hr',
    'template-selection': 'policy',
    'guardrails': 'policy',
    'preview': 'policy',
    'history': 'policy',
    'proposal-review': 'review',
    'snapshot-audit': 'audit',
    'frame-petition-queue': 'frames',
    'human-review-queue': 'hr',
  };

  const POLICY_INPUT_IDS = [
    'template-base',
    'template-version',
    'topic-keywords',
    'topic-threshold',
    'enforce-scope',
    'toxicity-level',
    'toxicity-block-personal-attacks',
    'toxicity-block-hate-speech',
    'toxicity-block-threats',
    'toxicity-block-sexual-harassment',
    'toxicity-block-mild-profanity',
    'pii-detect-email',
    'pii-detect-phone',
    'pii-detect-address',
    'pii-detect-full-names',
    'pii-detect-social-handles',
    'pii-action',
    'min-length',
    'max-length',
    'flood-threshold',
    'duplicate-detection',
    'rate-limiting',
    'injection-protection',
    'injection-block-markdown',
    'injection-patterns',
  ];

  function setText(id, value) {
    const node = document.getElementById(id);
    if (node) node.textContent = value;
  }

  function sanitizeUiMessage(message, fallback = 'Something went wrong while loading admin data.') {
    const raw = String(message || '').trim();
    if (!raw) return fallback;
    if (/<!doctype html>|<html|<body|<head/i.test(raw)) {
      return 'Live admin data could not load from this server. Open the application backend to review current templates, queues, and audit data.';
    }
    return raw.replace(/\s+/g, ' ');
  }

  function setHeroConnectionState(text, { hasLiveData = AdminState.hasLiveData } = {}) {
    const node = document.getElementById('hero-data-state');
    if (!node) return;
    node.textContent = text;
    node.className = hasLiveData ? 'metric-good' : '';
  }

  function updateHeroSummary(activeTemplate = AdminState.currentTemplate) {
    const templateName = activeTemplate?.template_name || activeTemplate?.base_template_id || 'No live template loaded';
    setText('hero-current-template', templateName);
    setText('hero-active-version', activeTemplate?.version ? `v${activeTemplate.version}` : '—');
    const historyCount = AdminState.history.length;
    setText('hero-history-depth', historyCount ? `${historyCount} version${historyCount === 1 ? '' : 's'} tracked` : 'No history loaded yet');
    setHeroConnectionState(
      AdminState.hasLiveData ? 'Live admin data connected' : 'Preview mode only'
    );
  }

  function setWorkspaceMeta(id, text) {
    setText(id, text);
  }

  function resolveWorkspaceFromHash(hashValue) {
    const normalized = String(hashValue || '').replace(/^#/, '');
    return WORKSPACE_HASH_MAP[normalized] || 'policy';
  }

  function setActiveWorkspace(workspaceName, options = {}) {
    const nextWorkspace = WORKSPACE_ORDER.includes(workspaceName) ? workspaceName : 'policy';
    AdminState.currentWorkspace = nextWorkspace;

    document.querySelectorAll('.admin-workspace-tab').forEach((tab) => {
      const isActive = tab.dataset.workspaceTarget === nextWorkspace;
      tab.setAttribute('aria-selected', isActive ? 'true' : 'false');
      tab.tabIndex = isActive ? 0 : -1;
    });

    document.querySelectorAll('.admin-workspace').forEach((panel) => {
      panel.hidden = panel.id !== `workspace-${nextWorkspace}`;
    });

    if (options.updateHash) {
      window.history.replaceState(null, '', `#workspace-${nextWorkspace}`);
    }

    if (options.scrollIntoView) {
      const panel = document.getElementById(`workspace-${nextWorkspace}`);
      if (panel) panel.scrollIntoView({ block: 'start', behavior: 'smooth' });
    }
  }

  function bindWorkspaceTabs() {
    const tabs = Array.from(document.querySelectorAll('.admin-workspace-tab'));
    tabs.forEach((tab, index) => {
      tab.addEventListener('click', () => {
        setActiveWorkspace(tab.dataset.workspaceTarget || 'policy', { updateHash: true, scrollIntoView: true });
      });
      tab.addEventListener('keydown', (event) => {
        if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
        event.preventDefault();
        let nextIndex = index;
        if (event.key === 'ArrowRight') nextIndex = (index + 1) % tabs.length;
        if (event.key === 'ArrowLeft') nextIndex = (index - 1 + tabs.length) % tabs.length;
        if (event.key === 'Home') nextIndex = 0;
        if (event.key === 'End') nextIndex = tabs.length - 1;
        tabs[nextIndex].focus();
        setActiveWorkspace(tabs[nextIndex].dataset.workspaceTarget || 'policy', { updateHash: true });
      });
    });

    window.addEventListener('hashchange', () => {
      const normalizedHash = String(window.location.hash || '').replace(/^#/, '');
      setActiveWorkspace(resolveWorkspaceFromHash(window.location.hash));
      const target = normalizedHash ? document.getElementById(normalizedHash) : null;
      if (target) target.scrollIntoView({ block: 'start', behavior: 'smooth' });
    });
  }

  function bindPolicyInputs() {
    POLICY_INPUT_IDS.forEach((id) => {
      const node = document.getElementById(id);
      if (!node) return;
      node.addEventListener('input', loadTemplatePreview);
      node.addEventListener('change', loadTemplatePreview);
    });
  }

  function bindProposalFilter() {
    const filter = document.getElementById('proposal-filter');
    if (!filter) return;
    filter.addEventListener('change', loadProposals);
  }

  function releaseRouteAuthGate() {
    const root = document.documentElement;
    root.classList.remove('route-auth-pending');
    root.removeAttribute('aria-busy');
  }

  function showAdminAccessDenied(error) {
    const page = document.querySelector('.admin-page');
    const panel = document.getElementById('admin-access-denied');
    const copy = document.getElementById('admin-access-denied-copy');
    const detail = document.getElementById('admin-access-denied-detail');
    if (!page || !panel || !copy || !detail) return;

    const status = Number(error?.status || 0);
    const code = String(error?.code || '');
    const isForbidden = status === 403 || code === 'ADMIN_FORBIDDEN';

    if (isForbidden) {
      copy.textContent = 'You are signed in, but this account does not have permission to use admin tools.';
      detail.textContent = 'Use a different account with admin privileges, or ask an existing admin to grant access.';
    } else {
      copy.textContent = 'Admin tools require a valid signed-in session.';
      detail.textContent = 'Please sign in again and then retry opening the admin page.';
    }

    page.classList.add('admin-locked');
  }

  function setActionFeedback(message, kind = 'success') {
    const feedback = document.getElementById('admin-action-feedback');
    if (!feedback) return;
    feedback.hidden = false;
    const safeMessage = sanitizeUiMessage(
      message,
      kind === 'loading'
        ? 'Loading admin state...'
        : 'Admin feedback is unavailable right now.'
    );
    if (kind === 'loading') {
      feedback.innerHTML = `<span class="spinner" aria-label="Loading" role="status"></span> ${BDA.escapeHtml(safeMessage)}`;
    } else {
      feedback.textContent = safeMessage;
    }
    feedback.className = 'notice';
    if (kind === 'loading') feedback.classList.add('is-loading');
    if (kind === 'success') feedback.classList.add('alert-success');
    if (kind === 'error') feedback.classList.add('alert-error');
  }

  function setActionButtonsDisabled(disabled) {
    const saveBtn = document.getElementById('save-draft-btn');
    const applyBtn = document.getElementById('apply-template-btn');
    if (typeof BDA !== 'undefined' && typeof BDA.setButtonBusy === 'function') {
      if (saveBtn) BDA.setButtonBusy(saveBtn, disabled, 'Saving...');
      if (applyBtn) BDA.setButtonBusy(applyBtn, disabled, 'Applying...');
    } else {
      if (saveBtn) saveBtn.disabled = disabled;
      if (applyBtn) applyBtn.disabled = disabled;
    }
  }

  function setInputValue(id, value) {
    const node = document.getElementById(id);
    if (node) node.value = value;
  }

  function setInputChecked(id, checked) {
    const node = document.getElementById(id);
    if (node) node.checked = !!checked;
  }

  function normalizeListInput(value) {
    if (Array.isArray(value)) {
      return value.filter(Boolean).map((item) => String(item).trim()).filter(Boolean);
    }
    if (typeof value === 'string') {
      return value
        .split(/[\n,;]/)
        .map((item) => item.trim())
        .filter(Boolean);
    }
    return [];
  }

  function listEquals(a, b) {
    const left = normalizeListInput(a);
    const right = normalizeListInput(b);
    return left.length === right.length && left.every((value, index) => value === right[index]);
  }

  function formatListPreview(items, limit = 3) {
    const normalized = normalizeListInput(items);
    if (!normalized.length) return 'No required keywords added yet.';
    const preview = normalized.slice(0, limit).join(', ');
    return normalized.length > limit ? `${preview}, +${normalized.length - limit} more` : preview;
  }

  function renderList(id, items, emptyLabel) {
    const node = document.getElementById(id);
    if (!node) return;
    const safeItems = Array.isArray(items) && items.length ? items : [emptyLabel];
    node.innerHTML = safeItems.map((item) => `<li>${BDA.escapeHtml(item)}</li>`).join('');
  }

  function getToxicitySummary(level) {
    const normalized = Number(level || 3);
    if (normalized <= 1) return 'Permissive, allows sharper rhetoric unless it becomes clearly abusive.';
    if (normalized === 2) return 'Open, but still catches direct harassment and obvious intimidation.';
    if (normalized === 3) return 'Balanced, blocks clear harassment and allows vigorous debate.';
    if (normalized === 4) return 'Tight, escalates borderline aggression faster and expects more civility.';
    return 'Strict, prioritizes calm discourse and blocks even softer forms of hostile language.';
  }

  function collectTemplatePayloadForPreview() {
    try {
      return collectTemplatePayload();
    } catch (error) {
      return null;
    }
  }

  function buildAllowedPreview(payload) {
    const items = [];
    const topic = payload.topic_requirements || {};
    const toxicity = payload.toxicity_settings || {};
    const pii = payload.pii_settings || {};
    const spam = payload.spam_rate_limit_settings || {};
    const prompt = payload.prompt_injection_settings || {};
    const keywords = normalizeListInput(topic.required_keywords);

    items.push(
      topic.relevance_threshold === 'strict'
        ? 'Posts that directly address the resolution and stay close to the stated scope.'
        : topic.relevance_threshold === 'permissive'
          ? 'Posts that stay related to the debate, even when they explore adjacent context.'
          : 'Posts that stay meaningfully related to the debate scope.'
    );
    if (keywords.length) {
      items.push(`Posts that mention at least one required phrase: ${formatListPreview(keywords)}.`);
    }
    if (topic.enforce_scope) {
      items.push('Arguments that stay within the debate definition and scope boundaries.');
    }
    items.push(
      toxicity.block_mild_profanity
        ? 'Firm disagreement that avoids profanity, harassment, and identity-based attacks.'
        : 'Vigorous disagreement is allowed when it stays respectful and does not become abusive.'
    );
    items.push(`Substantive posts between ${spam.min_length || 0} and ${spam.max_length || 0} characters.`);
    if (pii.action === 'redact') {
      items.push('Posts with removable personal details can proceed after those details are redacted.');
    } else if (pii.action === 'flag') {
      items.push('Posts that trigger PII detection can move into manual review instead of immediate blocking.');
    }
    if (prompt.enabled) {
      items.push(
        prompt.block_markdown_hiding
          ? 'Normal evidence formatting remains allowed, but content cannot hide attempts to steer the adjudicator.'
          : 'Participants can use normal formatting, provided they do not try to manipulate system instructions.'
      );
    }
    return items.slice(0, 6);
  }

  function buildBlockedPreview(payload) {
    const items = [];
    const topic = payload.topic_requirements || {};
    const toxicity = payload.toxicity_settings || {};
    const pii = payload.pii_settings || {};
    const spam = payload.spam_rate_limit_settings || {};
    const prompt = payload.prompt_injection_settings || {};
    const piiTypes = [];

    if (toxicity.block_personal_attacks) items.push('Personal attacks and ad hominem language.');
    if (toxicity.block_hate_speech) items.push('Hate speech, discriminatory language, and targeted dehumanization.');
    if (toxicity.block_threats) items.push('Threats, intimidation, or coercive language.');
    if (toxicity.block_sexual_harassment) items.push('Sexual harassment or sexualized abuse.');
    if (toxicity.block_mild_profanity) items.push('Profanity that would otherwise be tolerated under a looser setting.');

    if (pii.detect_email) piiTypes.push('email addresses');
    if (pii.detect_phone) piiTypes.push('phone numbers');
    if (pii.detect_address) piiTypes.push('physical addresses');
    if (pii.detect_full_names) piiTypes.push('full names');
    if (pii.detect_social_handles) piiTypes.push('social handles');
    if (piiTypes.length) {
      const actionText = pii.action === 'redact'
        ? 'will be redacted before the post is allowed'
        : pii.action === 'flag'
          ? 'will trigger manual review'
          : 'will cause the full post to be blocked';
      items.push(`Detected ${piiTypes.join(', ')} ${actionText}.`);
    }

    if (topic.enforce_scope || topic.relevance_threshold !== 'permissive') {
      items.push(
        topic.relevance_threshold === 'strict'
          ? 'Posts that drift away from the resolution or fail to address it directly.'
          : 'Posts that fall outside the defined debate scope or read as off-topic.'
      );
    }
    if (spam.duplicate_detection || spam.rate_limiting) {
      items.push('Duplicate, flooding, or rate-limited submissions that look like spam rather than debate.');
    }
    if (prompt.enabled) {
      items.push('Attempts to manipulate system instructions, prompt state, or hidden adjudication behavior.');
    }
    return items.slice(0, 7);
  }

  function buildDraftChangeList(payload, activeTemplate) {
    if (!payload) {
      return ['Select a base template to generate a draft change summary.'];
    }

    if (!activeTemplate) {
      return ['Live template data is unavailable, so this draft is being previewed without a server-side baseline.'];
    }

    const changes = [];
    const activeTopic = activeTemplate.topic_requirements || {};
    const activeToxicity = activeTemplate.toxicity_settings || {};
    const activePii = activeTemplate.pii_settings || {};
    const activeSpam = activeTemplate.spam_rate_limit_settings || {};
    const activePrompt = activeTemplate.prompt_injection_settings || {};

    if (payload.base_template_id !== activeTemplate.base_template_id) {
      changes.push(`Base template changes from ${activeTemplate.template_name || activeTemplate.base_template_id} to ${payload.template_name}.`);
    }
    if (payload.version !== String(activeTemplate.version || '')) {
      changes.push(`Version label changes from ${activeTemplate.version || '—'} to ${payload.version}.`);
    }
    if (payload.topic_requirements.relevance_threshold !== (activeTopic.relevance_threshold || 'moderate')) {
      changes.push(`Topic relevance moves to ${payload.topic_requirements.relevance_threshold} review.`);
    }
    if (!listEquals(payload.topic_requirements.required_keywords, activeTopic.required_keywords)) {
      changes.push(`Required keywords update to ${formatListPreview(payload.topic_requirements.required_keywords)}.`);
    }
    if (!!payload.topic_requirements.enforce_scope !== !!activeTopic.enforce_scope) {
      changes.push(payload.topic_requirements.enforce_scope
        ? 'Scope boundaries become stricter and will be enforced from the debate definition.'
        : 'Scope boundaries become looser and off-topic handling will rely more on relevance scoring.');
    }
    if (Number(payload.toxicity_settings.sensitivity_level || 3) !== Number(activeToxicity.sensitivity_level || 3)) {
      changes.push(`Toxicity sensitivity shifts to level ${payload.toxicity_settings.sensitivity_level}.`);
    }
    if (payload.pii_settings.action !== (activePii.action || 'block')) {
      changes.push(`PII handling changes to ${payload.pii_settings.action}.`);
    }
    if (Number(payload.spam_rate_limit_settings.flood_threshold_per_hour || 0) !== Number(activeSpam.flood_threshold_per_hour || 0)) {
      changes.push(`Flooding threshold changes to ${payload.spam_rate_limit_settings.flood_threshold_per_hour} posts per hour.`);
    }
    if (payload.prompt_injection_settings.enabled !== !!activePrompt.enabled) {
      changes.push(payload.prompt_injection_settings.enabled
        ? 'Prompt injection detection becomes active for the next snapshot.'
        : 'Prompt injection detection is turned off for the next snapshot.');
    }
    if (!listEquals(payload.prompt_injection_settings.custom_patterns, activePrompt.custom_patterns)) {
      const patternCount = normalizeListInput(payload.prompt_injection_settings.custom_patterns).length;
      changes.push(patternCount
        ? `${patternCount} custom prompt-pattern check${patternCount === 1 ? '' : 's'} will be applied.`
        : 'Custom prompt-pattern checks are cleared from this draft.');
    }

    return changes.length ? changes.slice(0, 6) : ['No draft changes detected against the active template.'];
  }

  function renderDraftSummary(payload, { isActiveTemplate, selectedLabel }) {
    const readiness = !payload
      ? 'Selection required before draft review.'
      : isActiveTemplate
        ? 'Matches the active policy, no unpublished changes.'
        : 'Draft differs from the active policy and is ready for review.';

    setText('summary-selected-template', selectedLabel || 'Choose a template to begin.');
    setText('summary-version', payload?.version || '—');
    setText(
      'summary-readiness',
      readiness
    );
    setText(
      'summary-scope',
      isActiveTemplate
        ? 'No new version pending. Applying again would republish the current policy state.'
        : 'If published, this draft affects future snapshots only and remains visible in the audit trail.'
    );
    setText(
      'summary-policy-note',
      isActiveTemplate
        ? 'You are currently looking at the active policy. Change a guardrail only when you have a concrete reason to move it.'
        : 'This draft now differs from the active policy. Make sure the participant-facing summary still reads as intentional, fair, and easy to predict.'
    );
  }

  function collectTemplatePayload() {
    const baseSelect = document.getElementById('template-base');
    const versionInput = document.getElementById('template-version');
    const selectedOption = baseSelect?.options?.[baseSelect.selectedIndex];
    const baseTemplateId = (baseSelect?.value || '').trim();

    if (!baseTemplateId) {
      throw new Error('Select a base template before saving or applying.');
    }

    const version = (versionInput?.value || '').trim() || '1.0.0';
    const customPatterns = normalizeListInput(document.getElementById('injection-patterns')?.value || '');
    const requiredKeywords = normalizeListInput(document.getElementById('topic-keywords')?.value || '');

    return {
      base_template_id: baseTemplateId,
      template_name: selectedOption?.textContent?.trim() || baseTemplateId,
      version,
      notes: 'Updated from admin UI',
      topic_requirements: {
        required_keywords: requiredKeywords,
        relevance_threshold: document.getElementById('topic-threshold')?.value || 'moderate',
        enforce_scope: !!document.getElementById('enforce-scope')?.checked,
      },
      toxicity_settings: {
        sensitivity_level: Number(document.getElementById('toxicity-level')?.value || 3),
        block_personal_attacks: !!document.getElementById('toxicity-block-personal-attacks')?.checked,
        block_hate_speech: !!document.getElementById('toxicity-block-hate-speech')?.checked,
        block_threats: !!document.getElementById('toxicity-block-threats')?.checked,
        block_sexual_harassment: !!document.getElementById('toxicity-block-sexual-harassment')?.checked,
        block_mild_profanity: !!document.getElementById('toxicity-block-mild-profanity')?.checked,
      },
      pii_settings: {
        detect_email: !!document.getElementById('pii-detect-email')?.checked,
        detect_phone: !!document.getElementById('pii-detect-phone')?.checked,
        detect_address: !!document.getElementById('pii-detect-address')?.checked,
        detect_full_names: !!document.getElementById('pii-detect-full-names')?.checked,
        detect_social_handles: !!document.getElementById('pii-detect-social-handles')?.checked,
        action: document.getElementById('pii-action')?.value || 'block',
      },
      spam_rate_limit_settings: {
        min_length: Number(document.getElementById('min-length')?.value || 50),
        max_length: Number(document.getElementById('max-length')?.value || 5000),
        flood_threshold_per_hour: Number(document.getElementById('flood-threshold')?.value || 10),
        duplicate_detection: !!document.getElementById('duplicate-detection')?.checked,
        rate_limiting: !!document.getElementById('rate-limiting')?.checked,
      },
      prompt_injection_settings: {
        enabled: !!document.getElementById('injection-protection')?.checked,
        block_markdown_hiding: !!document.getElementById('injection-block-markdown')?.checked,
        custom_patterns: customPatterns,
      },
    };
  }

  function populateBaseTemplateOptions(availableBases, activeBaseTemplateId) {
    const baseSelect = document.getElementById('template-base');
    if (!baseSelect) return;

    const selectedBefore = baseSelect.value || activeBaseTemplateId || 'standard_civility';
    const options = (availableBases || []).slice();

    const hasCustom = options.some((item) => item.template_id === 'custom');
    if (!hasCustom) {
      options.push({
        template_id: 'custom',
        name: 'Custom Configuration',
        description: 'Saved custom configuration',
      });
    }

    baseSelect.innerHTML = '';
    options.forEach((item) => {
      const option = document.createElement('option');
      option.value = item.template_id;
      option.textContent = item.name;
      baseSelect.appendChild(option);
    });

    if ([...baseSelect.options].some((opt) => opt.value === selectedBefore)) {
      baseSelect.value = selectedBefore;
    } else if ([...baseSelect.options].some((opt) => opt.value === activeBaseTemplateId)) {
      baseSelect.value = activeBaseTemplateId;
    } else if (baseSelect.options.length > 0) {
      baseSelect.selectedIndex = 0;
    }
  }

  function applyTemplateToForm(template) {
    if (!template) return;

    AdminState.currentTemplate = template;
    const topic = template.topic_requirements || {};
    const toxicity = template.toxicity_settings || {};
    const pii = template.pii_settings || {};
    const spam = template.spam_rate_limit_settings || {};
    const prompt = template.prompt_injection_settings || {};

    setInputValue('template-version', template.version || '1.0.0');
    setInputValue('topic-keywords', normalizeListInput(topic.required_keywords).join(', '));
    setInputValue('topic-threshold', topic.relevance_threshold || 'moderate');
    setInputChecked('enforce-scope', topic.enforce_scope);

    setInputValue('toxicity-level', String(toxicity.sensitivity_level ?? 3));
    setInputChecked('toxicity-block-personal-attacks', toxicity.block_personal_attacks);
    setInputChecked('toxicity-block-hate-speech', toxicity.block_hate_speech);
    setInputChecked('toxicity-block-threats', toxicity.block_threats);
    setInputChecked('toxicity-block-sexual-harassment', toxicity.block_sexual_harassment);
    setInputChecked('toxicity-block-mild-profanity', toxicity.block_mild_profanity);

    setInputChecked('pii-detect-email', pii.detect_email);
    setInputChecked('pii-detect-phone', pii.detect_phone);
    setInputChecked('pii-detect-address', pii.detect_address);
    setInputChecked('pii-detect-full-names', pii.detect_full_names);
    setInputChecked('pii-detect-social-handles', pii.detect_social_handles);
    setInputValue('pii-action', pii.action || 'block');

    setInputValue('min-length', String(spam.min_length ?? 50));
    setInputValue('max-length', String(spam.max_length ?? 5000));
    setInputValue('flood-threshold', String(spam.flood_threshold_per_hour ?? 10));
    setInputChecked('duplicate-detection', spam.duplicate_detection);
    setInputChecked('rate-limiting', spam.rate_limiting);

    setInputChecked('injection-protection', prompt.enabled);
    setInputChecked('injection-block-markdown', prompt.block_markdown_hiding);
    setInputValue('injection-patterns', normalizeListInput(prompt.custom_patterns).join('\n'));

    const baseSelect = document.getElementById('template-base');
    if (baseSelect && template.base_template_id && [...baseSelect.options].some((opt) => opt.value === template.base_template_id)) {
      baseSelect.value = template.base_template_id;
    }

    setText('toxicity-summary', getToxicitySummary(toxicity.sensitivity_level ?? 3));
  }

  function getReasonPillClass(reason) {
    const normalized = String(reason || '').toLowerCase();
    if (normalized.includes('toxicity') || normalized.includes('harassment')) return 'bad';
    if (normalized.includes('pii') || normalized.includes('off_topic')) return 'warn';
    return '';
  }

  function renderModerationOutcomes(data) {
    const outcomes = data || {};
    const allowed = Number(outcomes.allowed_count || 0);
    const blocked = Number(outcomes.blocked_count || 0);
    const topReason = outcomes.top_reason ? String(outcomes.top_reason) : '—';
    const blockRatePercent = `${((Number(outcomes.block_rate || 0)) * 100).toFixed(1)}%`;

    document.getElementById('metric-allowed-posts').textContent = String(allowed);
    document.getElementById('metric-blocked-posts').textContent = String(blocked);
    document.getElementById('metric-block-rate').textContent = blockRatePercent;
    document.getElementById('metric-top-reason').textContent = topReason === '—' ? topReason : topReason.replace(/_/g, ' ');
    document.getElementById('metric-borderline-rate').textContent = Number(outcomes.borderline_rate || 0).toFixed(4);
    const suppression = outcomes.suppression_policy || {};
    document.getElementById('metric-suppression-policy').textContent = `k=${suppression.k || 5}`;
    setWorkspaceMeta(
      'workspace-tab-audit-meta',
      allowed || blocked ? `${blockRatePercent} block rate` : 'No snapshot data yet'
    );
    const affected = suppression.affected_buckets || [];
    document.getElementById('suppression-policy-detail').textContent = affected.length
      ? `${affected.length} bucket(s) suppressed: ${affected.map((bucket) => `${bucket.channel}:${bucket.key}`).join(', ')}`
      : 'No suppressed buckets in the current snapshot.';

    const tbody = document.getElementById('block-reasons-tbody');
    const rows = Array.isArray(outcomes.block_reasons) ? outcomes.block_reasons : [];
    if (!rows.length) {
      tbody.innerHTML = '<tr><td colspan="4" class="text-center-muted">No moderation snapshot data available yet.</td></tr>';
      return;
    }

    tbody.innerHTML = rows.map((row) => {
      const reason = String(row.reason || 'unknown');
      const count = Number(row.count || 0);
      const percentage = Number(row.percentage || 0).toFixed(1);
      const description = row.description ? BDA.escapeHtml(row.description) : 'Moderation rule triggered.';
      const pillClass = getReasonPillClass(reason);
      return `
        <tr>
          <td data-label="Reason Code"><span class="pill ${pillClass}">${BDA.escapeHtml(reason.toUpperCase())}</span></td>
          <td class="mono" data-label="Count">${count}</td>
          <td data-label="Percentage">${percentage}%</td>
          <td data-label="Description">${description}</td>
        </tr>
      `;
    }).join('');
  }

  let activeProposalId = null;
  let activeDecisionAction = null;

  async function loadFramePetitions() {
    const tbody = document.getElementById('frame-petitions-tbody');
    if (!tbody) return;
    try {
      const debate = await BDA.loadDebate();
      if (!debate?.debate_id) {
        setWorkspaceMeta('workspace-tab-frames-meta', 'No active debate selected');
        tbody.innerHTML = '<tr><td colspan="4" class="text-center-muted">No active debate selected.</td></tr>';
        return;
      }
      const response = await BDA.api(`/api/debate/${encodeURIComponent(debate.debate_id)}/frame-petitions`, { suppressAuthRedirect: true });
      const petitions = response.petitions || [];
      setWorkspaceMeta(
        'workspace-tab-frames-meta',
        petitions.length ? `${petitions.length} petition${petitions.length === 1 ? '' : 's'} in queue` : 'No petitions submitted'
      );
      if (!petitions.length) {
        tbody.innerHTML = '<tr><td colspan="4" class="text-center-muted">No frame petitions submitted.</td></tr>';
        return;
      }
      tbody.innerHTML = petitions.map((petition) => `
        <tr>
          <td class="mono" data-label="Petition">${BDA.escapeHtml(petition.petition_id || '-')}</td>
          <td data-label="Status">${BDA.escapeHtml(petition.status || 'pending')}</td>
          <td class="mono" data-label="Submitted">${BDA.escapeHtml(BDA.formatDateTime(petition.created_at))}</td>
          <td data-label="Decision">${BDA.escapeHtml(petition.governance_decision?.reason || '-')}</td>
        </tr>
      `).join('');
    } catch (error) {
      setWorkspaceMeta('workspace-tab-frames-meta', 'Queue unavailable');
      tbody.innerHTML = `<tr><td colspan="4" class="text-center-bad">${BDA.escapeHtml(error.message || 'Failed to load frame petitions')}</td></tr>`;
    }
  }

  async function loadProposals() {
    const filter = document.getElementById('proposal-filter')?.value || '';
    try {
      const url = '/api/admin/debate-proposals' + (filter ? `?status=${encodeURIComponent(filter)}` : '');
      const data = await BDA.api(url);
      renderProposals(data.proposals || []);
    } catch (error) {
      setWorkspaceMeta('workspace-tab-review-meta', 'Queue unavailable');
      const tbody = document.getElementById('proposal-review-tbody');
      if (tbody) {
        tbody.innerHTML = `<tr><td colspan="4" class="text-center-muted">Failed to load proposals.</td></tr>`;
      }
    }
  }

  function renderProposals(proposals) {
    const tbody = document.getElementById('proposal-review-tbody');
    const countPill = document.getElementById('proposal-count-pill');
    if (countPill) countPill.textContent = `${proposals.length} proposal${proposals.length !== 1 ? 's' : ''}`;
    setWorkspaceMeta(
      'workspace-tab-review-meta',
      proposals.length ? `${proposals.length} visible proposal${proposals.length === 1 ? '' : 's'}` : 'No proposals in this filter'
    );
    if (!tbody) return;

    if (proposals.length === 0) {
      tbody.innerHTML = '<tr><td colspan="4" class="text-center-muted">No proposals found.</td></tr>';
      return;
    }

    tbody.innerHTML = proposals.map(p => {
      const statusClass = p.status === 'accepted' ? 'good' : p.status === 'rejected' ? 'bad' : 'warn';
      const acceptBtn = p.status === 'pending'
        ? `<button class="button success-action btn-compact" data-action="accept-proposal" data-proposal-id="${p.proposal_id}">Accept</button>`
        : '';
      const rejectBtn = p.status === 'pending'
        ? `<button class="button secondary btn-compact" data-action="show-reject-panel" data-proposal-id="${p.proposal_id}">Reject</button>`
        : '';
      const debateLink = p.accepted_debate_id
        ? `<a href="new_debate.html?debate_id=${encodeURIComponent(p.accepted_debate_id)}">${p.accepted_debate_id}</a>`
        : '—';
      return `
        <tr>
          <td data-label="Motion">
            <div class="font-600">${BDA.escapeHtml(p.motion)}</div>
            <small class="text-muted">${BDA.escapeHtml(p.moderation_criteria.substring(0, 120))}${p.moderation_criteria.length > 120 ? '...' : ''}</small>
            ${p.accepted_debate_id ? `<small class="block-mt-4">Debate: ${debateLink}</small>` : ''}
          </td>
          <td class="mono" data-label="Submitted">${BDA.formatDateTime(p.created_at)}</td>
          <td data-label="Status"><span class="pill ${statusClass}">${p.status}</span></td>
          <td data-label="Actions">
            <div class="row gap-6-wrap">
              ${acceptBtn}
              ${rejectBtn}
            </div>
          </td>
        </tr>
      `;
    }).join('');
  }

  async function acceptProposal(proposalId) {
    try {
      setActionButtonsDisabled(true);
      const response = await BDA.api(`/api/admin/debate-proposals/${encodeURIComponent(proposalId)}/accept`, {
        method: 'POST',
        body: JSON.stringify({}),
      });
      setActionFeedback(`Accepted proposal. Created debate ${response.debate_id}.`, 'success');
      await loadProposals();
    } catch (error) {
      setActionFeedback(error.message || 'Failed to accept proposal.', 'error');
    } finally {
      setActionButtonsDisabled(false);
    }
  }

  function showRejectPanel(proposalId) {
    setActiveWorkspace('review');
    activeProposalId = proposalId;
    activeDecisionAction = 'reject';
    const panel = document.getElementById('proposal-decision-panel');
    const title = document.getElementById('proposal-decision-title');
    const confirmBtn = document.getElementById('proposal-decision-confirm-btn');
    if (panel) panel.style.display = 'grid';
    if (title) title.textContent = 'Reject Proposal';
    if (confirmBtn) {
      confirmBtn.textContent = 'Confirm Reject';
      confirmBtn.className = 'button';
    }
    document.getElementById('proposal-decision-reason').value = '';
    document.getElementById('proposal-decision-reason').focus();
  }

  function cancelProposalDecision() {
    activeProposalId = null;
    activeDecisionAction = null;
    const panel = document.getElementById('proposal-decision-panel');
    if (panel) panel.style.display = 'none';
    document.getElementById('proposal-decision-reason').value = '';
  }

  async function confirmProposalDecision() {
    if (!activeProposalId || activeDecisionAction !== 'reject') return;
    const reason = document.getElementById('proposal-decision-reason').value.trim();
    if (!reason) {
      setActionFeedback('Please provide a reason for rejection.', 'error');
      return;
    }
    try {
      setActionButtonsDisabled(true);
      await BDA.api(`/api/admin/debate-proposals/${encodeURIComponent(activeProposalId)}/reject`, {
        method: 'POST',
        body: JSON.stringify({ reason }),
      });
      setActionFeedback('Proposal rejected.', 'success');
      cancelProposalDecision();
      await loadProposals();
    } catch (error) {
      setActionFeedback(error.message || 'Failed to reject proposal.', 'error');
    } finally {
      setActionButtonsDisabled(false);
    }
  }

  function renderTemplateHistory(history) {
    const tbody = document.getElementById('template-history-tbody');
    const records = Array.isArray(history) ? history : [];

    if (!records.length) {
      tbody.innerHTML = '<tr><td colspan="5" class="text-center-muted">No template history found yet.</td></tr>';
      return;
    }

    tbody.innerHTML = records.map((item) => {
      const status = String(item.status || 'draft').toLowerCase();
      const pillClass = status === 'active' ? 'good' : status === 'applied' ? 'warn' : '';
      const statusLabel = status === 'active' ? 'Active' : status === 'applied' ? 'Applied' : 'Draft';
      const description = item.notes || `Base: ${item.base_template_id}`;
      const actor = item.author_user_id || 'system';
      const timestamp = item.applied_at || item.updated_at || item.created_at;
      return `
        <tr>
          <td class="mono" data-label="Version">${BDA.escapeHtml(item.version || '-')}</td>
          <td class="mono" data-label="Timestamp">${BDA.escapeHtml(BDA.formatDateTime(timestamp))}</td>
          <td data-label="Admin">${BDA.escapeHtml(actor)}</td>
          <td data-label="Changes">${BDA.escapeHtml(description)}</td>
          <td data-label="Status"><span class="pill ${pillClass}">${statusLabel}</span></td>
        </tr>
      `;
    }).join('');
  }

  function loadTemplatePreview() {
    const baseSelect = document.getElementById('template-base');
    const statePill = document.getElementById('template-state-pill');
    const headerState = document.getElementById('template-current-state');
    const templateNote = document.querySelector('#template-selection .template-note');
    const previewPill = document.getElementById('preview-confidence-pill');
    if (!baseSelect || !statePill || !headerState || !templateNote || !previewPill) return;

    const selectedValue = baseSelect.value;
    const selectedLabel = baseSelect.options[baseSelect.selectedIndex]?.text || 'No template selected';
    const activeTemplate = AdminState.currentTemplate;
    const payload = collectTemplatePayloadForPreview();
    const isActiveTemplate = !!payload && !!activeTemplate &&
      selectedValue === activeTemplate.base_template_id &&
      (document.getElementById('template-version')?.value || '').trim() === String(activeTemplate.version || '') &&
      payload.topic_requirements.relevance_threshold === (activeTemplate.topic_requirements?.relevance_threshold || 'moderate') &&
      payload.topic_requirements.enforce_scope === !!activeTemplate.topic_requirements?.enforce_scope &&
      listEquals(payload.topic_requirements.required_keywords, activeTemplate.topic_requirements?.required_keywords) &&
      Number(payload.toxicity_settings.sensitivity_level || 3) === Number(activeTemplate.toxicity_settings?.sensitivity_level || 3) &&
      payload.toxicity_settings.block_personal_attacks === !!activeTemplate.toxicity_settings?.block_personal_attacks &&
      payload.toxicity_settings.block_hate_speech === !!activeTemplate.toxicity_settings?.block_hate_speech &&
      payload.toxicity_settings.block_threats === !!activeTemplate.toxicity_settings?.block_threats &&
      payload.toxicity_settings.block_sexual_harassment === !!activeTemplate.toxicity_settings?.block_sexual_harassment &&
      payload.toxicity_settings.block_mild_profanity === !!activeTemplate.toxicity_settings?.block_mild_profanity &&
      payload.pii_settings.action === (activeTemplate.pii_settings?.action || 'block') &&
      payload.spam_rate_limit_settings.min_length === Number(activeTemplate.spam_rate_limit_settings?.min_length ?? 50) &&
      payload.spam_rate_limit_settings.max_length === Number(activeTemplate.spam_rate_limit_settings?.max_length ?? 5000) &&
      payload.spam_rate_limit_settings.flood_threshold_per_hour === Number(activeTemplate.spam_rate_limit_settings?.flood_threshold_per_hour ?? 10) &&
      payload.spam_rate_limit_settings.duplicate_detection === !!activeTemplate.spam_rate_limit_settings?.duplicate_detection &&
      payload.spam_rate_limit_settings.rate_limiting === !!activeTemplate.spam_rate_limit_settings?.rate_limiting &&
      payload.prompt_injection_settings.enabled === !!activeTemplate.prompt_injection_settings?.enabled &&
      payload.prompt_injection_settings.block_markdown_hiding === !!activeTemplate.prompt_injection_settings?.block_markdown_hiding &&
      listEquals(payload.prompt_injection_settings.custom_patterns, activeTemplate.prompt_injection_settings?.custom_patterns);

    if (payload) {
      setText('toxicity-summary', getToxicitySummary(payload.toxicity_settings.sensitivity_level));
    }

    if (!selectedValue) {
      statePill.className = 'pill warn';
      statePill.textContent = 'Selection required';
      headerState.className = 'pill warn';
      headerState.textContent = 'Select a template';
      previewPill.className = 'pill warn admin-step-status';
      previewPill.textContent = 'Selection required';
      templateNote.textContent = 'Select a template to preview how moderation policy changes would be described.';
      renderDraftSummary(null, { isActiveTemplate: false, selectedLabel });
      renderList('preview-allowed-list', [], 'Add a template and guardrail settings to populate this policy summary.');
      renderList('preview-blocked-list', [], 'Blocked behavior will appear here once a draft is selected.');
      renderList('preview-change-list', ['Choose a template to compare this draft against the active policy.'], 'Choose a template to compare this draft against the active policy.');
      setText('preview-summary-copy', 'Choose a template and adjust the guardrails to generate a live participant-facing summary.');
      return;
    }

    statePill.className = isActiveTemplate ? 'pill good' : 'pill warn';
    statePill.textContent = isActiveTemplate ? 'Active' : 'Draft Change';
    headerState.className = isActiveTemplate ? 'pill good' : 'pill warn';
    headerState.textContent = isActiveTemplate ? 'Matches the active policy' : 'Draft change pending review';
    previewPill.className = isActiveTemplate ? 'pill good admin-step-status' : 'pill warn admin-step-status';
    previewPill.textContent = isActiveTemplate ? 'No unpublished changes' : 'Participant preview updated';

    if (isActiveTemplate) {
      templateNote.textContent = 'Template changes apply to the next snapshot only. Existing snapshots remain immutable, and each version stays visible in the audit trail.';
    } else {
      templateNote.textContent = `Previewing "${selectedLabel}". If applied, this moderation posture will affect only future snapshots and will remain visible in the audit trail.`;
    }

    renderDraftSummary(payload, { isActiveTemplate, selectedLabel });
    renderList('preview-allowed-list', buildAllowedPreview(payload), 'No allowed-content summary is available yet.');
    renderList('preview-blocked-list', buildBlockedPreview(payload), 'No blocked-content summary is available yet.');
    renderList('preview-change-list', buildDraftChangeList(payload, activeTemplate), 'No draft changes detected.');
    setText(
      'preview-summary-copy',
      isActiveTemplate
        ? `Participants will continue to see ${selectedLabel} as the active moderation posture. The current draft matches the live policy state.`
        : `Participants would see ${selectedLabel} as the next moderation posture. This draft keeps the current policy scope but changes the enforcement details listed alongside it.`
    );
  }

  // ==========================================================================
  // Human Review / Fact-Check Audit workspace
  // ==========================================================================

  const HR_FLAG_ORDER = [
    'CONTRADICTORY_TIER1_EVIDENCE',
    'HIGH_IMPACT_INSUFFICIENT',
    'HIGH_IMPACT_LLM_DIRECTION',
    'ENTITY_AMBIGUITY',
    'SCOPE_MISMATCH',
    'TEMPORAL_SCOPE_AMBIGUITY',
    'SCIENTIFIC_SCOPE_OVERCLAIM',
    'POLICY_GAP',
    'LLM_VALIDATION_FAILURE',
    'CONNECTOR_FAILURE',
    'SOURCE_CONFLICT',
    'CAUSAL_COMPLEXITY',
  ];

  function formatTier(tier) {
    if (tier === 1 || tier === '1') return 'T1';
    if (tier === 2 || tier === '2') return 'T2';
    if (tier === 3 || tier === '3') return 'T3';
    return '—';
  }

  function statusClass(status) {
    if (status === 'SUPPORTED') return 'status-supported';
    if (status === 'REFUTED') return 'status-refuted';
    if (status === 'INSUFFICIENT') return 'status-insufficient';
    return '';
  }

  function renderFlagTags(flags) {
    if (!Array.isArray(flags) || flags.length === 0) return '<span class="text-muted">—</span>';
    const critical = new Set(['CONTRADICTORY_TIER1_EVIDENCE', 'HIGH_IMPACT_INSUFFICIENT', 'HIGH_IMPACT_LLM_DIRECTION']);
    return flags.map(f => {
      const cls = critical.has(f) ? 'flag-tag critical' : 'flag-tag';
      return `<span class="${cls}">${BDA.escapeHtml(f)}</span>`;
    }).join('');
  }

  async function loadHumanReviewWorkspace() {
    try {
      await Promise.all([
        loadReviewQueue(),
        loadCoverageTrace(),
      ]);
    } catch (error) {
      console.warn('Human review workspace load error:', error);
      setWorkspaceMeta('workspace-tab-hr-meta', 'Queue unavailable');
    }
  }

  async function loadReviewQueue() {
    // TODO: replace with real endpoint when backend is ready
    // const data = await BDA.api('/api/human-review/flagged-premises', { suppressAuthRedirect: true });
    // For now, derive from existing topic API
    const debate = await BDA.loadDebate();
    if (!debate.has_debate) {
      setWorkspaceMeta('workspace-tab-hr-meta', 'No active debate');
      return;
    }

    let premises = [];
    try {
      const topicsData = await BDA.api('/api/debate/topics');
      const topics = topicsData.topics || [];
      for (const t of topics) {
        try {
          const topic = await BDA.api(`/api/debate/topics/${encodeURIComponent(t.topic_id)}`);
          const facts = topic.facts || [];
          for (const f of facts) {
            const flags = f.v15_human_review_flags || [];
            const status = f.v15_status || (f.p_true === 1.0 ? 'SUPPORTED' : f.p_true === 0.0 ? 'REFUTED' : 'INSUFFICIENT');
            const p = f.v15_p !== undefined ? f.v15_p : f.p_true;
            if (flags.length || status === 'INSUFFICIENT') {
              premises.push({
                premise_id: f.canon_fact_id,
                topic_id: t.topic_id,
                topic_name: t.name,
                side: f.side,
                status,
                p,
                best_tier: f.v15_best_evidence_tier,
                insufficiency_reason: f.v15_insufficiency_reason || '',
                flags,
                text: f.canon_fact_text,
                operationalization: f.operationalization || '',
                evidence_tier_counts: f.evidence_tier_counts || {},
              });
            }
          }
        } catch (e) {
          console.warn('Failed to load topic for HR:', t.topic_id, e);
        }
      }
    } catch (error) {
      console.warn('Failed to load review queue:', error);
    }

    // Populate stats
    const pending = premises.filter(p => p.flags.length > 0).length;
    document.getElementById('hr-total-flagged').textContent = premises.length;
    document.getElementById('hr-pending').textContent = pending;
    document.getElementById('hr-nochange').textContent = '0';
    document.getElementById('hr-correction').textContent = '0';
    setWorkspaceMeta('workspace-tab-hr-meta', `${premises.length} flagged premise${premises.length === 1 ? '' : 's'}`);

    // Render queue table
    const tbody = document.getElementById('hr-queue-tbody');
    if (premises.length === 0) {
      tbody.innerHTML = '<tr><td colspan="9" class="text-center-muted">No premises are currently flagged for human review.</td></tr>';
    } else {
      tbody.innerHTML = premises.slice(0, 100).map(p => `
        <tr>
          <td data-label="Flag(s)">${renderFlagTags(p.flags)}</td>
          <td class="mono" data-label="Premise ID">${BDA.escapeHtml(p.premise_id)}</td>
          <td data-label="Topic">${BDA.escapeHtml(p.topic_name || p.topic_id)}</td>
          <td data-label="Side">${BDA.escapeHtml(p.side)}</td>
          <td class="${statusClass(p.status)}" data-label="Status">${BDA.escapeHtml(p.status)}</td>
          <td class="mono" data-label="p">${BDA.formatNumber(Number(p.p), 1)}</td>
          <td class="mono" data-label="Best Tier">${formatTier(p.best_tier)}</td>
          <td data-label="Insufficiency Reason">${BDA.escapeHtml(p.insufficiency_reason) || '<span class="text-muted">—</span>'}</td>
          <td data-label="Actions"><button class="pill" type="button" data-action="open-fact-check-audit" data-premise-id="${BDA.escapeHtml(p.premise_id)}">Audit</button></td>
        </tr>
      `).join('');
    }

    // Populate audit selector
    const select = document.getElementById('hr-audit-select');
    if (select) {
      const options = premises.map(p => `<option value="${BDA.escapeHtml(p.premise_id)}">${BDA.escapeHtml(p.premise_id)} — ${BDA.escapeHtml(p.text?.slice(0, 60) || '')}</option>`).join('');
      select.innerHTML = '<option value="">Select a premise to audit...</option>' + options;
      select.addEventListener('change', (e) => {
        if (e.target.value) openFactCheckAudit(e.target.value);
      });
    }

    // Render flag dashboard
    renderFlagDashboard(premises);
  }

  function renderFlagDashboard(premises) {
    const counts = {};
    premises.forEach(p => {
      (p.flags || []).forEach(f => {
        counts[f] = (counts[f] || 0) + 1;
      });
    });

    const total = premises.length;
    const reviewed = 0;
    const corrections = 0;
    const nochange = 0;

    document.getElementById('hr-dash-total').textContent = total;
    document.getElementById('hr-dash-reviewed').textContent = reviewed;
    document.getElementById('hr-dash-corrections').textContent = corrections;
    document.getElementById('hr-dash-nochange').textContent = nochange;

    const tbody = document.getElementById('hr-dash-tbody');
    const orderedFlags = HR_FLAG_ORDER.filter(f => counts[f] !== undefined).concat(
      Object.keys(counts).filter(f => !HR_FLAG_ORDER.includes(f))
    );

    if (orderedFlags.length === 0) {
      tbody.innerHTML = '<tr><td colspan="4" class="text-center-muted">No flags recorded.</td></tr>';
      return;
    }

    tbody.innerHTML = orderedFlags.map(flag => {
      const count = counts[flag];
      const suppressed = count < 5;
      const displayCount = suppressed ? '<span class="suppressed-count">&lt;5</span>' : String(count);
      const pct = suppressed ? '—' : `${((count / total) * 100).toFixed(1)}%`;
      return `
        <tr>
          <td data-label="Flag">${BDA.escapeHtml(flag)}</td>
          <td class="mono" data-label="Count">${displayCount}</td>
          <td class="mono" data-label="% of flagged">${pct}</td>
          <td data-label="Suppressed?">${suppressed ? 'Yes' : 'No'}</td>
        </tr>
      `;
    }).join('');
  }

  async function openFactCheckAudit(premiseId) {
    const panel = document.getElementById('hr-audit-panel');
    const select = document.getElementById('hr-audit-select');
    if (select) select.value = premiseId;
    panel.style.display = 'block';

    // Find premise in loaded topics data or fetch fresh
    let premise = null;
    try {
      const debate = await BDA.loadDebate();
      if (debate.has_debate) {
        const topicsData = await BDA.api('/api/debate/topics');
        for (const t of (topicsData.topics || [])) {
          const topic = await BDA.api(`/api/debate/topics/${encodeURIComponent(t.topic_id)}`);
          const found = (topic.facts || []).find(f => f.canon_fact_id === premiseId);
          if (found) {
            premise = { ...found, topic_id: t.topic_id, topic_name: t.name };
            break;
          }
        }
      }
    } catch (e) {
      console.warn('Failed to load premise for audit:', e);
    }

    if (!premise) {
      document.getElementById('hr-audit-premise').textContent = premiseId;
      document.getElementById('hr-audit-status').textContent = 'Not found';
      return;
    }

    const status = premise.v15_status || (premise.p_true === 1.0 ? 'SUPPORTED' : premise.p_true === 0.0 ? 'REFUTED' : 'INSUFFICIENT');
    const p = premise.v15_p !== undefined ? premise.v15_p : premise.p_true;

    document.getElementById('hr-audit-premise').textContent = premise.canon_fact_id;
    document.getElementById('hr-audit-snapshot').textContent = '-';
    document.getElementById('hr-audit-status').textContent = status;
    document.getElementById('hr-audit-p').textContent = BDA.formatNumber(Number(p), 1);
    document.getElementById('hr-audit-auth-hash').textContent = premise.authoritative_result_hash ? (premise.authoritative_result_hash.slice(0, 16) + '…') : '—';

    // Claim expression tree (placeholder until backend returns real tree)
    document.getElementById('hr-audit-tree').textContent = JSON.stringify({
      node_type: 'ATOMIC',
      subclaim_id: premise.canon_fact_id,
      text: premise.canon_fact_text,
      status,
      p,
      best_evidence_tier: premise.v15_best_evidence_tier,
      insufficiency_reason: premise.v15_insufficiency_reason,
      human_review_flags: premise.v15_human_review_flags,
    }, null, 2);

    // Evidence items
    const evTbody = document.getElementById('hr-audit-evidence-tbody');
    const tiers = premise.evidence_tier_counts || {};
    if (Object.keys(tiers).length === 0) {
      evTbody.innerHTML = '<tr><td colspan="6" class="text-center-muted">No evidence items recorded.</td></tr>';
    } else {
      evTbody.innerHTML = Object.entries(tiers).map(([source, count]) => `
        <tr>
          <td class="mono" data-label="ID">${BDA.escapeHtml(source)}</td>
          <td data-label="Source">${BDA.escapeHtml(source)}</td>
          <td class="mono" data-label="Tier">${formatTier(source.includes('1') ? 1 : source.includes('2') ? 2 : 3)}</td>
          <td data-label="Direction">—</td>
          <td data-label="Confidence">—</td>
          <td data-label="Method">—</td>
        </tr>
      `).join('');
    }

    // Synthesis logic
    document.getElementById('hr-audit-synthesis').textContent = JSON.stringify({
      status_rule_applied: status === 'SUPPORTED' ? 'Tier 1/2 decisive evidence' : status === 'REFUTED' ? 'Tier 1/2 decisive refutation' : premise.v15_insufficiency_reason || 'INSUFFICIENT default',
      policy_rule_id: 'EMPIRICAL_ATOMIC',
      decisive_evidence: [],
      insufficiency_trigger: premise.v15_insufficiency_reason || null,
      authority_ranking_applied: false,
      claim_expression_node_type: 'ATOMIC',
    }, null, 2);

    // Replay manifest placeholder
    document.getElementById('hr-audit-manifest').textContent = JSON.stringify({
      manifest_id: 'manifest_' + premise.canon_fact_id,
      parameter_pack: {
        decomposition_version: 'v1.5.1',
        evidence_policy_version: 'v1.5.1',
        synthesis_rule_engine_version: 'v1.5.1',
      },
      input_hashes: { [premise.canon_fact_id]: 'sha256:...' },
      authoritative_output_hashes: { [premise.canon_fact_id]: 'sha256:...' },
      merkle_root: 'sha256:...',
    }, null, 2);

    // Display summary
    const displayEl = document.getElementById('hr-audit-display');
    displayEl.textContent = premise.operationalization
      ? `Operationalization: ${premise.operationalization}`
      : 'No display summary available for this premise.';
  }

  async function loadCoverageTrace() {
    try {
      const debate = await BDA.loadDebate();
      if (!debate.has_debate) return;
      const audits = await BDA.api('/api/debate/audits');
      const trace = audits.coverage_adequacy_trace || {};
      const overall = trace.overall || {};
      const perTopic = trace.per_topic || {};

      document.getElementById('hr-cov-targets').textContent = overall.total_targets ?? '-';
      document.getElementById('hr-cov-rate').textContent = BDA.formatNumber(overall.coverage_rate, 3);
      document.getElementById('hr-cov-emp').textContent = overall.empirical_rebuttals ?? '-';
      document.getElementById('hr-cov-norm').textContent = overall.normative_rebuttals ?? '-';
      document.getElementById('hr-cov-inf').textContent = overall.inference_rebuttals ?? '-';
      document.getElementById('hr-cov-scope').textContent = overall.scope_definition_shifts ?? '-';

      const tbody = document.getElementById('hr-cov-tbody');
      const entries = Object.entries(perTopic);
      if (entries.length === 0) {
        tbody.innerHTML = '<tr><td colspan="7" class="text-center-muted">No coverage trace data available.</td></tr>';
        return;
      }
      tbody.innerHTML = entries.map(([topicId, t]) => `
        <tr>
          <td class="mono" data-label="Topic">${BDA.escapeHtml(topicId)}</td>
          <td class="mono" data-label="Targets">${t.targets ?? '-'}</td>
          <td class="mono" data-label="Coverage Rate">${BDA.formatNumber(t.coverage_rate, 3)}</td>
          <td class="mono" data-label="EMPIRICAL">${t.empirical_rebuttals ?? '-'}</td>
          <td class="mono" data-label="NORMATIVE">${t.normative_rebuttals ?? '-'}</td>
          <td class="mono" data-label="INFERENCE">${t.inference_rebuttals ?? '-'}</td>
          <td class="mono" data-label="SCOPE/DEF">${t.scope_definition_shifts ?? '-'}</td>
        </tr>
      `).join('');
    } catch (error) {
      console.warn('Failed to load coverage trace:', error);
      document.getElementById('hr-cov-tbody').innerHTML = '<tr><td colspan="7" class="text-center-muted">Coverage trace unavailable.</td></tr>';
    }
  }

  async function injectHelpPanel() {
    const placeholder = document.getElementById('shared-help-panel');
    if (!placeholder) return;
    try {
      const response = await fetch('components/help-panel-admin.html');
      if (response.ok) {
        placeholder.outerHTML = await response.text();
        if (window.BDA?.setupHelpPanel) {
          window.BDA.setupHelpPanel();
        }
      }
    } catch (error) {
      console.warn('Failed to load admin help panel:', error);
    }
  }

  async function refreshAdminState() {
    const [currentResponse, historyResponse] = await Promise.all([
      BDA.api('/api/admin/moderation-template/current', { suppressAuthRedirect: true }),
      BDA.api('/api/admin/moderation-template/history?limit=50', { suppressAuthRedirect: true }),
    ]);

    AdminState.hasLiveData = true;
    AdminState.availableBases = currentResponse.available_bases || [];
    AdminState.history = historyResponse.history || [];

    const activeTemplate = currentResponse.template || null;
    populateBaseTemplateOptions(AdminState.availableBases, activeTemplate?.base_template_id);
    if (activeTemplate) {
      applyTemplateToForm(activeTemplate);
    }
    renderTemplateHistory(AdminState.history);
    renderModerationOutcomes(currentResponse.moderation_outcomes || {});
    updateHeroSummary(activeTemplate);
    setWorkspaceMeta('workspace-tab-policy-meta', activeTemplate?.version ? `Active version ${activeTemplate.version}` : 'Editing next snapshot policy');
    loadFramePetitions();
    loadTemplatePreview();
  }

  async function saveDraft() {
    try {
      const payload = collectTemplatePayload();
      setActionButtonsDisabled(true);
      setActionFeedback('Saving draft configuration...', 'loading');
      const response = await BDA.api('/api/admin/moderation-template/draft', {
        method: 'POST',
        body: JSON.stringify(payload),
      });
      await refreshAdminState();
      setActionFeedback(
        `Draft saved: ${response.template?.template_name || payload.template_name} v${response.template?.version || payload.version}.`,
        'success'
      );
    } catch (error) {
      const errorMsg = error?.message || 'Failed to save draft configuration.';
      const requestId = error?.payload?.request_id || '';
      if (requestId) console.error(`[request_id: ${requestId}]`, errorMsg);
      setActionFeedback(errorMsg, 'error');
    } finally {
      setActionButtonsDisabled(false);
    }
  }

  async function applyTemplate() {
    try {
      const payload = collectTemplatePayload();
      setActionButtonsDisabled(true);
      setActionFeedback('Applying template and updating active version...', 'loading');
      const response = await BDA.api('/api/admin/moderation-template/apply', {
        method: 'POST',
        body: JSON.stringify(payload),
      });
      await refreshAdminState();
      setActionFeedback(
        `Applied ${response.template?.template_name || payload.template_name} v${response.template?.version || payload.version}. It will take effect on the next snapshot.`,
        'success'
      );
    } catch (error) {
      const errorMsg = error?.message || 'Failed to apply template.';
      const requestId = error?.payload?.request_id || '';
      if (requestId) console.error(`[request_id: ${requestId}]`, errorMsg);
      setActionFeedback(errorMsg, 'error');
    } finally {
      setActionButtonsDisabled(false);
    }
  }

  document.addEventListener('DOMContentLoaded', async () => {
    const session = await Auth.verifySession();
    if (!session.ok) {
      if (session.reason === 'network-error') {
        setActionFeedback('Admin service is unavailable. Please try again later.', 'error');
        releaseRouteAuthGate();
        return;
      }
      Auth.redirectToLogin(
        session.reason === 'expired' ? 'session-expired' : 'admin-login-required'
      );
      return;
    }

    bindWorkspaceTabs();
    bindPolicyInputs();
    bindProposalFilter();
    setActiveWorkspace(resolveWorkspaceFromHash(window.location.hash));
    updateHeroSummary();
    loadTemplatePreview();
    if (window.location.hash) {
      const initialTarget = document.getElementById(String(window.location.hash).replace(/^#/, ''));
      if (initialTarget) initialTarget.scrollIntoView({ block: 'start' });
    }
    await injectHelpPanel();
    try {
      setActionFeedback('Loading moderation template state...', 'loading');
      await refreshAdminState();
      setActionFeedback('Moderation template state loaded.', 'success');
    } catch (error) {
      const code = String(error?.code || '');
      const status = Number(error?.status || 0);
      const errorMsg = error?.message || 'Failed to load moderation template state.';
      const requestId = error?.payload?.request_id || '';
      if (requestId) console.error(`[request_id: ${requestId}]`, errorMsg);
      if (status === 403 || code === 'ADMIN_FORBIDDEN') {
        showAdminAccessDenied(error);
        releaseRouteAuthGate();
        return;
      }
      if (status === 401 || code === 'AUTH_REQUIRED' || code === 'AUTH_INVALID') {
        if (typeof Auth.clearSession === 'function') {
          Auth.clearSession();
        }
        Auth.redirectToLogin('admin-login-required');
        return;
      }
      AdminState.hasLiveData = false;
      updateHeroSummary();
      setWorkspaceMeta('workspace-tab-policy-meta', 'Previewing without live admin data');
      setWorkspaceMeta('workspace-tab-review-meta', 'Queue unavailable');
      setWorkspaceMeta('workspace-tab-audit-meta', 'Audit unavailable');
      setWorkspaceMeta('workspace-tab-frames-meta', 'Queue unavailable');
      setWorkspaceMeta('workspace-tab-hr-meta', 'Queue unavailable');
      setActionFeedback(errorMsg, 'error');
      loadTemplatePreview();
      releaseRouteAuthGate();
      return;
    }
    try {
      await loadProposals();
    } catch (error) {
      setWorkspaceMeta('workspace-tab-review-meta', 'Queue unavailable');
      console.warn('Failed to load proposals:', error);
    }
    try {
      await loadHumanReviewWorkspace();
    } catch (error) {
      setWorkspaceMeta('workspace-tab-hr-meta', 'Queue unavailable');
      console.warn('Failed to load human review workspace:', error);
    }
    releaseRouteAuthGate();
  });
