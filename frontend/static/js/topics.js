const API_BASE = window.location.origin;

const REVIEW_THRESHOLDS = {
  drift: 0.50,
  coherence: 0.50,
  distinctness: 0.50,
  highRelevance: 0.30,
  smallLeadMargin: 0.05,
};

const TOPICS_STATE = {
  rawTopics: [],
  query: '',
  sort: 'relevance_desc',
  flags: new Set(),
};

function toFiniteNumber(value, fallback = 0) {
  const n = Number(value);
  return Number.isFinite(n) ? n : fallback;
}

function computeLeadMargin(scores) {
  if (!scores || typeof scores !== 'object') return null;
  const qualities = Object.values(scores)
    .map((sideScore) => toFiniteNumber(sideScore && sideScore.quality, Number.NaN))
    .filter((quality) => Number.isFinite(quality))
    .sort((a, b) => b - a);

  if (qualities.length < 2) return null;
  return Math.abs(qualities[0] - qualities[1]);
}

function getTopicReviewFlags(topic) {
  const flags = [];
  const relevance = toFiniteNumber(topic.relevance, 0);
  const drift = toFiniteNumber(topic.drift_score, 0);
  const coherence = toFiniteNumber(topic.coherence, 0);
  const distinctness = toFiniteNumber(topic.distinctness, 0);
  const leadMargin = computeLeadMargin(topic.scores);

  if (relevance >= REVIEW_THRESHOLDS.highRelevance) flags.push('high_relevance');
  if (drift >= REVIEW_THRESHOLDS.drift) flags.push('high_drift');
  if (coherence <= REVIEW_THRESHOLDS.coherence) flags.push('low_coherence');
  if (distinctness <= REVIEW_THRESHOLDS.distinctness) flags.push('low_distinctness');
  if (
    drift >= REVIEW_THRESHOLDS.drift ||
    coherence <= REVIEW_THRESHOLDS.coherence ||
    distinctness <= REVIEW_THRESHOLDS.distinctness ||
    (relevance >= REVIEW_THRESHOLDS.highRelevance && Number.isFinite(leadMargin) && leadMargin <= REVIEW_THRESHOLDS.smallLeadMargin)
  ) {
    flags.push('needs_review');
  }
  return flags;
}

function matchesQuery(topic, query) {
  if (!query) return true;
  const q = query.toLowerCase().trim();
  if (!q) return true;
  const name = String(topic.name || '').toLowerCase();
  const scope = String(topic.scope || '').toLowerCase();
  const id = String(topic.topic_id || '').toLowerCase();
  return name.includes(q) || scope.includes(q) || id.includes(q);
}

function sortTopics(items, mode) {
  const sorted = items.slice();
  const tiebreak = (a, b) => {
    const nameA = String(a.name || '').toLowerCase();
    const nameB = String(b.name || '').toLowerCase();
    if (nameA !== nameB) return nameA.localeCompare(nameB);
    return String(a.topic_id || '').localeCompare(String(b.topic_id || ''));
  };

  switch (mode) {
    case 'relevance_desc':
      sorted.sort((a, b) => (b.relevance - a.relevance) || tiebreak(a, b));
      break;
    case 'drift_desc':
      sorted.sort((a, b) => (b.drift_score - a.drift_score) || tiebreak(a, b));
      break;
    case 'contested_asc': {
      sorted.sort((a, b) => {
        const marginA = computeLeadMargin(a.scores);
        const marginB = computeLeadMargin(b.scores);
        const finiteA = Number.isFinite(marginA);
        const finiteB = Number.isFinite(marginB);
        if (!finiteA && !finiteB) return tiebreak(a, b);
        if (!finiteA) return 1;
        if (!finiteB) return -1;
        return (marginA - marginB) || tiebreak(a, b);
      });
      break;
    }
    case 'coherence_asc':
      sorted.sort((a, b) => (a.coherence - b.coherence) || tiebreak(a, b));
      break;
    case 'distinctness_asc':
      sorted.sort((a, b) => (a.distinctness - b.distinctness) || tiebreak(a, b));
      break;
    case 'name_asc':
      sorted.sort((a, b) => tiebreak(a, b));
      break;
    default:
      sorted.sort((a, b) => (b.relevance - a.relevance) || tiebreak(a, b));
  }
  return sorted;
}

