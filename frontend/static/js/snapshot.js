function toggleHelp() {
  BDA.toggleHelp();
}

function showSnapshotEmpty(messageHtml) {
  const empty = document.getElementById('snapshot-empty');
  document.getElementById('snapshot-content').style.display = 'none';
  empty.innerHTML = messageHtml;
  empty.style.display = 'block';
}

function showSnapshotContent() {
  document.getElementById('snapshot-empty').style.display = 'none';
  document.getElementById('snapshot-content').style.display = 'block';
}

function renderDebateChoices(debates) {
  if (!debates.length) {
    return '<strong>No debate selected.</strong> Create a debate from <a href="new_debate.html">New Debate / Post Point</a> to generate a live snapshot.';
  }

  const buttons = debates.map((debate) => `
    <button class="pill" data-debate-id="${BDA.escapeHtml(debate.debate_id)}">${BDA.escapeHtml(debate.resolution)}</button>
  `).join('');

  return `
    <strong>No active debate selected.</strong> Choose a public debate to inspect its live snapshot.
    <div class="choice-list">${buttons}</div>
  `;
}

function renderSnapshot(snapshot) {
  document.getElementById('snapshot-id').textContent = snapshot.snapshot_id || '-';
  document.getElementById('snapshot-timestamp').textContent = BDA.formatDateTime(snapshot.timestamp);
  document.getElementById('snapshot-trigger').textContent = snapshot.trigger_type || '-';
  document.getElementById('snapshot-status').textContent = snapshot.status || 'valid';
  document.getElementById('snapshot-status-pill').style.display = snapshot.status === 'incident' ? 'inline-flex' : 'inline-flex';
  document.getElementById('template-name').textContent = snapshot.template_name || '-';
  document.getElementById('template-version').textContent = snapshot.template_version || '-';
  document.getElementById('borderline-rate').textContent = BDA.formatNumber(snapshot.borderline_rate || 0, 4);
  const suppression = snapshot.suppression_policy || {};
  document.getElementById('suppression-k').textContent = `k=${suppression.k || 5}`;
  document.getElementById('suppressed-bucket-count').textContent = suppression.affected_bucket_count ?? (suppression.affected_buckets || []).length ?? 0;
  document.getElementById('allowed-count').textContent = snapshot.allowed_count ?? '-';
  document.getElementById('blocked-count').textContent = snapshot.blocked_count ?? '-';

  // Incident report
  const incident = snapshot.incident_report || null;
  if (snapshot.status === 'incident' && incident) {
    document.getElementById('incident-empty').style.display = 'none';
    document.getElementById('incident-content').style.display = 'block';
    document.getElementById('incident-title').textContent = incident.title || 'Incident';
    document.getElementById('incident-ts').textContent = BDA.formatDateTime(incident.timestamp || incident.created_at);
    document.getElementById('incident-desc').textContent = incident.description || 'No description available.';
    document.getElementById('incident-unreliable').textContent = incident.unreliable_outputs || 'Not specified.';
    document.getElementById('incident-remediation').textContent = incident.remediation_planned || 'No remediation plan documented.';
  } else {
    document.getElementById('incident-empty').style.display = 'block';
    document.getElementById('incident-content').style.display = 'none';
  }

  // AU completeness
  const au = snapshot.au_completeness || {};
  document.getElementById('au-completeness-mean').textContent = BDA.formatNumber(au.mean, 3);
  const dist = au.distribution || {};
  document.getElementById('au-completeness-dist').textContent = `${BDA.formatNumber(dist.p25, 3)} / ${BDA.formatNumber(dist.p50, 3)} / ${BDA.formatNumber(dist.p75, 3)}`;

  const reasonsRow = document.getElementById('block-reasons-row');
  const reasons = Object.entries(snapshot.block_reasons || {}).sort((a, b) => b[1] - a[1]);
  if (!reasons.length) {
    reasonsRow.innerHTML = '<small class="text-muted">No blocked-post data in this snapshot.</small>';
  } else {
    reasonsRow.innerHTML = reasons.map(([reason, count]) =>
      `<span class="pill">${BDA.escapeHtml(reason)}: <span class="mono">${count}</span></span>`
    ).join('');
  }

  // Integrity fields
  const inputHash = snapshot.input_hash_root || '-';
  const outputHash = snapshot.output_hash_root || '-';
  document.getElementById('integrity-input-hash').textContent = inputHash.length > 16 ? inputHash.slice(0, 16) + '…' : inputHash;
  document.getElementById('integrity-input-hash').title = inputHash;
  document.getElementById('integrity-output-hash').textContent = outputHash.length > 16 ? outputHash.slice(0, 16) + '…' : outputHash;
  document.getElementById('integrity-output-hash').title = outputHash;

  const recipeVersions = snapshot.recipe_versions || {};
  const recipeContainer = document.getElementById('integrity-recipe-versions');
  recipeContainer.innerHTML = Object.entries(recipeVersions).map(([k, v]) =>
    `<span class="pill text-72">${BDA.escapeHtml(k)}: ${BDA.escapeHtml(String(v))}</span>`
  ).join('');

  const replayManifest = snapshot.replay_manifest || {};
  document.getElementById('integrity-replay-manifest').textContent = JSON.stringify(replayManifest, null, 2);

  // Governance context
  document.getElementById('governance-frame-mode').textContent = snapshot.frame_mode || '-';
  document.getElementById('governance-cadence').textContent = snapshot.review_cadence_months ? `${snapshot.review_cadence_months} month(s)` : '-';
  const policy = snapshot.policy_context || {};
  document.getElementById('governance-template').textContent = policy.moderation_template_name ? `${policy.moderation_template_name} (${policy.moderation_template_version || '?'})` : '-';

  // Participation concentration
  const part = snapshot.participation_concentration || {};
  document.getElementById('snap-part-entropy').textContent = part.entropy_bucket || BDA.formatNumber(part.participation_entropy, 3) || '-';
  document.getElementById('snap-top1-share').textContent = part.top_1pct_share_bucket || BDA.formatNumber(part.top_1pct_share, 3) || '-';
  const mix = part.channel_mix || {};
  document.getElementById('snap-channel-mix').textContent = Object.entries(mix).map(([k, v]) => `${k}=${BDA.formatNumber(v, 2)}`).join(', ') || '-';
}

