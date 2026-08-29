from flask import Blueprint, jsonify, render_template, request
from stats_core.web.common import error_response


def blueprint(service):
    bp = Blueprint("product", __name__)

    @bp.get("/preview/products")
    def preview(): return render_template("product_preview.html")

    @bp.get("/api/product-close")
    def product_close(): return jsonify({"ok": True, "beta": False, **service.current_payload()})

    @bp.post("/api/product-close/refresh")
    def refresh():
        try: service.refresh(); return jsonify({"ok": True, **service.current_payload()})
        except Exception as exc: return error_response(exc)

    @bp.get("/api/product-markets")
    def markets():
        values, warning = service.market_choices()
        data = {"ok": True, "markets": values, "selected": service.current_payload()["market"]}
        if warning: data["warning"] = warning
        return jsonify(data)

    @bp.post("/api/product-market")
    def set_market():
        try:
            payload, warning = service.set_market((request.get_json(silent=True) or {}).get("market"))
            data = {"ok": True, **payload}
            if warning: data["warning"] = warning
            return jsonify(data)
        except Exception as exc: return error_response(exc)

    return bp
