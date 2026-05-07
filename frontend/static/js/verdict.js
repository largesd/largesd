function toggleHelp() {
  BDA.toggleHelp();
}

function showVerdictEmpty(messageHtml) {
  const empty = document.getElementById('verdict-empty');
  document.getElementById('verdict-content').style.display = 'none';
  empty.innerHTML = messageHtml;
  empty.style.display = 'block';
}

function showVerdictContent() {
  document.getElementById('verdict-empty').style.display = 'none';
  document.getElementById('verdict-content').style.display = 'block';
}

function renderDebateChoices(debates) {
  if (!debates.length) {
    return '<strong>No debate selected.</strong> Create a debate from <a href="new_debate.html">New Debate / Post Point</a> to compute a live verdict.';
  }

  const buttons = debates.map((debate) => `
    <button class="pill" data-debate-id="${BDA.escapeHtml(debate.debate_id)}">${BDA.escapeHtml(debate.resolution)}</button>
  `).join('');

  return `
    <strong>No active debate selected.</strong> Choose a public debate to inspect its live verdict.
    <div class="choice-list">${buttons}</div>
  `;
}

function verdictClass(verdict) {
  if (verdict === 'FOR') return 'verdict-for';
  if (verdict === 'AGAINST') return 'verdict-against';
  return 'verdict-neutral';
}

function renderInterval(ciLow, ciHigh, margin) {
  const min = Math.min(ciLow, 0, margin);
  const max = Math.max(ciHigh, 0, margin);
  const span = Math.max(max - min, 0.001);
  const percent = (value) => ((value - min) / span) * 100;

  document.getElementById('axis-min').textContent = BDA.formatNumber(min, 4);
  document.getElementById('axis-max').textContent = BDA.formatNumber(max, 4);
  document.getElementById('ci-band').style.left = `${percent(ciLow)}%`;
  document.getElementById('ci-band').style.width = `${Math.max(percent(ciHigh) - percent(ciLow), 1)}%`;
  document.getElementById('ci-zero').style.left = `${percent(0)}%`;
  document.getElementById('ci-point').style.left = `${percent(margin)}%`;
}

function buildReadout(verdict, contributions, ci) {
  if (!contributions.length) {
    return 'No topic contributions are available yet.';
  }

  const sorted = contributions.slice().sort((a, b) => Math.abs(b.contribution_to_d) - Math.abs(a.contribution_to_d));
  const top = sorted[0];
  const direction = top.contribution_to_d >= 0 ? 'FOR' : 'AGAINST';
  const second = sorted[1];

  if (verdict === 'NO VERDICT') {
    return `The interval still crosses zero. ${top.topic_id} contributes the strongest movement toward ${direction}, but the lead is not stable enough to commit.`;
  }

  const secondText = second
    ? ` The next-largest mover is ${second.topic_id}, which pushes ${second.contribution_to_d >= 0 ? 'FOR' : 'AGAINST'}.`
    : '';

  return `Current live verdict: ${verdict}. ${top.topic_id} is the strongest driver of the margin, and CI(D) stays on the ${verdict === 'FOR' ? 'positive' : 'negative'} side of zero.${secondText}`;
}

function buildIntervalExplanation(ciLow, ciHigh, verdict) {
  if (ciLow <= 0 && ciHigh >= 0) {
    return 'The confidence interval still spans both sides of zero, so the system keeps the verdict at NO VERDICT.';
  }
  if (verdict === 'FOR') {
    return 'The entire interval stays above zero, so the current evidence supports a FOR verdict.';
  }
  if (verdict === 'AGAINST') {
    return 'The entire interval stays below zero, so the current evidence supports an AGAINST verdict.';
  }
  return 'The system is using the live interval to decide whether the margin is truly separated from zero.';
}

