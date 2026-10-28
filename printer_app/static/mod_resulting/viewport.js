/* Presentation-only sheet viewport. Never reads or writes MOD draft data. */
(() => {
  'use strict';
  const sheets = document.getElementById('sheets');
  const controls = document.getElementById('sheetZoom');
  if (!sheets || !controls) return;
  const mobile = window.matchMedia('(max-width:900px)');
  const levels = [1, 1.5, 2, 3, 4];
  const storageKey = 'mod-resulting:sheet-zoom';
  const minus = document.getElementById('zoomOut');
  const plus = document.getElementById('zoomIn');
  const fit = document.getElementById('zoomFit');
  let index = 0;
  try {
    const saved = Number(sessionStorage.getItem(storageKey));
    index = Math.max(0, levels.indexOf(saved));
  } catch (_) { /* Storage is optional; zoom still works. */ }

  function updateControls() {
    minus.disabled = index === 0;
    plus.disabled = index === levels.length - 1;
    sheets.dataset.zoom = String(levels[index]);
  }
  function visibleSheet() {
    const top = document.querySelector('.floating-controls').getBoundingClientRect().bottom;
    const candidates = [...sheets.querySelectorAll('.mod-sheet:not([hidden])')];
    return candidates.find(sheet => sheet.getBoundingClientRect().bottom > top) || candidates[0];
  }
  function zoom(next) {
    if (!mobile.matches) return;
    const sheet = visibleSheet();
    const old = sheet?.getBoundingClientRect();
    const top = document.querySelector('.floating-controls').getBoundingClientRect().bottom;
    // Keep the visible sheet and the viewed point in place as every sheet scales.
    const anchorX = window.innerWidth / 2;
    const anchorY = old ? Math.max(old.top, top) : top;
    const x = old ? Math.max(0, Math.min(1, (anchorX - old.left) / old.width)) : 0;
    const y = old ? Math.max(0, Math.min(1, (anchorY - old.top) / old.height)) : 0;
    index = Math.max(0, Math.min(levels.length - 1, next));
    updateControls();
    try { sessionStorage.setItem(storageKey, String(levels[index])); } catch (_) {}
    if (!sheet) return;
    const changed = sheet.getBoundingClientRect();
    sheets.scrollLeft = index === 0 ? 0 : sheets.scrollLeft + changed.left + x * changed.width - anchorX;
    window.scrollBy(0, changed.top + y * changed.height - anchorY);
  }
  minus.addEventListener('click', () => zoom(index - 1));
  plus.addEventListener('click', () => zoom(index + 1));
  fit.addEventListener('click', () => zoom(0));
  mobile.addEventListener('change', () => {
    if (!mobile.matches) sheets.scrollLeft = 0;
  });
  updateControls();
  // Native pinch zoom remains available: no gesture interception or scale limits.
})();
