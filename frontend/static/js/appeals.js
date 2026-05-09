    (function gateAppealsRouteBeforePaint() {
      const root = document.documentElement;
      const routePath = window.location.protocol === 'file:'
        ? '/appeals.html'
        : (window.location.pathname || '/appeals.html');
      const next = `${routePath}${window.location.search || ''}${window.location.hash || ''}`;
      window.__BDA_APPEALS_NEXT__ = next;
      root.classList.add('route-auth-pending');
      root.setAttribute('aria-busy', 'true');
      try {
        const token = localStorage.getItem('access_token');
        if (!token) {
          const params = new URLSearchParams();
          params.set('reason', 'appeals-login-required');
          params.set('next', next);
          window.location.replace(`login.html?${params.toString()}`);
        }
      } catch (error) {
        window.location.replace('login.html?reason=appeals-login-required');
      }
    })();

// Populate CSRF token from cookie into hidden form field
(function() {
  const match = document.cookie.match(/csrf_token=([^;]+)/);
  if (match) {
    const input = document.getElementById('csrf_token');
    if (input) input.value = decodeURIComponent(match[1]);
  }
})();

const APPEALS_LOADING_ROW = '<tr><td colspan="4"><span class="skeleton skeleton-table-row"></span></td></tr>';
const APPEALS_EMPTY_ROW = `
  <tr class="appeals-empty-row">
    <td colspan="4">
      <div class="appeals-empty-state">
        <strong>No appeals in queue</strong>
        <span>The queue will populate here after the first filing for this debate context.</span>
      </div>
    </td>
  </tr>
`;
const APPEAL_FIELD_IDS = ['appeal-grounds', 'appeal-evidence', 'appeal-relief'];
const APPEALS_ENDPOINT = '/api/governance/appeals?limit=100';

let hasHydratedAppeals = false;
let latestAppealsLoadRequest = 0;

function setAppealsMessage(message, kind = 'info') {
  const node = document.getElementById('appeals-message');
  if (!message) {
    node.hidden = true;
    node.textContent = '';
    node.className = 'notice';
    node.setAttribute('role', 'status');
    node.setAttribute('aria-live', 'polite');
    return;
  }

  node.hidden = false;
  node.className = 'notice';
  node.textContent = message;
  node.setAttribute('role', kind === 'error' ? 'alert' : 'status');
  node.setAttribute('aria-live', kind === 'error' ? 'assertive' : 'polite');
  if (kind === 'success') node.classList.add('alert-success');
  if (kind === 'error') node.classList.add('alert-error');
}

function releaseRouteAuthGate() {
  const root = document.documentElement;
  root.classList.remove('route-auth-pending');
  root.removeAttribute('aria-busy');
}

function formatAppealStatusLabel(status) {
  const normalized = String(status || 'pending').trim().toLowerCase();
  return normalized ? normalized.charAt(0).toUpperCase() + normalized.slice(1) : 'Pending';
}

function getAppealStatusTone(status) {
  const normalized = String(status || 'pending').trim().toLowerCase();
  if (normalized === 'accepted') return 'good';
  if (normalized === 'rejected') return 'bad';
  return 'warn';
}

function renderAppealStatusPill(status) {
  const label = formatAppealStatusLabel(status);
  const tone = getAppealStatusTone(status);
  return `<span class="pill ${tone}">${BDA.escapeHtml(label)}</span>`;
}

function getAppealSubmittedAt(appeal) {
  return appeal?.submitted_at || appeal?.created_at || '';
}

function formatAppealsRefreshTime(value) {
  const date = value instanceof Date ? value : new Date(value);
  if (Number.isNaN(date.getTime())) return 'Just now';
  return date.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' });
}

function updateAppealsMeta({ queueCount, pendingCount, updatedLabel } = {}) {
  const queueNode = document.getElementById('appeals-queue-count');
  const pendingNode = document.getElementById('appeals-pending-count');
  const updatedNode = document.getElementById('appeals-last-updated');
  if (queueNode && queueCount !== undefined) queueNode.textContent = String(queueCount);
  if (pendingNode && pendingCount !== undefined) pendingNode.textContent = String(pendingCount);
  if (updatedNode && updatedLabel !== undefined) updatedNode.textContent = updatedLabel;
}

