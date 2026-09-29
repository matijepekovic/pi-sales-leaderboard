(() => {
  const node = document.getElementById('jobMap');
  if (!node) return;

  const status = document.getElementById('jobMapStatus');
  const error = document.getElementById('jobMapError');
  const marketFilter = document.getElementById('jobMapMarket');
  const repFilter = document.getElementById('jobMapRep');
  const productFilter = document.getElementById('jobMapProduct');
  const locateButton = document.getElementById('jobMapLocate');
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
  let pollTimer = null;
  let loadGeneration = 0;
  let filtersReady = false;

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
    if (job.source_record_url) actions.append(action('Open in Salesforce', job.source_record_url));
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
    select.value = Array.from(select.options).some(option => option.value === current) ? current : '';
  }

  function selectedFilters() {
    return {
      market: marketFilter.value,
      rep: repFilter.value,
      product: productFilter.value,
    };
  }

  function enableFilters() {
    filtersReady = true;
    for (const select of filters) select.disabled = false;
    locateButton.disabled = false;
  }

  function clearMapForFilterChange() {
    if (!filtersReady) return;
    cancelPoll();
    loadGeneration += 1;
    jobs = [];
    markers.clearLayers();
    locationLayer.clearLayers();
    delete error.dataset.sourceError;
    error.hidden = true;
    locateButton.disabled = false;
    status.textContent = 'Filters selected — tap Load nearby.';
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
    const circle = L.circle([latitude, longitude], {
      radius: radiusMeters,
      weight: 2,
      opacity: 0.7,
      fillOpacity: 0.04,
    }).addTo(locationLayer);
    L.circleMarker([latitude, longitude], {
      radius: 7,
      weight: 3,
      fillOpacity: 1,
    }).addTo(locationLayer).bindTooltip('Your location');
    map.fitBounds(circle.getBounds(), {padding: [18, 18]});
  }

  function cancelPoll() {
    if (pollTimer !== null) {
      window.clearTimeout(pollTimer);
      pollTimer = null;
    }
  }

  async function fetchJson(url, timeoutMs) {
    const controller = new AbortController();
    const timeout = window.setTimeout(() => controller.abort(), timeoutMs);
    try {
      const response = await fetch(url.toString(), {
        headers: {'Accept': 'application/json'},
        signal: controller.signal,
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
      const hasSnapshot = Number(payload.captured_at) > 0;

      if (hasSnapshot) {
        fillSelect(marketFilter, data.markets, 'All markets');
        fillSelect(repFilter, data.reps, 'All reps');
        fillSelect(productFilter, data.product_types, 'All products');
        enableFilters();
      }

      if (payload.error && !hasSnapshot) {
        status.textContent = 'Map filters unavailable';
        error.dataset.sourceError = '1';
        error.textContent = payload.error;
        error.hidden = false;
        return;
      }

      if (payload.refreshing && !hasSnapshot) {
        status.textContent = 'Preparing map filters…';
        if (Date.now() < deadline) {
          pollTimer = window.setTimeout(() => readFilters(deadline), 1500);
        } else {
          status.textContent = 'Map filters still refreshing';
          error.dataset.sourceError = '1';
          error.textContent = 'Filter refresh is still running in the background. Reload the page to check again.';
          error.hidden = false;
        }
        return;
      }

      if (payload.refreshing && hasSnapshot) {
        status.textContent = 'Choose filters, then Load nearby · refreshing filter choices…';
      } else {
        status.textContent = 'Choose filters, then tap Load nearby.';
      }
      delete error.dataset.sourceError;
      error.hidden = true;
    } catch (exc) {
      status.textContent = 'Map filters unavailable';
      error.dataset.sourceError = '1';
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

  async function readNearby(latitude, longitude, generation, deadline) {
    try {
      const payload = await localSnapshot(latitude, longitude);
      if (generation !== loadGeneration) return;

      radiusMiles = Number.isFinite(payload.radius_miles) ? payload.radius_miles : configuredRadiusMiles;
      jobs = Array.isArray(payload.jobs) ? payload.jobs : [];
      showLocation(latitude, longitude);
      delete error.dataset.sourceError;
      error.hidden = true;
      const shown = renderJobs();

      if (payload.error) {
        error.dataset.sourceError = '1';
        error.textContent = payload.error;
        error.hidden = false;
      }

      if (payload.refreshing) {
        status.textContent = jobs.length
          ? shown + ' filtered nearby jobs shown · refreshing…'
          : 'Applying filters, then checking ' + radiusMiles + ' miles…';
        locateButton.disabled = false;
        if (Date.now() < deadline) {
          pollTimer = window.setTimeout(
            () => readNearby(latitude, longitude, generation, deadline),
            1500,
          );
        } else {
          error.dataset.sourceError = '1';
          error.textContent = 'Filtered map refresh is still running in the background. Tap Load nearby to check again.';
          error.hidden = false;
          status.textContent = jobs.length ? shown + ' filtered nearby jobs shown' : 'Map data still refreshing';
        }
        return;
      }

      locateButton.disabled = false;
      if (jobs.length) {
        const noun = shown === 1 ? 'job' : 'jobs';
        status.textContent = shown + ' filtered ' + noun + ' within ' + radiusMiles + ' miles';
      } else if (payload.error) {
        status.textContent = 'Map data unavailable';
      } else {
        status.textContent = '0 filtered jobs within ' + radiusMiles + ' miles';
        error.textContent = 'No jobs matched the selected filters within ' + radiusMiles + ' miles.';
        error.hidden = false;
      }
    } catch (exc) {
      if (generation !== loadGeneration) return;
      locateButton.disabled = false;
      status.textContent = 'Map unavailable';
      error.dataset.sourceError = '1';
      error.textContent = String(exc.message || exc);
      error.hidden = false;
    }
  }

  function loadNearby() {
    if (!filtersReady) return;
    cancelPoll();
    loadGeneration += 1;
    const generation = loadGeneration;

    if (!navigator.geolocation) {
      status.textContent = 'Location required';
      error.textContent = 'This browser does not provide location access.';
      error.hidden = false;
      return;
    }

    locateButton.disabled = true;
    status.textContent = 'Getting your location…';
    error.hidden = true;

    let settled = false;
    const locationWatchdog = window.setTimeout(() => {
      if (settled || generation !== loadGeneration) return;
      settled = true;
      locateButton.disabled = false;
      status.textContent = 'Location unavailable';
      error.textContent = 'Your location took too long to resolve. Tap Load nearby to try again.';
      error.hidden = false;
    }, 12000);

    navigator.geolocation.getCurrentPosition(
      position => {
        if (settled || generation !== loadGeneration) return;
        settled = true;
        window.clearTimeout(locationWatchdog);
        const latitude = Number(position.coords.latitude);
        const longitude = Number(position.coords.longitude);
        if (!Number.isFinite(latitude) || !Number.isFinite(longitude)) {
          locateButton.disabled = false;
          status.textContent = 'Location unavailable';
          error.textContent = 'Your device returned an invalid location.';
          error.hidden = false;
          return;
        }
        radiusMiles = configuredRadiusMiles;
        showLocation(latitude, longitude);
        status.textContent = 'Applying filters, then checking ' + radiusMiles + ' miles…';
        readNearby(latitude, longitude, generation, Date.now() + 60000);
      },
      geolocationError => {
        if (settled || generation !== loadGeneration) return;
        settled = true;
        window.clearTimeout(locationWatchdog);
        status.textContent = 'Location required';
        error.textContent = geolocationError && geolocationError.code === 1
          ? 'Allow location access to load jobs near you.'
          : 'Your location could not be determined. Try again.';
        error.hidden = false;
        locateButton.disabled = false;
      },
      {enableHighAccuracy: false, timeout: 10000, maximumAge: 60000},
    );
  }

  for (const select of filters) select.addEventListener('change', clearMapForFilterChange);
  locateButton.addEventListener('click', loadNearby);

  readFilters(Date.now() + 60000);
})();
