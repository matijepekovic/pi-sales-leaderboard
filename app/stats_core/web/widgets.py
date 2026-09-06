"""HTTP boundary for Widget definitions and real-data previews."""
from flask import Blueprint, jsonify, request

from stats_core.errors import ValidationError
from stats_core.web.common import error_response


def blueprint(widgets):
    bp = Blueprint("widgets", __name__)

    def body():
        value = request.get_json(silent=True)
        if not isinstance(value, dict):
            raise ValidationError("Widget requests must contain a JSON object.")
        return value

    @bp.get("/api/widgets")
    def list_widgets():
        try:
            return jsonify({"ok": True, "widgets": widgets.list()})
        except Exception as exc:
            return error_response(exc)

    @bp.get("/api/widgets/<widget_id>")
    def get_widget(widget_id):
        try:
            return jsonify({"ok": True, "widget": widgets.get(widget_id)})
        except Exception as exc:
            return error_response(exc)

    @bp.post("/api/widgets")
    def create_widget():
        try:
            return jsonify({"ok": True, "widget": widgets.save(body())})
        except Exception as exc:
            return error_response(exc)

    @bp.put("/api/widgets/<widget_id>")
    def update_widget(widget_id):
        try:
            return jsonify({"ok": True, "widget": widgets.save(body(), widget_id)})
        except Exception as exc:
            return error_response(exc)

    @bp.delete("/api/widgets/<widget_id>")
    def delete_widget(widget_id):
        try:
            widgets.delete(widget_id)
            return jsonify({"ok": True})
        except Exception as exc:
            return error_response(exc)

    @bp.post("/api/widgets/preview")
    def preview_widget():
        try:
            incoming = body()
            if "widget" in incoming and set(incoming) - {"widget", "context"}:
                raise ValidationError("Widget preview requests may contain only the Widget and its context.")
            definition = incoming.get("widget") if "widget" in incoming else {key: value for key, value in incoming.items() if key != "context"}
            return jsonify({"ok": True, "payload": widgets.preview(definition, incoming.get("context"))})
        except Exception as exc:
            return error_response(exc)

    return bp
