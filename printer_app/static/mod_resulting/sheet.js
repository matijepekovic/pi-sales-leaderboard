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
  const checkboxDialog = document.getElementById('checkboxDialog');
  const checkboxCurrent = document.getElementById('checkboxCurrent');
  const checkboxText = document.getElementById('checkboxText');
  const checkboxTextarea = document.getElementById('checkboxTextarea');
  const checkboxChoice = document.getElementById('checkboxChoice');
  const checkboxBoolean = document.getElementById('checkboxBoolean');
  const checkboxApply = document.getElementById('checkboxApply');
  let checkboxSpecs = {};
  try { checkboxSpecs = JSON.parse(root.dataset.checkboxSpecs || '{}'); }
  catch (_) { checkboxSpecs = {}; }
  let checkboxTarget = null;

  function hasCheckmark(value) {
    if (value == null || value === false) return false;
    if (value === true) return true;
    const text = String(value).trim().toLocaleLowerCase();
    return !!text && !['false', 'no', '0', 'off', 'unchecked', 'none', 'null'].includes(text);
  }
  function readableCheckbox(value) {
    if (value === undefined || value === null || value === '') return '—';
    if (value === true) return 'True';
    if (value === false) return 'False';
    return String(value);
  }
  function showCheckboxValue(sheet, input, onSave) {
    const key = input.dataset.key;
    const entry = sheet.checkboxValues?.[key];
    const raw = entry ? entry.value : undefined;
    const info = checkboxSpecs[key];
    const canEdit = sheet.dataset.submitted !== 'yes' &&
      info?.editable === true && ['boolean', 'string', 'textarea', 'picklist'].includes(info.kind);
    checkboxTarget = null;
    checkboxCurrent.textContent = readableCheckbox(raw);
    // Editable fields display their source value inside their actual input.
    checkboxCurrent.hidden = canEdit;
    for (const id of ['checkboxTextEditor', 'checkboxTextareaEditor', 'checkboxChoiceEditor', 'checkboxBooleanEditor']) {
      document.getElementById(id).hidden = true;
    }
    checkboxApply.hidden = true;
    if (canEdit) {
      const kind = info.kind;
      if (kind === 'boolean') {
        checkboxBoolean.value = hasCheckmark(raw) ? 'true' : 'false';
        document.getElementById('checkboxBooleanEditor').hidden = false;
      } else if (kind === 'picklist') {
        checkboxChoice.replaceChildren();
        if (info.nullable) checkboxChoice.add(new Option('Empty', ''));
        for (const item of info.choices || []) {
          checkboxChoice.add(new Option(item.label, item.value));
        }
        if (raw !== null && raw !== undefined && raw !== '' &&
            ![...checkboxChoice.options].some(option => option.value === raw)) {
          // Existing inactive values can still be seen. They cannot be
          // reselected for a new write without active Salesforce metadata.
          const existing = new Option(String(raw), String(raw));
          existing.disabled = true;
          checkboxChoice.add(existing, 0);
        }
        checkboxChoice.value = raw == null ? '' : String(raw);
        document.getElementById('checkboxChoiceEditor').hidden = false;
      } else if (kind === 'textarea') {
        checkboxTextarea.value = raw == null ? '' : String(raw);
        checkboxTextarea.maxLength = Math.min(Number(info.length) || 3000, 3000);
        document.getElementById('checkboxTextareaEditor').hidden = false;
      } else {
        checkboxText.value = raw == null ? '' : String(raw);
        checkboxText.maxLength = Math.min(Number(info.length) || 3000, 3000);
        document.getElementById('checkboxTextEditor').hidden = false;
      }
      checkboxTarget = {kind, info, onSave};
      checkboxApply.hidden = false;
      if (kind === 'picklist' &&
          ![...checkboxChoice.options].some(option => !option.disabled)) {
        checkboxApply.disabled = true;
      } else {
        checkboxApply.disabled = false;
      }
    }
    openDialog(checkboxDialog, canEdit
      ? (info.kind === 'boolean' ? '#checkboxBoolean' :
         info.kind === 'picklist' ? '#checkboxChoice' :
         info.kind === 'textarea' ? '#checkboxTextarea' : '#checkboxText')
      : '.editor-secondary');
  }
  checkboxApply.addEventListener('click', () => {
    if (!checkboxTarget) return;
    const {kind, info, onSave} = checkboxTarget;
    let value;
    if (kind === 'boolean') value = checkboxBoolean.value === 'true';
    else if (kind === 'picklist') {
      if (checkboxChoice.selectedOptions[0]?.disabled) return;
      value = checkboxChoice.value || null;
    } else if (kind === 'textarea') value = checkboxTextarea.value || null;
    else value = checkboxText.value || null;
    if (value === null && !info.nullable) return;
    checkboxTarget = null;
    closeDialog(checkboxDialog);
    onSave(value);
  });
  checkboxDialog.addEventListener('close', () => { checkboxTarget = null; });

  function inspectCheckbox(sheet, input, onSave) {
    const label = input.closest('label') || input;
    const cell = input.closest('.cell');
    if (cell) cell.dataset.checkboxInspect = 'yes';
    label.title = 'Hold to view value';
    let timer = null;
    let origin = null;
    let longHeld = false;
    let suppressClick = false;
    let resetClick = null;
    function cancel() {
      if (timer !== null) clearTimeout(timer);
      timer = null;
      origin = null;
      longHeld = false;
    }
    function open() {
      cancel();
      suppressClick = true;
      clearTimeout(resetClick);
      resetClick = setTimeout(() => { suppressClick = false; }, 1000);
      showCheckboxValue(sheet, input, onSave);
    }
    label.addEventListener('pointerdown', event => {
      if (event.button !== 0 || event.isPrimary === false) return;
      cancel();
      origin = {x:event.clientX, y:event.clientY};
      // Open when the press is released, so the releasing click cannot land
      // on the newly opened native dialog backdrop and close it immediately.
      timer = setTimeout(() => { longHeld = true; }, 600);
    });
    label.addEventListener('pointermove', event => {
      if (origin && Math.hypot(event.clientX-origin.x, event.clientY-origin.y) > 12)
        cancel();
    });
    label.addEventListener('pointerup', event => {
      if (longHeld) {
        event.preventDefault();
        open();
      } else cancel();
    });
    label.addEventListener('pointercancel', cancel);
    label.addEventListener('pointerleave', cancel);
    label.addEventListener('click', event => {
      if (suppressClick) {
        event.preventDefault();
        event.stopImmediatePropagation();
        suppressClick = false;
      }
    }, true);
    label.addEventListener('contextmenu', event => {
      event.preventDefault();
      if (origin) longHeld = true;
      else if (!checkboxDialog.open) open();
    });
  }

  // The native dialog top layer escapes PDF sheet clipping and zoom, traps
  // focus, and positions every editor in the viewport on desktop and mobile.
  // One modal can be open across ALL sheets, never one per work order.
  function openDialog(dialog, focusSelector) {
    if (!dialog || dialog.open) return;
    // Keep the edited sheet visible while a pinch reset completes.
    const ownerSheet = dialog.closest('.mod-sheet');
    if (ownerSheet) ownerSheet.dataset.dialogPending = 'yes';
    let shown = false;
    const show = () => {
      if (shown || !dialog.isConnected) return;
      shown = true;
      for (const open of document.querySelectorAll('.editor-dialog[open]')) {
        if (open !== dialog) open.close();
      }
      dialog.showModal();
      if (ownerSheet) ownerSheet.removeAttribute('data-dialog-pending');
      document.body.classList.add('dialog-open');
      dialog.dispatchEvent(new Event('mod-dialog-open'));
      if (focusSelector) dialog.querySelector(focusSelector)?.focus({preventScroll:true});
    };
    // Presentation-only boundary: reset the zoom before the dialog exists in
    // the top layer. If the viewport owner is unavailable, the dialog still opens.
    const opening = {handled:false, show};
    dialog.dispatchEvent(new CustomEvent('mod-dialog-opening', {
      bubbles:true, detail:opening
    }));
    if (!opening.handled) show();
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
  function serialize(sheet) {
    const draft = JSON.parse(sheet.dataset.initial || '{}');
    for (const input of sheet.querySelectorAll('[data-key]')) {
      if (input instanceof HTMLSelectElement && input.multiple) {
        draft[input.dataset.key] = [...input.selectedOptions].map(option => option.value).join(';');
      } else {
        draft[input.dataset.key] = input.type === 'checkbox' ? input.checked : input.value;
      }
    }
    // Preserve raw source values independently from the visible checkboxes.
    // Only explicit changes set edited=true; an unmodified value stays exact.
    draft.checkbox_values = sheet.checkboxValues || draft.checkbox_values || {};
    // Black Notes and popup Redlines are separate; migrate old mixed runs.
    draft.note_runs = [];
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
  function manualRedlinePreview(sheet, draft) {
    const display = sheet.querySelector('.manual-redlines');
    if (!display) return;
    display.textContent = draft.redlines || '';
    display.hidden = !display.textContent;
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
  function moneyCents(input) {
    const value = String(input ?? '').trim();
    const match = /^\$?\s*(\d{1,3}(?:,\d{3})+|\d+)(?:\.(\d{1,2}))?$/.exec(value);
    if (!match) return null;
    const cents = Number(match[1].replace(/,/g, '')) * 100 +
      Number((match[2] || '').padEnd(2, '0'));
    return Number.isSafeInteger(cents) ? cents : null;
  }
  function centsText(cents) {
    if (!Number.isSafeInteger(cents)) return '';
    const fraction = cents % 100;
    return String(Math.floor(cents / 100)) +
      (fraction ? '.' + String(fraction).padStart(2, '0') : '');
  }
  function numericExtremes(notes) {
    // The Numbers column may contain annotations. Ignore letters, extract
    // independent valid amounts, and never join or round their digits.
    const tokens = String(notes || '').matchAll(
      /(?<![\d.,-])\$?\s*(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d{1,2})?(?![\d.]|,\d)/g
    );
    const values = [...tokens].map(match => moneyCents(match[0]))
      .filter(value => value !== null);
    return {
      highest: values.length ? centsText(Math.max(...values)) : '',
      lowest: values.length ? centsText(Math.min(...values)) : ''
    };
  }
  function depositPaymentPreview(draft) {
    const manual = String(draft.deposit_override || '').trim();
    if (manual) return manual;
    const products = draft.dispo === 'sale' ? draft.sale_products :
      draft.additional_products ? draft.product_results : {};
    let deposits = 0, payments = 0, sold = false, hasPayment = false;
    for (const info of Object.values(products || {})) {
      if (draft.dispo !== 'sale' && info.result !== 'sale') continue;
      const price = moneyCents(info.price);
      if (price === null || price <= 0) continue;
      const deposit = moneyCents(info.deposit);
      if (deposit === null) return '';
      sold = true;
      deposits += deposit;
      if (String(info.payment || '').trim()) {
        const payment = moneyCents(info.payment);
        if (payment === null) return '';
        hasPayment = true;
        payments += payment;
      }
    }
    return sold ? centsText(deposits) + '/' + (hasPayment ? centsText(payments) : '') : '';
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
  function fitSalePreview(sheet) {
    // Keep Sale details at the bottom of the existing MOD Notes box. Scale
    // only that preview's font until its wrapped lines fit above the border,
    // reserving room for the black Notes editor and other redline entries.
    const display = sheet.querySelector('.sale-in-redline');
    const area = sheet.querySelector('.notes-text');
    if (!display || display.hidden || !area || !area.clientHeight) return;
    display.dataset.saleFit = '0';
    const otherHeight = [...area.querySelectorAll(
      '.manual-redlines,.result-detail-in-redline,.dnr-in-redline'
    )].filter(element => !element.hidden).reduce(
      (height, element) => height + element.getBoundingClientRect().height, 0
    );
    const notesReserve = Math.min(20, area.clientHeight * .24);
    const available = Math.max(3, area.clientHeight - otherHeight - notesReserve);
    for (let level = 0; level <= 7; level++) {
      display.dataset.saleFit = String(level);
      if (display.getBoundingClientRect().height <= available + .5 &&
          display.scrollWidth <= display.clientWidth + 1) break;
    }
  }
  function applyVisibility() {
    const needle = search.value.trim().toLocaleLowerCase();
    for (const sheet of sheets) {
      const nameMatches = (
        sheet.dataset.name.includes(needle) ||
        (sheet.dataset.reps || '').includes(needle)
      );
      const complete = !!sheet.dataset.dispo && sheet.dataset.overrideActive !== 'yes';
      // Keep the edited sheet visible until its dialog is closed, even if
      // "Hide completed" is enabled and selecting a dispo completes the sheet.
      const editorOpen = sheet.dataset.dialogPending === 'yes' ||
        !!sheet.querySelector('.editor-dialog[open]');
      const wasHidden = sheet.hidden;
      sheet.hidden = !editorOpen && (!nameMatches || (hideCompleted.checked && complete));
      if (wasHidden && !sheet.hidden) fitSalePreview(sheet);
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
      if (background.naturalWidth > 0) {
        sheet.classList.add('surface-ready');
        fitSalePreview(sheet);
      }
    };
    background.addEventListener('load', showSurface);
    background.addEventListener('error', () => {
      sheet.classList.remove('surface-ready');
      message('Printer could not render this MOD sheet. Refresh to retry.', sheet);
    });
    if (background.complete) showSurface();
    const init = JSON.parse(sheet.dataset.initial || '{}');
    sheet.checkboxValues = JSON.parse(JSON.stringify(init.checkbox_values || {}));
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
    fitSalePreview(sheet);
    const noteInput = sheet.querySelector('.mod-notes-input');
    const redlineInput = sheet.querySelector('[data-key="redlines"]');
    // Preserve already-saved red ink by moving legacy mixed-color runs into
    // the independent Redlines editor when the sheet is next edited.
    if (Array.isArray(init.note_runs) && init.note_runs.some(run => run.red) &&
        init.note_runs.map(run => run.text).join('') === init.notes) {
      noteInput.value = init.note_runs.filter(run => !run.red)
        .map(run => run.text).join('');
      const oldRed = init.note_runs.filter(run => run.red)
        .map(run => run.text.trim()).filter(Boolean).join('\n');
      redlineInput.value = [init.redlines || '', oldRed].filter(Boolean).join('\n');
    }
    manualRedlinePreview(sheet, {redlines:redlineInput.value});
    const product = sheet.querySelector('.product-panel');
    const dnr = sheet.querySelector('.dnr-panel');
    const cxl = sheet.querySelector('.cxl-panel');
    const sale = sheet.querySelector('.sale-panel');
    const priceDialog = sheet.querySelector('.price-panel');
    const redlineDialog = sheet.querySelector('.redlines-panel');
    sheet.querySelector('.red-pen')?.addEventListener('click', () =>
      openDialog(redlineDialog, '[data-key="redlines"]'));
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
      const draft = serialize(sheet);
      const amounts = numericExtremes(draft.numbers);
      const calculated = {
        start_price_override: amounts.highest,
        final_price_override: amounts.lowest,
        deposit_override: depositPaymentPreview({...draft, deposit_override:''})
      };
      for (const key of ['start_price_override', 'final_price_override', 'deposit_override']) {
        const input = priceDialog?.querySelector('[data-key="' + key + '"]');
        const preview = sheet.querySelector('[data-price-display="' + key + '"]');
        if (!preview || !input) continue;
        input.placeholder = calculated[key];
        const value = input.value || calculated[key];
        preview.textContent = key === 'deposit_override' ? value :
          (value ? '$' + value : '');
      }
    }
    syncPricePreviews();
    // Native dialogs own their input interactions even while in the top layer.
    // Refresh the worksheet cell directly as values change and when the
    // dialog closes; the sheet-level listener still owns draft persistence.
    for (const dialog of [priceDialog, sale, product]) {
      dialog?.addEventListener('input', syncPricePreviews);
      dialog?.addEventListener('close', syncPricePreviews);
    }
    syncSaleRows();
    const overrideButton = sheet.querySelector('.override-sheet');
    // Inspectors are installed before completed-sheet inputs are disabled:
    // locked sheets still support reading, but never saving raw values.
    for (const input of sheet.querySelectorAll('input[type="checkbox"][data-key]')) {
      inspectCheckbox(sheet, input, value => {
        sheet.checkboxValues[input.dataset.key] = {value, edited:true};
        input.checked = hasCheckmark(value);
        showRelated(input);
        redraw();
      });
    }
    overrideButton?.addEventListener('click', async () => {
      overrideButton.hidden = true;
      try {
        await post(root.dataset.override, {
          work_order_id:sheet.dataset.id, revision:sheet.dataset.revision
        });
        // Rebuild listeners in their normal editable state, with no stale
        // completed-sheet controls or dangling delayed saves.
        location.reload();
      } catch (error) {
        overrideButton.hidden = false;
        message('Override failed: ' + error.message, sheet);
      }
    });
    if (sheet.dataset.submitted === 'yes') {
      for (const input of sheet.querySelectorAll('input,select,textarea,button')) {
        if (input !== overrideButton) input.disabled = true;
      }
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
      manualRedlinePreview(sheet,draft);
      dnrPreview(sheet,draft);
      resultDetailPreview(sheet,draft);
      salePreview(sheet,draft);
      syncPricePreviews();
      applyVisibility();
      if (!sheet.hidden) fitSalePreview(sheet);
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
        if (input.matches('input[type="checkbox"][data-key]') &&
            checkboxSpecs[input.dataset.key]) {
          sheet.checkboxValues[input.dataset.key] = {
            value:input.checked, edited:true
          };
        }
        showRelated(input);
        syncIndividualSaleRows();
        redraw();
      }
    });
    sheet.addEventListener('input', event => {
      const input = event.target;
      if (!(input instanceof HTMLElement)) return;
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
  window.addEventListener('resize', () => {
    for (const sheet of sheets) fitSalePreview(sheet);
  });
  search.addEventListener('input', applyVisibility);
  hideCompleted.addEventListener('change', applyVisibility);
  applyVisibility();

  dayMod.addEventListener('change', async () => {
    try {
      if (!dayMod.value) throw new Error('Choose a MOD from Salesforce.');
      await post(root.dataset.mod, {mod_user_id:dayMod.value});
      // The selected MOD is already shown in the control. No success banner.
      message('');
    } catch (error) { message(error.message); }
  });
  document.getElementById('refresh').addEventListener('click', async event => {
    const button = event.currentTarget;
    button.disabled = true;
    try {
      await flushAll();
      await post(root.dataset.refresh);
      location.reload();
    } catch (error) { message(error.message); button.disabled = false; }
  });

  const clearDialog = document.getElementById('clearConfirm');
  const clearButton = document.getElementById('clearLocal');
  const confirmClear = document.getElementById('confirmClear');
  clearButton.addEventListener('click', () => openDialog(clearDialog, '#cancelClear'));
  confirmClear.addEventListener('click', async () => {
    confirmClear.disabled = true;
    clearButton.disabled = true;
    try {
      // Clear intentionally discards unsaved edits: do not call flushAll().
      // Drain any save already in flight before the authoritative reset so
      // it cannot reintroduce stale local data after Clear.
      for (const timeout of timers.values()) clearTimeout(timeout);
      timers.clear();
      await Promise.all([...pending.values()].map(task => task.catch(() => {})));
      await post(root.dataset.clear);
      location.reload();
    } catch (error) {
      closeDialog(clearDialog);
      message('Clear failed: ' + error.message);
      // Restore normal autosave if the Salesforce read failed: the repository
      // leaves local data untouched until a complete remote snapshot arrives.
      for (const sheet of sheets) {
        if (sheet.dataset.dirty === 'yes') scheduleSave(sheet);
      }
      clearButton.disabled = false;
    } finally {
      confirmClear.disabled = false;
    }
  });

  const confirmation = document.getElementById('endConfirm');
  const methodDialog = document.getElementById('endMethod');
  const selectionDialog = document.getElementById('endSelect');
  const submitButton = document.getElementById('submitDay');
  const selectionList = document.getElementById('endList');
  const selectionSearch = document.getElementById('endSearch');
  const selectionCount = document.getElementById('endSelectionCount');
  const submitSelected = document.getElementById('submitSelected');
  const selectAll = document.getElementById('endSelectAll');

  function eligibleSheets() {
    return sheets.filter(sheet =>
      sheet.dataset.dispo && sheet.dataset.submitted !== 'yes');
  }
  function selectedWorkOrders() {
    return [...selectionList.querySelectorAll('input[type=checkbox]:checked')]
      .map(input => input.value);
  }
  function updateSelection() {
    const choices = [...selectionList.querySelectorAll('input[type=checkbox]')];
    const chosen = selectedWorkOrders().length;
    selectionCount.textContent = chosen + ' of ' + choices.length + ' selected';
    selectAll.textContent = chosen === choices.length ? 'Clear All' : 'Select All';
    submitSelected.disabled = submitButton.dataset.liveWrites !== 'yes' || chosen === 0;
  }
  function buildSelection() {
    selectionSearch.value = '';
    selectionList.replaceChildren();
    for (const sheet of eligibleSheets()) {
      const label = document.createElement('label');
      label.className = 'end-choice';
      const input = document.createElement('input');
      input.type = 'checkbox';
      input.value = sheet.dataset.id;
      input.setAttribute('aria-label', 'Select Work Order ' + sheet.dataset.workNumber);
      input.addEventListener('change', updateSelection);
      const content = document.createElement('span');
      content.className = 'end-choice-content';
      const name = document.createElement('strong');
      name.textContent = sheet.dataset.customer;
      const detail = document.createElement('small');
      detail.textContent = sheet.dataset.workNumber + ' · ' +
        sheet.querySelector('[data-key="dispo"]').selectedOptions[0].textContent;
      content.append(name, detail);
      label.append(input, content);
      selectionList.append(label);
    }
    updateSelection();
  }
  selectionSearch.addEventListener('input', () => {
    const needle = selectionSearch.value.trim().toLocaleLowerCase();
    for (const label of selectionList.querySelectorAll('.end-choice')) {
      label.hidden = !label.textContent.toLocaleLowerCase().includes(needle);
    }
  });
  selectAll.addEventListener('click', () => {
    const inputs = [...selectionList.querySelectorAll('input[type=checkbox]')];
    const allSelected = inputs.every(input => input.checked);
    for (const input of inputs) input.checked = !allSelected;
    updateSelection();
  });
  async function submitBatch(button, selected) {
    button.disabled = true;
    try {
      await flushAll();
      const fields = selected === null ? {mode:'all'} :
        {mode:'selected',work_order_ids:JSON.stringify(selected)};
      const result = await post(root.dataset.submit, fields);
      closeDialog(methodDialog);
      closeDialog(selectionDialog);
      location.reload();
    } catch (error) {
      closeDialog(methodDialog);
      closeDialog(selectionDialog);
      message('Submission stopped: ' + error.message);
    } finally {
      button.disabled = submitButton.dataset.liveWrites !== 'yes';
      updateSelection();
    }
  }
  document.getElementById('cancelEnd').addEventListener('click',
    () => closeDialog(confirmation));
  document.getElementById('cancelEndSecondary').addEventListener('click',
    () => closeDialog(confirmation));
  submitButton.addEventListener('click', async () => {
    try {
      await flushAll();
      if (!dayMod.value) throw new Error('Select the MOD for this day before submission.');
      if (!eligibleSheets().length) throw new Error('No new MOD sheets have a disposition.');
      openDialog(confirmation, '#cancelEndSecondary');
    } catch (error) { message(error.message); }
  });
  document.getElementById('proceedEnd').addEventListener('click', () => {
    closeDialog(confirmation);
    document.getElementById('reviewCount').textContent =
      eligibleSheets().length + ' eligible Work Order(s). MOD: ' +
      dayMod.selectedOptions[0].textContent;
    openDialog(methodDialog);
  });
  document.getElementById('submitAll').addEventListener('click', event =>
    submitBatch(event.currentTarget, null));
  document.getElementById('chooseSelected').addEventListener('click', () => {
    closeDialog(methodDialog);
    buildSelection();
    openDialog(selectionDialog);
  });
  submitSelected.addEventListener('click', event => {
    const selected = selectedWorkOrders();
    if (selected.length) submitBatch(event.currentTarget, selected);
  });
})();