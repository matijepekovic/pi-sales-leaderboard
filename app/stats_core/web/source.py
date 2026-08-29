from flask import Blueprint, jsonify, request
from stats_core.web.common import error_response


def blueprint(service):
    bp = Blueprint("source", __name__)

    @bp.get("/api/source/options")
    def options(): return jsonify({"ok": True, **service.options()})

    @bp.post("/api/source/test")
    def test():
        try: return jsonify({"ok": True, **service.test_connection()})
        except Exception as exc: return error_response(exc)

    @bp.post("/api/source/refresh")
    def refresh():
        try:
            result = service.refresh(); return jsonify(result), (200 if result.get("ok") else 400)
        except Exception as exc: return error_response(exc)

    @bp.get("/api/source/report")
    def report(): return jsonify({"ok": True, **service.report()})

    @bp.get("/api/source/workbooks")
    def workbooks():
        try: return jsonify({"ok": True, "workbooks": service.workbooks()})
        except Exception as exc: return error_response(exc)

    @bp.get("/api/source/views")
    def all_views():
        try: return jsonify({"ok": True, "views": service.all_views()})
        except Exception as exc: return error_response(exc)

    @bp.get("/api/source/workbooks/<path:workbook>/views")
    def views(workbook):
        try: return jsonify({"ok": True, "views": service.views(workbook)})
        except Exception as exc: return error_response(exc)

    @bp.post("/api/source/columns")
    def columns():
        try: return jsonify({"ok": True, **service.columns(request.get_json(silent=True) or {})})
        except Exception as exc: return error_response(exc)

    @bp.post("/api/source/preview")
    def preview():
        try: return jsonify({"ok": True, **service.preview(request.get_json(silent=True) or {})})
        except Exception as exc: return error_response(exc)

    @bp.post("/api/source/preview/stop")
    def stop_preview(): return jsonify({"ok": True, "preview": service.stop_preview()})

    @bp.post("/api/source/test-view")
    def test_view():
        try: return jsonify({"ok": True, **service.test_view(request.get_json(silent=True) or {})})
        except Exception as exc: return error_response(exc)

    return bp
