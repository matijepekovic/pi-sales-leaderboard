(() => {
  'use strict';
  const root = document.body;
  const report = JSON.parse(root.dataset.report || '{}');
  const edits = JSON.parse(root.dataset.edits || '{}');
  edits.inputs ||= {};
  edits.outputs ||= {};
  const status = document.getElementById('calcStatus');
  const download = document.getElementById('downloadCalc');
  const buttons = [
    document.getElementById('confirmCalc'),
    document.getElementById('bottomConfirm'),
  ];
  const inputFields = [...document.querySelectorAll('[data-input]')];
  const outputFields = [...document.querySelectorAll('[data-output]')];
  const field = key => document.querySelector('[data-output="' + key + '"]');
  let dirty = false;
  let pollTimer;

  function number(value) {
    const raw = String(value ?? '').trim().replace(/[$,]/g, '');
    if (!raw) return null;
    const parsed = Number(raw);
    return Number.isFinite(parsed) ? parsed : null;
  }
  function percent(numerator, denominator) {
    if (numerator === null || denominator === null || denominator <= 0) return '';
    return (100 * numerator / denominator).toFixed(1) + '%';
  }
  function money(amount) {
    if (amount === null || !Number.isFinite(amount)) return '';
    return '$' + amount.toLocaleString('en-US', {
      minimumFractionDigits:2, maximumFractionDigits:2
    });
  }
  function calc() {
    const values = Object.fromEntries(
      inputFields.map(input => [input.dataset.input, number(input.value)])
    );
    const all = ['sold','pns','nh','np','nra','cxl'].every(key => values[key] !== null);
    const pitched = all ? values.sold + values.pns : null;
    const denominator = all ? pitched + values.nh + values.np + values.nra : null;
    const denominatorNoNra = all ? pitched + values.nh + values.np : null;
    const leads = values.cxl === null ? null :
                  Number(report.work_orders) - Number(report.oos) - values.cxl;
    const valuesOut = {
      leads: leads === null ? '' : String(leads),
      pitch: percent(pitched, denominator),
      pitch_nra: percent(pitched, denominatorNoNra),
      close: percent(values.sold, leads),
      close_nra: percent(values.sold, leads === null || values.nra === null
                                    ? null : leads - values.nra),
      total: money(values.revenue),
      dpl: money(values.revenue !== null && leads > 0
                 ? values.revenue / leads : null),
      nra_total: values.nra === null ? '' : String(values.nra)
    };
    for (const input of outputFields) {
      const key = input.dataset.output;
      if (!Object.prototype.hasOwnProperty.call(edits.outputs, key)) {
        input.value = valuesOut[key] ?? '';
      }
    }
  }
  function changed() {
    dirty = true;
    download.hidden = true;
    status.textContent = 'Unsaved OLY Calc changes. Press Confirm.';
  }
  for (const input of inputFields) {
    input.addEventListener('input', () => {
      edits.inputs[input.dataset.input] = input.value;
      calc();
      changed();
    });
  }
  for (const output of outputFields) {
    output.addEventListener('input', () => {
      edits.outputs[output.dataset.output] = output.value;
      changed();
    });
  }

  async function confirm() {
    buttons.forEach(button => button.disabled = true);
    try {
      const fields = new URLSearchParams({
        csrf:root.dataset.csrf,
        job_id:root.dataset.jobId,
        revision:root.dataset.revision,
        edits:JSON.stringify(edits)
      });
      const response = await fetch(root.dataset.confirm, {
        method:'POST', body:fields,
        headers:{Accept:'application/json'}
      });
      const result = await response.json();
      if (!response.ok || !result.ok) throw new Error(result.error || 'Could not confirm OLY Calc.');
      root.dataset.revision = String(result.revision);
      dirty = false;
      status.textContent = 'OLY Calc confirmed. Generating the PDF.';
      poll();
    } catch (error) {
      status.textContent = error.message;
    } finally {
      buttons.forEach(button => button.disabled = false);
    }
  }

  async function poll() {
    clearTimeout(pollTimer);
    try {
      const response = await fetch(root.dataset.status, {cache:'no-store'});
      const state = await response.json();
      if (!response.ok || !state.ok) throw new Error(state.error || 'Status unavailable.');
      if (state.state === 'failed') {
        status.textContent = state.error || 'OLY Calc PDF generation failed.';
        download.hidden = true;
        return;
      }
      if (state.ready && !dirty) {
        download.href = state.download_url;
        download.hidden = false;
        status.textContent = 'OLY Calc PDF is ready.';
        return;
      }
      if (!dirty) {
        const stages = {
          queued:'Queued for background PDF generation.',
          rendering:'Generating the calculation report.',
          awaiting_confirmation:'Report generated. Confirm your OLY Calc values.',
          pending_finalize:'Applying confirmed edits.',
          finalizing:'Finalizing OLY Calc PDF.'
        };
        status.textContent = (state.confirmed ? 'OLY Calc confirmed. ' : '') +
                             (stages[state.state] || 'Preparing PDF.');
      }
    } catch (error) {
      if (!dirty) status.textContent = error.message;
    }
    pollTimer = setTimeout(poll, 1800);
  }
  buttons.forEach(button => button.addEventListener('click', confirm));
  calc();
  poll();
})();