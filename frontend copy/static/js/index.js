// Home page data loading and page-specific behavior.

function setButtonBusy(button, isBusy, busyLabel) {
  if (!button) return;
  if (!button.dataset.defaultLabel) {
    button.dataset.defaultLabel = button.textContent.trim();
  }
  button.disabled = isBusy;
  button.setAttribute('aria-busy', String(isBusy));
  button.textContent = isBusy ? busyLabel : button.dataset.defaultLabel;
}

function updateHomeCTA(hasDebate) {
  const ctaLink = document.getElementById('home-cta-link');
  const ctaCopy = document.getElementById('home-cta-copy');
  const ctaLabel = document.querySelector('#home-cta-primary .action-lane-label');
  if (!ctaLink) return;

  if (hasDebate) {
    ctaLink.textContent = 'Post an argument';
    ctaLink.href = 'new_debate.html';
    if (ctaCopy) ctaCopy.textContent = 'Submit FOR or AGAINST argument units with explicit facts and inference.';
    if (ctaLabel) ctaLabel.textContent = 'Contribute';
  } else {
    ctaLink.textContent = 'Propose a debate';
    ctaLink.href = 'propose.html';
    if (ctaCopy) ctaCopy.textContent = 'Start a new debate by submitting a motion and frame for admin review.';
    if (ctaLabel) ctaLabel.textContent = 'Start';
  }
}

function setHomeLoadingState(isLoading) {
  const statusEl = document.getElementById('api-status');
  const changesList = document.getElementById('changes-list');
  const resolutionBlock = document.getElementById('debate-prompt-content');

  if (statusEl && isLoading) {
    statusEl.removeAttribute('title');
  }
  if (changesList) {
    changesList.setAttribute('aria-busy', String(isLoading));
  }
  if (resolutionBlock) {
    resolutionBlock.classList.toggle('loading', isLoading);
  }
}