function setAppealsTableState(state) {
  const tableWrap = document.getElementById('appeals-table-wrap');
  const workspace = document.querySelector('.appeals-workspace');
  if (!tableWrap) return;
  tableWrap.classList.toggle('is-empty', state === 'empty');
  if (workspace) workspace.dataset.queueState = state;
}

function setAppealSubmitDisabled(disabled) {
  const button = document.getElementById('appeal-submit-btn');
  if (!button) return;
  if (typeof BDA !== 'undefined' && typeof BDA.setButtonBusy === 'function') {
    BDA.setButtonBusy(button, disabled, 'Submitting Appeal...');
  } else {
    button.disabled = disabled;
    button.setAttribute('aria-busy', String(disabled));
    button.textContent = disabled ? 'Submitting Appeal...' : 'Submit Appeal';
  }
}

function normalizeEvidenceList(raw) {
  return String(raw || '')
    .split('\n')
    .map((line) => line.trim())
    .filter(Boolean);
}

function getAppealField(fieldId) {
  return document.getElementById(fieldId);
}

function getAppealFieldErrorNode(fieldId) {
  return document.getElementById(`${fieldId}-error`);
}

function clearAppealFieldError(fieldId) {
  const field = getAppealField(fieldId);
  const errorNode = getAppealFieldErrorNode(fieldId);
  if (field) field.removeAttribute('aria-invalid');
  if (errorNode) {
    errorNode.textContent = '';
    errorNode.hidden = true;
  }
}

function setAppealFieldError(fieldId, message) {
  const field = getAppealField(fieldId);
  const errorNode = getAppealFieldErrorNode(fieldId);
  if (field) field.setAttribute('aria-invalid', 'true');
  if (errorNode) {
    errorNode.textContent = message;
    errorNode.hidden = false;
  }
}

function resetAppealValidation() {
  APPEAL_FIELD_IDS.forEach((fieldId) => clearAppealFieldError(fieldId));
}

function validateAppealForm() {
  const groundsField = getAppealField('appeal-grounds');
  const evidenceField = getAppealField('appeal-evidence');
  const reliefField = getAppealField('appeal-relief');

  resetAppealValidation();

  const values = {
    grounds: groundsField.value.trim(),
    requestedRelief: reliefField.value.trim(),
    evidenceReferences: normalizeEvidenceList(evidenceField.value),
  };

  let firstInvalidField = null;

  if (values.grounds.length < 10) {
    setAppealFieldError('appeal-grounds', 'Grounds must be at least 10 characters.');
    firstInvalidField = firstInvalidField || groundsField;
  }

  if (values.requestedRelief.length < 5) {
    setAppealFieldError('appeal-relief', 'Requested relief must be at least 5 characters.');
    firstInvalidField = firstInvalidField || reliefField;
  }

  if (firstInvalidField) {
    setAppealsMessage('Please correct the highlighted fields and try again.', 'error');
    firstInvalidField.focus();
    return null;
  }

  return values;
}

function renderAppealsLoadingRow() {
  const tbody = document.getElementById('appeals-tbody');
  setAppealsTableState('loading');
  tbody.innerHTML = APPEALS_LOADING_ROW;
}

function renderAppealsMobilePlaceholder(message, kind = 'empty') {
  const list = document.getElementById('appeals-mobile-list');
  if (!list) return;
  const itemClass = kind === 'error' ? 'appeals-mobile-error' : 'appeals-mobile-empty';
  list.innerHTML = `<p class="${itemClass}">${BDA.escapeHtml(message)}</p>`;
}

function renderAppealsErrorRow(message, retryCallback = null) {
  const tbody = document.getElementById('appeals-tbody');
  setAppealsTableState('error');
  const retryHtml = retryCallback
    ? `<button type="button" class="retry-btn" data-retry="true">Retry</button>`
    : '';
  tbody.innerHTML = `<tr><td colspan="4" class="text-center-bad">${BDA.escapeHtml(message)} ${retryHtml}</td></tr>`;
  if (retryCallback) {
    const retryBtn = tbody.querySelector('[data-retry="true"]');
    if (retryBtn) retryBtn.addEventListener('click', retryCallback);
  }
}

