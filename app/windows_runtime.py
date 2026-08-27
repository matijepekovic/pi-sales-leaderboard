"""Windows-only runtime adjustments for the packaged production build.

The source application was originally an appliance service supervised by
systemd/labwc. The Windows installer supplies its own launcher, so this module
disables Linux-only startup work and replaces the legacy source ZIP updater
with the signed public Windows installer update path. Persistent leaderboard
data remains in the existing per-user data directory.
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
        pass


def install(app, server_module) -> bool:
    global _INSTALLED
    if _INSTALLED:
        return False

    _remove_linux_autostart_block()

    def windows_kiosk_startup_status():
        set_meta("kiosk_startup_status", "Windows startup managed by Stats launcher")

    server_module.ensure_labwc_kiosk_autostart = windows_kiosk_startup_status
    windows_kiosk_startup_status()

    # Automatic source-tree updates remain forbidden. Windows updates are
    # verified against the public Ed25519 release key and installed by Inno.
    settings = get_settings()
    if settings.get("github_auto_update"):
        settings["github_auto_update"] = False
        save_settings(settings)

    def source_zip_disabled():
        return jsonify({
            "ok": False,
            "error": (
                "Source ZIP updates are disabled on Windows. Use the signed "
                "Stats installer updater in Software."
            ),
        }), 409

    if "api_github_check" in app.view_functions:
        app.view_functions["api_github_check"] = source_zip_disabled
    if "api_system_update" in app.view_functions:
        app.view_functions["api_system_update"] = source_zip_disabled

    import windows_update
    windows_update.install(app, server_module)

    set_meta("runtime_platform", "windows")
    set_meta("github_update_status", "Windows signed-installer updater ready")
    _INSTALLED = True
    return True