function getFilteredTopics() {
  let items = TOPICS_STATE.rawTopics.filter((t) => matchesQuery(t, TOPICS_STATE.query));

  if (TOPICS_STATE.flags.size > 0) {
    items = items.filter((t) => {
      const flags = getTopicReviewFlags(t);
      return flags.some((f) => TOPICS_STATE.flags.has(f));
    });
  }

  return sortTopics(items, TOPICS_STATE.sort);
}

function syncTopicControlsFromUrl() {
  const params = new URLSearchParams(window.location.search);
  TOPICS_STATE.query = params.get('q') || '';
  TOPICS_STATE.sort = params.get('sort') || 'relevance_desc';
  TOPICS_STATE.flags = new Set();
  const flagsParam = params.get('flags');
  if (flagsParam) {
    flagsParam.split(',').forEach((f) => {
      const trimmed = f.trim();
      if (trimmed) TOPICS_STATE.flags.add(trimmed);
    });
  }
}

function syncTopicUrlFromState() {
  const url = new URL(window.location.href);
  if (TOPICS_STATE.query) url.searchParams.set('q', TOPICS_STATE.query);
  else url.searchParams.delete('q');

  if (TOPICS_STATE.sort !== 'relevance_desc') url.searchParams.set('sort', TOPICS_STATE.sort);
  else url.searchParams.delete('sort');

  if (TOPICS_STATE.flags.size > 0) url.searchParams.set('flags', Array.from(TOPICS_STATE.flags).join(','));
  else url.searchParams.delete('flags');

  window.history.replaceState({}, '', url);
}

function updateControlsUI() {
  const searchEl = document.getElementById('topics-search');
  const sortEl = document.getElementById('topics-sort');
  if (searchEl) searchEl.value = TOPICS_STATE.query;
  if (sortEl) sortEl.value = TOPICS_STATE.sort;

  document.querySelectorAll('.topics-filter-chip').forEach((label) => {
    const flag = label.dataset.flag;
    const active = TOPICS_STATE.flags.has(flag);
    label.classList.toggle('active', active);
    const input = label.querySelector('input');
    if (input) input.checked = active;
  });

  const clearBtn = document.getElementById('topics-clear-btn');
  if (clearBtn) {
    const hasFilters = TOPICS_STATE.query || TOPICS_STATE.flags.size > 0 || TOPICS_STATE.sort !== 'relevance_desc';
    clearBtn.style.display = hasFilters ? 'inline-flex' : 'none';
  }
}

function renderTopicDiagnostics(data) {
  const dominance = data.dominance || {};
  document.getElementById('topic-rel-formula').textContent = data.relevance_formula_mode || 'legacy_linear';
  document.getElementById('topic-top3-pre').textContent = BDA.formatNumber(dominance.top_3_canonical_mass_share || 0, 4);
  document.getElementById('topic-top3-sel').textContent = BDA.formatNumber(dominance.top_3_selected_mass_share || 0, 4);
  document.getElementById('topic-micro-rate').textContent = BDA.formatNumber(data.micro_topic_rate || 0, 4);
  document.getElementById('topic-gini').textContent = BDA.formatNumber(data.gini_coefficient || 0, 4);
}

