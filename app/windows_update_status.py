"""Expose the last detached Windows update result to the Software UI."""
from __future__ import annotations

import json
from pathlib import Path

from flask import jsonify

_INSTALLED = False
_ENDPOINT = "api_windows_update_status"


def _latest_status(data_root: Path):
    root = Path(data_root) / "updates" / "windows"
    if not root.exists():
        return None
    files = list(root.glob("*/last-update-status.json"))
    if not files:
        return None
    path = max(files, key=lambda item: item.stat().st_mtime_ns)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    if not isinstance(data, dict):
        return None
    return {
        "state": str(data.get("state") or ""),
        "version": str(data.get("version") or ""),
        "message": str(data.get("message") or ""),
        "time": str(data.get("time") or ""),
        "exit_code": data.get("exit_code"),
    }


def install(app, server_module) -> bool:
    global _INSTALLED
    if _INSTALLED:
        return False

    def status():
        return jsonify({
            "ok": True,
            "status": _latest_status(Path(server_module.PERSISTENT_DATA_DIR)),
        })

    app.add_url_rule(
        "/api/windows/update/status",
        endpoint=_ENDPOINT,
        view_func=status,
        methods=["GET"],
    )
    _INSTALLED = True
    return True
