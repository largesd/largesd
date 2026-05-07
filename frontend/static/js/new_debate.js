BDA.registerAction('submit-post', submitPost);
BDA.registerAction('preview-post', previewPost);
BDA.registerAction('copy-email-body', copyEmailBody);
BDA.registerAction('clear-pending', clearPending);
BDA.registerAction('remove-pending', (el) => removePendingPost(parseInt(el.dataset.index, 10)));

let hasActiveDebate = false;
let currentDebateId = null;
let currentResolution = '';
let currentDebateSource = null;

function canUseLiveApiMode() {
  return typeof Auth !== 'undefined' && Auth.isLoggedIn();
}

function hasGithubPostingConfig() {
  DataBridge.loadConfig();
  return DataBridge.isConfigured();
}

async function init() {
  DataBridge.loadConfig();
  if (!hasGithubPostingConfig() && !canUseLiveApiMode()) {
    window.location.href = 'setup.html';
    return;
  }
  updateSubmissionModeUI();
  await loadDebate();
  await loadTopics();
  updatePostSectionState();
  updatePendingPostsList();
  if (typeof DebateSelector !== 'undefined') {
    await DebateSelector.init('debate-selector', {
      onSelect: async (debateId) => {
        await loadDebate();
        await loadTopics();
        updatePostSectionState();
      }
    });
  }
}

async function loadDebate() {
  let data = null;
  let source = null;

  try {
    if (canUseLiveApiMode()) {
      data = await BDA.loadDebate({
        preferLiveApi: true,
        suppressAuthRedirect: true,
      });
      if (data?.has_debate) {
        source = 'api';
      }
    }
  } catch (error) {
    console.warn('Live debate context unavailable, falling back to GitHub cache:', error);
  }

  try {
    if ((!data || !data.has_debate) && hasGithubPostingConfig()) {
      await DataBridge.ensureData();
      const cachedDebate = DataBridge.getDebate();
      if (cachedDebate?.has_debate) {
        data = cachedDebate;
        source = 'github';
      }
    }
  } catch (error) {
    console.error('Error loading cached debate:', error);
  }

  try {
    currentDebateSource = source;
    currentDebateId = data?.debate_id || null;
    currentResolution = data?.resolution || '';
    hasActiveDebate = !!(
      data?.has_debate &&
      currentDebateId &&
      currentDebateId !== 'null' &&
      currentDebateId !== 'undefined' &&
      currentResolution &&
      currentResolution.toLowerCase() !== 'untitled'
    );

    if (hasActiveDebate) {
      BDA.setActiveDebateId(currentDebateId);
      document.getElementById('display-resolution').textContent = currentResolution;
      document.getElementById('current-resolution').textContent = currentResolution;
      document.getElementById('debate-status').textContent = 'Active debate';
      const snap = source === 'github'
        ? DataBridge.getSnapshot()
        : await BDA.loadSnapshot({ preferLiveApi: true, suppressAuthRedirect: true });
      if (snap && snap.has_snapshot) {
        BDA.updateStateStrip(snap);
      } else {
        resetStateStrip();
      }
    } else {
      document.getElementById('display-resolution').textContent = 'No active debate';
      document.getElementById('current-resolution').textContent = 'No active debate';
      document.getElementById('debate-status').textContent = 'No active debate';
      resetStateStrip();
    }
  } catch (error) {
    console.error('Error loading debate:', error);
    const errorMsg = error?.message || 'Error loading debate.';
    const requestId = error?.payload?.request_id || '';
    const displayResEl = document.getElementById('display-resolution');
    if (typeof BDA !== 'undefined' && typeof BDA.showInlineError === 'function' && displayResEl) {
      BDA.showInlineError(displayResEl, errorMsg, () => {
        if (requestId) console.error(`[request_id: ${requestId}] Retry loading debate`);
        loadDebate();
      });
    }
    hasActiveDebate = false;
    currentDebateId = null;
    currentResolution = '';
    currentDebateSource = null;
  } finally {
    updateSubmissionModeUI();
  }
}

function resetStateStrip() {
  document.getElementById('header-verdict').textContent = 'NO VERDICT';
  document.getElementById('header-confidence').textContent = '-';
  document.getElementById('header-snapshot').textContent = '-';
}

