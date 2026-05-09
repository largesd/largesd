async function init() {
  const session = await Auth.verifySession();
  if (!session.ok) {
    if (session.reason === 'network-error') {
      BDA.showStatus('Proposal service is unavailable. Please try again later.', true);
      return;
    }
    Auth.redirectToLogin(
      session.reason === 'expired' ? 'session-expired' : 'auth-required'
    );
    return;
  }
  await loadMyProposals();
}

BDA.registerAction('submit-proposal', submitProposal);

async function submitProposal() {
  const motion = document.getElementById('proposal-motion').value.trim();
  const moderationCriteria = document.getElementById('proposal-moderation-criteria').value.trim();
  const debateFrame = document.getElementById('proposal-debate-frame').value.trim();
  const sidesRaw = document.getElementById('proposal-frame-sides').value.trim();
  const evaluationCriteriaRaw = document.getElementById('proposal-evaluation-criteria').value.trim();

  if (!motion || !moderationCriteria || !debateFrame) {
    BDA.showStatus('Please fill in all required fields (Motion, Moderation Criteria, Debate Frame).', true);
    return;
  }

  const payload = {
    motion,
    moderation_criteria: moderationCriteria,
    debate_frame: debateFrame,
  };

  if (sidesRaw) {
    payload.frame_sides = sidesRaw.split('\n').map(s => s.trim()).filter(Boolean);
  }
  if (evaluationCriteriaRaw) {
    payload.frame_evaluation_criteria = evaluationCriteriaRaw.split('\n').map(s => s.trim()).filter(Boolean);
  }

  try {
    const response = await BDA.api('/api/debate-proposals', {
      method: 'POST',
      body: JSON.stringify(payload),
    });
    BDA.showStatus(`Proposal submitted: ${response.proposal_id}. Status: ${response.status}`);
    document.getElementById('proposal-motion').value = '';
    document.getElementById('proposal-moderation-criteria').value = '';
    document.getElementById('proposal-debate-frame').value = '';
    document.getElementById('proposal-frame-sides').value = '';
    document.getElementById('proposal-evaluation-criteria').value = '';
    await loadMyProposals();
  } catch (error) {
    BDA.showStatus(error.message || 'Failed to submit proposal.', true);
  }
}

async function loadMyProposals() {
  const container = document.getElementById('my-proposals-list');
  try {
    const data = await BDA.api('/api/debate-proposals/mine');
    const proposals = data.proposals || [];
    if (proposals.length === 0) {
      container.innerHTML = `
        <div class="callout soft">
          <p>You have not submitted any proposals yet.</p>
        </div>
      `;
      return;
    }
    container.innerHTML = proposals.map(p => `
      <article class="proposal-item">
        <div class="row proposal-head">
          <strong>${BDA.escapeHtml(p.motion)}</strong>
          <span class="pill ${p.status === 'accepted' ? 'good' : p.status === 'rejected' ? 'bad' : 'warn'}">${p.status}</span>
        </div>
        <div class="proposal-meta">
          <small>Created: ${BDA.formatDateTime(p.created_at)}</small>
          ${p.reviewed_at ? `<small>Reviewed: ${BDA.formatDateTime(p.reviewed_at)}</small>` : ''}
          ${p.decision_reason ? `<small>Reason: ${BDA.escapeHtml(p.decision_reason)}</small>` : ''}
          ${p.accepted_debate_id ? `<small>Debate: <a href="new_debate.html?debate_id=${encodeURIComponent(p.accepted_debate_id)}">${p.accepted_debate_id}</a></small>` : ''}
        </div>
      </article>
    `).join('');
  } catch (error) {
    container.innerHTML = `
      <div class="callout soft">
        <p>Could not load your proposals. ${BDA.escapeHtml(error.message || '')}</p>
      </div>
    `;
  }
}

document.addEventListener('DOMContentLoaded', init);
