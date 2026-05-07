function showGovernanceEmpty(messageHtml) {
  const empty = document.getElementById('governance-empty');
  document.getElementById('governance-content').style.display = 'none';
  empty.innerHTML = messageHtml;
  empty.style.display = 'block';
}

function showGovernanceContent() {
  document.getElementById('governance-empty').style.display = 'none';
  document.getElementById('governance-content').style.display = 'block';
}

function renderHealthRows(summary, judgePool, fairness) {
  const rows = [];
  const fairnessCount = Number(summary?.fairness_audits_count || fairness?.audits?.length || 0);
  const openIncidents = Number(summary?.open_incidents_count || 0);
  const pendingAppeals = Number(summary?.pending_appeals_count || 0);
  const judgesTotal = Number(judgePool?.total_judges || 0);
  const judgesActive = Number(judgePool?.active_judges || 0);

  rows.push({
    metric: 'Judge pool utilization',
    value: `${judgesActive}/${judgesTotal || '-'}`,
    note: 'Number of active judges available for scoring workloads.',
  });
  rows.push({
    metric: 'Fairness audits recorded',
    value: String(fairnessCount),
    note: 'Recent fairness runs available through /api/governance/fairness-audits.',
  });
  rows.push({
    metric: 'Appeals pending',
    value: String(pendingAppeals),
    note: 'Appeals currently waiting for review.',
  });
  rows.push({
    metric: 'Open incidents',
    value: String(openIncidents),
    note: 'Incidents in non-resolved status.',
  });

  document.getElementById('gov-health-tbody').innerHTML = rows.map((row) => `
    <tr>
      <td data-label="Metric">${BDA.escapeHtml(row.metric)}</td>
      <td class="mono" data-label="Value">${BDA.escapeHtml(row.value)}</td>
      <td data-label="Notes">${BDA.escapeHtml(row.note)}</td>
    </tr>
  `).join('');

  document.getElementById('gov-appeals-pending').textContent = String(pendingAppeals);
  document.getElementById('gov-incidents-open').textContent = String(openIncidents);

  // Judge pool details
  const details = [];
  if (judgePool?.composition) {
    details.push(`<p class="my-4-text-82"><strong>Composition:</strong> ${BDA.escapeHtml(JSON.stringify(judgePool.composition))}</p>`);
  }
  if (judgePool?.qualification_rubric_summary) {
    details.push(`<p class="my-4-text-82"><strong>Qualification rubric:</strong> ${BDA.escapeHtml(judgePool.qualification_rubric_summary)}</p>`);
  }
  if (judgePool?.randomized_assignment_recipe) {
    details.push(`<p class="my-4-text-82"><strong>Assignment recipe:</strong> ${BDA.escapeHtml(judgePool.randomized_assignment_recipe)} (seed: ${BDA.escapeHtml(judgePool.assignment_seed || '-')})</p>`);
  }
  if (judgePool?.rotation_policy) {
    const rp = judgePool.rotation_policy;
    details.push(`<p class="my-4-text-82"><strong>Rotation:</strong> max consecutive=${rp.max_consecutive_snapshots || '-'}, cooldown=${rp.cooldown_snapshots || '-'}</p>`);
  }
  if (judgePool?.aggregate_coi_stats) {
    details.push(`<p class="my-4-text-82"><strong>COI stats:</strong> ${BDA.escapeHtml(JSON.stringify(judgePool.aggregate_coi_stats))}</p>`);
  }
  if (judgePool?.calibration_protocol_status) {
    details.push(`<p class="my-4-text-82"><strong>Calibration:</strong> ${BDA.escapeHtml(judgePool.calibration_protocol_status)}</p>`);
  }
  document.getElementById('judge-pool-details').innerHTML = details.length
    ? details.join('')
    : '<small class="text-muted">No detailed judge pool data available.</small>';

  // Fairness audit dates
  const audits = fairness?.audits || [];
  const lastAudit = audits.length ? audits[0] : null;
  document.getElementById('fairness-last').textContent = lastAudit ? BDA.formatDateTime(lastAudit.audit_date || lastAudit.created_at) : '-';
  document.getElementById('fairness-next').textContent = lastAudit?.next_audit_date || '-';
}