async function loadData() {
  const statusEl = document.getElementById('api-status');
  const refreshBtn = document.getElementById('refresh-data-btn');
  const generateSnapshotBtn = document.getElementById('generate-snapshot-btn');
  const ghRefreshBtn = document.getElementById('github-refresh-btn');
  const changesList = document.getElementById('changes-list');
  const resolutionEl = document.getElementById('resolution-display');
  const frameDisplay = document.getElementById('frame-display');
  const frameMetaDisplay = document.getElementById('frame-meta-display');
  const sidesDisplay = document.getElementById('sides-display');
  const criteriaDisplay = document.getElementById('criteria-display');

  setButtonBusy(refreshBtn, true, 'Refreshing...');
  setButtonBusy(ghRefreshBtn, true, 'Refreshing...');
  setHomeLoadingState(true);
  statusEl.textContent = 'Loading...';
  statusEl.className = 'api-status';

  try {
    // Hard cutover: prefer DataBridge (GitHub mode)
    DataBridge.loadConfig();
    if (DataBridge.isConfigured()) {
      ghRefreshBtn.hidden = false;
      refreshBtn.hidden = true;
      if (generateSnapshotBtn) generateSnapshotBtn.hidden = true;
      await DataBridge.ensureData();
      const debateData = DataBridge.getDebate();
      const snapshotData = DataBridge.getSnapshot();

      if (debateData.has_debate && debateData.resolution) {
        const frame = DataBridge.getFrame();
        resolutionEl.textContent = debateData.resolution;
        resolutionEl.classList.remove('is-empty');
        frameDisplay.textContent = debateData.motion ? `Motion: ${debateData.motion}` : '';
        frameDisplay.hidden = !debateData.motion;
        frameMetaDisplay.textContent = frame ? `Active frame: v${frame.version || 1} | ${frame.stage || 'substantive'}` : '';
        frameMetaDisplay.hidden = !frame;
        const hasSides = frame && Array.isArray(frame.sides) && frame.sides.length > 0;
        sidesDisplay.textContent = hasSides ? `Sides: ${frame.sides.map((side) => side.label || side).join(', ')}` : '';
        sidesDisplay.hidden = !hasSides;
        criteriaDisplay.hidden = true;
        if (debateData.debate_id) {
          BDA.setActiveDebateId(debateData.debate_id);
        }
        updateHomeCTA(true);
      } else {
        resolutionEl.textContent = 'No debate started yet.';
        resolutionEl.classList.add('is-empty');
        frameDisplay.hidden = true;
        frameMetaDisplay.hidden = true;
        sidesDisplay.hidden = true;
        criteriaDisplay.hidden = true;
        updateHomeCTA(false);
      }

      if (snapshotData && snapshotData.has_snapshot) {
        updateSnapshotDisplay(snapshotData);
        await loadLatestChanges(snapshotData);
      } else if (!debateData.has_debate) {
        resetToEmptyState();
      }

      statusEl.textContent = 'GitHub mode';
      statusEl.className = 'api-status connected';
      statusEl.title = 'Cached ' + DataBridge.formatCacheAge();
    } else if (Auth.isLoggedIn() && BDA.getActiveDebateId()) {
      // Live backend mode
      refreshBtn.hidden = false;
      ghRefreshBtn.hidden = true;
      if (generateSnapshotBtn) generateSnapshotBtn.hidden = false;
      try {
        const debateData = await BDA.loadDebate({ preferLiveApi: true });
        const snapshotData = await BDA.loadSnapshot({ preferLiveApi: true });
        if (debateData && debateData.has_debate && debateData.resolution) {
          resolutionEl.textContent = debateData.resolution;
          resolutionEl.classList.remove('is-empty');
          if (debateData.debate_id) {
            BDA.setActiveDebateId(debateData.debate_id);
          }
          updateHomeCTA(true);
        } else {
          resolutionEl.textContent = 'No debate started yet.';
          resolutionEl.classList.add('is-empty');
          updateHomeCTA(false);
        }
        if (snapshotData && snapshotData.has_snapshot) {
          updateSnapshotDisplay(snapshotData);
          await loadLatestChanges(snapshotData);
        } else {
          resetToEmptyState();
        }
        statusEl.textContent = 'Connected';
        statusEl.className = 'api-status connected';
      } catch (err) {
        console.error('Live API load failed:', err);
        statusEl.textContent = 'API Error';
        statusEl.className = 'api-status error';
        if (changesList) {
          changesList.innerHTML = '<li class="post-error">Failed to load from API. Check connection.</li>';
        }
      }
    } else {
      // Not configured — show empty state with setup prompt
      refreshBtn.hidden = true;
      ghRefreshBtn.hidden = true;
      if (generateSnapshotBtn) generateSnapshotBtn.hidden = true;
      if (changesList) {
        changesList.innerHTML = '<li>Open <a href="setup.html">Setup</a> to configure your debate source.</li>';
      }
      statusEl.textContent = 'Setup required';
      statusEl.className = 'api-status error';
      resolutionEl.textContent = 'Welcome to Blind Debate Adjudicator. Configure a data source to get started.';
      resolutionEl.classList.remove('is-empty');
      return;
    }
  } catch (error) {
    console.error('Error loading data:', error);
    if (DataBridge.isConfigured() && ghRefreshBtn) {
      ghRefreshBtn.hidden = false;
    }
    if (refreshBtn) {
      refreshBtn.hidden = true;
    }
    if (generateSnapshotBtn) {
      generateSnapshotBtn.hidden = true;
    }
    statusEl.textContent = 'Offline';
    statusEl.className = 'api-status error';

    // Try to show cached data even on error
    if (DataBridge.hasCache()) {
      const debateData = DataBridge.getDebate();
      const snapshotData = DataBridge.getSnapshot();
      if (debateData.has_debate && debateData.resolution) {
        resolutionEl.textContent = debateData.resolution;
        resolutionEl.classList.remove('is-empty');
      }
      if (snapshotData && snapshotData.has_snapshot) {
        updateSnapshotDisplay(snapshotData);
      }
    }
  } finally {
    setButtonBusy(refreshBtn, false, 'Refreshing...');
    setButtonBusy(generateSnapshotBtn, false, 'Generating...');
    setButtonBusy(ghRefreshBtn, false, 'Refreshing...');
    setHomeLoadingState(false);
  }
}

async function loadLatestChanges(snapshotData) {
  const list = document.getElementById('changes-list');
  if (!list) return;

  let changes = [];
  try {
    const diff = DataBridge.getSnapshotDiff();
    if (diff && diff.changes && diff.changes.length > 0) {
      changes = diff.changes.slice(0, 3).map((change) => BDA.escapeHtml(change.description || String(change)));
    }
  } catch (_error) {
    // Ignore cache diff issues and fall back to derived messages.
  }

  if (changes.length === 0 && snapshotData) {
    const verdict = snapshotData.verdict || 'NO VERDICT';
    const confidence = snapshotData.confidence !== null && snapshotData.confidence !== undefined
      ? snapshotData.confidence.toFixed(2)
      : '-';
    const trigger = snapshotData.trigger_type || 'Activity';

    if (verdict === 'FOR') {
      changes.push(`Verdict is <strong>FOR</strong> with confidence ${confidence}.`);
    } else if (verdict === 'AGAINST') {
      changes.push(`Verdict is <strong>AGAINST</strong> with confidence ${confidence}.`);
    } else {
      changes.push('The overall decision remains <strong>NO VERDICT</strong> because CI(D) still crosses 0.');
    }
    changes.push(`Latest snapshot triggered by <strong>${BDA.escapeHtml(trigger)}</strong>.`);
    if (snapshotData.topic_contributions && snapshotData.topic_contributions.length > 0) {
      const top = snapshotData.topic_contributions[0];
      changes.push(`<strong>${BDA.escapeHtml(top.topic_id || 'Top topic')}</strong> contributes the largest movement toward ${BDA.escapeHtml(top.side || 'FOR')}.`);
    }
  }

  if (changes.length === 0) {
    changes.push('No snapshot data available yet. Generate a snapshot to see changes.');
  }

  list.innerHTML = changes.map((change) => `<li>${change}</li>`).join('');
}

