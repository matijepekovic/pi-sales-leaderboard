(() => {
  const node = document.getElementById('jobMap');
  if (!node) return;
  const status = document.getElementById('jobMapStatus');
  const error = document.getElementById('jobMapError');
  if (!window.L) {
    status.textContent = 'Map unavailable';
    error.textContent = 'The map library could not load.';
    error.hidden = false;
    return;
  }
  const map = L.map(node, {preferCanvas: true}).setView([39.5, -98.35], 4);
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
    const actions = document.createElement('div');
    actions.className = 'job-map-popup-actions';
    const mod = new URL(node.dataset.modSheetUrl, window.location.href);
    mod.searchParams.set('work_order', job.work_order_number);
    actions.append(action('MOD Sheet', mod.toString()));
    if (job.source_record_url) actions.append(action('Open in Salesforce', job.source_record_url));
    wrapper.append(actions);
    return wrapper;
  }

  fetch(node.dataset.jobsUrl, {headers: {'Accept': 'application/json'}})
    .then(async response => {
      const payload = await response.json();
      if (!response.ok || !payload.ok) throw new Error(payload.error || 'Could not load jobs.');
      return payload.jobs || [];
    })
    .then(jobs => {
      const bounds = [];
      for (const job of jobs) {
        if (!Number.isFinite(job.latitude) || !Number.isFinite(job.longitude)) continue;
        L.marker([job.latitude, job.longitude]).addTo(map).bindPopup(popup(job));
        bounds.push([job.latitude, job.longitude]);
      }
      status.textContent = bounds.length + (bounds.length === 1 ? ' job mapped' : ' jobs mapped');
      if (bounds.length === 1) map.setView(bounds[0], 15);
      else if (bounds.length > 1) map.fitBounds(bounds, {padding: [24, 24], maxZoom: 15});
      else {
        error.textContent = 'No mapped jobs matched the current status rules.';
        error.hidden = false;
      }
    })
    .catch(exc => {
      status.textContent = 'Map unavailable';
      error.textContent = String(exc.message || exc);
      error.hidden = false;
    });
})();
