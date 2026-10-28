/* Visible-viewport positioning for MOD popups.
   Browser pinch zoom and the mobile keyboard change the *visual* viewport,
   not necessarily the page layout viewport. Keep the editor readable inside
   the actual visible area without disabling native pinch zoom.
   The only style updates target a rule in our same-origin CSS stylesheet,
   preserving Printer's strict no-inline-style CSP. */
(() => {
  'use strict';
  const link = document.querySelector('link[data-dialog-viewport]');
  let rule;
  try { rule = link?.sheet?.cssRules?.[0]; } catch (_) { return; }
  if (!rule || rule.selectorText !== '.editor-dialog[open]') return;

  const dialogs = [...document.querySelectorAll('.editor-dialog')];
  let active = null;
  let scheduled = false;

  function reset() {
    rule.style.cssText = '';
  }
  function viewport() {
    const visual = window.visualViewport;
    const number = (value, fallback) => Number.isFinite(value) ? value : fallback;
    return {
      left: number(visual?.offsetLeft, 0),
      top: number(visual?.offsetTop, 0),
      width: Math.max(1, number(visual?.width, window.innerWidth)),
      height: Math.max(1, number(visual?.height, window.innerHeight)),
      scale: Math.min(6, Math.max(1, number(visual?.scale, 1)))
    };
  }
  function reposition() {
    if (!active?.open) {
      reset();
      return;
    }
    const view = viewport();
    const natural = Math.abs(view.scale - 1) < 0.01 &&
      Math.abs(view.left) < 1 && Math.abs(view.top) < 1 &&
      Math.abs(view.width - window.innerWidth) < 2 &&
      Math.abs(view.height - window.innerHeight) < 2;
    // At normal 1x with no keyboard obstruction, the native dialog and its
    // flex layout own positioning. Only compensate when the visual viewport
    // is genuinely pinched, offset, or shortened by the mobile keyboard.
    if (natural) {
      reset();
      return;
    }
    const wide = active.classList.contains('sale-panel') ||
      active.classList.contains('product-panel');
    const preferredWidth = wide ? 600 :
      active.classList.contains('price-panel') ? 440 : 420;
    // Size text in device pixels, not zoomed page pixels. A 3x pinched page
    // still gets an approximately 16px dialog input, not an unusable 48px one.
    // Never force a minimum wider/taller than the real visible viewport.
    // This matters for 4x/5x pinch and for the keyboard nearly filling it.
    const width = Math.min(preferredWidth, Math.max(1, view.width * view.scale - 16));
    const maxHeight = Math.max(1, view.height * view.scale - 16);
    const scale = 1 / view.scale;
    const props = [
      ['position', 'fixed'], ['inset', 'auto'], ['margin', '0'],
      ['right', 'auto'], ['bottom', 'auto'],
      ['width', width + 'px'], ['max-width', width + 'px'],
      ['max-height', maxHeight + 'px'],
      ['transform-origin', 'top left'],
      ['transform', 'scale(' + scale + ')']
    ];
    for (const [name, value] of props) rule.style.setProperty(name, value);

    const left = view.left + Math.max(0, (view.width - width * scale) / 2);
    const renderedHeight = Math.min(active.offsetHeight, maxHeight) * scale;
    const top = view.top + Math.max(0, (view.height - renderedHeight) / 2);
    rule.style.setProperty('left', left + 'px');
    rule.style.setProperty('top', top + 'px');

    // Scroll only the dialog content when a keyboard opens over an input.
    const input = document.activeElement;
    if (input && active.contains(input) && input.matches('input,textarea,select')) {
      const bounds = input.getBoundingClientRect();
      const box = active.getBoundingClientRect();
      if (bounds.bottom > box.bottom - 20 / view.scale ||
          bounds.top < box.top + 20 / view.scale) {
        input.scrollIntoView({block:'nearest', inline:'nearest'});
      }
    }
  }
  function schedule() {
    if (scheduled) return;
    scheduled = true;
    requestAnimationFrame(() => {
      scheduled = false;
      reposition();
    });
  }

  // The old Fit button reset the sheet's zoom and horizontal pan. Do the
  // same automatically before EVERY popup instead of showing a Fit button.
  // When the phone is pinch-zoomed, nudge the viewport's initial scale and
  // restore it across frames. This returns Chromium to 1x; visual-viewport
  // positioning remains the fallback where a browser ignores the reset.
  document.addEventListener('mod-dialog-opening', event => {
    const gate = event.detail;
    if (!gate || typeof gate.show !== 'function') return;
    gate.handled = true;
    const sheets = document.getElementById('sheets');
    if (sheets) {
      sheets.dataset.zoom = '1';
      sheets.scrollLeft = 0;
    }
    const meta = document.querySelector('meta[name="viewport"]');
    const scale = window.visualViewport?.scale || 1;
    if (!meta || Math.abs(scale - 1) < 0.01) {
      gate.show();
      return;
    }
    const original = meta.getAttribute('content');
    const nudged = original?.replace(
      /initial-scale\s*=\s*[\d.]+/i, 'initial-scale=1.001'
    );
    if (!original || !nudged || nudged === original) {
      gate.show();
      return;
    }
    meta.setAttribute('content', nudged);
    requestAnimationFrame(() => {
      // Never leave browser zoom restricted or change initial scale permanently.
      meta.setAttribute('content', original);
      requestAnimationFrame(gate.show);
    });
  });

  for (const dialog of dialogs) {
    dialog.addEventListener('mod-dialog-open', () => {
      active = dialog;
      reposition();
    });
    dialog.addEventListener('close', () => {
      active = dialogs.find(item => item.open) || null;
      schedule();
    });
    dialog.addEventListener('focusin', schedule);
  }
  window.visualViewport?.addEventListener('resize', schedule, {passive:true});
  window.visualViewport?.addEventListener('scroll', schedule, {passive:true});
  window.addEventListener('resize', schedule);
  window.addEventListener('orientationchange', schedule);
})();
