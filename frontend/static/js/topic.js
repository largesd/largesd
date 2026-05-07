function formatTier(tier) {
  if (tier === 1 || tier === '1') return 'T1';
  if (tier === 2 || tier === '2') return 'T2';
  if (tier === 3 || tier === '3') return 'T3';
  return '—';
}

// Get topic ID from URL parameter
const urlParams = new URLSearchParams(window.location.search);
const topicId = urlParams.get('id') || 't1';

async function loadTopicData() {
  try {
    // Load debate and snapshot
    const debateData = await BDA.loadDebate();
    if (debateData.has_debate) {
      const snapshotData = await BDA.loadSnapshot();
      if (snapshotData) {
        BDA.updateStateStrip(snapshotData);
      }
    }

    // Load specific topic
    const topic = await BDA.api(`/api/debate/topics/${topicId}`);

    if (topic.error) {
      document.getElementById('topic-name').textContent = 'Topic Not Found';
      document.getElementById('topic-scope').textContent = topic.error;
      return;
    }

    // Update topic info
    document.getElementById('topic-name').textContent = topic.name || `Topic ${topicId}`;
    document.getElementById('topic-scope').textContent = topic.scope || '';
    document.getElementById('topic-id-badge').textContent = topicId;
    document.getElementById('topic-status').textContent = 'Active';

    if (topic.operation && topic.operation !== 'created') {
      const opBadge = document.getElementById('topic-operation');
      opBadge.textContent = topic.operation;
      opBadge.style.display = 'inline-block';
    }

    // Update metrics
    document.getElementById('meta-relevance').textContent = BDA.formatNumber(topic.relevance, 3);
    document.getElementById('meta-drift').textContent = BDA.formatNumber(topic.drift_score, 3);
    document.getElementById('meta-coherence').textContent = BDA.formatNumber(topic.coherence, 3);
    document.getElementById('meta-distinctness').textContent = BDA.formatNumber(topic.distinctness, 3);

    // Update summaries
    if (topic.summary_for) {
      document.getElementById('summary-for').textContent = topic.summary_for;
      document.getElementById('summary-for').style.color = '';
    }
    if (topic.summary_against) {
      document.getElementById('summary-against').textContent = topic.summary_against;
      document.getElementById('summary-against').style.color = '';
    }

    // Update scores table
    updateScoresTable(topic.scores);

    // Update facts
    updateFacts(topic.facts);

  } catch (error) {
    console.error('Error loading topic:', error);
    const topicNameEl = document.getElementById('topic-name');
    const errorMsg = error?.message || 'Error loading topic.';
    const requestId = error?.payload?.request_id || '';
    if (typeof BDA !== 'undefined' && typeof BDA.showInlineError === 'function') {
      BDA.showInlineError(topicNameEl, errorMsg, () => {
        if (requestId) console.error(`[request_id: ${requestId}] Retry loading topic`);
        loadTopicData();
      });
    } else {
      topicNameEl.textContent = 'Error Loading Topic';
    }
  }
}

function updateScoresTable(scores) {
  const tbody = document.getElementById('scores-tbody');

  const forScores = scores?.FOR || {};
  const againstScores = scores?.AGAINST || {};

  tbody.innerHTML = `
    <tr class="side-for">
      <td data-label="Side"><strong>FOR</strong></td>
      <td class="mono" data-label="Factuality (F)">${BDA.formatNumber(forScores.factuality, 3)}</td>
      <td class="mono" data-label="Reasoning">${BDA.formatNumber(forScores.reasoning, 3)}</td>
      <td class="mono" data-label="Coverage">${BDA.formatNumber(forScores.coverage, 3)}</td>
      <td class="mono" data-label="Quality (Q)"><strong>${BDA.formatNumber(forScores.quality, 3)}</strong></td>
    </tr>
    <tr class="side-against">
      <td data-label="Side"><strong>AGAINST</strong></td>
      <td class="mono" data-label="Factuality (F)">${BDA.formatNumber(againstScores.factuality, 3)}</td>
      <td class="mono" data-label="Reasoning">${BDA.formatNumber(againstScores.reasoning, 3)}</td>
      <td class="mono" data-label="Coverage">${BDA.formatNumber(againstScores.coverage, 3)}</td>
      <td class="mono" data-label="Quality (Q)"><strong>${BDA.formatNumber(againstScores.quality, 3)}</strong></td>
    </tr>
  `;
}

function updateFacts(facts) {
  const forFacts = facts?.filter(f => f.side === 'FOR') || [];
  const againstFacts = facts?.filter(f => f.side === 'AGAINST') || [];

  renderFactList('for-facts', forFacts, 'var(--good)');
  renderFactList('against-facts', againstFacts, 'var(--warn)');
}