function renderHistogram(values, containerId) {
  const container = document.getElementById(containerId);
  if (!values || values.length < 2) {
    container.innerHTML = '<small class="text-muted">Not enough replicate values for histogram.</small>';
    return;
  }
  const min = Math.min(...values);
  const max = Math.max(...values);
  const buckets = 10;
  const counts = new Array(buckets).fill(0);
  const span = Math.max(max - min, 0.0001);
  values.forEach((v) => {
    const idx = Math.min(buckets - 1, Math.floor(((v - min) / span) * buckets));
    counts[idx]++;
  });
  const maxCount = Math.max(...counts);
  container.innerHTML = `
    <div class="grid-gap-4-mt-8">
      ${counts.map((c, i) => {
        const left = BDA.formatNumber(min + (i * span) / buckets, 3);
        const widthPct = maxCount > 0 ? (c / maxCount) * 100 : 0;
        return `<div class="grid-80-1fr-auto-gap-8-items-center-text-78">
          <span class="mono">${left}</span>
          <div class="bar-track">
            <div class="bar-fill" data-width="${widthPct}"></div>
          </div>
          <span class="mono">${c}</span>
        </div>`;
      }).join('')}
    </div>
    <div class="row mt-8">
      <span class="pill">n=${values.length}</span>
      <span class="pill">min=${BDA.formatNumber(min, 4)}</span>
      <span class="pill">max=${BDA.formatNumber(max, 4)}</span>
    </div>
  `;
  container.querySelectorAll('[data-width]').forEach(el => {
    el.style.width = el.dataset.width + '%';
    el.removeAttribute('data-width');
  });
}

function renderVerdict(snapshot, verdictData) {
  const verdict = snapshot.verdict || verdictData.verdict || 'NO VERDICT';
  const verdictCss = verdictClass(verdict);
  const ciLow = snapshot.ci_d?.[0] ?? verdictData.ci_d?.[0] ?? 0;
  const ciHigh = snapshot.ci_d?.[1] ?? verdictData.ci_d?.[1] ?? 0;
  const margin = snapshot.margin_d ?? verdictData.margin_d ?? 0;

  document.getElementById('overall-for').textContent = BDA.formatNumber(snapshot.overall_for, 2);
  document.getElementById('overall-against').textContent = BDA.formatNumber(snapshot.overall_against, 2);
  document.getElementById('margin-d').textContent = BDA.formatNumber(margin, 4);
  document.getElementById('ci-d').textContent = `[${BDA.formatNumber(ciLow, 4)}, ${BDA.formatNumber(ciHigh, 4)}]`;
  document.getElementById('confidence-badge').textContent = BDA.formatNumber(snapshot.confidence, 2);
  document.getElementById('verdict-pill').innerHTML = `Current state: <strong class="${verdictCss}">${verdict}</strong>`;
  document.getElementById('verdict-badge').innerHTML = `Verdict: <b>${verdict}</b>`;
  document.getElementById('dist-explanation').textContent = buildIntervalExplanation(ciLow, ciHigh, verdict);

  renderInterval(ciLow, ciHigh, margin);

  const contributions = verdictData.topic_contributions || [];
  document.getElementById('plain-readout').innerHTML = `<strong>Summary:</strong> ${BDA.escapeHtml(buildReadout(verdict, contributions, [ciLow, ciHigh]))}`;
  renderDrivers(contributions);
  renderVerdictMetadata(verdictData);

  renderContributions(contributions);

  // Factuality breakdown
  const factuality = verdictData.factuality || {};
  const fbEntries = Object.entries(factuality.topic_breakdown || {});
  const fbTbody = document.getElementById('factuality-tbody');
  if (!fbEntries.length) {
    fbTbody.innerHTML = '<tr><td colspan="5" class="text-center-muted">No factuality breakdown available.</td></tr>';
  } else {
    fbTbody.innerHTML = fbEntries.map(([key, val]) => `
      <tr>
        <td class="mono" data-label="Topic-side">${BDA.escapeHtml(key)}</td>
        <td class="mono" data-label="F_t,s">${BDA.formatNumber(val.f_ts, 3)}</td>
        <td class="mono" data-label="F_supported_only">${val.f_supported_only !== null && val.f_supported_only !== undefined ? BDA.formatNumber(val.f_supported_only, 3) : '—'}</td>
        <td class="mono" data-label="Insufficiency rate">${BDA.formatNumber(val.insufficiency_rate || 0, 3)}</td>
        <td class="mono" data-label="Tier counts">${BDA.escapeHtml(JSON.stringify(val.tier_counts || {}))}</td>
      </tr>
    `).join('');
  }

  // Judge dispersion
  const dispersion = verdictData.judge_dispersion || {};
  const dispRows = [
    { component: 'Reasoning', ...dispersion.reasoning },
    { component: 'Coverage', ...dispersion.coverage },
    { component: 'Normative', ...dispersion.normative },
  ].filter(r => r.median !== undefined);
  const dispTbody = document.getElementById('dispersion-tbody');
  if (!dispRows.length) {
    dispTbody.innerHTML = '<tr><td colspan="4" class="text-center-muted">No dispersion data available.</td></tr>';
  } else {
    dispTbody.innerHTML = dispRows.map((r) => `
      <tr>
        <td data-label="Component">${BDA.escapeHtml(r.component)}</td>
        <td class="mono" data-label="Median">${BDA.formatNumber(r.median, 3)}</td>
        <td class="mono" data-label="IQR">${BDA.formatNumber(r.iqr, 3)}</td>
        <td data-label="Interpretation">${BDA.escapeHtml(r.interpretation || '-')}</td>
      </tr>
    `).join('');
  }

  // Replicate distribution
  const dDist = verdictData.d_distribution || [];
  renderHistogram(dDist, 'replicate-distribution');
  const repMeta = verdictData.replicate_composition_metadata || {};
  const repContainer = document.getElementById('replicate-distribution');
  if (repContainer && dDist.length) {
    const extra = document.createElement('div');
    extra.className = 'row';
    extra.style.marginTop = '8px';
    extra.innerHTML = `
      <span class="pill">CI method: <span class="mono">${BDA.escapeHtml(verdictData.ci_method || 'bootstrap')}</span></span>
      <span class="pill">Replicates: <span class="mono">${dDist.length}</span></span>
      <span class="pill">Judges: <span class="mono">${repMeta.judge_count ?? '-'}</span></span>
    `;
    repContainer.appendChild(extra);
  }

  // Drop-component sensitivity
  const drop = verdictData.drop_component_sensitivity || {};
  const dropEntries = Object.entries(drop);
  const dropTbody = document.getElementById('verdict-drop-tbody');
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

  // Frame sensitivity
  const frameSens = verdictData.frame_sensitivity || {};
  const frames = frameSens.frames || [];
  const fsTbody = document.getElementById('frame-sensitivity-tbody');
  if (!frames.length) {
    fsTbody.innerHTML = '<tr><td colspan="5" class="text-center-muted">No multi-frame data available.</td></tr>';
  } else {
    fsTbody.innerHTML = frames.map((f) => `
      <tr>
        <td class="mono" data-label="Frame">${BDA.escapeHtml(f.frame_id || '-')}</td>
        <td class="mono" data-label="Overall FOR">${BDA.formatNumber(f.overall_for, 3)}</td>
        <td class="mono" data-label="Overall AGAINST">${BDA.formatNumber(f.overall_against, 3)}</td>
        <td class="mono" data-label="D">${BDA.formatNumber(f.margin_d, 4)}</td>
        <td data-label="Verdict">${BDA.escapeHtml(f.verdict || 'NO VERDICT')}</td>
      </tr>
    `).join('');
  }
  const fsMeta = document.getElementById('frame-sensitivity-meta');
  if (fsMeta && frameSens.max_delta_d !== undefined) {
    fsMeta.innerHTML = `<span class="pill">max_delta_D: <span class="mono">${BDA.formatNumber(frameSens.max_delta_d, 4)}</span></span>`;
  }
}

