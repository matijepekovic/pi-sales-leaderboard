const root = document.getElementById('sfExplorer');
const el = id => document.getElementById(id);
const operators = {
  eq: 'Equals', ne: 'Does not equal', contains: 'Contains', starts_with: 'Starts with',
  gt: 'After / greater than', gte: 'On or after / at least', lt: 'Before / less than',
  lte: 'On or before / at most', between: 'Between', is_empty: 'Is empty',
  not_empty: 'Is not empty', includes: 'Includes', excludes: 'Excludes',
};
const numberTypes = new Set(['int', 'double', 'currency', 'percent', 'long']);
const emptyOperators = new Set(['is_empty', 'not_empty']);
const requests = new Map();
let catalog = [];
let view = null;
let history = [];
let generation = 0;
let filterSequence = 0;

function node(tag, text, className) {
  const result = document.createElement(tag);
  if (text !== undefined) result.textContent = text;
  if (className) result.className = className;
  return result;
}
function button(text, action, className) {
  const result = node('button', text, className);
  result.type = 'button';
  result.addEventListener('click', action);
  return result;
}
function message(text = '', error = false) {
  el('sfMessage').textContent = text;
  el('sfMessage').classList.toggle('error', error);
  el('sfMessage').hidden = !text;
}
function raw(value) {
  if (value === null || value === undefined) return '';
  return typeof value === 'object' ? JSON.stringify(value, null, 2) : String(value);
}
function isEmpty(value) { return value === null || value === undefined || value === ''; }
function label(field) { return field.label || field.name; }
function fieldList(model) { return model.metadata?.fields || []; }
function fieldFor(model, name) { return fieldList(model).find(field => field.name === name); }
function objectPath(name) { return '/objects/' + encodeURIComponent(name); }
function recordPath(name, id) { return objectPath(name) + '/records/' + encodeURIComponent(id); }
function isCurrent(model, version) { return view === model && generation === version; }
function abortRequest(key) {
  requests.get(key)?.abort();
  requests.delete(key);
}
function leaveView() {
  for (const key of requests.keys()) if (key !== 'catalog') abortRequest(key);
  if (view) {
    view.loading = false;
    view.searchBusy = false;
    for (const related of Object.values(view.related || {})) related.loading = false;
  }
  generation += 1;
}
async function request(path, key, options = {}) {
  abortRequest(key);
  const controller = new AbortController();
  requests.set(key, controller);
  try {
    const response = await fetch(root.dataset.api + path, {
      credentials: 'same-origin', ...options, signal: controller.signal,
      headers: {Accept: 'application/json', ...options.headers},
    });
    if (response.status === 413) throw new Error('Search filters are too large. Shorten the filter values.');
    if (response.redirected || response.status === 401 || response.status === 403) {
      throw new Error('Sign in to Print Control again, then reload Object Explorer.');
    }
    if (!response.headers.get('content-type')?.includes('application/json')) {
      throw new Error('Could not load Salesforce data. Try again.');
    }
    const data = await response.json();
    if (!response.ok || !data.ok) throw new Error(data.message || data.error || 'Could not load Salesforce data. Try again.');
    return data;
  } finally {
    if (requests.get(key) === controller) requests.delete(key);
  }
}
function showError(error) { if (error.name !== 'AbortError') message(error.message || 'Could not load Salesforce data. Try again.', true); }

