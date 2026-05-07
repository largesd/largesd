const ANALYSIS_TABS = ['evidence', 'audits'];

const AUDITS_STATE = {
  topics: [],
  selectedTopicId: null,
  audits: null,
};

function toggleHelp() {
  BDA.toggleHelp();
}

function getRequestedTab() {
  const tab = new URLSearchParams(window.location.search).get('tab');
  return ANALYSIS_TABS.includes(tab) ? tab : 'audits';
}

function getRequestedTopicId() {
  return new URLSearchParams(window.location.search).get('topic') || null;
}

BDA.registerAction('set-analysis-tab', (el) => setAnalysisTab(el.dataset.tab));

function setAnalysisTab(tab, options = {}) {
  const { updateUrl = true } = options;
  const safeTab = ANALYSIS_TABS.includes(tab) ? tab : 'audits';

  document.querySelectorAll('.analysis-tab').forEach((button) => {
    const active = button.dataset.tab === safeTab;
    button.classList.toggle('active', active);
    button.setAttribute('aria-selected', String(active));
    button.setAttribute('tabindex', active ? '0' : '-1');
  });

  document.querySelectorAll('.analysis-panel').forEach((panel) => {
    panel.hidden = panel.dataset.tabPanel !== safeTab;
  });

  if (updateUrl) {
    const url = new URL(window.location.href);
    url.searchParams.set('tab', safeTab);
    const query = url.searchParams.toString();
    const next = `${url.pathname}${query ? `?${query}` : ''}${url.hash}`;
    window.history.replaceState({}, '', next);
  }
}

function bindTabEvents() {
  document.querySelectorAll('.analysis-tab').forEach((button) => {
    button.addEventListener('click', () => setAnalysisTab(button.dataset.tab));
    button.addEventListener('keydown', (event) => {
      if (!['ArrowLeft', 'ArrowRight'].includes(event.key)) return;
      event.preventDefault();
      const currentIndex = ANALYSIS_TABS.indexOf(button.dataset.tab);
      const direction = event.key === 'ArrowRight' ? 1 : -1;
      const nextIndex = (currentIndex + direction + ANALYSIS_TABS.length) % ANALYSIS_TABS.length;
      const nextTab = ANALYSIS_TABS[nextIndex];
      setAnalysisTab(nextTab);
      const nextButton = document.querySelector(`.analysis-tab[data-tab="${nextTab}"]`);
      if (nextButton) nextButton.focus();
    });
  });
}

function showAnalysisEmpty(messageHtml) {
  const empty = document.getElementById('analysis-empty');
  document.getElementById('analysis-content').style.display = 'none';
  empty.innerHTML = messageHtml;
  empty.style.display = 'block';
}

function showAnalysisContent() {
  document.getElementById('analysis-empty').style.display = 'none';
  document.getElementById('analysis-content').style.display = 'block';
}

function renderDebateChoices(debates) {
  if (!debates.length) {
    return '<strong>No debate selected.</strong> Create a debate from <a href="new_debate.html">New Debate / Post Point</a> to unlock evidence and audits.';
  }

  const buttons = debates.map((debate) => `
    <button class="pill" data-debate-id="${BDA.escapeHtml(debate.debate_id)}">${BDA.escapeHtml(debate.resolution)}</button>
  `).join('');

  return `
    <strong>No active debate selected.</strong> Choose a public debate to inspect evidence targets and audit stress tests.
    <div class="choice-list">${buttons}</div>
  `;
}

function currentStateText(target) {
  if (target.type === 'fact' && target.current_p !== null && target.current_p !== undefined) {
    return `p=${BDA.formatNumber(target.current_p, 2)}, leverage=${BDA.formatNumber(target.leverage_score, 2)}`;
  }
  return `leverage=${BDA.formatNumber(target.leverage_score, 2)}`;
}