function renderVerdictMetadata(verdictData) {
  const replicate = verdictData.replicate_composition_metadata || {};
  const formulas = verdictData.formula_metadata || {};
  document.getElementById('d-sample-count').textContent = (verdictData.d_distribution || []).length;
  document.getElementById('replicate-judges').textContent = replicate.judge_count ?? '-';
  document.getElementById('verdict-rel-formula').textContent = formulas.relevance?.active_mode || '-';
  document.getElementById('verdict-coverage-mode').textContent = formulas.feature_flags?.COVERAGE_MODE || '-';
  document.getElementById('verdict-formula-raw').textContent = JSON.stringify(formulas, null, 2);
}

function renderDrivers(contributions) {
  const tbody = document.getElementById('drivers-tbody');
  if (!contributions.length) {
    tbody.innerHTML = '<tr><td colspan="3" class="text-center-muted">No driver data available yet.</td></tr>';
    return;
  }
  const rows = contributions
    .slice()
    .sort((a, b) => Math.abs(b.contribution_to_d) - Math.abs(a.contribution_to_d))
    .slice(0, 5)
    .map((item) => {
      const side = item.contribution_to_d > 0 ? 'FOR' : item.contribution_to_d < 0 ? 'AGAINST' : 'Neutral';
      const colorClass = item.contribution_to_d > 0 ? 'text-good' : item.contribution_to_d < 0 ? 'text-warn' : 'text-muted';
      return `
        <tr>
          <td data-label="Topic">${BDA.escapeHtml(item.name || item.topic_id)}</td>
          <td class="${colorClass}" data-label="Side push">${side}</td>
          <td class="mono" data-label="Strength">${BDA.formatNumber(Math.abs(item.contribution_to_d), 4)}</td>
        </tr>
      `;
    });
  tbody.innerHTML = rows.join('');
}

