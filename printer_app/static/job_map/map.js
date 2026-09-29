(() => {
  const node = document.getElementById('jobMap');
  if (!node) return;

  const status = document.getElementById('jobMapStatus');
  const error = document.getElementById('jobMapError');
  const marketFilter = document.getElementById('jobMapMarket');
  const repFilter = document.getElementById('jobMapRep');
  const productFilter = document.getElementById('jobMapProduct');
  const locateButton = document.getElementById('jobMapLocate');
  const diagnoseButton = document.getElementById('jobMapDiagnose');
  const sinceInput = document.getElementById('jobMapSince');
  const lastMonthButton = document.getElementById('jobMapLastMonth');
  const lastYearButton = document.getElementById('jobMapLastYear');
  const loadSinceButton = document.getElementById('jobMapLoadSince');
  const syncStatus = document.getElementById('jobMapSyncStatus');
  const diagnosticsDetails = document.getElementById('jobMapDiagnostics');
  const diagnosticsText = document.getElementById('jobMapDiagnosticsText');
  const filters = [marketFilter, repFilter, productFilter];
  const configuredRadiusMiles = Number(node.dataset.radiusMiles);

  if (!Number.isFinite(configuredRadiusMiles) || configuredRadiusMiles <= 0) {
    status.textContent = 'Map unavailable';
    error.textContent = 'The map radius configuration is invalid.';
    error.hidden = false;
    return;
  }
  if (!window.L) {
    status.textContent = 'Map unavailable';
    error.textContent = 'The map library could not load.';
    error.hidden = false;
    return;
  }

  const map = L.map(node, {preferCanvas: true});
  const markers = L.layerGroup().addTo(map);
  const locationLayer = L.layerGroup().addTo(map);
  let jobs = [];
  let radiusMiles = configuredRadiusMiles;
  let filtersReady = false;
  let loadGeneration = 0;
  let filterPollTimer = null;
  let syncPollTimer = null;
  let syncWasRunning = false;

  L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
    maxZoom: 19,
    attribution: '&copy; OpenStreetMap contributors',
  }).addTo(map);

  function text(tag, value, className = '') {
    const element = document.createElement(tag);
    if (className) element.className = className;
    element.textContent = value;
    return element;
  }

  function action(label, href) {
    const link = document.createElement('a');
    link.textContent = label;
    link.href = href;
    link.target = '_blank';
    link.rel = 'noopener';
    return link;
  }

  function popup(job) {
    const wrapper = document.createElement('div');
    wrapper.className = 'job-map-popup';
    wrapper.append(text('strong', job.lead_name || ('Work order ' + job.work_order_number)));
    wrapper.append(text('small', 'Work order ' + job.work_order_number));
    if (job.market) wrapper.append(text('small', 'Market: ' + job.market));
    if (job.product_type) wrapper.append(text('small', 'Product: ' + job.product_type));
    if (Array.isArray(job.assigned_reps) && job.assigned_reps.length) {
      wrapper.append(text('small', 'Rep: ' + job.assigned_reps.join(', ')));
    }
    const actions = document.createElement('div');
    actions.className = 'job-map-popup-actions';
    const mod = new URL(node.dataset.modSheetUrl, window.location.href);
    mod.searchParams.set('work_order', job.work_order_number);
    actions.append(action('MOD Sheet', mod.toString()));
    if (job.source_record_url) {
      actions.append(action('Open in Salesforce', job.source_record_url));
    }
    wrapper.append(actions);
    return wrapper;
  }

  function normalized(value) {
    return String(value || '').trim().toLocaleLowerCase();
  }

  function optionsFor(values) {
    const unique = new Map();
    for (const value of values || []) {
      const clean = String(value || '').trim();
      if (clean) unique.set(normalized(clean), clean);
    }
    return Array.from(unique.values()).sort((a, b) => a.localeCompare(b));
  }

  function fillSelect(select, values, allLabel) {
    const current = select.value;
    select.replaceChildren();
    const all = document.createElement('option');
    all.value = '';
    all.textContent = allLabel;
    select.append(all);
    for (const value of optionsFor(values)) {
      const option = document.createElement('option');
      option.value = value;
      option.textContent = value;
      select.append(option);
    }
    select.value = Array.from(select.options).some(option => option.value === current)
      ? current
      : '';
  }

  function selectedFilters() {
    return {
      market: marketFilter.value,
      rep: repFilter.value,
      product: productFilter.value,
    };
  }

  function updateHistoryButtons() {
    const enabled = filtersReady && Boolean(marketFilter.value);
    lastMonthButton.disabled = !enabled;
    lastYearButton.disabled = !enabled;
    loadSinceButton.disabled = !enabled || !sinceInput.value;
  }

  function enableFilters() {
    filtersReady = true;
    for (const select of filters) select.disabled = false;
    locateButton.disabled = false;
    diagnoseButton.disabled = false;
    updateHistoryButtons();
  }

  function clearMapForFilterChange() {
    if (!filtersReady) return;
    loadGeneration += 1;
    jobs = [];
    markers.clearLayers();
    locationLayer.clearLayers();
    error.hidden = true;
    diagnosticsText.textContent = 'Filters changed — run Load nearby or Refresh diagnostics.';
    status.textContent = 'Filters selected — tap Load nearby.';
    updateHistoryButtons();
    readSyncStatus();
  }

  function renderJobs() {
    markers.clearLayers();
    let shown = 0;
    for (const job of jobs) {
      if (!Number.isFinite(job.latitude) || !Number.isFinite(job.longitude)) continue;
      L.marker([job.latitude, job.longitude]).addTo(markers).bindPopup(popup(job));
      shown += 1;
    }
    return shown;
  }

  function showLocation(latitude, longitude) {
    locationLayer.clearLayers();
    const radiusMeters = radiusMiles * 1609.344;
    const center = L.latLng(latitude, longitude);
    map.fitBounds(center.toBounds(radiusMeters * 2), {padding: [18, 18]});
    L.circle(center, {
      radius: radiusMeters,
      weight: 2,
      opacity: 0.7,
      fillOpacity: 0.04,
    }).addTo(locationLayer);
    L.circleMarker(center, {
      radius: 7,
      weight: 3,
      fillOpacity: 1,
    }).addTo(locationLayer).bindTooltip('Your location');
  }

  async function fetchJson(url, timeoutMs, options = {}) {
    const controller = new AbortController();
    const timeout = window.setTimeout(() => controller.abort(), timeoutMs);
    try {
      const response = await fetch(url.toString(), {
        headers: {'Accept': 'application/json', ...(options.headers || {})},
        signal: controller.signal,
        ...options,
      });
      const payload = await response.json();
      if (!response.ok || !payload.ok) {
        throw new Error(payload.error || 'Request failed.');
      }
      return payload;
    } catch (exc) {
      if (exc && exc.name === 'AbortError') {
        throw new Error('The local map service did not respond. Try again.');
      }
      throw exc;
    } finally {
      window.clearTimeout(timeout);
    }
  }

  async function readFilters(deadline) {
    try {
      const url = new URL(node.dataset.filtersUrl, window.location.href);
      const payload = await fetchJson(url, 10000);
      const data = payload.filters || {};
      const hasChoices = (
        (Array.isArray(data.markets) && data.markets.length)
        || (Array.isArray(data.reps) && data.reps.length)
        || (Array.isArray(data.product_types) && data.product_types.length)
      );

      if (hasChoices) {
        fillSelect(marketFilter, data.markets, 'All markets');
        fillSelect(repFilter, data.reps, 'All reps');
        fillSelect(productFilter, data.product_types, 'All products');
        enableFilters();
      }

      if (payload.error && !hasChoices) {
        status.textContent = 'Map filters unavailable';
        error.textContent = payload.error;
        error.hidden = false;
        return;
      }

      if (payload.refreshing && !hasChoices) {
        status.textContent = 'Preparing map filters…';
        if (Date.now() < deadline) {
          if (filterPollTimer !== null) window.clearTimeout(filterPollTimer);
          filterPollTimer = window.setTimeout(() => readFilters(deadline), 1500);
        } else {
          status.textContent = 'Map filters still refreshing';
          error.textContent = 'Filter choices are still refreshing in the background.';
          error.hidden = false;
        }
        return;
      }

      status.textContent = 'Choose filters, then tap Load nearby.';
      error.hidden = true;
    } catch (exc) {
      status.textContent = 'Map filters unavailable';
      error.textContent = String(exc.message || exc);
      error.hidden = false;
    }
  }

  async function localSnapshot(latitude, longitude) {
    const url = new URL(node.dataset.jobsUrl, window.location.href);
    const selected = selectedFilters();
    url.searchParams.set('lat', String(latitude));
    url.searchParams.set('lon', String(longitude));
    if (selected.market) url.searchParams.set('market', selected.market);
    if (selected.rep) url.searchParams.set('rep', selected.rep);
    if (selected.product) url.searchParams.set('product', selected.product);
    return fetchJson(url, 10000);
  }

  function diagnosticLines(payload, latitude, longitude) {
    const selected = selectedFilters();
    const detail = payload && payload.diagnostics ? payload.diagnostics : {};
    const lines = [
      'Phone: ' + latitude.toFixed(6) + ', ' + longitude.toFixed(6),
      'Filters: Market=' + (selected.market || 'All')
        + ' | Rep=' + (selected.rep || 'All')
        + ' | Product=' + (selected.product || 'All'),
      'Radius: ' + radiusMiles + ' miles',
      'Local history updated: ' + (payload && payload.captured_at
        ? new Date(Number(payload.captured_at) * 1000).toLocaleString()
        : 'not loaded'),
      '',
      'Local records after market/product: ' + Number(detail.local_records || 0),
      'Grouped work orders: ' + Number(detail.grouped_jobs || 0),
      'Jobs matching rep: ' + Number(detail.rep_matched_jobs || 0),
      'Jobs with map location: ' + Number(detail.jobs_with_location || 0),
      'Jobs missing map location: ' + Number(detail.jobs_missing_location || 0),
      'Excluded by lead status: ' + Number(detail.excluded_status || 0),
      'Outside ' + radiusMiles + ' miles: ' + Number(detail.outside_radius || 0),
      'Visible jobs: ' + Number(detail.visible_jobs || 0),
    ];

    const candidates = Array.isArray(detail.candidates) ? detail.candidates : [];
    lines.push('', 'Nearest candidates (' + candidates.length + ' shown):');
    if (!candidates.length) {
      lines.push('  none');
    } else {
      for (const item of candidates) {
        const distance = Number(item.distance_miles);
        const lat = Number(item.latitude);
        const lon = Number(item.longitude);
        lines.push(
          '  ' + String(item.work_order_number || '—')
          + ' | ' + (Number.isFinite(distance) ? distance.toFixed(3) + ' mi' : 'distance ?')
          + ' | ' + String(item.outcome || 'unknown')
          + ' | status=' + String(item.lead_status || '—')
          + ' | ' + String(item.lead_name || '—')
          + ' | ' + (Number.isFinite(lat) ? lat.toFixed(6) : '?')
          + ', ' + (Number.isFinite(lon) ? lon.toFixed(6) : '?')
        );
      }
    }
    if (payload && payload.error) lines.push('', 'Map note: ' + String(payload.error));
    return lines;
  }

  async function readNearby(latitude, longitude, generation, openDiagnostics = false) {
    try {
      const payload = await localSnapshot(latitude, longitude);
      if (generation !== loadGeneration) return;

      radiusMiles = Number.isFinite(payload.radius_miles)
        ? payload.radius_miles
        : configuredRadiusMiles;
      jobs = Array.isArray(payload.jobs) ? payload.jobs : [];
      showLocation(latitude, longitude);
      const shown = renderJobs();
      diagnosticsText.textContent = diagnosticLines(payload, latitude, longitude).join('\n');
      if (openDiagnostics) diagnosticsDetails.open = true;

      locateButton.disabled = false;
      diagnoseButton.disabled = false;
      if (payload.error) {
        error.textContent = payload.error;
        error.hidden = false;
      } else {
        error.hidden = true;
      }

      if (jobs.length) {
        status.textContent = shown + ' filtered ' + (shown === 1 ? 'job' : 'jobs')
          + ' within ' + radiusMiles + ' miles';
      } else if (payload.error) {
        status.textContent = 'No local map result';
      } else {
        status.textContent = '0 filtered jobs within ' + radiusMiles + ' miles';
        error.textContent = 'No locally loaded jobs matched the selected filters within '
          + radiusMiles + ' miles.';
        error.hidden = false;
      }
    } catch (exc) {
      if (generation !== loadGeneration) return;
      locateButton.disabled = false;
      diagnoseButton.disabled = false;
      status.textContent = 'Map unavailable';
      error.textContent = String(exc.message || exc);
      error.hidden = false;
    }
  }

  function geolocationMessage(value) {
    if (!value) return 'Your iPhone did not return a location.';
    if (value.code === 1) return 'Location permission was denied for this site.';
    if (value.code === 2) return 'Your iPhone could not determine its location.';
    if (value.code === 3) return 'Your iPhone location request timed out.';
    return String(value.message || 'Your iPhone did not return a location.');
  }

  function acquireLocation(generation) {
    return new Promise((resolve, reject) => {
      if (!window.isSecureContext) {
        reject(new Error('Location requires the HTTPS map address.'));
        return;
      }
      if (!navigator.geolocation) {
        reject(new Error('This browser does not provide location access.'));
        return;
      }

      let finished = false;
      let watchId = null;
      let singleFinished = false;
      let watchFinished = false;
      let singleError = null;
      let watchError = null;

      function cleanup() {
        if (watchId !== null) navigator.geolocation.clearWatch(watchId);
        window.clearTimeout(deadline);
      }

      function succeed(position) {
        if (finished || generation !== loadGeneration) return;
        const latitude = Number(position && position.coords && position.coords.latitude);
        const longitude = Number(position && position.coords && position.coords.longitude);
        if (!Number.isFinite(latitude) || !Number.isFinite(longitude)) return;
        finished = true;
        cleanup();
        resolve({latitude, longitude});
      }

      function maybeFail() {
        if (finished || generation !== loadGeneration) return;
        if (!singleFinished || !watchFinished) return;
        finished = true;
        cleanup();
        reject(new Error(geolocationMessage(watchError || singleError)));
      }

      const deadline = window.setTimeout(() => {
        if (finished || generation !== loadGeneration) return;
        finished = true;
        cleanup();
        reject(new Error(
          'Location permission is allowed, but the iPhone did not return coordinates. Tap Load nearby to retry.'
        ));
      }, 15000);

      try {
        navigator.geolocation.getCurrentPosition(
          succeed,
          value => {
            singleFinished = true;
            singleError = value;
            maybeFail();
          },
          {enableHighAccuracy: false, timeout: 10000, maximumAge: 300000},
        );
      } catch (exc) {
        singleFinished = true;
        singleError = exc;
      }

      try {
        watchId = navigator.geolocation.watchPosition(
          succeed,
          value => {
            watchFinished = true;
            watchError = value;
            maybeFail();
          },
          {enableHighAccuracy: true, timeout: 12000, maximumAge: 300000},
        );
      } catch (exc) {
        watchFinished = true;
        watchError = exc;
      }

      maybeFail();
    });
  }

  async function loadNearby(openDiagnostics = false) {
    if (!filtersReady) return;
    loadGeneration += 1;
    const generation = loadGeneration;
    locateButton.disabled = true;
    diagnoseButton.disabled = true;
    status.textContent = 'Getting your location…';
    error.hidden = true;

    let location;
    try {
      location = await acquireLocation(generation);
    } catch (exc) {
      if (generation !== loadGeneration) return;
      locateButton.disabled = false;
      diagnoseButton.disabled = false;
      status.textContent = 'Location unavailable';
      error.textContent = String(exc.message || exc);
      error.hidden = false;
      return;
    }

    if (generation !== loadGeneration) return;
    radiusMiles = configuredRadiusMiles;
    status.textContent = 'Checking locally loaded jobs…';
    await readNearby(
      location.latitude,
      location.longitude,
      generation,
      openDiagnostics,
    );
  }

  function ymd(value) {
    const year = value.getFullYear();
    const month = String(value.getMonth() + 1).padStart(2, '0');
    const day = String(value.getDate()).padStart(2, '0');
    return year + '-' + month + '-' + day;
  }

  function shiftedMonth(months) {
    const now = new Date();
    const originalDay = now.getDate();
    const target = new Date(now.getFullYear(), now.getMonth(), 1);
    target.setMonth(target.getMonth() + months);
    const lastDay = new Date(
      target.getFullYear(), target.getMonth() + 1, 0
    ).getDate();
    target.setDate(Math.min(originalDay, lastDay));
    return target;
  }

  function shiftedYear(years) {
    const now = new Date();
    const target = new Date(now.getFullYear() + years, now.getMonth(), 1);
    const lastDay = new Date(
      target.getFullYear(), target.getMonth() + 1, 0
    ).getDate();
    target.setDate(Math.min(now.getDate(), lastDay));
    return target;
  }

  function selectedCoverage(payload) {
    const selected = normalized(marketFilter.value);
    const coverage = payload && payload.coverage ? payload.coverage : {};
    for (const value of Object.values(coverage)) {
      if (normalized(value && value.market) === selected) return value;
    }
    return null;
  }

  function renderSyncState(payload) {
    const state = payload && payload.sync ? payload.sync : {};
    const coverage = selectedCoverage(payload);
    const currentMarket = marketFilter.value;
    if (state.status === 'queued' || state.status === 'running') {
      const progress = Number(state.total_chunks) > 0
        ? ' · ' + Number(state.completed_chunks || 0) + '/' + Number(state.total_chunks) + ' chunks'
        : '';
      const chunk = state.chunk_start
        ? ' · ' + state.chunk_start + ' to ' + state.chunk_end
        : '';
      syncStatus.textContent = 'Loading ' + state.market + ' history' + progress + chunk
        + ' · ' + Number(state.records_written || 0) + ' records written';
      return true;
    }
    if (state.status === 'failed') {
      syncStatus.textContent = 'History load failed'
        + (state.chunk_start ? ' at ' + state.chunk_start + ' to ' + state.chunk_end : '')
        + ': ' + String(state.error || 'unknown error');
      return false;
    }
    if (coverage && currentMarket) {
      syncStatus.textContent = 'Local history for ' + coverage.market + ': '
        + coverage.since_date + ' through ' + coverage.through_date
        + (coverage.incremental_error
          ? ' · automatic update error: ' + coverage.incremental_error
          : '');
    } else if (currentMarket) {
      syncStatus.textContent = 'No local history loaded for ' + currentMarket + ' yet.';
    } else {
      syncStatus.textContent = 'Choose a market, then load a history range.';
    }
    return false;
  }

  async function readSyncStatus() {
    try {
      const url = new URL(node.dataset.syncUrl, window.location.href);
      const payload = await fetchJson(url, 10000);
      const running = renderSyncState(payload);
      if (running) {
        syncWasRunning = true;
        if (syncPollTimer !== null) window.clearTimeout(syncPollTimer);
        syncPollTimer = window.setTimeout(readSyncStatus, 1800);
      } else {
        updateHistoryButtons();
        if (syncWasRunning) {
          syncWasRunning = false;
          readFilters(Date.now() + 60000);
        }
      }
    } catch (exc) {
      syncStatus.textContent = 'Could not read history sync status: ' + String(exc.message || exc);
    }
  }

  async function requestHistory(sinceDate) {
    if (!filtersReady || !marketFilter.value) {
      syncStatus.textContent = 'Choose a market before loading history.';
      return;
    }
    const throughDate = ymd(new Date());
    const body = new URLSearchParams();
    body.set('csrf', node.dataset.csrf || '');
    body.set('since', sinceDate);
    body.set('through', throughDate);
    body.set('market', marketFilter.value);

    lastMonthButton.disabled = true;
    lastYearButton.disabled = true;
    loadSinceButton.disabled = true;
    syncStatus.textContent = 'Queueing history load…';
    try {
      const payload = await fetchJson(
        new URL(node.dataset.syncUrl, window.location.href),
        10000,
        {
          method: 'POST',
          headers: {'Content-Type': 'application/x-www-form-urlencoded;charset=UTF-8'},
          body: body.toString(),
        },
      );
      renderSyncState({sync: payload.sync, coverage: {}});
      if (syncPollTimer !== null) window.clearTimeout(syncPollTimer);
      syncPollTimer = window.setTimeout(async () => {
        await readSyncStatus();
        readFilters(Date.now() + 60000);
      }, 1200);
    } catch (exc) {
      syncStatus.textContent = 'Could not start history load: ' + String(exc.message || exc);
      updateHistoryButtons();
    }
  }

  sinceInput.value = ymd(shiftedMonth(-1));
  sinceInput.addEventListener('change', updateHistoryButtons);
  for (const select of filters) {
    select.addEventListener('change', clearMapForFilterChange);
  }
  locateButton.addEventListener('click', () => loadNearby(false));
  diagnoseButton.addEventListener('click', () => loadNearby(true));
  lastMonthButton.addEventListener('click', () => {
    const since = ymd(shiftedMonth(-1));
    sinceInput.value = since;
    requestHistory(since);
  });
  lastYearButton.addEventListener('click', () => {
    const since = ymd(shiftedYear(-1));
    sinceInput.value = since;
    requestHistory(since);
  });
  loadSinceButton.addEventListener('click', () => requestHistory(sinceInput.value));

  readFilters(Date.now() + 60000);
  readSyncStatus();
})();
