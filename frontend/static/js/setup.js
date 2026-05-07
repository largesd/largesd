  // Populate CSRF token from cookie into hidden form field
  (function() {
    const match = document.cookie.match(/csrf_token=([^;]+)/);
    if (match) {
      const input = document.getElementById('csrf_token');
      if (input) input.value = decodeURIComponent(match[1]);
    }
  })();

  (function() {
    DataBridge.loadConfig();
    if (DataBridge.isConfigured() && !window.location.search.includes('force=true')) {
      window.location.href = 'index.html';
    }
  })();

  function showStatus(text, type) {
    const el = document.getElementById('status-msg');
    el.textContent = text;
    el.className = 'status-msg ' + (type || 'info');
  }
  function clearStatus() {
    const el = document.getElementById('status-msg');
    el.className = 'status-msg';
    el.textContent = '';
  }

  document.getElementById('setup-form').addEventListener('submit', (e) => e.preventDefault());
  BDA.registerAction('handle-save', handleSave);
  BDA.registerAction('handle-test', handleTest);

  async function handleTest() {
    clearStatus();
    const url = document.getElementById('github-url').value.trim();
    if (!url) { showStatus('Please enter a GitHub URL first.', 'error'); return; }
    showStatus('Testing connection…', 'info');
    const saveBtn = document.getElementById('save-btn');
    const testBtn = document.getElementById('test-btn');
    if (typeof BDA !== 'undefined' && typeof BDA.setButtonBusy === 'function') {
      BDA.setButtonBusy(saveBtn, true, 'Testing...');
      BDA.setButtonBusy(testBtn, true, 'Testing...');
    } else {
      saveBtn.disabled = true; testBtn.disabled = true;
    }
    try {
      const response = await fetch(url, { method: 'GET', cache: 'no-store' });
      if (!response.ok) throw new Error('HTTP ' + response.status);
      const data = await response.json();
      if (!data.debate || !data.snapshot) throw new Error('URL returned JSON but does not look like a debate results file.');
      showStatus('Connection successful. Valid debate results file found.', 'success');
    } catch (err) {
      showStatus('Test failed: ' + err.message, 'error');
    } finally {
      if (typeof BDA !== 'undefined' && typeof BDA.setButtonBusy === 'function') {
        BDA.setButtonBusy(saveBtn, false);
        BDA.setButtonBusy(testBtn, false);
      } else {
        saveBtn.disabled = false; testBtn.disabled = false;
      }
    }
  }

  async function handleSave() {
    clearStatus();
    const url = document.getElementById('github-url').value.trim();
    const email = document.getElementById('dest-email').value.trim();
    if (!url) { showStatus('GitHub URL is required.', 'error'); return; }
    if (!email) { showStatus('Destination email is required.', 'error'); return; }
    try { new URL(url); } catch { showStatus('Invalid URL format.', 'error'); return; }

    const saveBtn = document.getElementById('save-btn');
    const testBtn = document.getElementById('test-btn');
    if (typeof BDA !== 'undefined' && typeof BDA.setButtonBusy === 'function') {
      BDA.setButtonBusy(saveBtn, true, 'Saving...');
      BDA.setButtonBusy(testBtn, true, 'Saving...');
    } else {
      saveBtn.disabled = true; testBtn.disabled = true;
    }

    try {
      const response = await fetch(url, { method: 'GET', cache: 'no-store' });
      if (!response.ok) throw new Error('HTTP ' + response.status);
      const data = await response.json();
      DataBridge.saveConfig(url, email);
      DataBridge.saveCache(data);
      showStatus('Configuration saved. Redirecting…', 'success');
      setTimeout(() => { window.location.href = 'index.html'; }, 800);
    } catch (err) {
      showStatus('Could not save: ' + err.message + '. Make sure the URL is correct and publicly accessible.', 'error');
      if (typeof BDA !== 'undefined' && typeof BDA.setButtonBusy === 'function') {
        BDA.setButtonBusy(saveBtn, false);
        BDA.setButtonBusy(testBtn, false);
      } else {
        saveBtn.disabled = false; testBtn.disabled = false;
      }
    }
  }