function renderTopicsSummary() {
  const filtered = getFilteredTopics();
  const summaryEl = document.getElementById('topics-results-summary');
  const total = TOPICS_STATE.rawTopics.length;
  const showing = filtered.length;

  const needsReviewCount = TOPICS_STATE.rawTopics.filter((t) => getTopicReviewFlags(t).includes('needs_review')).length;

  let html = `Showing ${showing} of ${total} topics`;
  if (needsReviewCount > 0) html += ` • ${needsReviewCount} flagged as needs review`;
  summaryEl.innerHTML = html;

  // Review first panel
  const panel = document.getElementById('review-first-panel');
  const grid = document.getElementById('review-first-grid');
  if (!panel || !grid) return;

  if (TOPICS_STATE.rawTopics.length === 0) {
    panel.style.display = 'none';
    return;
  }

  const normalized = TOPICS_STATE.rawTopics.map((topic) => ({
    ...topic,
    _topicId: String(topic.topic_id || ''),
    _relevance: toFiniteNumber(topic.relevance, 0),
    _leadMargin: computeLeadMargin(topic.scores),
    _drift: toFiniteNumber(topic.drift_score, 0),
    _coherence: toFiniteNumber(topic.coherence, 0),
  }));

  const withMargin = normalized.filter((t) => Number.isFinite(t._leadMargin));
  const mostContested = (withMargin.length > 0 ? withMargin : normalized)
    .slice()
    .sort((a, b) => (
      toFiniteNumber(a._leadMargin, 1) - toFiniteNumber(b._leadMargin, 1)
      || b._relevance - a._relevance
      || a._topicId.localeCompare(b._topicId)
    ))[0];

  const biggestMover = (withMargin.length > 0 ? withMargin : normalized)
    .slice()
    .sort((a, b) => (
      (b._relevance * toFiniteNumber(b._leadMargin, 1))
      - (a._relevance * toFiniteNumber(a._leadMargin, 1))
      || b._relevance - a._relevance
      || a._topicId.localeCompare(b._topicId)
    ))[0];

  const highestDrift = normalized.slice().sort((a, b) => b._drift - a._drift || a._topicId.localeCompare(b._topicId))[0];
  const lowestCoherence = normalized.slice().sort((a, b) => a._coherence - b._coherence || a._topicId.localeCompare(b._topicId))[0];

  const cards = [];
  if (mostContested) {
    cards.push(`
      <div class="review-first-card">
        <p class="review-first-label">Most contested</p>
        <a class="review-first-title" href="topic.html?id=${encodeURIComponent(mostContested._topicId)}">${BDA.escapeHtml(mostContested.name || mostContested._topicId)}</a>
        <p class="review-first-meta is-placeholder" aria-hidden="true">&nbsp;</p>
        <div class="topic-row-actions">
          <a class="pill" href="audits.html?tab=audits&topic=${encodeURIComponent(mostContested._topicId)}#topic-geometry">Open audit</a>
        </div>
      </div>
    `);
  }
  if (biggestMover) {
    cards.push(`
      <div class="review-first-card">
        <p class="review-first-label">Biggest verdict mover</p>
        <a class="review-first-title" href="topic.html?id=${encodeURIComponent(biggestMover._topicId)}">${BDA.escapeHtml(biggestMover.name || biggestMover._topicId)}</a>
        <p class="review-first-meta is-placeholder" aria-hidden="true">&nbsp;</p>
        <div class="topic-row-actions">
          <a class="pill" href="audits.html?tab=audits&topic=${encodeURIComponent(biggestMover._topicId)}#topic-geometry">Open audit</a>
        </div>
      </div>
    `);
  }
  if (highestDrift) {
    cards.push(`
      <div class="review-first-card">
        <p class="review-first-label">Highest drift</p>
        <a class="review-first-title" href="topic.html?id=${encodeURIComponent(highestDrift._topicId)}">${BDA.escapeHtml(highestDrift.name || highestDrift._topicId)}</a>
        <p class="review-first-meta">Drift ${highestDrift._drift.toFixed(2)}</p>
        <div class="topic-row-actions">
          <a class="pill" href="audits.html?tab=audits&topic=${encodeURIComponent(highestDrift._topicId)}#topic-geometry">Open audit</a>
        </div>
      </div>
    `);
  }
  if (lowestCoherence) {
    cards.push(`
      <div class="review-first-card">
        <p class="review-first-label">Lowest coherence</p>
        <a class="review-first-title" href="topic.html?id=${encodeURIComponent(lowestCoherence._topicId)}">${BDA.escapeHtml(lowestCoherence.name || lowestCoherence._topicId)}</a>
        <p class="review-first-meta">Coherence ${lowestCoherence._coherence.toFixed(2)}</p>
        <div class="topic-row-actions">
          <a class="pill" href="audits.html?tab=audits&topic=${encodeURIComponent(lowestCoherence._topicId)}#topic-geometry">Open audit</a>
        </div>
      </div>
    `);
  }

  grid.innerHTML = cards.join('');
  panel.style.display = cards.length ? 'block' : 'none';
}

