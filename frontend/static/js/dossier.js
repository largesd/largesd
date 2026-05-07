function showDossierEmpty(messageHtml) {
  const empty = document.getElementById('dossier-empty');
  document.getElementById('dossier-content').style.display = 'none';
  empty.innerHTML = messageHtml;
  empty.style.display = 'block';
}

function showDossierContent() {
  document.getElementById('dossier-empty').style.display = 'none';
  document.getElementById('dossier-content').style.display = 'block';
}

function renderEvidenceGaps(evidenceGaps) {
  const tbody = document.getElementById('evidence-gaps-tbody');
  const entries = Object.entries(evidenceGaps || {});
  if (!entries.length) {
    tbody.innerHTML = '<tr><td colspan="6" class="text-center-muted">No evidence gap data available.</td></tr>';
    return;
  }

  tbody.innerHTML = entries.map(([key, value]) => `
    <tr>
      <td class="mono" data-label="Topic-side">${BDA.escapeHtml(key)}</td>
      <td class="mono" data-label="Insufficiency rate">${BDA.formatNumber(Number(value.insufficiency_rate || 0), 3)}</td>
      <td class="mono" data-label="Supported-only factuality">${BDA.formatNumber(Number(value.f_supported_only || 0), 3)}</td>
      <td class="mono" data-label="All-claims factuality">${BDA.formatNumber(Number(value.f_all || 0), 3)}</td>
      <td class="mono" data-label="max_abs_delta_D">${BDA.formatNumber(Number(value.max_abs_delta_d || 0), 4)}</td>
      <td class="mono" data-label="Tier distribution">${BDA.escapeHtml(JSON.stringify(value.tier_distribution || {}))}</td>
    </tr>
  `).join('');
}

function renderSelectionDiagnostics(selectionDiagnostics) {
  const tbody = document.getElementById('selection-diag-tbody');
  const entries = Object.entries(selectionDiagnostics || {});
  if (!entries.length) {
    tbody.innerHTML = '<tr><td colspan="4" class="text-center-muted">No selection diagnostics recorded yet.</td></tr>';
    document.getElementById('selection-diag-raw').textContent = 'No selection diagnostics available.';
    return;
  }

  tbody.innerHTML = entries.map(([key, value]) => {
    const selectedFacts = Number(value?.summary?.total_facts_selected ?? value?.counts?.selected_facts ?? value?.selected_fact_ids?.length ?? 0);
    const selectedArgs = Number(value?.summary?.total_arguments_selected ?? value?.counts?.selected_arguments ?? value?.selected_arg_ids?.length ?? 0);
    const seed = value?.selection_recipe?.seed ?? value?.seed ?? '-';
    return `
      <tr>
        <td class="mono" data-label="Topic-side">${BDA.escapeHtml(key)}</td>
        <td class="mono" data-label="Selected facts">${selectedFacts}</td>
        <td class="mono" data-label="Selected arguments">${selectedArgs}</td>
        <td class="mono" data-label="Selection seed">${BDA.escapeHtml(String(seed))}</td>
      </tr>
    `;
  }).join('');

  document.getElementById('selection-diag-raw').textContent = JSON.stringify(selectionDiagnostics, null, 2);
}

function renderDecisiveOutputs(dossier) {
  const premises = (dossier.decisive_premises || []).map((item) => ({
    type: 'premise',
    id: item.canon_fact_id,
    side: item.side,
    score: item.p_or_q_score ?? item.p_true,
    text: item.text,
    provenance: (item.span_ids || []).join(', '),
  }));
  const argumentsRows = (dossier.decisive_arguments || []).map((item) => ({
    type: 'argument',
    id: item.canon_arg_id,
    side: item.side,
    score: item.reasoning_score,
    text: item.text,
    provenance: (item.span_ids || []).join(', '),
  }));
  const rows = [...premises, ...argumentsRows].slice(0, 12);
  const tbody = document.getElementById('decisive-outputs-tbody');
  if (!rows.length) {
    tbody.innerHTML = '<tr><td colspan="5" class="text-center-muted">No decisive outputs published for this snapshot.</td></tr>';
    return;
  }
  tbody.innerHTML = rows.map((row) => `
    <tr>
      <td data-label="Type">${BDA.escapeHtml(row.type)}</td>
      <td data-label="Item"><strong class="mono">${BDA.escapeHtml(row.id || '-')}</strong><br><small>${BDA.escapeHtml(row.text || '')}</small></td>
      <td data-label="Side">${BDA.escapeHtml(row.side || '-')}</td>
      <td class="mono" data-label="Score">${BDA.formatNumber(Number(row.score || 0), 3)}</td>
      <td class="mono" data-label="Provenance">${BDA.escapeHtml(row.provenance || '-')}</td>
    </tr>
  `).join('');
}