async function triggerGenerateSnapshot() {
  const btn = document.getElementById('generate-snapshot-btn');
  const statusEl = document.getElementById('api-status');
  const changesList = document.getElementById('changes-list');

  setButtonBusy(btn, true, 'Generating...');
  if (statusEl) {
    statusEl.textContent = 'Queueing snapshot...';
    statusEl.className = 'api-status';
  }
  if (changesList) {
    changesList.innerHTML = '<li>Queueing snapshot generation...</li>';
  }

  try {
    const result = await BDA.generateSnapshot({
      triggerType: 'manual',
      onProgress: (job) => {
        if (statusEl) {
          const progress = job.progress != null ? ` (${Math.round(job.progress)}%)` : '';
          statusEl.textContent = `Generating snapshot${progress}...`;
        }
        if (changesList && job.status === 'running') {
          changesList.innerHTML = `<li>Snapshot generation in progress${job.progress != null ? ` — ${Math.round(job.progress)}%` : ''}...</li>`;
        }
      },
    });

    if (statusEl) {
      statusEl.textContent = 'Snapshot ready';
      statusEl.className = 'api-status connected';
    }

    if (result.snapshot && result.snapshot.has_snapshot) {
      updateSnapshotDisplay(result.snapshot);
      await loadLatestChanges(result.snapshot);
      BDA.showStatus('Snapshot generated successfully.');
    } else {
      BDA.showStatus('Snapshot generated, but no data returned.', true);
    }
  } catch (error) {
    console.error('Snapshot generation failed:', error);
    if (statusEl) {
      statusEl.textContent = 'Snapshot failed';
      statusEl.className = 'api-status error';
    }
    if (changesList) {
      changesList.innerHTML = `<li class="post-error">Snapshot generation failed: ${BDA.escapeHtml(error.message || 'Unknown error')}</li>`;
    }
    BDA.showStatus('Snapshot generation failed: ' + (error.message || 'Unknown error'), true);
  } finally {
    setButtonBusy(btn, false, 'Generating...');
  }
}

async function refreshFromGitHub() {
  const statusEl = document.getElementById('api-status');
  const btn = document.getElementById('github-refresh-btn');
  setButtonBusy(btn, true, 'Refreshing...');
  statusEl.removeAttribute('title');
  statusEl.textContent = 'Refreshing from GitHub...';
  try {
    await DataBridge.refreshFromGitHub();
    await loadData();
    statusEl.textContent = 'Updated from GitHub';
    statusEl.className = 'api-status connected';
    statusEl.title = 'Cached ' + DataBridge.formatCacheAge();
  } catch (error) {
    statusEl.textContent = 'Refresh failed';
    BDA.showStatus('Failed to refresh from GitHub: ' + error.message, true);
  } finally {
    setButtonBusy(btn, false, 'Refreshing...');
  }
}

function updateSnapshotDisplay(data) {
  const verdict = data.verdict || 'NO VERDICT';

  if (window.BDA && typeof BDA.updateStateStrip === 'function') {
    BDA.updateStateStrip(data);
  }

  document.getElementById('kpi-verdict').textContent = verdict;
  document.getElementById('kpi-confidence').textContent = data.confidence !== null && data.confidence !== undefined
    ? data.confidence.toFixed(2)
    : '-';
  document.getElementById('kpi-trigger').textContent = data.trigger_type || '-';
  applyVerdictTone(verdict);

  document.getElementById('badge-snapshot-id').textContent = data.snapshot_id || '-';
  document.getElementById('badge-timestamp').textContent = data.timestamp ? BDA.formatDateTime(data.timestamp) : '-';
  document.getElementById('badge-trigger').textContent = data.trigger_type || '-';

  document.getElementById('template-name').textContent = data.template_name || '-';
  document.getElementById('template-version').textContent = data.template_version || '-';

  document.getElementById('allowed-count').textContent = data.allowed_count !== undefined ? data.allowed_count : '-';
  document.getElementById('blocked-count').textContent = data.blocked_count !== undefined ? data.blocked_count : '-';

  const blockReasonsEl = document.getElementById('block-reasons');
  if (data.block_reasons && Object.keys(data.block_reasons).length > 0) {
    blockReasonsEl.textContent = '';
    Object.entries(data.block_reasons).forEach(([reason, count]) => {
      const pill = document.createElement('span');
      pill.className = 'pill warn';
      pill.textContent = `${reason}: ${count}`;
      blockReasonsEl.appendChild(pill);
    });
  } else {
    const emptyPill = document.createElement('span');
    emptyPill.className = 'pill';
    emptyPill.textContent = '-';
    blockReasonsEl.textContent = '';
    blockReasonsEl.appendChild(emptyPill);
  }
}

