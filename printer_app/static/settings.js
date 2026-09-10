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
