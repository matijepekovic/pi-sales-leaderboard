/* Printer Settings: connection checks only; no credentials are put in URLs/storage. */
(() => {
  const form = document.getElementById('printerSettings');
  const button = document.getElementById('testEmail');
  const output = document.getElementById('emailTestResult');
  button.addEventListener('click', async () => {
    button.disabled = true;
    output.textContent = 'Testing Gmail connection…';
    try {
      const response = await fetch(button.dataset.url, {
        method: 'POST', body: new FormData(form), credentials: 'same-origin'
      });
      const result = await response.json();
      output.textContent = result.message || 'Test failed. Refresh the page and try again.';
      output.className = result.ok ? 'good' : 'error';
    } catch (_) {
      output.textContent = 'Could not complete the test. Check the connection and try again.';
      output.className = 'error';
    } finally {
      button.disabled = false;
    }
  });
})();

/* Read-only status: web restarts during installation, so transient errors retry. */
(() => {
  const section = document.getElementById('printerUpdate');
  if (!section) return;
  const output = document.getElementById('printerUpdateStatus');
  const button = document.getElementById('updatePrinterOnly');
  async function refreshPrinterUpdate() {
    try {
      const response = await fetch(section.dataset.statusUrl, {
        credentials: 'same-origin', cache: 'no-store'
      });
      if (!response.ok) return;
      const status = await response.json();
      output.textContent = status.state + ' — ' + status.message;
      const busy = status.state === 'QUEUED' || status.state === 'INSTALLING';
      button.disabled = busy;
      output.className = status.state === 'ERROR' ? 'error' :
        status.state === 'READY' || status.state === 'UP TO DATE' ? 'good' : 'muted';
    } catch (_) {
      // Printer web can briefly restart while the update service installs it.
    }
  }
  refreshPrinterUpdate();
  setInterval(refreshPrinterUpdate, 5000);
})();
