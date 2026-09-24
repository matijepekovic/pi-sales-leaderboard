(() => {
  const state = document.querySelector('[data-mod-sheet-runtime]');
  if (!state) return;

  const status = document.getElementById('modSourceStatus');
  const user = document.getElementById('modSourceUser');
  const error = document.getElementById('modSourceError');
  const retry = document.getElementById('modSourceRetry');
  const submit = document.getElementById('modSubmit');
  const testPrint = document.getElementById('modTestPrint');
  const refreshReps = document.getElementById('modRefreshReps');
  const repsStatus = document.getElementById('modRepsStatus');
  const shell = document.getElementById('modSourceLog');
  const clearActivity = document.getElementById('modSourceClear');
  const form = document.getElementById('modSheetForm');
  const mode = form?.dataset.mode || 'manual';
  const requireConnection = form?.dataset.requireConnection !== 'false';
  const fields = [
    {key: 'market_segment', label: 'Market Segment', allValue: '', select: document.getElementById('marketSegment')},
    {key: 'product_category', label: 'Product Category', allValue: 'All', select: document.getElementById('productCategory')},
    {key: 'source_type', label: 'Source Type', allValue: 'All', select: document.getElementById('srcType')},
    {key: 'assigned_service_resource', label: 'Assigned Service Resource', allValue: '', select: document.getElementById('assignedServiceResource')},
  ];
  const marketField = fields.find(item => item.key === 'market_segment');
  const resourceField = fields.find(item => item.key === 'assigned_service_resource');
  let loading = false;
  let connected = false;
  let resourceLoading = false;
  let resourceReady = false;
  const startDate = document.getElementById('startDate');
  const endDate = document.getElementById('endDate');

  function updateActions() {
    submit.disabled = (requireConnection && (!connected || loading)) || !resourceReady;
    if (testPrint) testPrint.disabled = !connected || loading || !resourceReady;
    refreshReps.disabled = !connected || loading || resourceLoading;
  }

  function appendActivity(line = '') {
    if (!shell) return;
    const current = shell.textContent ? shell.textContent + '\n' : '';
    const lines = (current + line).split('\n');
    shell.textContent = lines.slice(-300).join('\n');
    shell.scrollTop = shell.scrollHeight;
  }

  function appendTrace(trace) {
    for (const entry of trace || []) {
      appendActivity('$ ' + String(entry.input || ''));
      appendActivity((entry.ok === false ? 'ERR ' : 'OK  ') + String(entry.result || ''));
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

  function setOptions(item, values, preserveSelection = false) {
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
    if ((item !== resourceField || preserveSelection) && selected && !choices.includes(selected)) {
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

  async function requestJson(url, timeoutMs, options = {}) {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), timeoutMs);
    appendActivity((options.method || 'GET') + ' ' + url);
    try {
      const response = await fetch(url, {
        ...options,
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
    appendActivity('');
    appendActivity('# ' + item.label);
    if (mode === 'manual') setPlaceholder(item.select, 'Loading…');
    const url = state.dataset.fieldUrl.replace('__FIELD__', encodeURIComponent(item.key));
    try {
      const payload = await requestJson(url, 100000);
      setOptions(item, payload.field.values);
      appendActivity('# resolved ' + item.label + ': ' + (payload.field.path || 'not found'));
      return true;
    } catch (exc) {
      if (mode === 'manual') setPlaceholder(item.select, 'Unavailable');
      appendActivity('ERR ' + item.label + ': ' + String(exc.message || exc));
      return false;
    }
  }

  async function loadResources(refresh = false) {
    if (resourceLoading) return;
    resourceLoading = true;
    updateActions();
    repsStatus.textContent = refresh ? 'Refreshing reps…' : 'Loading saved reps…';
    const url = refresh ? state.dataset.repsRefreshUrl
      : state.dataset.fieldUrl.replace('__FIELD__', encodeURIComponent(resourceField.key));
    const options = {};
    if (refresh) {
      // Snapshot the current lookup scope only on an explicit click. Status
      // checkboxes belong to report generation, not the saved names dropdown.
      const body = new URLSearchParams({
        csrf: state.dataset.csrf,
        marketsegment: currentSelection(marketField),
        startdate: startDate.value,
        enddate: endDate.value,
        productCategory: currentSelection(fields[1]),
        sourceType: currentSelection(fields[2]),
      });
      if (mode === 'settings') body.set('dateScope', 'today');
      options.method = 'POST';
      options.body = body;
    }
    try {
      const payload = await requestJson(url, 100000, options);
      const selected = currentSelection(resourceField);
      setOptions(resourceField, payload.field.values, !refresh && mode === 'settings');
      resourceReady = true;
      repsStatus.textContent = payload.saved
        ? (refresh ? 'Rep list replaced.' : 'Using saved reps.')
        : 'No saved reps yet. Press Refresh reps.';
      if (refresh && selected && resourceField.select.value !== selected) {
        repsStatus.textContent += ' Previous rep is absent; All selected.';
      }
    } catch (exc) {
      // Keep existing options and selection on failures. Never silently fall
      // back to All, append partial pages, or replace saved names with errors.
      repsStatus.textContent = refresh
        ? 'Refresh failed. Existing reps kept. Press Refresh reps to retry.'
        : 'Could not read saved reps. Press Refresh reps after connecting.';
      appendActivity('ERR Assigned Service Resource: ' + String(exc.message || exc));
    } finally {
      resourceLoading = false;
      updateActions();
    }
  }

  async function load() {
    if (loading) return;
    loading = true;
    connected = false;
    status.textContent = 'Checking source…';
    user.textContent = '';
    error.hidden = true;
    retry.hidden = true;
    updateActions();
    if (mode === 'manual') {
      for (const item of fields.filter(item => item !== resourceField)) {
        setPlaceholder(item.select, 'Waiting for connection…');
      }
    }

    appendActivity('');
    appendActivity('# connection');
    try {
      const payload = await requestJson(state.dataset.connectionUrl, 25000);
      connected = true;
      status.textContent = 'Connected';
      user.textContent = payload.username ? ' · ' + payload.username : '';
      appendActivity('# connected' + (payload.alias ? ' as ' + payload.alias : ''));

      const fieldResults = await Promise.all(fields.filter(item => item !== resourceField).map(loadField));
      const fieldError = fieldResults.some(ok => !ok);
      updateActions();
      if (fieldError) {
        error.textContent = mode === 'settings'
          ? 'Connected to the MOD source, but one or more filter lists could not refresh. Your saved values are still available.'
          : 'Connected to the MOD source, but one or more filter lists could not load. Generate still works with the available filters.';
        error.hidden = false;
        retry.hidden = false;
      }
    } catch (exc) {
      connected = false;
      status.textContent = 'Not connected';
      const message = exc.name === 'AbortError'
        ? 'MOD source connection check timed out.'
        : String(exc.message || exc);
      error.textContent = message;
      error.hidden = false;
      retry.hidden = false;
      updateActions();
      appendActivity('ERR ' + message);
    } finally {
      loading = false;
      updateActions();
    }
  }

  for (const item of fields) {
    item.select.addEventListener('change', () => {
      item.select.dataset.selected = item.select.value;
    });
  }
  refreshReps.addEventListener('click', () => {
    if (!refreshReps.disabled) loadResources(true);
  });

  if (clearActivity) {
    clearActivity.addEventListener('click', () => {
      shell.textContent = 'Source activity cleared.';
    });
  }
  retry.addEventListener('click', load);

  form.addEventListener('submit', event => {
    if (!resourceReady || (requireConnection && (!connected || loading))) {
      event.preventDefault();
      return;
    }
    const values = Object.fromEntries(new FormData(form).entries());
    delete values.csrf;
    appendActivity('');
    appendActivity(mode === 'settings' ? '# Save daily MOD settings' : '# Generate MOD PDF');
    appendActivity('INPUT ' + JSON.stringify(values));
    appendActivity(mode === 'settings'
      ? 'RESULT permanent settings submitted'
      : 'RESULT request opened in a new tab');
  });

  loadResources(); // Local persistence only, independent of the source connection.
  load();
})();
