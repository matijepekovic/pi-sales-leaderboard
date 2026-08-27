"""Windows-only runtime adjustments for the packaged production build.

The source application was originally an appliance service supervised by
systemd/labwc.  The Windows installer supplies its own launcher/watchdog, so
this module disables Linux-only startup work and blocks the old source-tree
update installers.  Persistent leaderboard data remains in the existing
per-user data directory and is never stored inside the replaceable app folder.
"""
from __future__ import annotations

import re
from pathlib import Path

from flask import jsonify

from database import get_settings, save_settings, set_meta

_INSTALLED = False
_LABWC_BEGIN = "# >>> PI TABLEAU LEADERBOARD KIOSK >>>"
_LABWC_END = "# <<< PI TABLEAU LEADERBOARD KIOSK <<<"


def _remove_linux_autostart_block() -> None:
    """Undo the Linux autostart block if server import created it on Windows."""
    autostart = Path.home() / ".config" / "labwc" / "autostart"
    if not autostart.exists():
        return
    try:
        text = autostart.read_text(encoding="utf-8")
        pattern = re.compile(
            re.escape(_LABWC_BEGIN) + r".*?" + re.escape(_LABWC_END) + r"\n?",
            re.S,
        )
        cleaned = pattern.sub("", text).strip()
        if cleaned:
            autostart.write_text(cleaned + "\n", encoding="utf-8")
        else:
            autostart.unlink(missing_ok=True)
            try:
                autostart.parent.rmdir()
                autostart.parent.parent.rmdir()
            except OSError:
                pass
    except Exception:
        # This is housekeeping only. A failure must never stop the app.
        pass


def install(app, server_module) -> bool:
    global _INSTALLED
    if _INSTALLED:
        return False

    _remove_linux_autostart_block()

    # The Windows launcher owns kiosk startup and restarts. Replace the Linux
    # labwc writer so a later Fullscreen request only creates the normal
    # restart-kiosk.request file, which the Windows launcher watches.
    def windows_kiosk_startup_status():
        set_meta("kiosk_startup_status", "Windows startup managed by Tablou Stats launcher")

    server_module.ensure_labwc_kiosk_autostart = windows_kiosk_startup_status
    windows_kiosk_startup_status()

    # Never let the packaged executable replace its own frozen files with the
    # legacy source ZIP updater. Signed public-release installers will own that
    # path. The manual Check for Updates UI may still compare versions safely.
    settings = get_settings()
    if settings.get("github_auto_update"):
        settings["github_auto_update"] = False
        save_settings(settings)

    def packaged_update_only():
        return jsonify({
            "ok": False,
            "error": (
                "This Windows build only accepts signed Tablou Stats installer "
                "updates. Source ZIP updates are disabled."
            ),
        }), 409

    if "api_github_check" in app.view_functions:
        app.view_functions["api_github_check"] = packaged_update_only
    if "api_system_update" in app.view_functions:
        app.view_functions["api_system_update"] = packaged_update_only

    set_meta("runtime_platform", "windows")
    set_meta("github_update_status", "Windows signed-installer updates")
    _INSTALLED = True
    return True