async function loadTopics() {
  const select = document.getElementById('argument-topic');
  if (!select) return;

  let topics = [];
  try {
    const topicData = await BDA.api('/api/debate/topics', {
      preferLiveApi: true,
      suppressAuthRedirect: true,
    });
    if (topicData && topicData.topics && topicData.topics.length > 0) {
      topics = topicData.topics;
    }
  } catch (e) {
    console.warn('Could not load topics from live API:', e);
  }

  try {
    if (topics.length === 0 && hasGithubPostingConfig()) {
      await DataBridge.ensureData();
      const topicData = DataBridge.getTopics();
      if (topicData && topicData.topics && topicData.topics.length > 0) {
        topics = topicData.topics;
      }
    }
  } catch (e) {
    console.warn('Could not load topics from cache:', e);
  }

  if (topics.length === 0) {
    const errorMsg = 'Failed to load topics.';
    if (typeof BDA !== 'undefined' && typeof BDA.showInlineError === 'function') {
      const container = document.getElementById('argument-topic')?.parentElement;
      if (container) {
        BDA.showInlineError(container, errorMsg, () => {
          loadTopics();
        });
      }
    }
  }

  // No hardcoded fallback: show honest empty state
  const topicHint = document.getElementById('topic-hint');
  if (topics.length === 0) {
    if (topicHint) topicHint.style.display = '';
  } else {
    if (topicHint) topicHint.style.display = 'none';
  }

  const seenTopicLabels = new Set();
  topics = topics.filter((topic) => {
    const label = String(topic.label || topic.name || topic.topic_id || topic.id || '')
      .trim()
      .toLowerCase();
    const scope = String(topic.scope || '')
      .trim()
      .toLowerCase();

    if (!label) return false;

    const dedupeKey = `${label}__${scope}`;
    if (seenTopicLabels.has(dedupeKey)) return false;
    seenTopicLabels.add(dedupeKey);
    return true;
  });

  // Build options
  const currentValue = select.value;
  select.innerHTML = '<option value="">Select topic area...</option>' +
    topics.map(t => `<option value="${BDA.escapeHtml(t.topic_id || t.id || '')}">${BDA.escapeHtml(t.label || t.name || t.topic_id || t.id || '')}</option>`).join('');
  if (currentValue) select.value = currentValue;
}

function updateSubmissionModeUI() {
  const emailMode = currentDebateSource === 'github' ||
    (!currentDebateSource && hasGithubPostingConfig() && !canUseLiveApiMode());
  const submitBtn = document.getElementById('submit-post-button');
  const notice = document.getElementById('email-mode-notice');
  const pendingSection = document.getElementById('pending-posts');
  const emailPanel = document.getElementById('email-preview-panel');

  if (submitBtn) {
    submitBtn.textContent = emailMode ? 'Generate Email' : 'Submit Argument';
  }
  if (notice) {
    notice.style.display = emailMode ? '' : 'none';
  }
  if (pendingSection) {
    pendingSection.style.display = emailMode ? '' : 'none';
  }
  if (!emailMode && emailPanel) {
    emailPanel.style.display = 'none';
  }
}

function updatePostSectionState() {
  const postSection = document.getElementById('post-section');
  const postAccessHint = document.getElementById('post-access-hint');
  const emailMode = currentDebateSource === 'github';

  if (postSection) {
    if (hasActiveDebate) {
      postSection.style.opacity = '1';
      postSection.style.pointerEvents = 'auto';
    } else {
      postSection.style.opacity = '0.5';
      postSection.style.pointerEvents = 'none';
    }
  }

  if (postAccessHint) {
    if (hasActiveDebate) {
      postAccessHint.textContent = emailMode
        ? 'Posting is available for the active debate via email.'
        : 'Posting is available for the active debate.';
    } else {
      postAccessHint.innerHTML = 'No active debate. <a href="propose.html">Propose one now →</a>';
    }
  }
}

function previewPost() {
  const side = document.querySelector('input[name="side"]:checked');
  const topic = document.getElementById('argument-topic');
  const facts = document.getElementById('facts-input').value.trim();
  const inference = document.getElementById('inference-input').value.trim();
  const counter = document.getElementById('counter-input').value.trim();

  if (!side || !facts || !inference) {
    BDA.showStatus('Please fill in all required fields.', true);
    return;
  }

  const previewPanel = document.getElementById('preview-panel');
  const previewContent = document.getElementById('preview-content');

  previewContent.innerHTML = `
    <div class="row preview-meta-row">
      <span class="side-label ${side.value.toLowerCase()}">${side.value}</span>
      <span class="pill">Topic: ${topic.options[topic.selectedIndex].text || 'New topic area'}</span>
    </div>
    <div class="preview-block">
      <strong>Facts:</strong>
      <div class="preview-block-body prewrap">${BDA.escapeHtml(facts)}</div>
    </div>
    <div class="preview-block">
      <strong>Inference:</strong>
      <div class="preview-block-body">${BDA.escapeHtml(inference)}</div>
    </div>
    ${counter ? `<div class="preview-block"><strong>Counter-arguments addressed:</strong> <div class="preview-inline-copy">${BDA.escapeHtml(counter)}</div></div>` : ''}
  `;

  previewPanel.style.display = 'grid';
}

