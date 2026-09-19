(() => {
  const state = document.getElementById('sfSandboxState');
  if (!state) return;

  const status = document.getElementById('sfConnectionStatus');
  const user = document.getElementById('sfConnectionUser');
  const error = document.getElementById('sfConnectionError');
  const retry = document.getElementById('sfRetry');
  const generate = document.getElementById('generate');
  const selects = {
    market_segment: document.getElementById('marketSegment'),
    product_category: document.getElementById('productCategory'),
    source_type: document.getElementById('srcType'),
  };

  function setOptions(select, values) {
    select.replaceChildren();
    const all = document.createElement('option');
    all.value = '';
    all.textContent = 'All';
    select.appendChild(all);
    for (const value of values || []) {
      const option = document.createElement('option');
      option.value = value;
      option.textContent = value;
      select.appendChild(option);
    }
    select.disabled = false;
  }

  async function load() {
    status.textContent = 'Checking Salesforce…';
    user.textContent = '';
    error.hidden = true;
    retry.hidden = true;
    generate.disabled = true;
    for (const select of Object.values(selects)) select.disabled = true;

    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 20000);
    try {
      const response = await fetch(state.dataset.metadataUrl, {
        signal: controller.signal,
        headers: {'Accept': 'application/json'},
      });
      const payload = await response.json();
      if (!response.ok || !payload.ok) {
        throw new Error(payload.error || 'Salesforce metadata request failed.');
      }
      status.textContent = 'Connected';
      user.textContent = payload.username ? ' · ' + payload.username : '';
      setOptions(selects.market_segment, payload.fields.market_segment);
      setOptions(selects.product_category, payload.fields.product_category);
      setOptions(selects.source_type, payload.fields.source_type);
      generate.disabled = false;
    } catch (exc) {
      status.textContent = 'Not connected';
      error.textContent = exc.name === 'AbortError'
        ? 'Salesforce connection check timed out. The page is still usable; retry when ready.'
        : String(exc.message || exc);
      error.hidden = false;
      retry.hidden = false;
    } finally {
      clearTimeout(timer);
    }
  }

  retry.addEventListener('click', load);
  load();
})();