function renderFrameInfo(payload) {
  const frame = payload?.active_frame || {};
  document.getElementById('frame-id').textContent = frame.frame_id || '-';
  document.getElementById('frame-version').textContent = String(frame.version ?? '-');
  document.getElementById('frame-statement').textContent = frame.statement || 'No active frame statement available.';
}

function renderHistory(history) {
  const tbody = document.getElementById('history-tbody');
  if (!history.length) {
    tbody.innerHTML = '<tr><td colspan="6" class="text-center-muted">No snapshot history yet.</td></tr>';
    return;
  }

  const rows = history.slice().reverse().map((item) => `
    <tr>
      <td class="mono" data-label="Snapshot">${BDA.escapeHtml(item.snapshot_id || '-')}</td>
      <td class="mono" data-label="Timestamp">${BDA.escapeHtml(BDA.formatDateTime(item.timestamp))}</td>
      <td data-label="Trigger">${BDA.escapeHtml(item.trigger_type || '-')}</td>
      <td data-label="Verdict">${BDA.escapeHtml(item.verdict || 'NO VERDICT')}</td>
      <td class="mono" data-label="Confidence">${BDA.formatNumber(item.confidence, 2)}</td>
      <td class="mono" data-label="D">${BDA.formatNumber(item.margin_d, 4)}</td>
    </tr>
  `);

  tbody.innerHTML = rows.join('');
}

function renderDiff(diff) {
  if (!diff || diff.error) {
    document.getElementById('diff-content').style.display = 'none';
    document.getElementById('diff-empty').textContent = 'A diff becomes available after at least two snapshots have been generated.';
    document.getElementById('diff-empty').style.display = 'block';
    return;
  }

  document.getElementById('diff-empty').style.display = 'none';
  document.getElementById('diff-content').style.display = 'block';
  document.getElementById('diff-old-id').textContent = diff.snapshot_id_old || '-';
  document.getElementById('diff-new-id').textContent = diff.snapshot_id_new || '-';
  document.getElementById('diff-confidence-delta').textContent = BDA.formatNumber(diff.confidence_change?.delta, 3);
  document.getElementById('diff-margin-delta').textContent = BDA.formatNumber(diff.margin_d_change?.delta, 4);

  const summaryList = [
    `${diff.summary?.posts_added || 0} new post(s) included`,
    `${diff.summary?.topics_changed || 0} topic change(s) detected`,
    `${diff.summary?.facts_added || 0} fact(s) added, ${diff.summary?.facts_modified || 0} modified, ${diff.summary?.facts_removed || 0} removed`,
    `${diff.summary?.arguments_added || 0} argument(s) added, ${diff.summary?.arguments_removed || 0} removed`,
    diff.verdict_change?.changed
      ? `Verdict changed from ${diff.verdict_change.old} to ${diff.verdict_change.new}`
      : `Verdict stayed ${diff.verdict_change?.new || 'NO VERDICT'}`
  ];
  document.getElementById('diff-summary-list').innerHTML = summaryList.map((item) => `<li>${BDA.escapeHtml(item)}</li>`).join('');

  const surfaces = [];
  if (diff.posts?.length) {
    surfaces.push(`posts:\n${diff.posts.slice(0, 5).map((post) => `- ${post.change_type} ${post.post_id} (${post.side}${post.topic_id ? `, ${post.topic_id}` : ''})`).join('\n')}`);
  }
  if (diff.topics?.length) {
    surfaces.push(`topics:\n${diff.topics.slice(0, 5).map((topic) => `- ${topic.change_type} ${topic.topic_id} ${topic.topic_name}`).join('\n')}`);
  }
  if (diff.facts?.length) {
    surfaces.push(`facts:\n${diff.facts.slice(0, 5).map((fact) => `- ${fact.change_type} ${fact.fact_id} (${fact.side})`).join('\n')}`);
  }
  if (diff.arguments?.length) {
    surfaces.push(`arguments:\n${diff.arguments.slice(0, 5).map((arg) => `- ${arg.change_type} ${arg.arg_id} (${arg.side})`).join('\n')}`);
  }
  if (diff.scores?.length) {
    surfaces.push(`scores:\n${diff.scores.slice(0, 6).map((score) => `- ${score.topic_id || 'overall'} ${score.side || ''} ${score.metric}: ${score.old_value} -> ${score.new_value}`).join('\n')}`);
  }

  document.getElementById('diff-surfaces').textContent = surfaces.length
    ? surfaces.join('\n\n')
    : 'No diff surface changes were recorded between the latest two snapshots.';
}

