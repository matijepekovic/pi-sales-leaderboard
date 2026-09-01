from flask import jsonify

from stats_core.errors import BusyError, ValidationError


def error_response(exc, default_status=400):
    if isinstance(exc, BusyError):
        status = 409
    elif isinstance(exc, PermissionError):
        status = 401
    elif isinstance(exc, (ValidationError, ValueError)):
        status = 400
    else:
        status = default_status
    return jsonify({"ok": False, "error": str(exc)}), status