function renderTargets(tbodyId, targets, includeEvidenceNeeded) {
  const tbody = document.getElementById(tbodyId);
  if (!targets.length) {
    tbody.innerHTML = '<tr><td colspan="5" class="text-center-muted">No targets in this bucket.</td></tr>';
    return;
  }

  tbody.innerHTML = targets.map((target) => {
    if (includeEvidenceNeeded) {
      return `
        <tr>
          <td data-label="Target"><strong>${BDA.escapeHtml(target.title)}</strong><br><small>${BDA.escapeHtml(target.type)}</small></td>
          <td data-label="Side">${BDA.escapeHtml(target.side || '—')}</td>
          <td class="mono" data-label="Current state">${BDA.escapeHtml(currentStateText(target))}</td>
          <td class="mono" data-label="Impact on D">${BDA.formatNumber(target.impact_on_margin, 4)}</td>
          <td data-label="Evidence needed">${BDA.escapeHtml(target.evidence_needed || '—')}</td>
        </tr>
      `;
    }

    return `
      <tr>
        <td data-label="Target"><strong>${BDA.escapeHtml(target.title)}</strong><br><small>${BDA.escapeHtml(target.type)}</small></td>
        <td data-label="Side">${BDA.escapeHtml(target.side || '—')}</td>
        <td class="mono" data-label="Leverage">${BDA.formatNumber(target.leverage_score, 2)}</td>
        <td class="mono" data-label="Impact on D">${BDA.formatNumber(target.impact_on_margin, 4)}</td>
        <td data-label="Evidence type">${BDA.escapeHtml(target.evidence_type || 'mixed')}</td>
      </tr>
    `;
  }).join('');
}

function renderEvidence(data) {
  document.getElementById('evidence-verdict').textContent = data.verdict || '-';
  document.getElementById('evidence-confidence').textContent = BDA.formatNumber(data.confidence, 2);
  document.getElementById('evidence-margin').textContent = BDA.formatNumber(data.margin_d, 4);
  document.getElementById('evidence-flip-margin').textContent = BDA.formatNumber(data.margin_needed_for_flip, 4);
  document.getElementById('evidence-summary').textContent = data.summary || 'No evidence-target summary available.';

  renderTargets('high-impact-tbody', data.high_impact_targets || [], true);
  renderTargets('medium-impact-tbody', data.medium_impact_targets || [], false);

  const allTargets = [...(data.high_impact_targets || []), ...(data.medium_impact_targets || [])];
  const triggerList = document.getElementById('trigger-list');
  if (!allTargets.length) {
    triggerList.innerHTML = '<li>No update triggers available for the current snapshot.</li>';
    return;
  }

  triggerList.innerHTML = allTargets.slice(0, 6).map((target) => `
    <li><strong>${BDA.escapeHtml(target.title)}:</strong> ${BDA.escapeHtml(target.update_trigger || 'No trigger available.')}</li>
  `).join('');
}

function quantiles(values) {
  if (!values.length) return ['-', '-', '-'];
  const sorted = values.slice().sort((a, b) => a - b);
  const pick = (ratio) => sorted[Math.min(sorted.length - 1, Math.floor((sorted.length - 1) * ratio))];
  return [pick(0.1), pick(0.5), pick(0.9)].map((value) => BDA.formatNumber(value, 2));
}

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

function getSelectedTopicMeta() {
  const id = AUDITS_STATE.selectedTopicId;
  if (!id) return null;
  return AUDITS_STATE.topics.find((t) => String(t.topic_id) === id) || null;
}

function filterTopicGeometry(items) {
  const id = AUDITS_STATE.selectedTopicId;
  if (!id) return items;
  return items.filter((item) => String(item.topic_id) === id);
}

function filterSymmetryTopicDeltas(topicDeltas) {
  const id = AUDITS_STATE.selectedTopicId;
  if (!id) return topicDeltas;
  const filtered = {};
  Object.entries(topicDeltas).forEach(([topicId, delta]) => {
    if (String(topicId) === id) filtered[topicId] = delta;
  });
  return filtered;
}