function setAppealsLoading(isLoading, options = {}) {
  const { preserveRows = false } = options;
  const tableWrap = document.getElementById('appeals-table-wrap');
  const refreshButton = document.getElementById('appeals-refresh-btn');

  if (tableWrap) tableWrap.setAttribute('aria-busy', String(isLoading));
  if (refreshButton) {
    refreshButton.disabled = isLoading;
    refreshButton.setAttribute('aria-busy', String(isLoading));
  }
  if (isLoading && !preserveRows) {
    renderAppealsLoadingRow();
    renderAppealsMobilePlaceholder('<span class="spinner" aria-label="Loading" role="status"></span> Loading appeals...');
  }
  if (isLoading) {
    const label = preserveRows ? 'Refreshing...' : 'Loading...';
    updateAppealsMeta({ updatedLabel: `<span class="spinner" aria-label="Loading" role="status"></span> ${label}` });
  }
}

function renderAppealsMobileList(rows) {
  const list = document.getElementById('appeals-mobile-list');
  if (!list) return;
  const appeals = Array.isArray(rows) ? rows : [];
  if (!appeals.length) {
    renderAppealsMobilePlaceholder('No appeals have been filed for this debate yet.');
    return;
  }

  list.innerHTML = appeals.map((appeal) => {
    const appealId = BDA.escapeHtml(appeal.appeal_id || '-');
    const statusPill = renderAppealStatusPill(appeal.status);
    const claimant = BDA.escapeHtml(appeal.claimant_id || 'unknown');
    const snapshotId = BDA.escapeHtml(appeal.snapshot_id || '-');
    const submitted = BDA.escapeHtml(BDA.formatDateTime(getAppealSubmittedAt(appeal)) || '-');
    return `
      <article class="appeals-mobile-item">
        <div class="appeals-mobile-item-head">
          <div class="appeals-mobile-item-heading">
            <p class="appeals-mobile-item-title">Appeal</p>
            <span class="appeals-mobile-item-id mono">${appealId}</span>
          </div>
          ${statusPill}
        </div>
        <dl class="appeals-mobile-meta">
          <div class="appeals-mobile-meta-row">
            <dt>Snapshot</dt>
            <dd class="mono">${snapshotId}</dd>
          </div>
          <div class="appeals-mobile-meta-row">
            <dt>Claimant</dt>
            <dd>${claimant}</dd>
          </div>
          <div class="appeals-mobile-meta-row">
            <dt>Filed</dt>
            <dd class="mono">${submitted}</dd>
          </div>
        </dl>
      </article>
    `;
  }).join('');
}

function renderAppeals(rows) {
  const tbody = document.getElementById('appeals-tbody');
  const appeals = Array.isArray(rows) ? rows : [];
  const pendingCount = appeals.filter((appeal) => String(appeal?.status || 'pending').trim().toLowerCase() === 'pending').length;
  hasHydratedAppeals = true;
  updateAppealsMeta({ queueCount: appeals.length, pendingCount });
  if (!appeals.length) {
    setAppealsTableState('empty');
    tbody.innerHTML = APPEALS_EMPTY_ROW;
    renderAppealsMobilePlaceholder('No appeals have been filed for this debate yet.');
    return;
  }

  setAppealsTableState('rows');
  tbody.innerHTML = appeals.map((appeal) => {
    const appealId = BDA.escapeHtml(appeal.appeal_id || '-');
    const snapshotId = BDA.escapeHtml(appeal.snapshot_id || '-');
    const claimant = BDA.escapeHtml(appeal.claimant_id || 'unknown');
    const submitted = BDA.escapeHtml(BDA.formatDateTime(getAppealSubmittedAt(appeal)) || '-');
    return `
      <tr>
        <td data-label="Appeal">
          <div class="appeals-appeal-cell">
            <span class="mono">${appealId}</span>
            <small>Snapshot <span class="mono">${snapshotId}</span></small>
          </div>
        </td>
        <td class="appeals-status-cell" data-label="Status">${renderAppealStatusPill(appeal.status)}</td>
        <td data-label="Claimant">${claimant}</td>
        <td class="mono" data-label="Filed">${submitted}</td>
      </tr>
    `;
  }).join('');
  renderAppealsMobileList(appeals);
}

