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
      draft[input.dataset.key] = input.type === 'checkbox' ? input.checked : input.value;
    }
    draft.product_results = {};
    if (draft.additional_products) {
      for (const row of sheet.querySelectorAll('[data-product]')) {
        const result = row.querySelector('[data-product-result]').value;
        const detail = row.querySelector('[data-product-detail]').value;
        if (result) draft.product_results[row.dataset.product] = {result, detail};
      }
    }
    return draft;
  }
  function dnrPreview(sheet, draft) {
    const text = sheet.querySelector('.dnr-in-redline');
    if (!text) return;
    text.textContent = draft.dnr && draft.dnr_reason ? 'DNR - ' + draft.dnr_reason : '';
    text.hidden = !text.textContent;
  }
  function applyVisibility() {
    const needle = search.value.trim().toLocaleLowerCase();
    for (const sheet of sheets) {
      const nameMatches = sheet.dataset.name.includes(needle);
      const complete = !!sheet.dataset.dispo;
      sheet.hidden = !nameMatches || (hideCompleted.checked && complete);
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
    const update = before.catch(() => {}).then(async () => {
      const data = await post(root.dataset.save, formFields(sheet));
      sheet.dataset.revision = String(data.revision);
      sheet.dataset.initial = JSON.stringify(serialize(sheet));
      message('', sheet);
    }).catch(error => {
      message('Not saved: ' + error.message, sheet);
      throw error;
    });
    pending.set(ident, update);
    return update;
  }
  function scheduleSave(sheet) {
    const ident = sheet.dataset.id;
    clearTimeout(timers.get(ident));
    const handle = setTimeout(() => {
      timers.delete(ident);
      queueSave(sheet).catch(() => {});
    }, 450);
    timers.set(ident, handle);
  }
  async function flushAll() {
    const saves = [];
    for (const sheet of sheets) {
      clearTimeout(timers.get(sheet.dataset.id));
      timers.delete(sheet.dataset.id);
      if (sheet.dataset.submitted !== 'yes') saves.push(queueSave(sheet));
    }
    await Promise.all(saves);
  }
  function setup(sheet) {
    const init = JSON.parse(sheet.dataset.initial || '{}');
    for (const row of sheet.querySelectorAll('[data-product]')) {
      const selected = init.product_results?.[row.dataset.product];
      if (selected) {
        row.querySelector('[data-product-result]').value = selected.result || '';
        row.querySelector('[data-product-detail]').value = selected.detail || '';
      }
    }
    dnrPreview(sheet, init);
    if (sheet.dataset.submitted === 'yes') {
      for (const input of sheet.querySelectorAll('input,select,textarea,button')) input.disabled = true;
      return;
    }
    const product = sheet.querySelector('.product-panel');
    const dnr = sheet.querySelector('.dnr-panel');
    const cxl = sheet.querySelector('.cxl-panel');
    function redraw() {
      const draft = serialize(sheet);
      sheet.dataset.dispo = draft.dispo;
      dnrPreview(sheet,draft);
      applyVisibility();
      scheduleSave(sheet);
    }
    function showRelated(input) {
      const draft = serialize(sheet);
      if (input.dataset.key === 'dispo') {
        cxl.hidden = draft.dispo !== 'cxl';
        if (draft.dispo === 'cxl') cxl.querySelector('input').focus();
      }
      if (input.dataset.key === 'dnr') {
        dnr.hidden = !draft.dnr;
        if (draft.dnr) dnr.querySelector('select').focus();
      }
      if (input.dataset.key === 'additional_products' && product) {
        product.hidden = !draft.additional_products;
        if (draft.additional_products) product.querySelector('select')?.focus();
      }
    }
    sheet.addEventListener('change', event => {
      const input = event.target;
      if (input instanceof HTMLElement && input.matches('[data-key],[data-product-result],[data-product-detail]')) {
        showRelated(input);
        redraw();
      }
    });
    sheet.addEventListener('input', event => {
      const input = event.target;
      if (input instanceof HTMLElement && input.matches('textarea[data-key],input[data-key]:not([type=checkbox])')) redraw();
    });
    sheet.querySelectorAll('.close-popover').forEach(button => button.addEventListener('click', () => {
      const panel = button.closest('.product-panel,.cxl-panel,.dnr-panel');
      if (panel) panel.hidden = true;
    }));
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
  document.getElementById('cancelEnd').addEventListener('click', () => { confirmation.hidden = true; });
  submitButton.addEventListener('click', async () => {
    try {
      await flushAll();
      if (!dayMod.value) throw new Error('Select the MOD for this day before submission.');
      const count = sheets.filter(s => s.dataset.dispo && s.dataset.submitted !== 'yes').length;
      if (!count) throw new Error('No new MOD sheets have a disposition.');
      document.getElementById('reviewCount').textContent =
        count + ' sheet(s) will be submitted. Sheets without a disposition will not be sent. MOD: ' + dayMod.selectedOptions[0].textContent;
      confirmation.hidden = false;
    } catch (error) { message(error.message); }
  });
  document.getElementById('confirmEnd').addEventListener('click', async event => {
    const button = event.currentTarget;
    button.disabled = true;
    try {
      await flushAll();
      const result = await post(root.dataset.submit);
      confirmation.hidden = true;
      message('Submitted ' + result.submitted + ' MOD sheet(s) to Salesforce.');
      location.reload();
    } catch (error) {
      confirmation.hidden = true;
      message('Submission stopped: ' + error.message);
    } finally { button.disabled = false; }
  });
})();