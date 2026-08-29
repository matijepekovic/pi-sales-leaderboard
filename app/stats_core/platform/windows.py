"""Windows platform adapter.

All Windows-only launching, restart and updater registration is owned here.
Core services do not import Windows modules.
"""
from __future__ import annotations

import os
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import remote_qr_v109
from flask import jsonify


class WindowsPlatform:
    native_display_source = "windows"

    def __init__(self, repos, data_dir: Path, version_service):
        self.repos = repos
        self.data_dir = Path(data_dir)
        self.version_service = version_service
        self.restart_request = self.data_dir / "restart-kiosk.request"

    def native_display_mode(self):
        return 0, 0

    def request_fullscreen(self):
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.restart_request.write_text(str(time.time()), encoding="utf-8")

    @staticmethod
    def restart_application(delay_seconds=1.2):
        threading.Timer(float(delay_seconds), lambda: os._exit(0)).start()

    def updater_facade(self):
        return SimpleNamespace(
            PERSISTENT_DATA_DIR=self.data_dir,
            software_version=self.version_service.current,
        )

    def register(self, app, public_endpoints):
        import windows_update
        import windows_update_status_v128
        import windows_update_diagnostics
        import windows_tableau_login_v124
        import windows_theme_editor_v122

        facade = self.updater_facade()
        windows_update.install(app, facade)
        windows_update_status_v128.install(app, facade)
        windows_update_diagnostics.install(app, facade)
        windows_tableau_login_v124.install(app)
        windows_theme_editor_v122.install(app, public_endpoints)

        if "api_github_status" not in app.view_functions:
            app.add_url_rule(
                "/api/github/status", endpoint="api_github_status", methods=["GET"],
                view_func=lambda: jsonify({
                    "ok": True, "auto_update": False,
                    "installed_version": self.version_service.current(),
                    "remote_version": "", "last_check": "",
                    "status": self.repos.meta.get("github_update_status", "Windows signed-installer updater ready"),
                    "check_minutes": 0,
                }),
            )

        def source_update_disabled():
            return jsonify({
                "ok": False,
                "error": "Source ZIP updates are disabled on Windows. Use the signed Stats installer updater in Software.",
            }), 409

        if "api_github_check" not in app.view_functions:
            app.add_url_rule("/api/github/check", endpoint="api_github_check", methods=["POST"], view_func=source_update_disabled)
        if "api_system_update" not in app.view_functions:
            app.add_url_rule("/api/system/update", endpoint="api_system_update", methods=["POST"], view_func=source_update_disabled)

        self.repos.meta.set("runtime_platform", "windows")
        self.repos.meta.set("kiosk_startup_status", "Windows startup managed by Stats launcher")
        self.repos.meta.set("github_update_status", "Windows signed-installer updater ready")

    def start_remote_qr_refresh(self):
        def refresh_once():
            try:
                url = remote_qr_v109.generate()
                self.repos.meta.set("remote_qr_url", url)
                self.repos.meta.set("remote_qr_error", "")
            except Exception as exc:
                self.repos.meta.set("remote_qr_url", "")
                self.repos.meta.set("remote_qr_error", str(exc))
        refresh_once()
        def worker():
            while True:
                time.sleep(30); refresh_once()
        threading.Thread(target=worker, name="stats-remote-qr", daemon=True).start()
