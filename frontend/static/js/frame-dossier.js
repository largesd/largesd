function renderFrameDossier(frames) {
  const active = frames?.active_frame || {};
  const dossier = active.dossier?.dossier || active.dossier || {};
  document.getElementById('fd-frame-id').textContent = active.frame_id || '-';
  document.getElementById('fd-version').textContent = String(active.version ?? '-');
  document.getElementById('fd-mode').textContent = frames?.mode || active.frame_mode || 'single';
  document.getElementById('fd-cadence').textContent = `${active.review_cadence_months || 6} months`;

  const sections = [
    ['Scope', dossier.scope || active.scope],
    ['Grounding rationale', dossier.grounding_rationale],
    ['Inclusion justification', dossier.inclusion_justification],
    ['Exclusion note', dossier.exclusion_note],
    ['Known tensions', (dossier.known_tensions || []).join('\n')],
    ['Prioritized values', (dossier.prioritized_values || []).join('\n')],
    ['Emergency override path', dossier.emergency_override_path || active.emergency_override_path],
  ];
  document.getElementById('fd-sections').innerHTML = sections.map(([title, value]) => `
    <section class="callout soft mb-16">
      <h3 class="mt-0">${BDA.escapeHtml(title)}</h3>
      <p class="pre-wrap-mb-0">${BDA.escapeHtml(value || 'Not published for this frame.')}</p>
    </section>
  `).join('');
}

async function loadFrameDossier() {
  try {
    const frames = await BDA.api('/api/governance/frames');
    document.getElementById('frame-dossier-content').style.display = 'block';
    renderFrameDossier(frames);
  } catch (error) {
    const empty = document.getElementById('frame-dossier-empty');
    empty.textContent = error.message || 'Unable to load frame dossier.';
    empty.style.display = 'block';
  }
}

document.addEventListener('DOMContentLoaded', loadFrameDossier);