function renderCatalog() {
  const term = el('sfObjectSearch').value.trim().toLowerCase();
  const objects = catalog.filter(item => (item.label + ' ' + item.name).toLowerCase().includes(term));
  const fragment = document.createDocumentFragment();
  for (const item of objects) {
    const entry = button('', () => openObject(item.name));
    entry.dataset.object = item.name;
    entry.setAttribute('aria-current', String(view?.name === item.name));
    const title = node('strong', label(item));
    if (item.custom) title.append(node('span', 'Custom', 'sf-custom'));
    entry.append(title, node('small', item.name));
    fragment.append(entry);
  }
  if (!objects.length) fragment.append(node('p', catalog.length ? 'No objects match that name.' : 'No objects available.', 'muted'));
  el('sfObjects').replaceChildren(fragment);
  el('sfObjectCount').textContent = objects.length + (term ? ' matching objects' : ' objects');
}
async function loadCatalog() {
  el('sfReloadObjects').disabled = true;
  el('sfObjectCount').textContent = 'Loading object names…';
  message();
  try {
    const data = await request('/objects', 'catalog');
    catalog = data.objects || [];
    renderCatalog();
  } catch (error) {
    showError(error);
    el('sfObjectCount').textContent = 'Use Reload to try again.';
  } finally { el('sfReloadObjects').disabled = false; }
}
function viewLabel(model) {
  if (model.kind === 'record') return model.record?.Name || model.id;
  return model.metadata?.object?.label || catalog.find(item => item.name === model.name)?.label || model.name;
}
function renderNavigation() {
  el('sfNavigation').hidden = !view;
  const fragment = document.createDocumentFragment();
  fragment.append(button('Objects', () => navigateBack(-1)));
  history.forEach((previous, index) => {
    fragment.append(node('span', '›'), button(viewLabel(previous), () => navigateBack(index)));
  });
  if (view) fragment.append(node('span', '›'), node('span', viewLabel(view)));
  el('sfBreadcrumbs').replaceChildren(fragment);
}
function renderView() {
  renderCatalog();
  renderNavigation();
  el('sfWelcome').hidden = Boolean(view);
  el('sfObjectView').hidden = view?.kind !== 'object';
  el('sfRecordView').hidden = view?.kind !== 'record';
  el('sfResultsSection').hidden = view?.kind !== 'object' || !view.search;
  if (view?.kind === 'object') renderObject(view);
  if (view?.kind === 'record') renderRecord(view);
}
function navigateBack(index = history.length - 1) {
  leaveView();
  view = index < 0 ? null : history[index];
  history = index < 0 ? [] : history.slice(0, index);
  message();
  renderView();
}
function pushView(next) {
  leaveView();
  if (view) history.push(view);
  view = next;
  message();
  renderView();
}
async function openObject(name) {
  const model = {kind: 'object', name, metadata: null, loading: true, columns: [], filters: [], match: 'all', fieldSearch: '', search: null, searchBusy: false};
  pushView(model);
  await loadObject(model);
}
async function loadObject(model) {
  const version = generation;
  model.loading = true;
  renderObject(model);
  message();
  try {
    const data = await request(objectPath(model.name), 'metadata');
    if (!isCurrent(model, version)) return;
    model.metadata = data;
    const available = new Set(data.fields.map(field => field.name));
    model.columns = [...new Set([...(available.has('Id') ? ['Id'] : []), ...(data.default_columns || [])])]
      .filter(name => available.has(name)).slice(0, 20);
  } catch (error) { if (isCurrent(model, version)) showError(error); }
  finally {
    model.loading = false;
    if (isCurrent(model, version)) { renderObject(model); renderNavigation(); }
  }
}
function invalidateSearch(model) {
  abortRequest('search');
  model.searchVersion = (model.searchVersion || 0) + 1;
  model.searchBusy = false;
  model.search = null;
  renderResults(model);
  renderSearchActions(model);
}
function renderObject(model) {
  el('sfObjectTitle').textContent = model.metadata?.object?.label || catalog.find(item => item.name === model.name)?.label || model.name;
  el('sfObjectApiName').textContent = model.name;
  el('sfObjectLoading').hidden = !model.loading;
  el('sfRetryObject').hidden = model.loading || Boolean(model.metadata);
  el('sfSearchForm').hidden = !model.metadata;
  el('sfFieldSearch').value = model.fieldSearch;
  el('sfMatch').value = model.match;
  if (model.metadata) { renderColumns(model); renderFilters(model); }
  renderSearchActions(model);
  renderResults(model);
}
function renderColumns(model) {
  const term = model.fieldSearch.trim().toLowerCase();
  const fragment = document.createDocumentFragment();
  const fields = fieldList(model).filter(field => (label(field) + ' ' + field.name).toLowerCase().includes(term));
  for (const field of fields) {
    const entry = node('label');
    const check = node('input');
    check.type = 'checkbox';
    check.value = field.name;
    check.checked = model.columns.includes(field.name);
    check.disabled = field.name === 'Id' || (!check.checked && model.columns.length >= 20);
    if (field.name === 'Id') check.title = 'Record ID is included so records can be opened.';
    check.addEventListener('change', () => {
      if (check.checked && model.columns.length < 20) model.columns.push(field.name);
      if (!check.checked) model.columns = model.columns.filter(name => name !== field.name);
      invalidateSearch(model);
      renderColumns(model);
    });
    const description = node('span', label(field));
    description.append(node('small', field.name + ' · ' + field.type));
    entry.append(check, description);
    fragment.append(entry);
  }
  if (!fields.length) fragment.append(node('p', 'No fields match that name.', 'muted'));
  el('sfColumns').replaceChildren(fragment);
  el('sfColumnCount').textContent = model.columns.length + ' selected';
}
function selectControl(name, choices, value) {
  const select = node('select');
  select.name = name;
  for (const choice of choices) {
    const option = node('option', choice.label);
    option.value = choice.value;
    select.append(option);
  }
  select.value = value;
  return select;
}
function labeledControl(text, input) { const container = node('label', text); container.append(input); return container; }
function filterValueControl(field, filter, key) {
  let input;
  const type = field.type;
  if (type === 'boolean') {
    input = selectControl(key, [{value: '', label: 'Choose…'}, {value: 'true', label: 'True'}, {value: 'false', label: 'False'}], String(filter[key] ?? ''));
  } else if (['picklist', 'multipicklist'].includes(type) && ['eq', 'ne', 'includes', 'excludes'].includes(filter.operator)) {
    input = selectControl(key, [{value: '', label: 'Choose…'}, ...(field.picklist_values || []).map(item => ({label: item.label || item.value, value: item.value}))], filter[key] || '');
  } else {
    input = node('input');
    input.name = key;
    input.type = type === 'date' ? 'date' : type === 'datetime' ? 'datetime-local' : numberTypes.has(type) ? 'number' : type === 'time' ? 'time' : 'text';
    if (numberTypes.has(type)) input.step = 'any';
    if (type === 'datetime' || type === 'time') input.step = '1';
    input.value = filter[key] ?? '';
  }
  input.required = true;
  input.addEventListener('input', () => { filter[key] = input.value; invalidateSearch(view); });
  input.addEventListener('change', () => { filter[key] = input.value; invalidateSearch(view); });
  return input;
}
function renderFilters(model) {
  const available = fieldList(model).filter(field => field.filterable && field.operators?.length);
  const fragment = document.createDocumentFragment();
  for (const filter of model.filters) {
    const row = node('div', undefined, 'sf-filter-row');
    row.dataset.filter = filter.id;
    const field = fieldFor(model, filter.field);
    const fieldSelect = selectControl('field', available.map(item => ({value: item.name, label: label(item) + ' · ' + item.name})), filter.field);
    fieldSelect.addEventListener('change', () => {
      filter.field = fieldSelect.value;
      filter.operator = fieldFor(model, filter.field).operators[0];
      filter.value = ''; filter.value2 = '';
      invalidateSearch(model); renderFilters(model);
    });
    const operatorSelect = selectControl('operator', field.operators.map(operator => ({value: operator, label: operators[operator] || operator})), filter.operator);
    operatorSelect.addEventListener('change', () => {
      filter.operator = operatorSelect.value;
      filter.value = ''; filter.value2 = '';
      invalidateSearch(model); renderFilters(model);
    });
    row.append(labeledControl('Field', fieldSelect), labeledControl('Condition', operatorSelect));
    const values = node('div', undefined, 'sf-filter-value');
    if (!emptyOperators.has(filter.operator)) {
      values.append(labeledControl(filter.operator === 'between' ? 'From' : 'Value', filterValueControl(field, filter, 'value')));
      if (filter.operator === 'between') values.append(labeledControl('To', filterValueControl(field, filter, 'value2')));
      if (field.type === 'datetime') values.append(node('span', 'Your local time (' + (Intl.DateTimeFormat().resolvedOptions().timeZone || 'device time zone') + ')', 'sf-date-zone'));
    }
    row.append(values);
    const remove = button('×', () => { model.filters = model.filters.filter(item => item !== filter); invalidateSearch(model); renderFilters(model); }, 'sf-remove');
    remove.setAttribute('aria-label', 'Remove filter');
    row.append(remove);
    fragment.append(row);
  }
  if (!model.filters.length) fragment.append(node('p', 'No filters. A search will show the first 50 records.', 'muted'));
  el('sfFilters').replaceChildren(fragment);
  el('sfAddFilter').disabled = model.filters.length >= 10 || !available.length;
}
function renderSearchActions(model) {
  const queryable = model.metadata?.object?.queryable !== false;
  el('sfRunSearch').disabled = !model.metadata || model.searchBusy || !model.columns.length || !queryable;
  el('sfRunSearch').textContent = model.searchBusy ? 'Loading…' : 'Run search';
  el('sfSearchHint').textContent = !queryable ? 'Salesforce does not allow record searches on this object.' : model.search ? 'Change columns or filters to start a new search.' : 'Records have not been loaded. Add filters, then run a search.';
}
function queryFor(model) {
  return {
    columns: [...model.columns], match: model.match,
    filters: model.filters.map(filter => {
      const field = fieldFor(model, filter.field);
      const value = key => {
        if (field.type === 'boolean') return filter[key] === 'true';
        if (field.type === 'datetime') return new Date(filter[key]).toISOString();
        return filter[key];
      };
      return {
        field: filter.field, operator: filter.operator,
        ...(!emptyOperators.has(filter.operator) ? {value: value('value')} : {}),
        ...(filter.operator === 'between' ? {value2: value('value2')} : {}),
      };
    }),
  };
}
async function runSearch(more = false) {
  const model = view;
  if (model?.kind !== 'object' || !model.metadata || model.searchBusy) return;
  if (!more && !el('sfSearchForm').reportValidity()) return;
  let query;
  try { query = more ? model.search.query : queryFor(model); }
  catch (_) { message('Enter a valid date and time for each filter.', true); return; }
  const version = generation;
  const searchVersion = model.searchVersion = (model.searchVersion || 0) + 1;
  const previous = more ? model.search : null;
  const form = new FormData();
  form.set('csrf', root.dataset.csrf);
  form.set('columns', JSON.stringify(query.columns));
  form.set('filters', JSON.stringify(query.filters));
  form.set('match', query.match);
  if (more) form.set('after', previous.next_after);
  model.searchBusy = true;
  if (!more) model.search = null;
  message(); renderSearchActions(model); renderResults(model);
  try {
    const data = await request(objectPath(model.name) + '/search', 'search', {method: 'POST', body: form});
    if (!isCurrent(model, version) || model.searchVersion !== searchVersion) return;
    model.search = {...data, query, records: [...(previous?.records || []), ...(data.records || [])]};
  } catch (error) { if (isCurrent(model, version) && model.searchVersion === searchVersion) showError(error); }
  finally {
    if (model.searchVersion === searchVersion) model.searchBusy = false;
    if (isCurrent(model, version)) { renderResults(model); renderSearchActions(model); }
  }
}
function resultTable(data, objectName) {
  if (!data.records?.length) return node('p', 'No matching records.', 'sf-result-empty');
  const table = node('table');
  const head = node('thead');
  const heading = node('tr');
  heading.append(node('th', 'Record'));
  for (const field of data.columns || []) {
    const th = node('th', label(field)); th.append(node('small', field.name)); heading.append(th);
  }
  head.append(heading);
  const body = node('tbody');
  for (const record of data.records) {
    const row = node('tr');
    const openCell = node('td');
    if (record.Id) {
      const open = button('Open', () => openRecord(objectName, record.Id));
      open.dataset.record = record.Id; open.dataset.object = objectName;
      open.setAttribute('aria-label', 'Open record ' + record.Id); openCell.append(open);
    }
    row.append(openCell);
    for (const field of data.columns || []) row.append(node('td', isEmpty(record[field.name]) ? '—' : raw(record[field.name]), isEmpty(record[field.name]) ? 'sf-empty' : ''));
    body.append(row);
  }
  table.append(head, body);
  return table;
}
function renderResults(model) {
  el('sfResultsSection').hidden = !model.search;
  if (!model.search) { el('sfResults').replaceChildren(); return; }
  el('sfResults').replaceChildren(resultTable(model.search, model.name));
  el('sfResultCount').textContent = model.search.records.length + ' records loaded';
  el('sfMore').hidden = !model.search.next_after;
  el('sfMore').disabled = model.searchBusy;
  el('sfMore').textContent = model.searchBusy ? 'Loading…' : 'Load more';
}
async function openRecord(name, id) {
  const model = {kind: 'record', name, id, record: null, fields: [], relationships: [], related: {}, loading: true, fieldSearch: '', hideEmpty: false, copyText: ''};
  pushView(model);
  await loadRecord(model);
}
async function loadRecord(model) {
  const version = generation;
  model.loading = true; renderRecord(model); message();
  try {
    const data = await request(recordPath(model.name, model.id), 'record');
    if (!isCurrent(model, version)) return;
    model.record = data.record;
    model.fields = data.fields || [];
    model.object = data.object;
    model.relationships = data.relationships || [];
  } catch (error) { if (isCurrent(model, version)) showError(error); }
  finally {
    model.loading = false;
    if (isCurrent(model, version)) { renderRecord(model); renderNavigation(); }
  }
}
function visibleRecordFields(model) {
  const term = model.fieldSearch.trim().toLowerCase();
  return model.fields.filter(field => (!model.hideEmpty || !isEmpty(model.record[field.name])) &&
    (label(field) + ' ' + field.name + ' ' + raw(model.record[field.name])).toLowerCase().includes(term));
}
function referenceControl(field, value) {
  const targets = field.reference_to || [];
  if (!targets.length || typeof value !== 'string' || !/^[a-zA-Z0-9]{15}(?:[a-zA-Z0-9]{3})?$/.test(value)) return null;
  const container = node('div', undefined, 'sf-reference');
  let objectName = targets[0];
  const open = button('Open ' + (targets.length === 1 ? objectName : 'linked record'), () => openRecord(objectName, value));
  open.dataset.referenceObject = objectName; open.dataset.referenceId = value;
  if (targets.length > 1) {
    const choose = selectControl('reference_object', targets.map(name => ({value: name, label: name})), objectName);
    choose.setAttribute('aria-label', 'Linked object for ' + label(field));
    choose.addEventListener('change', () => { objectName = choose.value; open.dataset.referenceObject = objectName; });
    container.append(choose);
  }
  container.append(open);
  return container;
}
function renderRecordFields(model) {
  if (!model.record) { el('sfRecordFields').replaceChildren(); return; }
  const table = node('table');
  const head = node('thead'); const heading = node('tr');
  heading.append(node('th', 'Field'), node('th', 'Value')); head.append(heading);
  const body = node('tbody');
  const fields = visibleRecordFields(model);
  for (const field of fields) {
    const row = node('tr'); row.dataset.field = field.name;
    const nameCell = node('td', undefined, 'sf-field-name');
    nameCell.append(node('strong', label(field)), node('small', field.name + ' · ' + field.type));
    const value = model.record[field.name];
    const valueCell = node('td');
    valueCell.append(node('div', isEmpty(value) ? '—' : raw(value), isEmpty(value) ? 'sf-empty' : 'sf-record-value'));
    const reference = referenceControl(field, value);
    if (reference) valueCell.append(reference);
    row.append(nameCell, valueCell); body.append(row);
  }
  table.append(head, body);
  el('sfRecordFields').replaceChildren(fields.length ? table : node('p', 'No fields match this view.', 'muted'));
}
function renderRecord(model) {
  el('sfRecordTitle').textContent = viewLabel(model);
  el('sfRecordIdentity').textContent = model.name + ' · ' + model.id;
  el('sfRecordLoading').hidden = !model.loading;
  el('sfRetryRecord').hidden = model.loading || Boolean(model.record);
  el('sfRecordTools').hidden = !model.record;
  el('sfCopy').disabled = !model.record;
  el('sfRecordFieldSearch').value = model.fieldSearch;
  el('sfHideEmpty').checked = model.hideEmpty;
  el('sfCopyFallback').hidden = !model.copyText;
  el('sfCopyText').value = model.copyText;
  renderRecordFields(model);
  renderRelationships(model);
}
function renderRelationships(model) {
  el('sfRelatedSection').hidden = !model.record;
  const fragment = document.createDocumentFragment();
  for (const relationship of model.relationships) {
    const state = model.related[relationship.name];
    const wrapper = node('div', undefined, 'sf-relationship');
    wrapper.dataset.relationshipPanel = relationship.name;
    const toggle = button('', () => toggleRelationship(model, relationship));
    toggle.dataset.relationship = relationship.name;
    toggle.setAttribute('aria-expanded', String(Boolean(state?.expanded)));
    const title = node('span', relationship.label || relationship.name);
    title.append(node('small', relationship.name + ' · ' + relationship.object));
    toggle.append(title, node('span', state?.expanded ? '−' : '+'));
    wrapper.append(toggle);
    if (state?.expanded) {
      const content = node('div', undefined, 'sf-relationship-content');
      if (state.data) {
        content.append(node('p', state.data.records.length + ' records loaded', 'sf-related-count'));
        const table = node('div', undefined, 'table-wrap');
        table.append(resultTable(state.data, relationship.object)); content.append(table);
      }
      if (state.loading) content.append(node('p', 'Loading related records…', 'muted'));
      if (state.error) {
        content.append(node('p', state.error, 'error'), button('Try again', () => loadRelationship(model, relationship, Boolean(state.data))));
      } else if (state.data?.next_after) {
        const more = button('Load more', () => loadRelationship(model, relationship, true), 'sf-related-more');
        more.dataset.relatedMore = relationship.name; more.disabled = state.loading; content.append(more);
      } else if (!state.loading && !state.data) {
        content.append(button('Load related records', () => loadRelationship(model, relationship)));
      }
      wrapper.append(content);
    }
    fragment.append(wrapper);
  }
  if (model.record && !model.relationships.length) fragment.append(node('p', 'No browsable relationships are available for this object.', 'muted'));
  el('sfRelated').replaceChildren(fragment);
}
async function toggleRelationship(model, relationship) {
  const state = model.related[relationship.name] ||= {expanded: false, loading: false, data: null, error: ''};
  state.expanded = !state.expanded;
  renderRelationships(model);
  if (state.expanded && !state.data && !state.loading) await loadRelationship(model, relationship);
}
async function loadRelationship(model, relationship, more = false) {
  const state = model.related[relationship.name];
  if (state.loading) return;
  const version = generation;
  const previous = more ? state.data : null;
  const suffix = more && previous.next_after ? '?after=' + encodeURIComponent(previous.next_after) : '';
  state.loading = true; state.error = '';
  renderRelationships(model);
  try {
    const data = await request(recordPath(model.name, model.id) + '/related/' + encodeURIComponent(relationship.name) + suffix, 'related:' + relationship.name);
    if (!isCurrent(model, version)) return;
    state.data = {...data, records: [...(previous?.records || []), ...(data.records || [])]};
  } catch (error) {
    if (error.name !== 'AbortError' && isCurrent(model, version)) state.error = error.message;
  } finally {
    state.loading = false;
    if (isCurrent(model, version)) renderRelationships(model);
  }
}
async function copyDetails() {
  const model = view;
  if (model?.kind !== 'record' || !model.record) return;
  const text = ['Salesforce object: ' + model.name, 'Record ID: ' + model.id, '', ...visibleRecordFields(model).map(field => label(field) + ' [' + field.name + ']: ' + (isEmpty(model.record[field.name]) ? '(empty)' : raw(model.record[field.name])))].join('\n');
  try {
    if (!navigator.clipboard?.writeText) throw new Error('Clipboard unavailable');
    await navigator.clipboard.writeText(text);
    if (view === model) message('Details copied.');
  } catch (_) {
    if (view !== model) return;
    model.copyText = text;
    el('sfCopyFallback').hidden = false;
    el('sfCopyText').value = text;
    el('sfCopyText').focus(); el('sfCopyText').select();
    message('Select and copy the details below.');
  }
}