function renderTopicsTable() {
  const tbody = document.getElementById('topics-tbody');
  const topics = getFilteredTopics();

  if (topics.length === 0) {
    tbody.innerHTML = `
      <tr>
        <td colspan="5" class="topics-status-row">
          No topics match your search or filters.
          <br><button type="button" class="pill topics-status-action" data-action="clear-topic-filters">Clear filters</button>
        </td>
      </tr>
    `;
    return;
  }

  tbody.innerHTML = topics.map((t) => {
    const flags = getTopicReviewFlags(t);
    const badgesHtml = flags
      .filter((f) => f !== 'needs_review' || flags.length === 1)
      .map((f) => `<span class="topic-badge ${BDA.escapeHtml(f)}">${BDA.escapeHtml(f.replace(/_/g, ' '))}</span>`)
      .join('');

    return `
      <tr data-testid="topic-row-${t.topic_id}">
        <td class="topic-name-cell" data-label="Name & scope">
          <a href="topic.html?id=${encodeURIComponent(t.topic_id)}">${BDA.escapeHtml(t.name || 'Untitled')}</a>
          ${t.scope ? `<p class="topic-scope">${BDA.escapeHtml(t.scope)}</p>` : ''}
          <div class="topic-meta-line">
            <span class="mono">${BDA.escapeHtml(t.topic_id)}</span>
            ${t.operation ? `<span class="mono">${BDA.escapeHtml(t.operation)}</span>` : ''}
            ${badgesHtml}
          </div>
          <div class="topic-row-actions">
            <a class="pill" href="topic.html?id=${encodeURIComponent(t.topic_id)}">Open detail</a>
            <a class="pill" href="audits.html?tab=audits&topic=${encodeURIComponent(t.topic_id)}#topic-geometry">Open audit</a>
          </div>
        </td>
        <td class="mono" data-label="Rel_t">${toFiniteNumber(t.relevance, 0).toFixed(2)}</td>
        <td class="mono" data-label="Drift">${toFiniteNumber(t.drift_score, 0).toFixed(2)}</td>
        <td class="mono" data-label="Coherence">${toFiniteNumber(t.coherence, 0).toFixed(2)}</td>
        <td class="mono" data-label="Distinctness">${toFiniteNumber(t.distinctness, 0).toFixed(2)}</td>
      </tr>
    `;
  }).join('');
}

BDA.registerAction('clear-topic-filters', clearTopicFilters);

function clearTopicFilters() {
  TOPICS_STATE.query = '';
  TOPICS_STATE.sort = 'relevance_desc';
  TOPICS_STATE.flags.clear();
  updateControlsUI();
  renderTopicsSummary();
  renderTopicsTable();
  syncTopicUrlFromState();
}

function applyTopicViewState() {
  renderTopicsSummary();
  renderTopicsTable();
  syncTopicUrlFromState();
}

function bindTopicControls() {
  const searchEl = document.getElementById('topics-search');
  const sortEl = document.getElementById('topics-sort');
  const clearBtn = document.getElementById('topics-clear-btn');

  const debouncedSearch = BDA.debounce((value) => {
    TOPICS_STATE.query = value;
    updateControlsUI();
    applyTopicViewState();
  }, 150);

  if (searchEl) {
    searchEl.addEventListener('input', (e) => debouncedSearch(e.target.value));
  }

  if (sortEl) {
    sortEl.addEventListener('change', (e) => {
      TOPICS_STATE.sort = e.target.value;
      updateControlsUI();
      applyTopicViewState();
    });
  }

  document.querySelectorAll('.topics-filter-chip').forEach((label) => {
    const input = label.querySelector('input');
    if (!input) return;
    input.addEventListener('change', () => {
      const flag = input.value;
      if (input.checked) TOPICS_STATE.flags.add(flag);
      else TOPICS_STATE.flags.delete(flag);
      updateControlsUI();
      applyTopicViewState();
    });
  });

  if (clearBtn) {
    clearBtn.addEventListener('click', clearTopicFilters);
  }
}

