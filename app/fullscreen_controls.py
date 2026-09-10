"""Remote control of the Pi's forced-fullscreen browser mode.

The pause flag lives outside the application directory so it survives browser
relaunches, reboots and software updates. Only an explicit enable removes it.
The existing graphical-session watchdog handles the browser restart; never
send F11 to whichever unrelated window happens to have focus.
"""
from pathlib import Path
import threading


class FullscreenControl:
    def __init__(self, data_dir=None):
        self.data_dir = Path(data_dir) if data_dir is not None else (
            Path.home() / ".local" / "share" / "pi-tableau-leaderboard"
        )
        self.disabled_flag = self.data_dir / "fullscreen-disabled.flag"
        self.restart_request = self.data_dir / "restart-kiosk.request"
        self._lock = threading.Lock()

    @property
    def enabled(self):
        return not self.disabled_flag.exists()

    def _write_enabled(self, enabled):
        if enabled:
            self.disabled_flag.unlink(missing_ok=True)
        else:
            self.disabled_flag.touch(exist_ok=True)

    def _request_restart(self):
        # The old and new watchdogs both consume this existing request file.
        self.restart_request.touch(exist_ok=True)

    def set_enabled(self, enabled):
        if type(enabled) is not bool:
            raise ValueError("enabled must be true or false.")
        with self._lock:
            self.data_dir.mkdir(parents=True, exist_ok=True)
            previous = self.enabled
            self._write_enabled(enabled)
            try:
                self._request_restart()
            except OSError:
                self._write_enabled(previous)
                raise
        return enabled


def install_routes(app, data_dir=None):
    """Use the existing appliance-control startup hook and settings PIN gate."""
    from flask import jsonify, request

    if "fullscreen_controls" in app.extensions:
        return False
    control = FullscreenControl(data_dir)

    def status():
        response = jsonify({"ok": True, "force_fullscreen": control.enabled})
        response.headers["Cache-Control"] = "no-store"
        return response

    def set_fullscreen():
        # A body-less POST is the legacy 'Force Fullscreen TV' command.
        # Malformed JSON must not accidentally turn enforcement back on.
        body = request.get_json(silent=True) if request.get_data() else {}
        if not isinstance(body, dict) or type(body.get("enabled", True)) is not bool:
            return jsonify({"ok": False, "error": "enabled must be true or false."}), 400
        enabled = body.get("enabled", True)
        try:
            control.set_enabled(enabled)
        except OSError:
            app.logger.exception("Could not change TV fullscreen mode")
            return jsonify({
                "ok": False,
                "error": "Could not save fullscreen mode or request the TV browser restart.",
            }), 500
        return jsonify({
            "ok": True,
            "force_fullscreen": enabled,
            "restart_requested": True,
            "message": (
                "Forced fullscreen enabled. TV browser relaunch requested."
                if enabled else
                "Forced fullscreen disabled until you enable it again. Windowed TV relaunch requested."
            ),
        })

    # Replace, rather than stack on, the legacy F11/relaunch handler. This also
    # keeps an already-open older remote's fullscreen button working correctly.
    if "api_tv_fullscreen" in app.view_functions:
        app.view_functions["api_tv_fullscreen"] = set_fullscreen
    else:
        app.add_url_rule("/api/tv/fullscreen", endpoint="api_tv_fullscreen",
                         view_func=set_fullscreen, methods=["POST"])
    app.add_url_rule("/api/tv/fullscreen", endpoint="api_tv_fullscreen_status",
                     view_func=status, methods=["GET"])
    app.extensions["fullscreen_controls"] = control
    return True
