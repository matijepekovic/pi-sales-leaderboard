/* Control the TV browser, not the phone's own fullscreen state. */
(() => {
  const oldButton = document.getElementById("fullscreenTV");
  if (!oldButton || document.getElementById("exitFullscreenTV")) return;

  // Remove the old click handler so one tap cannot send a second, body-less
  // enable request after the new action. Keep the ID used by the remote layout.
  const enableButton = oldButton.cloneNode(true);
  enableButton.textContent = "Enable forced fullscreen";
  oldButton.replaceWith(enableButton);
  const exitButton = document.createElement("button");
  exitButton.id = "exitFullscreenTV";
  exitButton.type = "button";
  exitButton.className = "btn";
  exitButton.textContent = "Exit fullscreen";
  enableButton.after(exitButton);

  const status = document.createElement("div");
  status.id = "fullscreenModeStatus";
  status.className = "small";
  status.style.marginTop = "10px";
  status.setAttribute("role", "status");
  status.setAttribute("aria-live", "polite");
  enableButton.parentElement.after(status);

  let busy = false;
  let revision = 0;

  function showState(enabled) {
    status.textContent = enabled
      ? "Forced fullscreen: ON. Exit fullscreen pauses enforcement."
      : "Forced fullscreen: OFF. Stays off until you enable it again, even after a restart.";
    enableButton.setAttribute("aria-pressed", String(enabled));
    exitButton.setAttribute("aria-pressed", String(!enabled));
  }

  async function call(options = {}) {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 10000);
    try {
      const response = await fetch("/api/tv/fullscreen", {
        ...options, cache: "no-store", signal: controller.signal,
      });
      if (response.status === 401) throw new Error("Unlock Settings to control fullscreen.");
      const data = await response.json();
      if (!response.ok || !data.ok) throw new Error(data.error || "Fullscreen request failed.");
      if (typeof data.force_fullscreen !== "boolean") throw new Error("Could not read fullscreen mode.");
      return data;
    } finally {
      clearTimeout(timeout);
    }
  }

  async function refresh() {
    if (busy || document.hidden) return;
    const started = revision;
    try {
      const data = await call();
      if (!busy && started === revision) showState(data.force_fullscreen);
    } catch (error) {
      if (!busy && started === revision) status.textContent = error.message;
    }
  }

  async function setMode(enabled) {
    if (busy) return;
    busy = true;
    revision += 1;
    enableButton.disabled = exitButton.disabled = true;
    status.textContent = enabled ? "Enabling forced fullscreen..." : "Exiting fullscreen...";
    try {
      const data = await call({
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({enabled}),
      });
      showState(data.force_fullscreen);
      status.textContent += " TV browser relaunch requested.";
    } catch (error) {
      status.textContent = error.name === "AbortError"
        ? "Could not confirm the change. Check the mode or try again."
        : error.message;
    } finally {
      busy = false;
      enableButton.disabled = exitButton.disabled = false;
    }
  }

  enableButton.addEventListener("click", () => setMode(true));
  exitButton.addEventListener("click", () => setMode(false));
  window.addEventListener("focus", refresh);
  document.addEventListener("visibilitychange", refresh);
  setInterval(refresh, 5000);
  refresh();
})();