function submitPost() {
  if (!hasActiveDebate) {
    BDA.showStatus('No active debate selected. Choose a debate and try again.', true);
    return;
  }

  if (!currentDebateId || currentDebateId === 'null' || currentDebateId === 'undefined') {
    BDA.showStatus('No valid debate ID is available for the active debate.', true);
    return;
  }

  if (!currentResolution || currentResolution.toLowerCase() === 'untitled') {
    BDA.showStatus('No valid debate resolution is available for the active debate.', true);
    return;
  }

  const side = document.querySelector('input[name="side"]:checked');
  const topic = document.getElementById('argument-topic');
  const factsEl = document.getElementById('facts-input');
  const inferenceEl = document.getElementById('inference-input');
  const counterEl = document.getElementById('counter-input');

  if (!side) {
    BDA.showStatus('Please select a side (FOR or AGAINST).', true);
    return;
  }

  // Topic is optional when no topics have been generated yet
  const topicHint = document.getElementById('topic-hint');
  if (!topic.value && !(topicHint && topicHint.style.display !== 'none')) {
    BDA.showStatus('Please select a topic area.', true);
    return;
  }

  if (!factsEl.value.trim() || !inferenceEl.value.trim()) {
    BDA.showStatus('Please provide both factual premises and an inference.', true);
    return;
  }

  const facts = factsEl.value.trim();
  const inference = inferenceEl.value.trim();
  const counter = counterEl.value.trim();

  if (currentDebateSource === 'api') {
    BDA.api('/api/debate/posts', {
      method: 'POST',
      body: JSON.stringify({
        side: side.value,
        topic_id: topic.value,
        facts,
        inference,
        counter_arguments: counter || ''
      }),
      preferLiveApi: true,
    }).then((response) => {
      const outcome = response?.modulation_outcome || 'allowed';
      const blockReason = response?.block_reason;
      if (outcome === 'allowed') {
        BDA.showStatus('Argument submitted.');
      } else {
        BDA.showStatus(
          `Argument submitted but was ${outcome}${blockReason ? ` (${blockReason})` : ''}.`,
          true
        );
      }
      factsEl.value = '';
      inferenceEl.value = '';
      counterEl.value = '';
      document.getElementById('preview-panel').style.display = 'none';
    }).catch((error) => {
      BDA.showStatus(error.message || 'Failed to submit argument.', true);
    });
    return;
  }

  const mailto = DataBridge.buildMailtoLink(
    currentDebateId,
    currentResolution,
    side.value,
    topic.value,
    facts,
    inference,
    counter || undefined
  );

  if (!mailto) {
    BDA.showStatus('Could not generate email. Open Setup and add a destination email first.', true);
    return;
  }

  // Show email preview panel
  const emailPanel = document.getElementById('email-preview-panel');
  const mailtoLink = document.getElementById('mailto-link');
  const bodyPreview = document.getElementById('email-body-preview');

  mailtoLink.href = mailto;
  bodyPreview.textContent = decodeURIComponent(mailto.split('body=')[1] || '');
  emailPanel.style.display = 'grid';

  // Add to pending
  BDA.addPendingPost({
    id: 'email-' + Date.now(),
    side: side.value,
    topic: topic.options[topic.selectedIndex].text,
    facts: facts,
    inference: inference,
    modulation_outcome: 'pending'
  });
  updatePendingPostsList();

  BDA.showStatus('Email generated. Open your email client to send the submission.');
}

function copyEmailBody() {
  const body = document.getElementById('email-body-preview').textContent;
  navigator.clipboard.writeText(body).then(() => {
    BDA.showStatus('Email body copied to clipboard.');
  }).catch(() => {
    BDA.showStatus('Failed to copy.', true);
  });
}

function updatePendingPostsList() {
  const container = document.getElementById('posts-list');
  const posts = BDA.state.pendingPosts;

  document.getElementById('pending-count').textContent = posts.length;

  if (posts.length === 0) {
    container.innerHTML = `
      <div class="callout soft pending-empty-state">
        <p>No email submissions generated yet.</p>
        <small>Emails are generated locally and sent via your email client.</small>
      </div>
    `;
    return;
  }

  container.innerHTML = posts.map((post, index) => `
    <article class="pending-post-item">
      <div class="row pending-post-head">
        <div class="row">
          <span class="side-label ${post.side.toLowerCase()}">${post.side}</span>
          <span class="pill">${BDA.escapeHtml(post.topic)}</span>
        </div>
        <span class="pill">${post.modulation_outcome}</span>
      </div>
      <div class="pending-post-body">
        <small>Facts:</small>
        <div class="pending-post-facts">${BDA.escapeHtml(post.facts.substring(0, 100))}${post.facts.length > 100 ? '...' : ''}</div>
      </div>
      <button class="button secondary pending-remove-btn" data-action="remove-pending" data-index="${index}">Remove</button>
    </article>
  `).join('');
}

function removePendingPost(index) {
  BDA.state.pendingPosts.splice(index, 1);
  BDA.savePendingPosts();
  updatePendingPostsList();
}

function clearPending() {
  if (BDA.state.pendingPosts.length === 0) return;
  if (confirm('Clear all pending posts? This cannot be undone.')) {
    BDA.clearPendingPosts();
    updatePendingPostsList();
  }
}

// Initialize
document.addEventListener('DOMContentLoaded', init);
