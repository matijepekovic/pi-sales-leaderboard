// Report-notes Settings controller. No knowledge of folders, queues or source vendors.
// The host supplies current print options and receives validated notes settings.
export function createNotesEditor({dialog, previewUrl, csrf, effectiveOptions}) {
  let activeId = null;
  const notesEnabled = document.getElementById('notes-enabled');
  const notesFields = document.getElementById('notes-fields');
  const notesStatus = document.getElementById('notes-status');
  const notesLink = document.getElementById('notes-preview-link');
  const notesControls = {
    font_size: document.getElementById('notes-font-size'),
    row_spacing_mm: document.getElementById('notes-row-spacing'),
    table_gap_mm: document.getElementById('notes-table-gap'),
  };
  let notesOriginal = {};
  let notesSelected = [];
  let notesAvailable = [];
  let notesCatalogLoaded = false;
  let notesRequest = 0;
  let notesAbort = null;
  let notesBlobUrl = null;
  const columnKey = value => value.normalize('NFKC').replace(/[↑↓]/g, '').replace(/\s+/g, ' ').trim().toLowerCase();
  function cancelNotesRequest() {
    ++notesRequest;
    if (notesAbort) notesAbort.abort();
    document.getElementById('notes-load-columns').disabled = false;
    document.getElementById('notes-preview').disabled = false;
  }
  function invalidateNotesPreview() {
    cancelNotesRequest();
    notesLink.hidden = true;
    notesStatus.textContent = '';
  }
  function open(reportId, settings) {
    activeId = reportId;
    invalidateNotesPreview();
    notesOriginal = {enabled: false, columns: [], font_size: 12, row_spacing_mm: 8, table_gap_mm: 5,
      ...settings};
    notesSelected = [...notesOriginal.columns];
    notesAvailable = [...notesSelected];
    notesCatalogLoaded = false;
    notesEnabled.checked = notesOriginal.enabled;
    notesFields.disabled = !notesEnabled.checked;
    for (const [key, control] of Object.entries(notesControls)) control.value = notesOriginal[key];
    drawNotesColumns();
  }
  function drawNotesColumns() {
    const list = document.getElementById('notes-columns');
    list.replaceChildren();
    const order = [...notesSelected, ...notesAvailable.filter(name => !notesSelected.some(v => columnKey(v) === columnKey(name)))];
    for (const name of order) {
      const row = document.createElement('div'); row.className = 'notes-column';
      const index = notesSelected.findIndex(value => columnKey(value) === columnKey(name));
      const label = document.createElement('label');
      const checkbox = document.createElement('input'); checkbox.type = 'checkbox'; checkbox.checked = index >= 0;
      label.append(checkbox, document.createTextNode(' ' + name));
      checkbox.onchange = () => {
        if (checkbox.checked) notesSelected.push(name);
        else notesSelected = notesSelected.filter(value => columnKey(value) !== columnKey(name));
        invalidateNotesPreview(); drawNotesColumns();
      };
      row.append(label);
      if (index >= 0) {
        for (const [delta, arrow, direction] of [[-1, '↑', 'up'], [1, '↓', 'down']]) {
          const move = document.createElement('button'); move.type = 'button'; move.textContent = arrow;
          move.setAttribute('aria-label', 'Move ' + name + ' ' + direction);
          move.disabled = index + delta < 0 || index + delta >= notesSelected.length;
          move.onclick = () => {
            [notesSelected[index], notesSelected[index + delta]] = [notesSelected[index + delta], notesSelected[index]];
            invalidateNotesPreview(); drawNotesColumns();
          };
          row.append(move);
        }
      }
      if (notesCatalogLoaded && !notesAvailable.some(value => columnKey(value) === columnKey(name))) {
        const warning = document.createElement('small'); warning.textContent = ' Missing from current report'; row.append(warning);
      }
      list.append(row);
    }
  }
  function readNotesEditor() {
    if (!notesEnabled.checked) return {...notesOriginal, enabled: false, columns: [...notesSelected]};
    if (Object.values(notesControls).some(field => !field.reportValidity())) return null;
    if (!notesSelected.length) {
      notesStatus.textContent = 'Load the report columns and select at least one field.'; return null;
    }
    if (notesCatalogLoaded && notesSelected.some(name => !notesAvailable.some(value => columnKey(value) === columnKey(name)))) {
      notesStatus.textContent = 'A selected column is missing. Choose the replacement before saving.'; return null;
    }
    return {enabled: true, columns: [...notesSelected],
      ...Object.fromEntries(Object.entries(notesControls).map(([key, input]) => [key, Number(input.value)]))};
  }
  async function requestNotesPreview(kind) {
    const notes = kind === 'columns' ? {} : readNotesEditor();
    if (!notes) return;
    invalidateNotesPreview();
    const requestId = notesRequest;
    const reportId = activeId;
    notesAbort = new AbortController();
    document.getElementById('notes-load-columns').disabled = true;
    document.getElementById('notes-preview').disabled = true;
    notesStatus.textContent = kind === 'columns' ? 'Loading the report columns…' : 'Building PDF preview…';
    try {
      const response = await fetch(previewUrl, {
        method: 'POST', signal: notesAbort.signal,
        body: new URLSearchParams({csrf: csrf(),
          report_id: reportId, kind, options: JSON.stringify(effectiveOptions()), notes: JSON.stringify(notes)}),
      });
      if (!response.ok) {
        const data = await response.json().catch(() => ({}));
        throw Error(data.error || 'Preview failed. Reload the page and check your session.');
      }
      if (kind === 'columns') {
        const data = await response.json();
        if (requestId !== notesRequest || reportId !== activeId) return;
        notesAvailable = data.columns; notesCatalogLoaded = true; drawNotesColumns();
        notesStatus.textContent = notesAvailable.length + ' columns loaded. Select the fields to repeat.';
      } else {
        if (!(response.headers.get('Content-Type') || '').includes('application/pdf')) throw Error('Reload the page and check your session.');
        const blob = await response.blob();
        if (requestId !== notesRequest || reportId !== activeId) return;
        if (notesBlobUrl) URL.revokeObjectURL(notesBlobUrl);
        notesBlobUrl = URL.createObjectURL(blob);
        notesLink.href = notesBlobUrl; notesLink.hidden = false;
        const scale = Number(response.headers.get('X-Notes-Scale') || 1);
        const rows = Number(response.headers.get('X-Notes-Rows') || 0);
        notesStatus.textContent = notes.enabled ? rows + ' job rows. ' +
          (scale < .999 ? 'Smallest page scale: ' + (scale * 100).toFixed(1) + '% to fit.' : 'Your requested size and spacing fit without shrinking.') : 'Original report preview ready.';
        if (notes.enabled && notes.font_size * scale < 6) notesStatus.textContent += ' Text is very small: reduce spacing or columns, or choose larger paper.';
      }
    } catch (error) {
      if (requestId === notesRequest && error.name !== 'AbortError') notesStatus.textContent = error.message;
    } finally {
      if (requestId === notesRequest) {
        document.getElementById('notes-load-columns').disabled = false;
        document.getElementById('notes-preview').disabled = false;
      }
    }
  }
  notesEnabled.onchange = () => { notesFields.disabled = !notesEnabled.checked; invalidateNotesPreview(); };
  for (const control of Object.values(notesControls)) control.addEventListener('input', invalidateNotesPreview);
  document.getElementById('override-fields').addEventListener('input', invalidateNotesPreview);
  document.getElementById('notes-load-columns').onclick = () => requestNotesPreview('columns');
  document.getElementById('notes-preview').onclick = () => requestNotesPreview('pdf');
  dialog.addEventListener('close', cancelNotesRequest);
  window.addEventListener('pagehide', () => { cancelNotesRequest(); if (notesBlobUrl) URL.revokeObjectURL(notesBlobUrl); });
  return {open, read: readNotesEditor};
}