function renderIncidents(incidents) {
  const rows = Array.isArray(incidents) ? incidents : [];
  const tbody = document.getElementById('gov-incidents-tbody');
  if (!rows.length) {
    tbody.innerHTML = '<tr><td colspan="4" class="text-center-muted">No incidents recorded.</td></tr>';
    return;
  }

  tbody.innerHTML = rows.map((incident) => `
    <tr>
      <td data-label="Title">${BDA.escapeHtml(incident.title || incident.incident_id || 'Incident')}</td>
      <td data-label="Status">${BDA.escapeHtml(incident.status || 'unknown')}</td>
      <td data-label="Severity">${BDA.escapeHtml(incident.severity || 'unknown')}</td>
      <td class="mono" data-label="Updated">${BDA.escapeHtml(BDA.formatDateTime(incident.updated_at || incident.created_at))}</td>
    </tr>
  `).join('');
}

function renderChangelog(entries) {
  const rows = Array.isArray(entries) ? entries : [];
  const tbody = document.getElementById('gov-changelog-tbody');
  if (!rows.length) {
    tbody.innerHTML = '<tr><td colspan="3" class="text-center-muted">No changelog entries available.</td></tr>';
    return;
  }

  tbody.innerHTML = rows.map((entry) => `
    <tr>
      <td data-label="Type">${BDA.escapeHtml(entry.change_type || 'change')}</td>
      <td data-label="Description">${BDA.escapeHtml(entry.description || entry.summary || '-')}</td>
      <td class="mono" data-label="Timestamp">${BDA.escapeHtml(BDA.formatDateTime(entry.timestamp || entry.created_at))}</td>
    </tr>
  `).join('');
}

function renderFramePetitions(petitions) {
  const rows = Array.isArray(petitions) ? petitions : [];
  const tbody = document.getElementById('gov-frame-petitions-tbody');
  if (!rows.length) {
    tbody.innerHTML = '<tr><td colspan="4" class="text-center-muted">No frame petitions submitted.</td></tr>';
    return;
  }
  tbody.innerHTML = rows.map((petition) => `
    <tr>
      <td class="mono" data-label="Petition ID">${BDA.escapeHtml(petition.petition_id || '-')}</td>
      <td data-label="Status">${BDA.escapeHtml(petition.status || 'pending')}</td>
      <td class="mono" data-label="Created">${BDA.escapeHtml(BDA.formatDateTime(petition.created_at))}</td>
      <td data-label="Decision">${BDA.escapeHtml(petition.governance_decision?.reason || '-')}</td>
    </tr>
  `).join('');
}

async function loadGovernance() {
  const debate = await BDA.loadDebate();
  const snapshot = await BDA.loadSnapshot();
  if (snapshot?.has_snapshot) {
    BDA.updateStateStrip(snapshot);
  }

  try {
    const [
      frames,
      summary,
      judgePool,
      fairness,
      incidents,
      changelog,
      petitions,
    ] = await Promise.all([
      BDA.api('/api/governance/frames'),
      BDA.api('/api/governance/summary'),
      BDA.api('/api/governance/judge-pool'),
      BDA.api('/api/governance/fairness-audits?limit=20'),
      BDA.api('/api/governance/incidents?limit=20'),
      BDA.api('/api/governance/changelog?limit=20'),
      debate?.debate_id ? BDA.api(`/api/debate/${encodeURIComponent(debate.debate_id)}/frame-petitions`) : Promise.resolve({ petitions: [] }),
    ]);

    showGovernanceContent();
    document.getElementById('gov-frame-id').textContent = frames?.active_frame?.frame_id || '-';
    document.getElementById('gov-frame-version').textContent = String(frames?.active_frame?.version ?? '-');
    document.getElementById('gov-frame-mode').textContent = frames?.mode || 'single';
    const schedule = frames?.review_schedule?.[0] || {};
    document.getElementById('gov-frame-review').textContent = schedule.review_date || frames?.active_frame?.next_review_date || '-';
    document.getElementById('gov-frame-cadence').textContent = `${schedule.review_cadence_months || frames?.active_frame?.review_cadence_months || 6} months`;
    document.getElementById('gov-frame-statement').textContent = frames?.active_frame?.statement || 'No active frame statement available.';
    document.getElementById('gov-frame-scope').textContent = frames?.active_frame?.scope || 'Frame scope unavailable.';

    renderHealthRows(summary || {}, judgePool || {}, fairness || {});
    renderFramePetitions(petitions?.petitions || []);
    renderIncidents(incidents?.incidents || []);
    renderChangelog(changelog?.entries || []);
  } catch (error) {
    showGovernanceEmpty(error.message || 'Failed to load governance data.');
  }
}

document.getElementById('governance-refresh-btn').addEventListener('click', () => {
  loadGovernance();
});

document.addEventListener('DOMContentLoaded', () => {
  loadGovernance();
});