async function loadData() {
  try {
    const debateData = await BDA.loadDebate();
    if (!debateData.has_debate) {
      document.getElementById('topics-tbody').innerHTML = '<tr><td colspan="5" class="topics-status-row">No active debate selected.</td></tr>';
      return;
    }

    const snapshotData = await BDA.loadSnapshot();
    if (snapshotData && snapshotData.has_snapshot) {
      BDA.updateStateStrip(snapshotData);
    }

    const topicsData = await BDA.api('/api/debate/topics');

    if (topicsData.topics) {
      TOPICS_STATE.rawTopics = topicsData.topics;
      syncTopicControlsFromUrl();
      renderTopicDiagnostics(topicsData);
      renderTopicsSummary();
      renderTopicsTable();
      updateControlsUI();
      bindTopicControls();
    }
  } catch (error) {
    console.error('Error loading data:', error);
    const tbody = document.getElementById('topics-tbody');
    const errorMsg = error?.message || 'Error loading topics.';
    const requestId = error?.payload?.request_id || '';
    if (typeof BDA !== 'undefined' && typeof BDA.showInlineError === 'function' && tbody) {
      BDA.showInlineError(tbody, errorMsg, () => {
        if (requestId) console.error(`[request_id: ${requestId}] Retry loading topics`);
        loadData();
      });
    } else if (tbody) {
      tbody.innerHTML = '<tr><td colspan="5" class="topics-status-row is-error">Error loading topics.</td></tr>';
    }
  }
}

// Initialize
document.addEventListener('DOMContentLoaded', loadData);

// Back to top button
const backToTop = document.querySelector('.back-to-top');
window.addEventListener('scroll', () => {
  if (window.scrollY > 300) backToTop.classList.add('visible');
  else backToTop.classList.remove('visible');
});

// Help panel toggle
function toggleHelp() {
  document.getElementById('helpPanel').classList.toggle('open');
  document.querySelector('.help-overlay').classList.toggle('visible');
}

// Table scroll indicator
document.querySelectorAll('.table-wrap').forEach(wrap => {
  wrap.classList.add('scrollable');
  wrap.addEventListener('scroll', () => {
    const isScrollable = wrap.scrollWidth > wrap.clientWidth;
    const isAtEnd = wrap.scrollLeft + wrap.clientWidth >= wrap.scrollWidth - 10;
    wrap.classList.toggle('show-fade', isScrollable && !isAtEnd);
  });
  wrap.dispatchEvent(new Event('scroll'));
});

// Mobile state strip
if (window.innerWidth <= 640) {
  document.querySelector('.state-wrap').style.display = 'none';
  document.querySelector('.state-wrap:last-of-type').style.display = 'grid';
}

// Tooltip system
const tooltipPopup = document.createElement('div');
tooltipPopup.className = 'tooltip-popup';
document.body.appendChild(tooltipPopup);

document.querySelectorAll('.tooltip').forEach(el => {
  el.addEventListener('mouseenter', (e) => {
    const text = el.getAttribute('data-tooltip');
    tooltipPopup.textContent = text;
    tooltipPopup.classList.add('visible');
    const rect = el.getBoundingClientRect();
    const popupRect = tooltipPopup.getBoundingClientRect();
    let top = rect.top - popupRect.height - 8;
    let left = rect.left + (rect.width / 2) - (popupRect.width / 2);
    left = Math.max(10, Math.min(left, window.innerWidth - popupRect.width - 10));
    if (top < 10) top = rect.bottom + 8;
    tooltipPopup.style.top = top + 'px';
    tooltipPopup.style.left = left + 'px';
  });
  el.addEventListener('mouseleave', () => {
    tooltipPopup.classList.remove('visible');
  });
});
