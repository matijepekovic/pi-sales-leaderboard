(() => {
  'use strict';
  const root = document.body;
  const csrf = root.dataset.csrf;
  const sheets = [...document.querySelectorAll('.mod-sheet')];
  const search = document.getElementById('nameSearch');
  const hideCompleted = document.getElementById('hideCompleted');
  const dayMod = document.getElementById('dailyMod');
  const notice = document.getElementById('notice');
  const timers = new Map();
  const pending = new Map();
  const timeDialog = document.getElementById('timeDialog');
  const timeTitle = document.getElementById('timeTitle');
  const timeHour = document.getElementById('timeHour');
  const timeMinute = document.getElementById('timeMinute');
  const timePeriod = document.getElementById('timePeriod');
  let timeTarget = null;

  // The native dialog top layer escapes PDF sheet clipping and zoom, traps
  // focus, and positions every editor in the viewport on desktop and mobile.
  // One modal can be open across ALL sheets, never one per work order.
  function openDialog(dialog, focusSelector) {
    if (!dialog) return;
    for (const open of document.querySelectorAll('.editor-dialog[open]')) {
      if (open !== dialog) open.close();
    }
    if (!dialog.open) dialog.showModal();
    document.body.classList.add('dialog-open');
    // The dedicated layout owner adjusts the popup before keyboard focus.
    dialog.dispatchEvent(new Event('mod-dialog-open'));
    if (focusSelector) dialog.querySelector(focusSelector)?.focus({preventScroll:true});
  }
  function closeDialog(dialog) {
    if (dialog?.open) dialog.close();
  }
  function openTimePicker(sheet, key) {
    const input = sheet.querySelector('[data-key="' + key + '"]');
    if (!input || input.disabled) return;
    timeTarget = input;
    timeTitle.textContent = key === 'call_1' ? 'Call 1 time' : 'Call 2 time';
    const match = /^(\d{1,2}):([0-5]\d) (AM|PM)$/.exec(input.value);
    timeHour.value = match ? String(Number(match[1])) : '12';
    timeMinute.value = match ? match[2] : '00';
    timePeriod.value = match ? match[3] : 'PM';
    openDialog(timeDialog, '#timeHour');
  }
  function writeTime(value) {
    if (!timeTarget) return;
    timeTarget.value = value;
    timeTarget.dispatchEvent(new Event('input', {bubbles:true}));
    closeDialog(timeDialog);
  }
  for (const dialog of document.querySelectorAll('.editor-dialog')) {
    dialog.addEventListener('close', () => {
      if (!document.querySelector('.editor-dialog[open]')) {
        document.body.classList.remove('dialog-open');
      }
      applyVisibility();
      if (dialog === timeDialog) timeTarget = null;
    });
    dialog.addEventListener('click', event => {
      if (event.target !== dialog) return;
      const box = dialog.getBoundingClientRect();
      if (event.clientX < box.left || event.clientX > box.right ||
          event.clientY < box.top || event.clientY > box.bottom) {
        closeDialog(dialog);
      }
    });
  }
  document.querySelectorAll('.close-popover').forEach(button => {
    button.addEventListener('click', () => closeDialog(button.closest('dialog')));
  });
  document.getElementById('timeApply').addEventListener('click', () => {
    writeTime(Number(timeHour.value) + ':' + timeMinute.value + ' ' + timePeriod.value);
  });
  document.getElementById('timeClear').addEventListener('click', () => writeTime(''));

  function message(text, sheet) {
    const target = sheet ? sheet.querySelector('.sheet-message') : notice;
    target.textContent = text;
    target.hidden = !text;
  }
  async function post(url, fields = {}) {
    const params = new URLSearchParams({csrf, ...fields});
    const response = await fetch(url, {
      method:'POST', body:params,
      headers:{'Accept':'application/json'}
    });
    const data = await response.json();
    if (!response.ok || !data.ok) throw new Error(data.error || 'Request failed');
    return data;
  }
  function compactRuns(runs) {
    const result = [];
    for (const run of runs) {
      if (!run.text) continue;
      if (result.length && result[result.length - 1].red === run.red) {
        result[result.length - 1].text += run.text;
      } else {
        result.push({text:run.text, red:run.red});
      }
    }
    return result;
  }
  function runSlice(runs, start, end) {
    let offset = 0;
    const result = [];
    for (const run of runs) {
      const left = Math.max(start - offset, 0);
      const right = Math.min(end - offset, run.text.length);
      if (right > left) result.push({text:run.text.slice(left,right),red:run.red});
      offset += run.text.length;
    }
    return result;
  }
  function changedNoteRuns(runs, text, red) {
    const before = runs.map(run => run.text).join('');
    if (before === text) return runs;
    let prefix = 0;
    while (prefix < before.length && prefix < text.length &&
           before[prefix] === text[prefix]) prefix++;
    let suffix = 0;
    while (suffix < before.length - prefix && suffix < text.length - prefix &&
           before[before.length - suffix - 1] === text[text.length - suffix - 1]) suffix++;
    return compactRuns([
      ...runSlice(runs, 0, prefix),
      {text:text.slice(prefix, text.length - suffix), red},
      ...runSlice(runs, before.length - suffix, before.length),
    ]);
  }
  function serialize(sheet) {
    const draft = JSON.parse(sheet.dataset.initial || '{}');
    for (const input of sheet.querySelectorAll('[data-key]')) {
      if (input instanceof HTMLSelectElement && input.multiple) {
        draft[input.dataset.key] = [...input.selectedOptions].map(option => option.value).join(';');
      } else {
        draft[input.dataset.key] = input.type === 'checkbox' ? input.checked : input.value;
      }
    }
    // Historical drafts may contain a separate redlines key. The editor
    // displays their concatenated text in the single MOD Notes input and
    // migrates it losslessly into the one notes key on its next save.
    draft.redlines = '';
    draft.note_runs = (sheet._noteRuns || []).map(run => ({
      text:run.text, red:run.red
    }));
    draft.product_results = {};
    if (draft.additional_products && draft.dispo !== 'sale') {
      for (const row of sheet.querySelectorAll('[data-product]')) {
        const result = row.querySelector('[data-product-result]').value;
        const detail = row.querySelector('[data-product-detail]').value;
        if (result) {
          const payment = row.querySelector('[data-product-payment]')?.value || '';
          draft.product_results[row.dataset.product] = {
            result, detail,
            price: row.querySelector('[data-product-price]')?.value || '',
            deposit: row.querySelector('[data-product-deposit]')?.value || '',
            ...(payment ? {payment} : {})
          };
        }
      }
    }
    draft.sale_products = {};
    for (const row of sheet.querySelectorAll('[data-sale-product]')) {
      const selected = row.querySelector('[data-sale-selected]');
      if (!selected?.checked) continue;
      const payment = row.querySelector('[data-sale-payment]').value;
      draft.sale_products[row.dataset.saleProduct] = {
        price: row.querySelector('[data-sale-price]').value,
        deposit: row.querySelector('[data-sale-deposit]').value,
        ...(payment ? {payment} : {})
      };
    }
    return draft;
  }
  function resultDetailPreview(sheet, draft) {
    const output = sheet.querySelector('.result-detail-in-redline');
    if (!output) return;
    const lines = [];
    if (draft.result_detail) lines.push(draft.result_detail);
    if (draft.additional_products && draft.dispo !== 'sale') {
      for (const info of Object.values(draft.product_results || {})) {
        if (info.detail) lines.push(info.detail);
      }
    }
    output.textContent = [...new Set(lines)].join('\n');
    output.hidden = !output.textContent;
  }
  function dnrPreview(sheet, draft) {
    const text = sheet.querySelector('.dnr-in-redline');
    if (!text) return;
    const reason = String(draft.dnr_reason || '').trim().replaceAll(';', '; ');
    text.textContent = draft.dnr && reason ? (/^dnr\s*-/i.test(reason) ? reason : 'DNR - ' + reason) : '';
    text.hidden = !text.textContent;
  }
  function formattedMoney(input) {
    const value = String(input || '').trim();
    const match = /^\$?\s*(\d{1,3}(?:,\d{3})+|\d+)(?:\.(\d{1,2}))?$/.exec(value);
    if (!match) return null;
    const whole = match[1].replace(/,/g, '').replace(/^0+(?=\d)/, '');
    const grouped = whole.replace(/\B(?=(\d{3})+(?!\d))/g, ',');
    const cents = (match[2] || '').padEnd(2, '0');
    return '$' + grouped + (cents && cents !== '00' ? '.' + cents : '');
  }
  function salePreview(sheet, draft) {
    const display = sheet.querySelector('.sale-in-redline');
    if (!display) return;
    const products = draft.dispo === 'sale' ? draft.sale_products :
      draft.additional_products ? draft.product_results : {};
    const lines = [];
    for (const [product, info] of Object.entries(products || {})) {
      if (draft.dispo !== 'sale' && info.result !== 'sale') continue;
      const price = formattedMoney(info.price);
      const deposit = formattedMoney(info.deposit);
      if (!price || price === '$0' || deposit === null) continue;
      const payment = info.payment ? formattedMoney(info.payment) : null;
      lines.push('SALE ' + product + ': ' + price + ' | Deposit: ' + deposit +
        (payment !== null ? ' | Payment: ' + payment : ''));
    }
    display.textContent = lines.join('\n');
    display.hidden = !display.textContent;
  }
  function applyVisibility() {
    const needle = search.value.trim().toLocaleLowerCase();
    for (const sheet of sheets) {
      const nameMatches = (
        sheet.dataset.name.includes(needle) ||
        (sheet.dataset.reps || '').includes(needle)
      );
      const complete = !!sheet.dataset.dispo;
      // Keep the edited sheet visible until its dialog is closed, even if
      // "Hide completed" is enabled and selecting a dispo completes the sheet.
      const editorOpen = !!sheet.querySelector('.editor-dialog[open]');
      sheet.hidden = !editorOpen && (!nameMatches || (hideCompleted.checked && complete));
    }
  }
  function formFields(sheet) {
    return {
      work_order_id:sheet.dataset.id,
      revision:sheet.dataset.revision,
      draft:JSON.stringify(serialize(sheet))
    };
  }
  function queueSave(sheet) {
    if (sheet.dataset.submitted === 'yes') return Promise.resolve();
    const ident = sheet.dataset.id;
    const before = pending.get(ident) || Promise.resolve();
    // Sequence saves per work order. Keep a draft marked dirty if its fields
    // changed while a previous request was still in flight.
    const update = before.catch(() => {}).then(async () => {
      if (sheet.dataset.dirty !== 'yes') return;
      const snapshot = JSON.stringify(serialize(sheet));
      const data = await post(root.dataset.save, {
        work_order_id:ident, revision:sheet.dataset.revision, draft:snapshot
      });
      sheet.dataset.revision = String(data.revision);
      sheet.dataset.initial = snapshot;
      sheet.dataset.dirty = JSON.stringify(serialize(sheet)) === snapshot ? 'no' : 'yes';
      message('', sheet);
    }).catch(error => {
      sheet.dataset.dirty = 'yes';
      message('Not saved: ' + error.message, sheet);
      throw error;
    });
    pending.set(ident, update);
    return update;
  }
  function scheduleSave(sheet) {
    const ident = sheet.dataset.id;
    sheet.dataset.dirty = 'yes';
    clearTimeout(timers.get(ident));
    const handle = setTimeout(() => {
      timers.delete(ident);
      queueSave(sheet).catch(() => {});
    }, 450);
    timers.set(ident, handle);
  }
  async function flushAll() {
    for (const sheet of sheets) {
      clearTimeout(timers.get(sheet.dataset.id));
      timers.delete(sheet.dataset.id);
    }
    // Wait for existing saves and then persist only fields that changed;
    // avoid rewriting hundreds of untouched sheets on every Refresh.
    for (let attempt = 0; attempt < 3; attempt++) {
      await Promise.all(sheets.map(sheet =>
        sheet.dataset.dirty === 'yes' ? queueSave(sheet) :
        pending.get(sheet.dataset.id) || Promise.resolve()));
      if (sheets.every(sheet => sheet.dataset.dirty !== 'yes')) return;
    }
    throw new Error('An unsaved sheet is still changing; retry after editing.');
  }
  function setup(sheet) {
    const background = sheet.querySelector('.printer-sheet');
    const showSurface = () => {
      if (background.naturalWidth > 0) sheet.classList.add('surface-ready');
    };
    background.addEventListener('load', showSurface);
    background.addEventListener('error', () => {
      sheet.classList.remove('surface-ready');
      message('Printer could not render this MOD sheet. Refresh to retry.', sheet);
    });
    if (background.complete) showSurface();
    const init = JSON.parse(sheet.dataset.initial || '{}');
    for (const row of sheet.querySelectorAll('[data-product]')) {
      const selected = init.product_results?.[row.dataset.product];
      if (selected) {
        row.querySelector('[data-product-result]').value = selected.result || '';
        row.querySelector('[data-product-detail]').value = selected.detail || '';
        row.querySelector('[data-product-price]').value = selected.price || '';
        row.querySelector('[data-product-deposit]').value = selected.deposit || '';
        row.querySelector('[data-product-payment]').value = selected.payment || '';
      }
    }
    function syncIndividualSaleRows() {
      for (const row of sheet.querySelectorAll('[data-product]')) {
        const sale = row.querySelector('[data-product-result]').value === 'sale';
        const fields = row.querySelector('.individual-sale-fields');
        if (fields) fields.hidden = !sale;
      }
    }
    syncIndividualSaleRows();
    sheet.dataset.dirty = 'no';
    dnrPreview(sheet, init);
    resultDetailPreview(sheet, init);
    salePreview(sheet, init);
    const noteArea = sheet.querySelector('.notes-text');
    const noteInput = sheet.querySelector('.mod-notes-input');
    const noteMirror = sheet.querySelector('.mod-notes-display');
    let noteRuns;
    if (Array.isArray(init.note_runs) && init.note_runs.length) {
      noteRuns = init.note_runs.map(run => ({text:run.text,red:run.red}));
    } else {
      noteRuns = init.notes ? [{text:init.notes,red:false}] : [];
    }
    if (init.redlines) {
      if (noteRuns.length) noteRuns.push({text:'\n',red:false});
      noteRuns.push({text:init.redlines,red:true});
    }
    sheet._noteRuns = compactRuns(noteRuns);
    function renderNoteRuns() {
      const elements = sheet._noteRuns.map(run => {
        const part = document.createElement('span');
        if (run.red) part.className = 'after-dispo';
        part.textContent = run.text;
        return part;
      });
      noteMirror.replaceChildren(...elements);
      noteArea.classList.add('mixed-notes-ready');
      noteMirror.scrollTop = noteInput.scrollTop;
    }
    function syncNoteMode() {
      // A disposition changes the ink used by FUTURE input only.
      // Existing black/red characters never get recolored.
      noteArea.dataset.notesMode =
        sheet.querySelector('[data-key="dispo"]').value ? 'red' : 'black';
    }
    renderNoteRuns();
    syncNoteMode();
    noteInput.addEventListener('scroll', () => {
      noteMirror.scrollTop = noteInput.scrollTop;
    });
    const product = sheet.querySelector('.product-panel');
    const dnr = sheet.querySelector('.dnr-panel');
    const cxl = sheet.querySelector('.cxl-panel');
    const sale = sheet.querySelector('.sale-panel');
    const priceDialog = sheet.querySelector('.price-panel');
    const saleButton = sheet.querySelector('.edit-sale-products');
    const cxlButton = sheet.querySelector('.edit-cxl-details');
    const productButton = sheet.querySelector('.edit-product-results');
    const dnrButton = sheet.querySelector('.edit-dnr-reasons');
    const separate = sheet.querySelector('.separate-products');
    if (separate) separate.hidden = init.dispo === 'sale';
    if (productButton) productButton.hidden = init.dispo === 'sale' || !init.additional_products;
    if (cxlButton) cxlButton.hidden = init.dispo !== 'cxl';
    if (dnrButton) dnrButton.hidden = !init.dnr;
    function syncPricePreviews() {
      for (const key of ('start_price_override', 'final_price_override', 'deposit_override')) {
        const input = priceDialog?.querySelector('[data-key="' + key + '"]');
        const preview = sheet.querySelector('[data-price-display="' + key + '"]');
        if (preview && input) preview.textContent = input.value ? '$' + input.value : '';
      }
    }
    syncPricePreviews();
    priceDialog?.querySelectorAll('input[data-key$="_override"]').forEach(input => {
      input.addEventListener('input', () => {
        const preview = sheet.querySelector(
          '[data-price-display="' + input.dataset.key + '"]'
        );
        if (preview) preview.textContent = input.value ? '$' + input.value : '';
        redraw();
      });
    });
    priceDialog?.addEventListener('close', syncPricePreviews);
    syncSaleRows();
    if (sheet.dataset.submitted === 'yes') {
      for (const input of sheet.querySelectorAll('input,select,textarea,button')) input.disabled = true;
      return;
    }
    const reasonSelect = sheet.querySelector('[data-key="dnr_reason"]');
    const reasonChoices = [...sheet.querySelectorAll('[data-reason-choice]')];
    function syncReasonSelect() {
      if (!reasonSelect) return;
      const checked = new Set(reasonChoices.filter(input => input.checked).map(input => input.value));
      for (const option of reasonSelect.options) option.selected = checked.has(option.value);
    }
    function syncReasonChoices() {
      if (!reasonSelect) return;
      const selected = new Set([...reasonSelect.selectedOptions].map(option => option.value));
      for (const input of reasonChoices) input.checked = selected.has(input.value);
    }
    syncReasonChoices();
    dnr?.addEventListener('close', () => {
      const checkbox = sheet.querySelector('[data-key="dnr"]');
      // With no selected reason DNR is unchecked, not Do Not Call.
      if (checkbox.checked && !reasonChoices.some(choice => choice.checked)) {
        checkbox.checked = false;
        if (dnrButton) dnrButton.hidden = true;
        redraw();
      }
    });
    function syncSaleRows() {
      for (const row of sheet.querySelectorAll('[data-sale-product]')) {
        const selected = row.querySelector('[data-sale-selected]');
        const enabled = !!selected?.checked;
        for (const field of row.querySelectorAll('[data-sale-price],[data-sale-deposit],[data-sale-payment]')) {
          field.disabled = !enabled;
        }
      }
    }
    function openSale() {
      if (!sale) return;
      openDialog(sale, '[data-sale-selected]');
    }
    function redraw() {
      const draft = serialize(sheet);
      sheet.dataset.dispo = draft.dispo;
      syncNoteMode();
      dnrPreview(sheet,draft);
      resultDetailPreview(sheet,draft);
      salePreview(sheet,draft);
      syncPricePreviews();
      applyVisibility();
      scheduleSave(sheet);
    }
    function showRelated(input) {
      const draft = serialize(sheet);
      if (separate) separate.hidden = draft.dispo === 'sale';
      if (productButton) productButton.hidden = draft.dispo === 'sale' || !draft.additional_products;
      if (cxlButton) cxlButton.hidden = draft.dispo !== 'cxl';
      if (dnrButton) dnrButton.hidden = !draft.dnr;
      if (input.dataset.key === 'dispo') {
        if (saleButton) saleButton.hidden = draft.dispo !== 'sale';
        if (draft.dispo === 'cxl') openDialog(cxl, '[data-key="cxl_at_lead"]');
        else if (draft.dispo === 'sale') openSale();
        else {
          closeDialog(cxl);
          closeDialog(sale);
        }
        if (draft.dispo === 'sale') closeDialog(product);
      }
      if (input.dataset.key === 'dnr') {
        if (draft.dnr) {
          openDialog(dnr, '[data-reason-choice]');
        } else {
          reasonChoices.forEach(choice => { choice.checked = false; });
          syncReasonSelect();
          closeDialog(dnr);
        }
      }
      if (input.dataset.key === 'additional_products' && product && draft.dispo !== 'sale') {
        if (draft.additional_products) openDialog(product, '[data-product-result]');
        else closeDialog(product);
      }
      if (input.matches?.('[data-sale-selected]')) syncSaleRows();
      if (input.matches?.('[data-key="dnr_reason"]')) syncReasonChoices();
    }
    sheet.addEventListener('change', event => {
      const input = event.target;
      if (!(input instanceof HTMLElement)) return;
      if (input.matches('[data-reason-choice]')) {
        syncReasonSelect();
        redraw();
      } else if (input.matches('[data-key],[data-product-result],[data-product-detail],[data-sale-selected]')) {
        showRelated(input);
        syncIndividualSaleRows();
        redraw();
      }
    });
    sheet.addEventListener('input', event => {
      const input = event.target;
      if (!(input instanceof HTMLElement)) return;
      if (input.dataset.key === 'notes') {
        sheet._noteRuns = changedNoteRuns(
          sheet._noteRuns, input.value, !!sheet.querySelector('[data-key="dispo"]').value
        );
        renderNoteRuns();
      }
      if (input.matches('textarea[data-key],input[data-key]:not([type=checkbox]),[data-sale-price],[data-sale-deposit],[data-sale-payment],[data-product-price],[data-product-deposit],[data-product-payment]')) redraw();
    });
    saleButton?.addEventListener('click', openSale);
    for (const button of sheet.querySelectorAll('[data-price-trigger]')) {
      button.addEventListener('click', () => {
        openDialog(priceDialog, '[data-key="' + button.dataset.priceTrigger + '"]');
      });
    }
    cxlButton?.addEventListener('click', () => openDialog(cxl, '[data-key="cxl_at_lead"]'));
    productButton?.addEventListener('click', () => openDialog(product, '[data-product-result]'));
    dnrButton?.addEventListener('click', () => openDialog(dnr, '[data-reason-choice]'));
    for (const button of sheet.querySelectorAll('[data-time-trigger]')) {
      button.addEventListener('click', () => openTimePicker(sheet, button.dataset.timeTrigger));
    }
  }
  for (const sheet of sheets) setup(sheet);
  search.addEventListener('input', applyVisibility);
  hideCompleted.addEventListener('change', applyVisibility);
  applyVisibility();

  dayMod.addEventListener('change', async () => {
    try {
      if (!dayMod.value) throw new Error('Choose a MOD from Salesforce.');
      const result = await post(root.dataset.mod, {mod_user_id:dayMod.value});
      message('MOD for today: ' + result.mod);
    } catch (error) { message(error.message); }
  });
  document.getElementById('refresh').addEventListener('click', async event => {
    const button = event.currentTarget;
    button.disabled = true;
    try {
      await flushAll();
      const result = await post(root.dataset.refresh);
      message('Pulled ' + result.count + ' MOD sheets. Reloading…');
      location.reload();
    } catch (error) { message(error.message); button.disabled = false; }
  });

  const confirmation = document.getElementById('endConfirm');
  const submitButton = document.getElementById('submitDay');
  document.getElementById('cancelEnd').addEventListener('click', () => closeDialog(confirmation));
  document.getElementById('cancelEndSecondary').addEventListener('click', () => closeDialog(confirmation));
  submitButton.addEventListener('click', async () => {
    try {
      await flushAll();
      if (!dayMod.value) throw new Error('Select the MOD for this day before submission.');
      const count = sheets.filter(s => s.dataset.dispo && s.dataset.submitted !== 'yes').length;
      if (!count) throw new Error('No new MOD sheets have a disposition.');
      document.getElementById('reviewCount').textContent =
        count + ' resulted sheet(s). Sheets without a disposition are excluded. MOD: '
        + dayMod.selectedOptions[0].textContent;
      openDialog(confirmation, '#cancelEndSecondary');
    } catch (error) { message(error.message); }
  });
  document.getElementById('confirmEnd').addEventListener('click', async event => {
    const button = event.currentTarget;
    button.disabled = true;
    try {
      await flushAll();
      const result = await post(root.dataset.submit);
      closeDialog(confirmation);
      message('Submitted ' + result.submitted + ' MOD sheet(s) to Salesforce.');
      location.reload();
    } catch (error) {
      closeDialog(confirmation);
      message('Submission stopped: ' + error.message);
    } finally { button.disabled = false; }
  });
})();