function renderCounterfactuals(counterfactuals) {
  const entries = Object.entries(counterfactuals || {});
  const tbody = document.getElementById('counterfactuals-tbody');
  if (!entries.length) {
    tbody.innerHTML = '<tr><td colspan="4" class="text-center-muted">No remove-topic counterfactuals available.</td></tr>';
    return;
  }
  tbody.innerHTML = entries.map(([topicId, item]) => `
    <tr>
      <td class="mono" data-label="Topic">${BDA.escapeHtml(topicId)}</td>
      <td class="mono" data-label="D without topic">${BDA.formatNumber(item.d_without_topic || 0, 4)}</td>
      <td class="mono" data-label="Change in D">${BDA.formatNumber(item.change_in_d || 0, 4)}</td>
      <td data-label="Would flip?">${item.would_flip_verdict ? 'yes' : 'no'}</td>
    </tr>
  `).join('');
}

function renderPriorityGaps(priorityGaps) {
  const empirical = (priorityGaps?.insufficient_empirical_items || []).slice();
  empirical.sort((a, b) => Math.abs(b.marginal_swing_delta_i || 0) - Math.abs(a.marginal_swing_delta_i || 0));
  const normative = priorityGaps?.high_dispersion_normative_items || [];
  const rows = [
    ...empirical.slice(0, 6).map((item) => `Empirical ${item.canon_fact_id}: δ_i=${BDA.formatNumber(item.marginal_swing_delta_i || 0, 4)} — ${item.operationalization || item.text || ''}`),
    ...normative.slice(0, 4).map((item) => `Normative ${item.canon_fact_id}: review frame acceptability (${item.normative_provenance || 'no provenance'})`),
  ];
  document.getElementById('priority-gaps-list').innerHTML = rows.length
    ? rows.map((row) => `<li>${BDA.escapeHtml(row)}</li>`).join('')
    : '<li>No priority gaps published for this snapshot.</li>';
}

function renderSensitivityAndTail(dossier) {
  const sensitivity = dossier.insufficiency_sensitivity || {};
  document.getElementById('insuff-true').textContent = BDA.formatNumber(sensitivity.D_if_insufficient_true || 0, 4);
  document.getElementById('insuff-false').textContent = BDA.formatNumber(sensitivity.D_if_insufficient_false || 0, 4);
  document.getElementById('insuff-deltas').textContent = `${BDA.formatNumber(sensitivity.delta_D_true || 0, 4)} / ${BDA.formatNumber(sensitivity.delta_D_false || 0, 4)}`;
  document.getElementById('unselected-tail-raw').textContent = JSON.stringify(dossier.unselected_tail_summary || {}, null, 2);

  // Swing analysis
  const swing = dossier.insufficiency_swing || {};
  document.getElementById('swing-max-delta').textContent = BDA.formatNumber(swing.max_abs_delta_D || 0, 4);
  document.getElementById('swing-bound').textContent = BDA.formatNumber(swing.overall_swing_bound || 0, 4);

  // Decisive premise rank
  const decisive = (dossier.decisive_premises || []).filter(p => p.status === 'INSUFFICIENT');
  decisive.sort((a, b) => Math.abs(b.marginal_swing_delta_i || 0) - Math.abs(a.marginal_swing_delta_i || 0));
  const rankTbody = document.getElementById('decisive-rank-tbody');
  if (!decisive.length) {
    rankTbody.innerHTML = '<tr><td colspan="5" class="text-center-muted">No INSUFFICIENT premises are currently decisive.</td></tr>';
  } else {
    rankTbody.innerHTML = decisive.slice(0, 10).map((p, i) => `
      <tr>
        <td data-label="Rank">${i + 1}</td>
        <td class="mono" data-label="Premise ID">${BDA.escapeHtml(p.canon_fact_id || p.premise_id || '-')}</td>
        <td data-label="Topic-side">${BDA.escapeHtml(p.topic_side || `${p.topic_id || ''}-${p.side || ''}`)}</td>
        <td data-label="Current status">${BDA.escapeHtml(p.status || 'INSUFFICIENT')}</td>
        <td class="mono" data-label="Marginal swing δ_i">${BDA.formatNumber(p.marginal_swing_delta_i || 0, 4)}</td>
      </tr>
    `).join('');
  }

  // Component breakdown
  const breakdown = dossier.component_breakdown || {};
  const cbEntries = Object.entries(breakdown);
  const cbTbody = document.getElementById('component-breakdown-tbody');
  if (!cbEntries.length) {
    cbTbody.innerHTML = '<tr><td colspan="6" class="text-center-muted">No component breakdown available.</td></tr>';
  } else {
    cbTbody.innerHTML = cbEntries.map(([key, val]) => `
      <tr>
        <td class="mono" data-label="Topic-side">${BDA.escapeHtml(key)}</td>
        <td class="mono" data-label="F (factuality)">${BDA.formatNumber(val.factuality, 3)}</td>
        <td class="mono" data-label="N (normative)">${BDA.formatNumber(val.normative, 3)}</td>
        <td class="mono" data-label="Reason">${BDA.formatNumber(val.reasoning, 3)}</td>
        <td class="mono" data-label="Coverage">${BDA.formatNumber(val.coverage, 3)}</td>
        <td class="mono" data-label="Q (geomean)"><strong>${BDA.formatNumber(val.quality, 3)}</strong></td>
      </tr>
    `).join('');
  }

  // Drop-component sensitivity
  const drop = dossier.drop_component_sensitivity || {};
  const dropEntries = Object.entries(drop);
  const dropTbody = document.getElementById('drop-component-tbody');
  if (!dropEntries.length) {
    dropTbody.innerHTML = '<tr><td colspan="5" class="text-center-muted">No drop-component sensitivity data available.</td></tr>';
  } else {
    dropTbody.innerHTML = dropEntries.map(([key, val]) => `
      <tr>
        <td class="mono" data-label="Topic">${BDA.escapeHtml(key)}</td>
        <td class="mono" data-label="D without F">${BDA.formatNumber(val.d_without_factuality, 4)}</td>
        <td class="mono" data-label="D without N">${BDA.formatNumber(val.d_without_normative, 4)}</td>
        <td class="mono" data-label="D without Reason">${BDA.formatNumber(val.d_without_reasoning, 4)}</td>
        <td class="mono" data-label="D without Coverage">${BDA.formatNumber(val.d_without_coverage, 4)}</td>
      </tr>
    `).join('');
  }

  // Coverage adequacy trace
  const trace = dossier.coverage_adequacy_trace || {};
  const overall = trace.overall || {};
  const traceRow = document.getElementById('coverage-trace-row');
  if (overall.empirical_rebuttals === undefined) {
    traceRow.innerHTML = '<small class="text-muted">No coverage trace available.</small>';
  } else {
    traceRow.innerHTML = `
      <span class="pill">EMPIRICAL: <span class="mono">${overall.empirical_rebuttals ?? '-'}</span></span>
      <span class="pill">NORMATIVE: <span class="mono">${overall.normative_rebuttals ?? '-'}</span></span>
      <span class="pill">INFERENCE: <span class="mono">${overall.inference_rebuttals ?? '-'}</span></span>
      <span class="pill">SCOPE/DEF: <span class="mono">${overall.scope_definition_shifts ?? '-'}</span></span>
    `;
  }
}