el('sfObjectSearch').addEventListener('input', renderCatalog);
el('sfReloadObjects').addEventListener('click', loadCatalog);
el('sfBack').addEventListener('click', () => navigateBack());
el('sfRetryObject').addEventListener('click', () => loadObject(view));
el('sfRetryRecord').addEventListener('click', () => loadRecord(view));
el('sfFieldSearch').addEventListener('input', event => {
  if (view?.kind !== 'object') return;
  view.fieldSearch = event.target.value; renderColumns(view);
});
el('sfAddFilter').addEventListener('click', () => {
  if (view?.kind !== 'object' || view.filters.length >= 10) return;
  const first = fieldList(view).find(field => field.filterable && field.operators?.length);
  if (!first) return;
  view.filters.push({id: String(++filterSequence), field: first.name, operator: first.operators[0], value: '', value2: ''});
  invalidateSearch(view); renderFilters(view);
});
el('sfMatch').addEventListener('change', event => { if (view?.kind === 'object') { view.match = event.target.value; invalidateSearch(view); } });
el('sfSearchForm').addEventListener('submit', event => { event.preventDefault(); runSearch(); });
el('sfMore').addEventListener('click', () => runSearch(true));
el('sfRecordFieldSearch').addEventListener('input', event => {
  if (view?.kind !== 'record') return;
  view.fieldSearch = event.target.value; view.copyText = ''; el('sfCopyFallback').hidden = true; renderRecordFields(view);
});
el('sfHideEmpty').addEventListener('change', event => {
  if (view?.kind !== 'record') return;
  view.hideEmpty = event.target.checked; view.copyText = ''; el('sfCopyFallback').hidden = true; renderRecordFields(view);
});
el('sfCopy').addEventListener('click', copyDetails);
loadCatalog();