function renderContributions(contributions) {
  const tbody = document.getElementById('contributions-tbody');
  if (!contributions.length) {
    tbody.innerHTML = '<tr><td colspan="13" class="text-center-muted">No contribution data available.</td></tr>';
    return;
  }

  const rows = contributions
    .slice()
    .sort((a, b) => Math.abs(b.contribution_to_d) - Math.abs(a.contribution_to_d))
    .map((item) => {
      const style = item.contribution_to_d > 0
        ? ' class="text-good"'
        : item.contribution_to_d < 0
          ? ' class="text-warn"'
          : '';
      return `
        <tr>
          <td data-label="Topic"><a href="topic.html?id=${encodeURIComponent(item.topic_id)}">${BDA.escapeHtml(item.topic_id)} ${BDA.escapeHtml(item.name || '')}</a></td>
          <td class="mono" data-label="Rel">${BDA.formatNumber(item.relevance, 2)}</td>
          <td class="mono" data-label="F_FOR">${BDA.formatNumber(item.f_for, 3)}</td>
          <td class="mono" data-label="F_AGAINST">${BDA.formatNumber(item.f_against, 3)}</td>
          <td class="mono" data-label="N_FOR">${BDA.formatNumber(item.n_for, 3)}</td>
          <td class="mono" data-label="N_AGAINST">${BDA.formatNumber(item.n_against, 3)}</td>
          <td class="mono" data-label="Reason_FOR">${BDA.formatNumber(item.reason_for, 3)}</td>
          <td class="mono" data-label="Reason_AGAINST">${BDA.formatNumber(item.reason_against, 3)}</td>
          <td class="mono" data-label="Cov_FOR">${BDA.formatNumber(item.cov_for, 3)}</td>
          <td class="mono" data-label="Cov_AGAINST">${BDA.formatNumber(item.cov_against, 3)}</td>
          <td class="mono" data-label="Q_FOR">${BDA.formatNumber(item.q_for, 2)}</td>
          <td class="mono" data-label="Q_AGAINST">${BDA.formatNumber(item.q_against, 2)}</td>
          <td class="mono" data-label="Contribution" ${style}>${item.contribution_to_d > 0 ? '+' : ''}${BDA.formatNumber(item.contribution_to_d, 4)}</td>
        </tr>
      `;
    });

  tbody.innerHTML = rows.join('');
}

async function initVerdictPage() {
  const debate = await BDA.loadDebate();
  if (!debate.has_debate) {
    const debates = await BDA.loadDebates();
    showVerdictEmpty(renderDebateChoices(debates));
    document.querySelectorAll('#verdict-empty [data-debate-id]').forEach((button) => {
      button.addEventListener('click', () => {
        BDA.setActiveDebateId(button.getAttribute('data-debate-id'));
        window.location.reload();
      });
    });
    return;
  }

  const snapshot = await BDA.loadSnapshot();
  if (!snapshot || !snapshot.has_snapshot) {
    showVerdictEmpty('This debate does not have a snapshot yet. Generate one from <a href="new_debate.html">New Debate / Post Point</a> first.');
    return;
  }

  BDA.updateStateStrip(snapshot);

  try {
    const verdictData = await BDA.api('/api/debate/verdict');
    if (verdictData.insufficient_data) {
      showVerdictEmpty(`<strong>Insufficient adjudication data</strong><p>${BDA.escapeHtml(verdictData.message || 'No allowed posts or scores are available for this debate yet.')}</p>`);
      return;
    }
    renderVerdict(snapshot, verdictData);
    showVerdictContent();
    BDA.setupTableScroll();
  } catch (error) {
    const errorMsg = error?.message || 'Unable to load live verdict data right now.';
    const requestId = error?.payload?.request_id || '';
    if (typeof BDA !== 'undefined' && typeof BDA.showInlineError === 'function') {
      const emptyEl = document.getElementById('verdict-empty');
      if (emptyEl) {
        BDA.showInlineError(emptyEl, errorMsg, () => {
          if (requestId) console.error(`[request_id: ${requestId}] Retry loading verdict`);
          initVerdictPage();
        });
      } else {
        showVerdictEmpty(`Unable to load live verdict data right now: ${BDA.escapeHtml(errorMsg)}`);
      }
    } else {
      showVerdictEmpty(`Unable to load live verdict data right now: ${BDA.escapeHtml(errorMsg)}`);
    }
  }
}

document.addEventListener('DOMContentLoaded', initVerdictPage);