async function loadDossier() {
  const debate = await BDA.loadDebate();
  if (!debate.has_debate) {
    showDossierEmpty('No active debate selected. Start one from <a href="new_debate.html">Post Argument</a> to unlock dossier data.');
    return;
  }

  const snapshot = await BDA.loadSnapshot();
  if (!snapshot || !snapshot.has_snapshot) {
    showDossierEmpty('This debate has no snapshot yet. Generate one from <a href="new_debate.html">Post Argument</a> before opening the dossier.');
    return;
  }

  BDA.updateStateStrip(snapshot);

  try {
    const dossier = await BDA.api('/api/debate/decision-dossier');
    if (dossier.insufficient_data) {
      showDossierEmpty(`<strong>Insufficient adjudication data</strong><p>${BDA.escapeHtml(dossier.message || 'No allowed posts or scores are available for this debate yet.')}</p>`);
      return;
    }
    showDossierContent();

    document.getElementById('dossier-snapshot-id').textContent = dossier.snapshot_id || '-';
    document.getElementById('dossier-verdict').textContent = dossier.verdict || 'NO VERDICT';
    document.getElementById('dossier-confidence').textContent = BDA.formatNumber(Number(dossier.confidence || 0), 3);

    const frame = dossier.frame || {};
    document.getElementById('frame-statement').textContent = frame.statement || 'No active frame metadata.';
    document.getElementById('frame-meta').textContent = frame.version
      ? `Frame ${frame.frame_id || '-'} • version ${frame.version}`
      : 'Frame version unavailable.';

    renderEvidenceGaps(dossier.evidence_gaps || {});
    renderSelectionDiagnostics(dossier.selection_diagnostics || {});
    renderDecisiveOutputs(dossier);
    renderCounterfactuals(dossier.counterfactuals || {});
    renderPriorityGaps(dossier.priority_gaps || {});
    renderSensitivityAndTail(dossier);
  } catch (error) {
    showDossierEmpty(error.message || 'Failed to load decision dossier.');
  }
}

document.addEventListener('DOMContentLoaded', () => {
  loadDossier();
});