function renderTopicGeometrySection() {
  const items = filterTopicGeometry(AUDITS_STATE.audits?.topic_geometry || []);
  const lineageTbody = document.getElementById('lineage-tbody');
  const geometryTbody = document.getElementById('geometry-tbody');

  if (!items.length) {
    lineageTbody.innerHTML = `<tr><td colspan="4" class="text-center-muted">${AUDITS_STATE.selectedTopicId ? 'No lineage data for the selected topic.' : 'No topic geometry available.'}</td></tr>`;
    geometryTbody.innerHTML = `<tr><td colspan="4" class="text-center-muted">${AUDITS_STATE.selectedTopicId ? 'No geometry data for the selected topic.' : 'No topic geometry available.'}</td></tr>`;
    document.getElementById('geometry-summary-row').innerHTML = '';
    return;
  }

  lineageTbody.innerHTML = items.map((topic) => `
    <tr>
      <td data-label="Topic"><a href="topic.html?id=${encodeURIComponent(topic.topic_id)}">${BDA.escapeHtml(topic.topic_id)} ${BDA.escapeHtml(topic.name || '')}</a></td>
      <td class="mono" data-label="Parent topic ids">${BDA.escapeHtml((topic.parent_topic_ids || []).join(', ') || '—')}</td>
      <td data-label="Operation">${BDA.escapeHtml(topic.operation || 'created')}</td>
      <td class="mono" data-label="Drift">${BDA.formatNumber(topic.drift_score, 2)}</td>
    </tr>
  `).join('');

  geometryTbody.innerHTML = items.map((topic) => `
    <tr>
      <td data-label="Topic"><a href="topic.html?id=${encodeURIComponent(topic.topic_id)}">${BDA.escapeHtml(topic.topic_id)} ${BDA.escapeHtml(topic.name || '')}</a></td>
      <td class="mono" data-label="Content mass">${BDA.formatNumber(topic.content_mass, 2)}</td>
      <td class="mono" data-label="Drift score">${BDA.formatNumber(topic.drift_score, 2)}</td>
      <td class="mono" data-label="Geometry quality">${BDA.formatNumber(topic.coherence, 2)} / ${BDA.formatNumber(topic.distinctness, 2)}</td>
    </tr>
  `).join('');

  const drift = quantiles(items.map((item) => item.drift_score || 0));
  const coherence = quantiles(items.map((item) => item.coherence || 0));
  const distinctness = quantiles(items.map((item) => item.distinctness || 0));
  document.getElementById('geometry-summary-row').innerHTML = `
    <span class="pill">Drift p10/p50/p90: <span class="mono">${drift.join(' / ')}</span></span>
    <span class="pill">Coherence p10/p50/p90: <span class="mono">${coherence.join(' / ')}</span></span>
    <span class="pill">Distinctness p10/p50/p90: <span class="mono">${distinctness.join(' / ')}</span></span>
  `;
}

function renderSymmetrySection() {
  const symmetry = AUDITS_STATE.audits?.label_symmetry || {};
  document.getElementById('symmetry-median-delta').textContent = BDA.formatNumber(symmetry.median_delta_d, 4);
  document.getElementById('symmetry-abs-delta').textContent = BDA.formatNumber(symmetry.abs_delta_d, 4);
  document.getElementById('symmetry-original-d').textContent = BDA.formatNumber(symmetry.original_d, 4);
  document.getElementById('symmetry-swapped-d').textContent = BDA.formatNumber(symmetry.swapped_d, 4);
  document.getElementById('symmetry-interpretation').textContent = symmetry.interpretation || 'No symmetry interpretation available.';

  const topicDeltas = Object.entries(filterSymmetryTopicDeltas(symmetry.topic_deltas || {}));
  const tbody = document.getElementById('symmetry-topics-tbody');
  if (!topicDeltas.length) {
    tbody.innerHTML = `<tr><td colspan="4" class="text-center-muted">${AUDITS_STATE.selectedTopicId ? 'No symmetry deltas for the selected topic.' : 'No topic-level symmetry deltas available.'}</td></tr>`;
    return;
  }

  tbody.innerHTML = topicDeltas.map(([topicId, delta]) => `
    <tr>
      <td data-label="Topic"><a href="topic.html?id=${encodeURIComponent(topicId)}">${BDA.escapeHtml(topicId)}</a></td>
      <td class="mono" data-label="ΔQ FOR">${BDA.formatNumber(delta.q_for_delta, 3)}</td>
      <td class="mono" data-label="ΔQ AGAINST">${BDA.formatNumber(delta.q_against_delta, 3)}</td>
      <td class="mono" data-label="Asymmetry">${BDA.formatNumber(delta.asymmetry_score, 3)}</td>
    </tr>
  `).join('');
}

