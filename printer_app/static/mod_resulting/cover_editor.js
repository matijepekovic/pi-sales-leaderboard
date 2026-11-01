(() => {
  'use strict';
  const root = document.body;
  const editor = document.getElementById('coverEditor');
  const status = document.getElementById('coverStatus');
  const download = document.getElementById('downloadCover');
  const confirmButton = document.getElementById('confirmCover');
  const bottomConfirm = document.getElementById('bottomConfirm');
  const edits = JSON.parse(root.dataset.edits || '{}');
  edits.rows = edits.rows || {};
  edits.summary = edits.summary || {};
  edits.grand = edits.grand || {};
  edits.totals = edits.totals || {};
  edits.manual_rows = edits.manual_rows || [];
  edits.hidden = edits.hidden || [];
  let dirty = false;
  let watching = null;

  function setModified() {
    dirty = true;
    download.hidden = true;
    status.textContent = 'Unsaved cover changes. Press Confirm to update the PDF.';
  }
  function manualRow(id) {
    return edits.manual_rows.find(row => row.id === id);
  }
  editor.addEventListener('input', event => {
    const node = event.target;
    if (!(node instanceof HTMLInputElement)) return;
    const {row, field, summary, grand, total} = node.dataset;
    if (row && field) {
      if (row.startsWith('manual:')) {
        const entry = manualRow(row);
        if (entry) entry[field] = node.value;
      } else {
        edits.rows[row] = edits.rows[row] || {};
        edits.rows[row][field] = node.value;
      }
    } else if (summary && field) {
      edits.summary[summary] = edits.summary[summary] || {};
      edits.summary[summary][field] = node.value;
    } else if (grand) {
      edits.grand[grand] = node.value;
    } else if (total) {
      edits.totals[total] = node.value;
    } else return;
    setModified();
  });

  editor.addEventListener('click', event => {
    const button = event.target.closest('button');
    if (!button) return;
    if (button.matches('.remove-row')) {
      const tr = button.closest('tr[data-row-id]');
      if (!tr) return;
      const id = tr.dataset.rowId;
      if (id.startsWith('manual:')) {
        edits.manual_rows = edits.manual_rows.filter(row => row.id !== id);
      } else if (!edits.hidden.includes(id)) {
        edits.hidden.push(id);
      }
      tr.remove();
      setModified();
    } else if (button.matches('.add-row')) {
      const section = button.closest('.division');
      const division = button.dataset.division;
      const tbody = section.querySelector('tbody');
      const headings = [...section.querySelectorAll('thead th[data-field]')];
      const id = 'manual:' + Date.now().toString(36) +
                 Math.random().toString(36).slice(2, 12);
      const row = {id, division};
      const tr = document.createElement('tr');
      tr.dataset.rowId = id;
      for (const heading of headings) {
        const field = heading.dataset.field;
        row[field] = '';
        const td = document.createElement('td');
        const input = document.createElement('input');
        input.dataset.row = id;
        input.dataset.field = field;
        input.maxLength = 160;
        input.setAttribute('aria-label', heading.textContent + ' for new cover row');
        td.appendChild(input);
        tr.appendChild(td);
      }
      const cell = document.createElement('td');
      const remove = document.createElement('button');
      remove.type = 'button';
      remove.className = 'remove-row';
      remove.textContent = 'Remove';
      remove.setAttribute('aria-label', 'Remove cover row');
      cell.appendChild(remove);
      tr.appendChild(cell);
      tbody.appendChild(tr);
      edits.manual_rows.push(row);
      setModified();
      tr.querySelector('input').focus();
    }
  });

  async function confirm() {
    for (const button of [confirmButton, bottomConfirm]) button.disabled = true;
    try {
      const fields = new URLSearchParams({
        csrf: root.dataset.csrf,
        job_id: root.dataset.jobId,
        revision: root.dataset.revision,
        edits: JSON.stringify(edits)
      });
      const response = await fetch(root.dataset.confirm, {
        method:'POST', body:fields, headers:{Accept:'application/json'}
      });
      const result = await response.json();
      if (!response.ok || !result.ok) {
        throw new Error(result.error || 'Could not confirm cover.');
      }
      root.dataset.revision = String(result.revision);
      dirty = false;
      status.textContent = 'Cover confirmed. The Redlines PDF is being finalized.';
      poll();
    } catch (error) {
      status.textContent = error.message;
    } finally {
      for (const button of [confirmButton, bottomConfirm]) button.disabled = false;
    }
  }

  async function poll() {
    clearTimeout(watching);
    try {
      const response = await fetch(root.dataset.status, {cache:'no-store'});
      const state = await response.json();
      if (!response.ok || !state.ok) throw new Error(state.error || 'Status unavailable.');
      if (state.state === 'failed') {
        status.textContent = state.error || 'PDF generation failed.';
        download.hidden = true;
        return;
      }
      if (state.ready && !dirty) {
        download.href = state.download_url;
        download.hidden = false;
        status.textContent = 'Redlines PDF ready: cover first, then all MOD sheets.';
        return;
      }
      if (!dirty) {
        const descriptions = {
          queued:'Queued for background PDF generation.',
          rendering:'Generating cover and MOD sheets.',
          awaiting_confirmation:'MOD PDFs generated. Press Confirm to finalize the cover.',
          pending_finalize:'Finalizing edited cover and Redlines PDF.',
          finalizing:'Combining cover and MOD sheets.'
        };
        status.textContent = descriptions[state.state] || 'Preparing PDF.';
      }
    } catch (error) {
      if (!dirty) status.textContent = error.message;
    }
    watching = setTimeout(poll, 1800);
  }
  confirmButton.addEventListener('click', confirm);
  bottomConfirm.addEventListener('click', confirm);
  poll();
})();