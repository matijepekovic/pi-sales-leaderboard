"""Windows-only Tableau connection test endpoint."""
from __future__ import annotations

from flask import jsonify, request

from sources.tableau_configured import ConfiguredTableauSource, config_of
from sources.tableau_v36_base import TableauError


def install(app, settings_repo):
    if "windows_tableau_login_test" in app.view_functions:
        return

    def test_login():
        body = request.get_json(silent=True) or {}
        server = str(body.get("server") or "").strip().rstrip("/")
        site = str(body.get("site") or "").strip()
        pat_name = str(body.get("pat_name") or "").strip()
        pat_secret = str(body.get("pat_secret") or "").strip()

        missing = [
            label
            for label, value in (
                ("Server", server),
                ("Site", site),
                ("PAT token name", pat_name),
            )
            if not value
        ]
        if missing:
            return jsonify({
                "ok": False,
                "error": f"Enter {', '.join(missing)}.",
            }), 400

        settings = dict(settings_repo.get() or {})
        source = dict(settings.get("source") or {})
        source.update({"server": server, "site": site, "pat_name": pat_name})
        settings["source"] = source
        if pat_secret:
            settings["tableau_pat_secret"] = pat_secret

        if not str(settings.get("tableau_pat_secret") or "").strip():
            return jsonify({"ok": False, "error": "Enter the PAT secret."}), 400

        tableau = ConfiguredTableauSource(settings, config_of(settings))
        base = token = None
        try:
            base, token, site_id = tableau.signin()
            return jsonify({
                "ok": True,
                "message": "Connection successful.",
                "site_id": bool(site_id),
            })
        except TableauError as exc:
            return jsonify({"ok": False, "error": str(exc)}), 400
        except Exception:
            return jsonify({
                "ok": False,
                "error": "Could not test the Tableau connection.",
            }), 500
        finally:
            if base and token:
                tableau.signout(base, token)

    app.add_url_rule(
        "/api/windows/tableau-login/test",
        endpoint="windows_tableau_login_test",
        view_func=test_login,
        methods=["POST"],
    )