async function loadAppeals(options = {}) {
  const { preserveRows = hasHydratedAppeals, clearMessageOnSuccess = true } = options;
  const requestId = ++latestAppealsLoadRequest;

  try {
    setAppealsLoading(true, { preserveRows });
    const [snapshot, response] = await Promise.all([
      BDA.loadSnapshot(),
      BDA.api(APPEALS_ENDPOINT),
    ]);

    if (requestId !== latestAppealsLoadRequest) return;
    if (snapshot?.has_snapshot) {
      BDA.updateStateStrip(snapshot);
    }
    if (!response) return;
    renderAppeals(response.appeals || []);
    updateAppealsMeta({ updatedLabel: formatAppealsRefreshTime(new Date()) });
    if (clearMessageOnSuccess) {
      setAppealsMessage('');
    }
  } catch (error) {
    if (requestId !== latestAppealsLoadRequest) return;
    const errorMessage = error.message || 'Failed to load appeals.';
    const requestIdStr = error?.payload?.request_id || '';
    if (!hasHydratedAppeals) {
      setAppealsMessage(errorMessage, 'error');
      renderAppealsErrorRow(errorMessage, () => {
        if (requestIdStr) console.error(`[request_id: ${requestIdStr}] Retry loading appeals`);
        loadAppeals();
      });
      renderAppealsMobilePlaceholder(errorMessage, 'error');
      updateAppealsMeta({ queueCount: '-', pendingCount: '-', updatedLabel: 'Unavailable' });
    } else {
      setAppealsMessage(`Latest refresh failed: ${errorMessage}. Showing the last loaded queue.`, 'error');
    }
  } finally {
    if (requestId === latestAppealsLoadRequest) {
      setAppealsLoading(false, { preserveRows: true });
    }
  }
}

async function submitAppeal() {
  const validated = validateAppealForm();
  if (!validated) return;

  try {
    setAppealSubmitDisabled(true);
    setAppealsMessage('Submitting appeal...', 'info');
    const response = await BDA.api('/api/governance/appeals', {
      method: 'POST',
      body: JSON.stringify({
        grounds: validated.grounds,
        evidence_references: validated.evidenceReferences,
        requested_relief: validated.requestedRelief,
      }),
    });
    if (!response) return;

    setAppealsMessage(`Appeal submitted successfully: ${response.appeal_id}`, 'success');
    document.getElementById('appeal-form').reset();
    resetAppealValidation();
    await loadAppeals({ clearMessageOnSuccess: false });
  } catch (error) {
    setAppealsMessage(error.message || 'Failed to submit appeal.', 'error');
  } finally {
    setAppealSubmitDisabled(false);
  }
}

document.getElementById('appeals-refresh-btn').addEventListener('click', () => {
  loadAppeals();
});
document.getElementById('appeals-back-to-top').addEventListener('click', () => {
  window.scrollTo({ top: 0, behavior: 'smooth' });
});
document.getElementById('appeal-form').addEventListener('submit', (event) => {
  event.preventDefault();
  submitAppeal();
});
APPEAL_FIELD_IDS.forEach((fieldId) => {
  const field = getAppealField(fieldId);
  if (!field) return;
  field.addEventListener('input', () => {
    if (fieldId === 'appeal-grounds' && field.value.trim().length >= 10) {
      clearAppealFieldError(fieldId);
    } else if (fieldId === 'appeal-relief' && field.value.trim().length >= 5) {
      clearAppealFieldError(fieldId);
    } else if (fieldId === 'appeal-evidence') {
      clearAppealFieldError(fieldId);
    }
  });
});

document.addEventListener('DOMContentLoaded', async () => {
  const session = await Auth.verifySession();
  if (!session.ok) {
    if (session.reason === 'network-error') {
      setAppealsMessage('Appeals service is unavailable. Please try again later.', 'error');
      renderAppealsErrorRow('Appeals service is unavailable.');
      renderAppealsMobilePlaceholder('Appeals service is unavailable.', 'error');
      updateAppealsMeta({ queueCount: '-', pendingCount: '-', updatedLabel: 'Unavailable' });
      releaseRouteAuthGate();
      return;
    }
    Auth.redirectToLogin(
      session.reason === 'expired' ? 'session-expired' : 'appeals-login-required',
      window.__BDA_APPEALS_NEXT__ || '/appeals.html'
    );
    return;
  }

  releaseRouteAuthGate();
  try {
    await loadAppeals();
  } catch (error) {
    setAppealsMessage('Appeals page could not finish loading. Refresh to try again.', 'error');
    renderAppealsErrorRow('Appeals page could not finish loading.');
    renderAppealsMobilePlaceholder('Appeals page could not finish loading.', 'error');
    updateAppealsMeta({ queueCount: '-', pendingCount: '-', updatedLabel: 'Unavailable' });
  }
});