function renderGlobalAuditSections() {
  const audits = AUDITS_STATE.audits || {};
  renderStability(audits.extraction_stability || {});
  renderDisagreement(audits.evaluator_disagreement || {});
  renderRelevanceSensitivity(audits.relevance_sensitivity || {});
  renderV12AuditMatrix(audits);
}

function renderSelectedTopicSummary() {
  const container = document.getElementById('selected-topic-summary');
  const meta = getSelectedTopicMeta();
  if (!meta || !AUDITS_STATE.selectedTopicId) {
    container.style.display = 'none';
    container.innerHTML = '';
    return;
  }

  container.innerHTML = `
    <h4>${BDA.escapeHtml(meta.name || 'Untitled')}</h4>
    <div class="row">
      <span class="pill">ID: <span class="mono">${BDA.escapeHtml(meta.topic_id)}</span></span>
      <span class="pill">Rel: <span class="mono">${BDA.formatNumber(meta.relevance, 2)}</span></span>
      <span class="pill">Drift: <span class="mono">${BDA.formatNumber(meta.drift_score, 2)}</span></span>
      <span class="pill">Coherence: <span class="mono">${BDA.formatNumber(meta.coherence, 2)}</span></span>
      <span class="pill">Distinctness: <span class="mono">${BDA.formatNumber(meta.distinctness, 2)}</span></span>
    </div>
    <div class="row mt-8">
      <a class="pill" href="topic.html?id=${encodeURIComponent(meta.topic_id)}">Open topic detail</a>
      <a class="pill" href="topics.html">Back to full topics list</a>
    </div>
  `;
  container.style.display = 'block';
}

function renderTopicFocusContext() {
  const contextEl = document.getElementById('topic-focus-context');
  const meta = getSelectedTopicMeta();
  if (!meta || !AUDITS_STATE.selectedTopicId) {
    contextEl.style.display = 'none';
    contextEl.textContent = '';
    return;
  }
  contextEl.innerHTML = `Topic focus is set to <strong>${BDA.escapeHtml(meta.name || meta.topic_id)}</strong>. The sections below (Extraction stability, Evaluator disagreement, Relevance sensitivity, v1.2 audit matrix) remain snapshot-wide because they are not topic-specific.`;
  contextEl.style.display = 'block';
}