function renderFactList(elementId, facts, colorVar) {
  const container = document.getElementById(elementId);

  if (facts.length === 0) {
    container.innerHTML = '<small class="text-muted">No facts yet.</small>';
    return;
  }

  container.innerHTML = facts.map(f => {
    const status = f.v15_status || (f.p_true === 1.0 ? 'SUPPORTED' : f.p_true === 0.0 ? 'REFUTED' : 'INSUFFICIENT');
    const p = f.v15_p !== undefined ? f.v15_p : f.p_true;
    const statusColor = status === 'SUPPORTED' ? 'var(--good)' : status === 'REFUTED' ? 'var(--bad)' : 'var(--warn)';
    const flags = f.v15_human_review_flags || [];
    const critical = new Set(['CONTRADICTORY_TIER1_EVIDENCE', 'HIGH_IMPACT_INSUFFICIENT', 'HIGH_IMPACT_LLM_DIRECTION']);
    const flagTags = flags.map(flag => {
      const cls = critical.has(flag) ? 'flag-tag critical' : 'flag-tag';
      return `<span class="${cls}">${BDA.escapeHtml(flag)}</span>`;
    }).join('');
    const tierCounts = f.evidence_tier_counts || {};
    const tierDist = Object.entries(tierCounts).map(([k, v]) => `${BDA.escapeHtml(k)}: ${v}`).join(', ') || 'None';
    const synth = f.synthesis_logic_json || {};
    const resolved = f.resolved_value || null;
    const provenance = f.provenance_spans || [];

    return `
    <div class="surface-box">
      <div class="text-13">${BDA.escapeHtml(f.canon_fact_text)}</div>
      <div class="row mt-8-text-11-wrap-gap-6">
        <span class="pill border-${status === 'SUPPORTED' ? 'good' : status === 'REFUTED' ? 'bad' : 'warn'} text-${status === 'SUPPORTED' ? 'good' : status === 'REFUTED' ? 'bad' : 'warn'}">${BDA.escapeHtml(status)}</span>
        <span class="pill mono">p=${BDA.formatNumber(Number(p), 1)}</span>
        <span class="pill mono">Best: ${formatTier(f.v15_best_evidence_tier)}</span>
        <span class="text-muted">${f.member_count} source${f.member_count !== 1 ? 's' : ''}</span>
      </div>
      ${status === 'INSUFFICIENT' && f.v15_insufficiency_reason ? `
      <div class="mt-6">
        <span class="pill warn text-72">${BDA.escapeHtml(f.v15_insufficiency_reason)}</span>
      </div>` : ''}
      ${flags.length ? `<div class="mt-6">${flagTags}</div>` : ''}
      ${f.operationalization ? `
      <details class="mt-8-text-82">
        <summary>Operationalization</summary>
        <p class="mt-4-text-ink-soft">${BDA.escapeHtml(f.operationalization)}</p>
      </details>` : ''}
      <details class="mt-8-text-82">
        <summary>Tier distribution</summary>
        <p class="mt-4-text-ink-soft">${tierDist}</p>
      </details>
      ${Object.keys(synth).length ? `
      <details class="mt-8-text-82">
        <summary>Synthesis logic</summary>
        <div class="codebox text-78-mt-4">${BDA.escapeHtml(JSON.stringify(synth, null, 2))}</div>
      </details>` : ''}
      ${resolved ? `
      <div class="mt-6-text-82">
        <span class="pill mono">Value: ${BDA.escapeHtml(String(resolved.value))} ${BDA.escapeHtml(resolved.unit || '')}</span>
        <span class="pill mono">Type: ${BDA.escapeHtml(resolved.type || '-')}</span>
        ${resolved.lower_bound !== undefined ? `<span class="pill mono">[${BDA.formatNumber(resolved.lower_bound, 3)}, ${BDA.formatNumber(resolved.upper_bound, 3)}]</span>` : ''}
      </div>` : ''}
      ${provenance.length ? `
      <details class="mt-8-text-82">
        <summary>Provenance spans (${provenance.length})</summary>
        <ul class="mt-4-pl-16-text-ink-soft">
          ${provenance.map(s => `<li class="mono">${BDA.escapeHtml(s.span_id || s)}</li>`).join('')}
        </ul>
      </details>` : ''}
    </div>
  `;
  }).join('');
}

async function loadTopicList() {
  try {
    const data = await BDA.api('/api/debate/topics');
    const topics = data.topics || [];

    const container = document.getElementById('topic-list');
    if (topics.length === 0) {
      container.innerHTML = '<small class="text-muted">No topics available.</small>';
      return;
    }

    container.innerHTML = topics.map(t => `
      <a href="topic.html?id=${t.topic_id}"
         class="subnav-link ${t.topic_id === topicId ? 'active' : ''}">
        ${t.topic_id}: ${t.name}
      </a>
    `).join('');

  } catch (error) {
    console.error('Error loading topic list:', error);
    const container = document.getElementById('topic-list');
    const errorMsg = error?.message || 'Failed to load topics.';
    const requestId = error?.payload?.request_id || '';
    if (typeof BDA !== 'undefined' && typeof BDA.showInlineError === 'function') {
      BDA.showInlineError(container, errorMsg, () => {
        if (requestId) console.error(`[request_id: ${requestId}] Retry loading topics`);
        loadTopicList();
      });
    } else if (container) {
      container.innerHTML = '<small class="text-muted">Failed to load topics.</small>';
    }
  }
}

function updateTopicAuditLink() {
  const link = document.getElementById('topic-audit-link');
  if (link && topicId) {
    link.href = `audits.html?tab=audits&topic=${encodeURIComponent(topicId)}#topic-geometry`;
  }
}

// Initialize
document.addEventListener('DOMContentLoaded', () => {
  loadTopicData();
  loadTopicList();
  updateTopicAuditLink();
});
