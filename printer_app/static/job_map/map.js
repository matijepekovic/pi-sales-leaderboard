(() => {
  const node = document.getElementById('jobMap');
  if (!node) return;
  const status = document.getElementById('jobMapStatus');
  const error = document.getElementById('jobMapError');
  const marketSelect = document.getElementById('jobMapMarket');
  const repSelect = document.getElementById('jobMapRep');
  if (!window.maplibregl) {
    status.textContent = 'Map unavailable';
    error.textContent = 'The map library could not load.';
    error.hidden = false;
    return;
  }

  const map = new maplibregl.Map({
    container: node,
    style: 'https://tiles.openfreemap.org/styles/liberty',
    center: [-98.35, 39.5],
    zoom: 3.5,
  });
  map.addControl(new maplibregl.NavigationControl(), 'top-left');

  let allJobs = [];
  let markers = [];

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
    const actions = document.createElement('div');
    actions.className = 'job-map-popup-actions';
    const mod = new URL(node.dataset.modSheetUrl, window.location.href);
    mod.searchParams.set('work_order', job.work_order_number);
    actions.append(action('MOD Sheet', mod.toString()));
    if (job.source_record_url) actions.append(action('Open in Salesforce', job.source_record_url));
    wrapper.append(actions);
    return wrapper;
  }

  function setOptions(select, values, allLabel) {
    const current = select.value;
    select.replaceChildren();
    const all = document.createElement('option');
    all.value = '';
    all.textContent = allLabel;
    select.appendChild(all);
    for (const value of values) {
      const option = document.createElement('option');
      option.value = value;
      option.textContent = value;
      select.appendChild(option);
    }
    select.value = values.includes(current) ? current : '';
  }

  function jobsForMarket() {
    const market = marketSelect.value;
    return market ? allJobs.filter(job => job.market_segment === market) : allJobs;
  }

  function refreshRepOptions() {
    const reps = new Set();
    for (const job of jobsForMarket()) {
      for (const rep of job.assigned_service_resources || []) if (rep) reps.add(rep);
    }
    setOptions(repSelect, [...reps].sort((a, b) => a.localeCompare(b)), 'All reps');
  }

  function render() {
    for (const marker of markers) marker.remove();
    markers = [];
    error.hidden = true;

    const market = marketSelect.value;
    const rep = repSelect.value;
    const visible = allJobs.filter(job =>
      (!market || job.market_segment === market)
      && (!rep || (job.assigned_service_resources || []).includes(rep))
    );

    const bounds = new maplibregl.LngLatBounds();
    let only = null;
    for (const job of visible) {
      if (!Number.isFinite(job.latitude) || !Number.isFinite(job.longitude)) continue;
      const point = [job.longitude, job.latitude];
      const marker = new maplibregl.Marker()
        .setLngLat(point)
        .setPopup(new maplibregl.Popup({offset: 24}).setDOMContent(popup(job)))
        .addTo(map);
      markers.push(marker);
      bounds.extend(point);
      only = point;
    }

    const count = markers.length;
    status.textContent = count + (count === 1 ? ' job mapped' : ' jobs mapped');
    if (count === 1) map.jumpTo({center: only, zoom: 15});
    else if (count > 1) map.fitBounds(bounds, {padding: 24, maxZoom: 15, duration: 0});
    else {
      error.textContent = 'No mapped jobs match these filters.';
      error.hidden = false;
    }
  }

  marketSelect.addEventListener('change', () => {
    refreshRepOptions();
    render();
  });
  repSelect.addEventListener('change', render);

  fetch(node.dataset.jobsUrl, {headers: {'Accept': 'application/json'}})
    .then(async response => {
      const payload = await response.json();
      if (!response.ok || !payload.ok) throw new Error(payload.error || 'Could not load jobs.');
      return payload.jobs || [];
    })
    .then(jobs => {
      allJobs = jobs.filter(job => Number.isFinite(job.latitude) && Number.isFinite(job.longitude));
      const markets = [...new Set(allJobs.map(job => job.market_segment).filter(Boolean))]
        .sort((a, b) => a.localeCompare(b));
      setOptions(marketSelect, markets, 'All markets');
      refreshRepOptions();
      render();
    })
    .catch(exc => {
      status.textContent = 'Map unavailable';
      error.textContent = String(exc.message || exc);
      error.hidden = false;
    });
})();