function renderTopicFocusBar() {
  const select = document.getElementById('topic-focus-select');
  const clearBtn = document.getElementById('topic-focus-clear');
  const pillsRow = document.getElementById('topic-focus-pills');

  // Build dropdown options from union of topics, geometry, and symmetry
  const allIds = new Set();
  AUDITS_STATE.topics.forEach((t) => allIds.add(String(t.topic_id)));
  (AUDITS_STATE.audits?.topic_geometry || []).forEach((t) => allIds.add(String(t.topic_id)));
  Object.keys(AUDITS_STATE.audits?.label_symmetry?.topic_deltas || {}).forEach((id) => allIds.add(String(id)));

  const idToName = new Map();
  AUDITS_STATE.topics.forEach((t) => idToName.set(String(t.topic_id), t.name || t.topic_id));
  (AUDITS_STATE.audits?.topic_geometry || []).forEach((t) => {
    if (!idToName.has(String(t.topic_id))) idToName.set(String(t.topic_id), t.name || t.topic_id);
  });

  const options = Array.from(allIds)
    .sort((a, b) => {
      const nameA = String(idToName.get(a) || a).toLowerCase();
      const nameB = String(idToName.get(b) || b).toLowerCase();
      return nameA.localeCompare(nameB) || a.localeCompare(b);
    })
    .map((id) => {
      const name = idToName.get(id) || id;
      const label = name !== id ? `${BDA.escapeHtml(name)} (${BDA.escapeHtml(id)})` : BDA.escapeHtml(id);
      const selected = AUDITS_STATE.selectedTopicId === id ? ' selected' : '';
      return `<option value="${BDA.escapeHtml(id)}"${selected}>${label}</option>`;
    });

  select.innerHTML = `<option value="">All topics</option>` + options.join('');
  clearBtn.style.display = AUDITS_STATE.selectedTopicId ? 'inline-flex' : 'none';

  // Quick focus pills: most contested, biggest mover, highest drift
  const normalized = AUDITS_STATE.topics.map((topic) => ({
    ...topic,
    _topicId: String(topic.topic_id || ''),
    _relevance: toFiniteNumber(topic.relevance, 0),
    _leadMargin: computeLeadMargin(topic.scores),
    _drift: toFiniteNumber(topic.drift_score, 0),
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

  const pills = [];
  if (mostContested) {
    pills.push(`<button type="button" class="pill topic-focus-pill" data-topic-id="${BDA.escapeHtml(mostContested._topicId)}">Most contested: ${BDA.escapeHtml(mostContested.name || mostContested._topicId)}</button>`);
  }
  if (biggestMover) {
    pills.push(`<button type="button" class="pill topic-focus-pill" data-topic-id="${BDA.escapeHtml(biggestMover._topicId)}">Biggest mover: ${BDA.escapeHtml(biggestMover.name || biggestMover._topicId)}</button>`);
  }
  if (highestDrift) {
    pills.push(`<button type="button" class="pill topic-focus-pill" data-topic-id="${BDA.escapeHtml(highestDrift._topicId)}">Highest drift: ${BDA.escapeHtml(highestDrift.name || highestDrift._topicId)}</button>`);
  }
  pillsRow.innerHTML = pills.join('');
}

function setSelectedTopic(topicId, options = {}) {
  const { updateUrl = true } = options;
  AUDITS_STATE.selectedTopicId = topicId || null;
  renderTopicFocusBar();
  renderSelectedTopicSummary();
  renderTopicFocusContext();
  renderTopicGeometrySection();
  renderSymmetrySection();
  if (updateUrl) syncTopicFilterUrl();
}

function syncTopicFilterUrl() {
  const url = new URL(window.location.href);
  if (AUDITS_STATE.selectedTopicId) url.searchParams.set('topic', AUDITS_STATE.selectedTopicId);
  else url.searchParams.delete('topic');
  window.history.replaceState({}, '', url);
}

function bindAuditTopicControls() {
  const select = document.getElementById('topic-focus-select');
  const clearBtn = document.getElementById('topic-focus-clear');
  const pillsRow = document.getElementById('topic-focus-pills');

  if (select) {
    select.addEventListener('change', (e) => {
      setSelectedTopic(e.target.value || null);
    });
  }

  if (clearBtn) {
    clearBtn.addEventListener('click', () => {
      setSelectedTopic(null);
    });
  }

  if (pillsRow) {
    pillsRow.addEventListener('click', (e) => {
      const pill = e.target.closest('.topic-focus-pill');
      if (!pill) return;
      setSelectedTopic(pill.dataset.topicId || null);
    });
  }
}

function rerenderAuditPanels() {
  renderTopicFocusBar();
  renderSelectedTopicSummary();
  renderTopicFocusContext();
  renderTopicGeometrySection();
  renderSymmetrySection();
  renderGlobalAuditSections();
}

function renderStability(stability) {
  const layers = [
    ['FACT', stability.fact_overlap || {}],
    ['ARGUMENT', stability.argument_overlap || {}]
  ];

  document.getElementById('stability-tbody').innerHTML = layers.map(([label, metrics]) => `
    <tr>
      <td data-label="Layer">${label}</td>
      <td class="mono" data-label="Jaccard">${BDA.formatNumber(metrics.jaccard, 3)}</td>
      <td class="mono" data-label="Precision">${BDA.formatNumber(metrics.precision, 3)}</td>
      <td class="mono" data-label="Recall">${BDA.formatNumber(metrics.recall, 3)}</td>
      <td class="mono" data-label="Set sizes">${metrics.intersection_size ?? 0} / ${metrics.set1_size ?? 0} / ${metrics.set2_size ?? 0}</td>
    </tr>
  `).join('');

  document.getElementById('stability-runs').textContent = stability.num_runs ?? '-';
  document.getElementById('stability-score').textContent = BDA.formatNumber(stability.stability_score, 3);

  const mismatches = stability.mismatches || [];
  document.getElementById('mismatch-report').textContent = mismatches.length
    ? mismatches.map((item) => `- ${item.type}: ${item.fact_text} [severity=${item.severity}, p=${BDA.formatNumber(item.p_true, 2)}]`).join('\n')
    : 'No extraction mismatches were recorded for this snapshot.';
}

function renderDisagreement(disagreement) {
  document.getElementById('disagreement-tbody').innerHTML = `
    <tr><td data-label="Quantity">Reasoning spread</td><td class="mono" data-label="Median / IQR">${BDA.formatNumber(disagreement.reasoning_iqr_median, 2)}</td><td data-label="Interpretation">Median IQR across judge reasoning scores.</td></tr>
    <tr><td data-label="Quantity">Coverage spread</td><td class="mono" data-label="Median / IQR">${BDA.formatNumber(disagreement.coverage_iqr_median, 2)}</td><td data-label="Interpretation">Median IQR across judge coverage scores.</td></tr>
    <tr><td data-label="Quantity">Overall score spread</td><td class="mono" data-label="Median / IQR">${BDA.formatNumber(disagreement.overall_iqr, 2)}</td><td data-label="Interpretation">Spread of final side scores.</td></tr>
  `;
}

function renderRelevanceSensitivity(data) {
  document.getElementById('rel-d-mean').textContent = BDA.formatNumber(data.d_mean, 4);
  document.getElementById('rel-d-std').textContent = BDA.formatNumber(data.d_std, 4);
  document.getElementById('rel-d-range').textContent = `${BDA.formatNumber(data.d_min, 4)} to ${BDA.formatNumber(data.d_max, 4)}`;
  document.getElementById('rel-stability-ratio').textContent = BDA.formatNumber(data.stability_ratio, 2);
  document.getElementById('rel-interpretation').textContent = data.interpretation || '-';

  const verdictDistribution = Object.entries(data.verdict_distribution || {});
  const row = document.getElementById('rel-verdict-distribution');
  row.innerHTML = verdictDistribution.length
    ? verdictDistribution.map(([label, count]) => `<span class="pill">${BDA.escapeHtml(label)}: <span class="mono">${count}</span></span>`).join('')
    : '<small class="text-muted">No verdict distribution available.</small>';
}

function renderV12AuditMatrix(audits) {
  const dominance = audits.topic_dominance || {};
  const merge = audits.merge_sensitivity || {};
  const participation = audits.participation_concentration || {};
  const concentration = participation.concentration_buckets || {};
  const integrity = audits.integrity_indicators || {};
  const template = integrity.template_similarity_prevalence || {};
  const cap = audits.centrality_cap_effect || {};
  const coverage = audits.coverage_adequacy_trace || {};
  const frame = audits.frame_sensitivity || {};
  const budget = audits.budget_adequacy || {};
  const rarity = audits.rarity_utilization || {};

  document.getElementById('audit-schema-version').textContent = audits.audit_schema_version || '-';
  document.getElementById('audit-top3-pre').textContent = BDA.formatNumber(dominance.top_3_canonical_mass_share || 0, 4);
  document.getElementById('audit-top3-sel').textContent = BDA.formatNumber(dominance.top_3_selected_mass_share || 0, 4);
  document.getElementById('audit-merge-stability').textContent = BDA.formatNumber(merge.mapping_stability || 0, 4);
  document.getElementById('audit-participation-entropy').textContent = BDA.formatNumber(participation.participation_entropy || 0, 4);
  document.getElementById('audit-top10-share').textContent = BDA.formatNumber(concentration.top_10pct_share || 0, 4);
  document.getElementById('audit-template-sim').textContent = BDA.formatNumber(template.template_similarity_rate || 0, 4);
  document.getElementById('audit-items-capped').textContent = cap.items_affected_by_cap ?? 0;
  document.getElementById('audit-cap-value').textContent = BDA.formatNumber(cap.cap_value || 0, 4);
  document.getElementById('audit-pool-capped').textContent = BDA.formatNumber(cap.fraction_of_pool_capped || 0, 4);
  document.getElementById('audit-coverage-mode').textContent = audits.formula_registry?.feature_flags?.COVERAGE_MODE || 'leverage_legacy';
  document.getElementById('audit-frame-delta').textContent = BDA.formatNumber(frame.max_delta_d || 0, 4);

  // Budget adequacy
  document.getElementById('audit-canonical-mass').textContent = BDA.formatNumber(budget.canonical_mass_represented || 0, 4);
  document.getElementById('audit-topk-coverage').textContent = BDA.formatNumber(budget.top_k_central_coverage || 0, 4);
  document.getElementById('audit-selection-coverage').textContent = BDA.formatNumber(budget.selection_coverage || 0, 4);

  // Rarity utilization
  document.getElementById('audit-rarity-rho').textContent = BDA.formatNumber(rarity.rarity_slice_rho || 0, 4);
  document.getElementById('audit-rarity-size').textContent = rarity.low_centrality_set_size ?? '-';
  document.getElementById('audit-rarity-util').textContent = BDA.formatNumber(rarity.rarity_utilization || 0, 4);
  document.getElementById('audit-rarity-impact').textContent = rarity.impact_on_verdict_description || '-';

  // Participation concentration
  const buckets = concentration.buckets || {};
  const bucketDisplay = Object.entries(buckets).map(([k, v]) => `${k}=${v}`).join(', ') || '-';
  document.getElementById('audit-conc-buckets').textContent = bucketDisplay;
  const mix = participation.channel_mix || {};
  const mixDisplay = Object.entries(mix).map(([k, v]) => `${k}=${BDA.formatNumber(v, 2)}`).join(', ') || '-';
  document.getElementById('audit-channel-mix').textContent = mixDisplay;

  // Drop-component sensitivity
  const drop = audits.drop_component_sensitivity || {};
  const dropEl = document.getElementById('audit-drop-component');
  if (Object.keys(drop).length) {
    dropEl.innerHTML = Object.entries(drop).map(([topic, vals]) => `
      <div class="row mb-6">
        <span class="mono min-w-120">${BDA.escapeHtml(topic)}</span>
        <span class="pill text-72">without F: ${BDA.formatNumber(vals.d_without_factuality, 4)}</span>
        <span class="pill text-72">without N: ${BDA.formatNumber(vals.d_without_normative, 4)}</span>
        <span class="pill text-72">without Reason: ${BDA.formatNumber(vals.d_without_reasoning, 4)}</span>
        <span class="pill text-72">without Cov: ${BDA.formatNumber(vals.d_without_coverage, 4)}</span>
      </div>
    `).join('');
  }

  document.getElementById('audit-v12-raw').textContent = JSON.stringify({
    topic_dominance: audits.topic_dominance,
    topic_concentration: audits.topic_concentration,
    merge_sensitivity: audits.merge_sensitivity,
    integrity_indicators: audits.integrity_indicators,
    participation_concentration: audits.participation_concentration,
    budget_adequacy: audits.budget_adequacy,
    centrality_cap_effect: audits.centrality_cap_effect,
    rarity_utilization: audits.rarity_utilization,
    coverage_adequacy_trace: audits.coverage_adequacy_trace,
    frame_sensitivity: audits.frame_sensitivity,
    drop_component_sensitivity: audits.drop_component_sensitivity,
  }, null, 2);
}

async function loadAuditDependencies() {
  const debate = await BDA.loadDebate();
  if (!debate.has_debate) {
    const debates = await BDA.loadDebates();
    showAnalysisEmpty(renderDebateChoices(debates));
    document.querySelectorAll('#analysis-empty [data-debate-id]').forEach((button) => {
      button.addEventListener('click', () => {
        BDA.setActiveDebateId(button.getAttribute('data-debate-id'));
        window.location.reload();
      });
    });
    return false;
  }

  const snapshot = await BDA.loadSnapshot();
  if (!snapshot || !snapshot.has_snapshot) {
    showAnalysisEmpty('This debate does not have auditable snapshot data yet. Generate a snapshot from <a href="new_debate.html">New Debate / Post Point</a> first.');
    return false;
  }

  BDA.updateStateStrip(snapshot);
  return true;
}

async function initAnalysisPage() {
  bindTabEvents();
  setAnalysisTab(getRequestedTab(), { updateUrl: false });

  const ready = await loadAuditDependencies();
  if (!ready) return;

  // Load topics first so the focus bar can populate
  try {
    const topicsData = await BDA.api('/api/debate/topics');
    AUDITS_STATE.topics = topicsData.topics || [];
  } catch (error) {
    console.warn('Unable to load topics for audit focus bar:', error);
    AUDITS_STATE.topics = [];
  }

  // Restore topic focus from URL
  const urlTopicId = getRequestedTopicId();
  if (urlTopicId) AUDITS_STATE.selectedTopicId = urlTopicId;

  let evidenceOk = false;
  let auditsOk = false;

  try {
    const evidence = await BDA.api('/api/debate/evidence-targets');
    renderEvidence(evidence);
    evidenceOk = true;
  } catch (error) {
    const errorMsg = error?.message || 'Unable to load live evidence targets right now.';
    const requestId = error?.payload?.request_id || '';
    const callout = document.getElementById('evidence-panel-error');
    if (typeof BDA !== 'undefined' && typeof BDA.showInlineError === 'function' && callout) {
      BDA.showInlineError(callout, errorMsg, () => {
        if (requestId) console.error(`[request_id: ${requestId}] Retry loading evidence targets`);
        initAnalysisPage();
      });
      callout.style.display = 'block';
    } else if (callout) {
      callout.innerHTML = `Unable to load live evidence targets right now: ${BDA.escapeHtml(errorMsg)}`;
      callout.style.display = 'block';
    }
  }

  try {
    const audits = await BDA.api('/api/debate/audits');
    AUDITS_STATE.audits = audits;
    rerenderAuditPanels();
    auditsOk = true;
  } catch (error) {
    const errorMsg = error?.message || 'Unable to load live audits right now.';
    const requestId = error?.payload?.request_id || '';
    const callout = document.getElementById('audits-panel-error');
    if (typeof BDA !== 'undefined' && typeof BDA.showInlineError === 'function' && callout) {
      BDA.showInlineError(callout, errorMsg, () => {
        if (requestId) console.error(`[request_id: ${requestId}] Retry loading audits`);
        initAnalysisPage();
      });
      callout.style.display = 'block';
    } else if (callout) {
      callout.innerHTML = `Unable to load live audits right now: ${BDA.escapeHtml(errorMsg)}`;
      callout.style.display = 'block';
    }
  }

  bindAuditTopicControls();

  if (!evidenceOk && !auditsOk) {
    showAnalysisEmpty('Unable to load live evidence or audits right now. Please try again.');
    return;
  }

  showAnalysisContent();
  BDA.setupTableScroll();
  BDA.setupTooltips();
}

document.addEventListener('DOMContentLoaded', initAnalysisPage);
