(() => {
  const state = document.querySelector('[data-mod-sheet-runtime]');
  if (!state) return;

  const status = document.getElementById('sfConnectionStatus');
  const user = document.getElementById('sfConnectionUser');
  const error = document.getElementById('sfConnectionError');
  const retry = document.getElementById('sfRetry');
  const submit = document.getElementById('modSubmit');
  const shell = document.getElementById('sfShellLog');
  const clearShell = document.getElementById('sfShellClear');
  const form = document.getElementById('sfModForm');
  const mode = form?.dataset.mode || 'manual';
  const requireConnection = form?.dataset.requireConnection !== 'false';
  const fields = [
    {key: 'market_segment', label: 'Market Segment', allValue: '', select: document.getElementById('marketSegment')},
    {key: 'product_category', label: 'Product Category', allValue: 'All', select: document.getElementById('productCategory')},
    {key: 'source_type', label: 'Source Type', allValue: 'All', select: document.getElementById('srcType')},
  ];
  let loading = false;

  function appendShell(line = '') {
    if (!shell) return;
    const current = shell.textContent ? shell.textContent + '\n' : '';
    const lines = (current + line).split('\n');
    shell.textContent = lines.slice(-300).join('\n');
    shell.scrollTop = shell.scrollHeight;
  }

  function appendTrace(trace) {
    for (const entry of trace || []) {
      appendShell('$ ' + String(entry.input || ''));
      appendShell((entry.ok === false ? 'ERR ' : 'OK  ') + String(entry.result || ''));
    }
  }

  function currentSelection(item) {
    return item.select.dataset.selected ?? item.select.value ?? item.allValue;
  }

  function setPlaceholder(select, text) {
    select.replaceChildren();
    const option = document.createElement('option');
    option.value = '';
    option.textContent = text;
    select.appendChild(option);
    select.disabled = true;
  }

  function setOptions(item, values) {
    const selected = currentSelection(item);
    const select = item.select;
    select.replaceChildren();
    const all = document.createElement('option');
    all.value = item.allValue;
    all.textContent = 'All';
    select.appendChild(all);
    for (const value of values || []) {
      const option = document.createElement('option');
      option.value = value;
      option.textContent = value;
      select.appendChild(option);
    }
    let choices = Array.from(select.options).map(option => option.value);
    if (selected && !choices.includes(selected)) {
      const saved = document.createElement('option');
      saved.value = selected;
      saved.textContent = selected;
      select.appendChild(saved);
      choices = [...choices, selected];
    }
    select.value = choices.includes(selected) ? selected : item.allValue;
    select.dataset.selected = select.value;
    select.disabled = false;
  }

  async function requestJson(url, timeoutMs) {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), timeoutMs);
    appendShell('GET ' + url);
    try {
      const response = await fetch(url, {
        signal: controller.signal,
        headers: {'Accept': 'application/json'},
      });
      const payload = await response.json();
      appendTrace(payload.trace);
      if (!response.ok || !payload.ok) {
        throw new Error(payload.error || 'MOD Sheet source request failed.');
      }
      return payload;
    } finally {
      clearTimeout(timer);
    }
  }

  async function loadField(item) {
    appendShell('');
    appendShell('# ' + item.label);
    if (mode === 'manual') setPlaceholder(item.select, 'Loading…');
    const url = state.dataset.fieldUrl.replace('__FIELD__', encodeURIComponent(item.key));
    try {
      const payload = await requestJson(url, 100000);
      setOptions(item, payload.field.values);
      appendShell('# resolved ' + item.label + ': ' + (payload.field.path || 'not found'));
      return true;
    } catch (exc) {
      if (mode === 'manual') setPlaceholder(item.select, 'Unavailable');
      appendShell('ERR ' + item.label + ': ' + String(exc.message || exc));
      return false;
    }
  }

  async function load() {
    if (loading) return;
    loading = true;
    status.textContent = 'Checking Salesforce…';
    user.textContent = '';
    error.hidden = true;
    retry.hidden = true;
    if (requireConnection) submit.disabled = true;
    if (mode === 'manual') {
      for (const item of fields) setPlaceholder(item.select, 'Waiting for connection…');
    }

    appendShell('');
    appendShell('# connection');
    try {
      const payload = await requestJson(state.dataset.connectionUrl, 25000);
      status.textContent = 'Connected';
      user.textContent = payload.username ? ' · ' + payload.username : '';
      appendShell('# connected' + (payload.alias ? ' as ' + payload.alias : ''));

      const fieldResults = await Promise.all(fields.map(loadField));
      const fieldError = fieldResults.some(ok => !ok);
      submit.disabled = false;
      if (fieldError) {
        error.textContent = mode === 'settings'
          ? 'Connected to Salesforce, but one or more filter lists could not refresh. Your saved values are still available.'
          : 'Connected to Salesforce, but one or more filter lists could not load. Generate still works with the available filters.';
        error.hidden = false;
        retry.hidden = false;
      }
    } catch (exc) {
      status.textContent = 'Not connected';
      const message = exc.name === 'AbortError'
        ? 'Salesforce connection check timed out.'
        : String(exc.message || exc);
      error.textContent = message;
      error.hidden = false;
      retry.hidden = false;
      if (!requireConnection) submit.disabled = false;
      appendShell('ERR ' + message);
    } finally {
      loading = false;
    }
  }

  for (const item of fields) {
    item.select.addEventListener('change', () => {
      item.select.dataset.selected = item.select.value;
    });
  }

  if (clearShell) {
    clearShell.addEventListener('click', () => {
      shell.textContent = 'Salesforce CLI activity cleared.';
    });
  }
  retry.addEventListener('click', load);

  form.addEventListener('submit', () => {
    const values = Object.fromEntries(new FormData(form).entries());
    delete values.csrf;
    appendShell('');
    appendShell(mode === 'settings' ? '# Save daily MOD settings' : '# Generate MOD PDF');
    appendShell('INPUT ' + JSON.stringify(values));
    appendShell(mode === 'settings'
      ? 'RESULT permanent settings submitted'
      : 'RESULT request opened in a new tab');
  });

  load();
})();