function resetToEmptyState() {
  if (window.BDA && typeof BDA.updateStateStrip === 'function') {
    BDA.updateStateStrip({ verdict: 'NO VERDICT', confidence: null, snapshot_id: null });
  }

  document.getElementById('kpi-verdict').textContent = 'NO VERDICT';
  document.getElementById('kpi-confidence').textContent = '-';
  document.getElementById('kpi-trigger').textContent = '-';
  applyVerdictTone('NO VERDICT');

  document.getElementById('badge-snapshot-id').textContent = '-';
  document.getElementById('badge-timestamp').textContent = '-';
  document.getElementById('badge-trigger').textContent = '-';

  document.getElementById('template-name').textContent = '-';
  document.getElementById('template-version').textContent = '-';

  document.getElementById('allowed-count').textContent = '-';
  document.getElementById('blocked-count').textContent = '-';
  const blockReasonsEl = document.getElementById('block-reasons');
  const emptyPill = document.createElement('span');
  emptyPill.className = 'pill';
  emptyPill.textContent = '-';
  blockReasonsEl.textContent = '';
  blockReasonsEl.appendChild(emptyPill);
}

function applyVerdictTone(verdict) {
  const verdictTone = window.BDA && typeof BDA.getVerdictTone === 'function'
    ? BDA.getVerdictTone(verdict)
    : verdict === 'FOR'
      ? 'good'
      : verdict === 'AGAINST'
        ? 'bad'
        : 'warn';

  const verdictTargets = [
    document.getElementById('verdict-display')?.closest('.state-item'),
    document.getElementById('verdict-mobile')?.closest('.state-compact'),
    document.getElementById('kpi-verdict'),
  ];

  verdictTargets.forEach((target) => {
    if (target) {
      target.dataset.stateTone = verdictTone;
    }
  });
}

function scrollToTop() {
  const prefersReducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  window.scrollTo({ top: 0, behavior: prefersReducedMotion ? 'auto' : 'smooth' });
}

function bindHomePageControls() {
  const bindings = [
    ['refresh-data-btn', () => { void loadData(); }],
    ['generate-snapshot-btn', () => { void triggerGenerateSnapshot(); }],
    ['github-refresh-btn', () => { void refreshFromGitHub(); }],
  ];

  bindings.forEach(([id, handler]) => {
    const element = document.getElementById(id);
    if (!element || element.dataset.bound === 'true') return;
    element.addEventListener('click', handler);
    element.dataset.bound = 'true';
  });

  const backToTop = document.querySelector('.back-to-top');
  if (backToTop && backToTop.dataset.bound !== 'true') {
    backToTop.addEventListener('click', scrollToTop);
    backToTop.dataset.bound = 'true';
  }
}

function initializeHomePage() {
  bindHomePageControls();

  const startLoad = () => {
    void loadData();
  };

  if (typeof window.requestAnimationFrame === 'function') {
    window.requestAnimationFrame(startLoad);
  } else {
    setTimeout(startLoad, 0);
  }

  if (!Auth.isLoggedIn()) {
    const notice = document.getElementById('login-notice');
    if (notice) {
      notice.hidden = false;
    }
  }
}

if (window.BDA) {
  BDA.setupMobileState = function () {
    const desktop = document.getElementById('state-wrap-desktop');
    const mobile = document.getElementById('state-wrap-mobile');
    if (!desktop || !mobile) return;

    const applyLayout = () => {
      const isMobile = window.innerWidth <= 640;
      desktop.hidden = isMobile;
      mobile.hidden = !isMobile;
    };

    applyLayout();
    window.addEventListener('resize', BDA.debounce(applyLayout, 120));
  };
}

document.addEventListener('DOMContentLoaded', initializeHomePage);