async function initSnapshotPage() {
  const debate = await BDA.loadDebate();
  if (!debate.has_debate) {
    const debates = await BDA.loadDebates();
    showSnapshotEmpty(renderDebateChoices(debates));

    document.querySelectorAll('#snapshot-empty [data-debate-id]').forEach((button) => {
      button.addEventListener('click', () => {
        const debateId = button.getAttribute('data-debate-id');
        BDA.setActiveDebateId(debateId);
        window.location.reload();
      });
    });
    return;
  }

  const snapshot = await BDA.loadSnapshot();
  if (!snapshot || !snapshot.has_snapshot) {
    showSnapshotEmpty('This debate does not have a snapshot yet. Add posts in <a href="new_debate.html">New Debate / Post Point</a>, then generate a snapshot.');
    return;
  }

  BDA.updateStateStrip(snapshot);
  renderSnapshot(snapshot);
  showSnapshotContent();

  try {
    const historyData = await BDA.api('/api/debate/snapshot-history');
    renderHistory(historyData.snapshots || []);
  } catch (error) {
    const container = document.getElementById('snapshot-history');
    const errorMsg = error?.message || 'Unable to load snapshot history.';
    const requestId = error?.payload?.request_id || '';
    if (typeof BDA !== 'undefined' && typeof BDA.showInlineError === 'function' && container) {
      BDA.showInlineError(container, errorMsg, () => {
        if (requestId) console.error(`[request_id: ${requestId}] Retry loading snapshot history`);
        initSnapshotPage();
      });
    } else {
      renderHistory([]);
    }
  }

  try {
    const diffData = await BDA.api('/api/debate/snapshot-diff');
    renderDiff(diffData);
  } catch (error) {
    const errorMsg = error?.message || 'Unable to load snapshot diff.';
    const requestId = error?.payload?.request_id || '';
    const diffSurfaces = document.getElementById('diff-surfaces');
    if (typeof BDA !== 'undefined' && typeof BDA.showInlineError === 'function' && diffSurfaces) {
      BDA.showInlineError(diffSurfaces, errorMsg, () => {
        if (requestId) console.error(`[request_id: ${requestId}] Retry loading snapshot diff`);
        initSnapshotPage();
      });
    } else {
      renderDiff({ error: errorMsg });
    }
  }

  try {
    const frameData = await BDA.api('/api/governance/frames');
    renderFrameInfo(frameData);
    // Frame set version
    if (frameData.frame_set_version) {
      document.getElementById('governance-frame-set-version').textContent = frameData.frame_set_version;
    }
    const schedule = (frameData.review_schedule || [])[0] || {};
    if (schedule.review_date || frameData.active_frame?.next_review_date) {
      document.getElementById('governance-next-review').textContent = schedule.review_date || frameData.active_frame.next_review_date;
    }
  } catch (error) {
    const errorMsg = error?.message || 'Unable to load frame data.';
    const requestId = error?.payload?.request_id || '';
    const frameInfoEl = document.getElementById('frame-info');
    if (typeof BDA !== 'undefined' && typeof BDA.showInlineError === 'function' && frameInfoEl) {
      BDA.showInlineError(frameInfoEl, errorMsg, () => {
        if (requestId) console.error(`[request_id: ${requestId}] Retry loading frame data`);
        initSnapshotPage();
      });
    } else {
      renderFrameInfo({});
    }
  }

  BDA.setupTableScroll();
  BDA.setupTooltips();
}

document.addEventListener('DOMContentLoaded', initSnapshotPage);
