"""Physical/keyboard/mouse/QR control configuration."""
from __future__ import annotations

from stats_core.errors import ValidationError

ACTIONS = ("previous", "next", "pair", "sort_prev", "sort_next")
DEFAULT_KEYS = {
    "previous": "ArrowLeft",
    "next": "ArrowRight",
    "pair": "ArrowUp",
    "sort_prev": "MouseWheelUp",
    "sort_next": "MouseWheelDown",
}
ALLOWED_INPUTS = (
    "ArrowLeft", "ArrowRight", "ArrowUp", "ArrowDown",
    *tuple(chr(code) for code in range(ord("a"), ord("z") + 1)),
    *tuple(str(n) for n in range(10)),
    "PageUp", "PageDown", "Home", "End", "Enter", " ", "[", "]",
    "MouseWheelUp", "MouseWheelDown",
    "MouseLeft", "MouseRight", "MouseMiddle",
)
_ALLOWED_SET = set(ALLOWED_INPUTS)

QR_DEFAULT_SIZE = 68
QR_DEFAULT_X = 100.0
QR_DEFAULT_Y = 0.0


class ControlsService:
    def __init__(self, repos, screens):
        self.repos = repos
        self.screens = screens

    def available_views(self):
        return self.screens.cycle_views()

    @staticmethod
    def _normalize_input(value):
        raw = str(value or "")
        if raw == " ":
            return " "
        value = raw.strip()
        aliases = {
            "left": "ArrowLeft", "arrowleft": "ArrowLeft",
            "right": "ArrowRight", "arrowright": "ArrowRight",
            "up": "ArrowUp", "arrowup": "ArrowUp",
            "down": "ArrowDown", "arrowdown": "ArrowDown",
            "pageup": "PageUp", "pagedown": "PageDown",
            "home": "Home", "end": "End", "enter": "Enter", "return": "Enter",
            "space": " ", "spacebar": " ",
            "mousewheelup": "MouseWheelUp", "wheelup": "MouseWheelUp",
            "mousewheeldown": "MouseWheelDown", "wheeldown": "MouseWheelDown",
            "mouseleft": "MouseLeft", "leftclick": "MouseLeft",
            "mouseright": "MouseRight", "rightclick": "MouseRight",
            "mousemiddle": "MouseMiddle", "middleclick": "MouseMiddle",
        }
        lowered = value.lower()
        if lowered in aliases:
            return aliases[lowered]
        if len(value) == 1:
            value = value.lower()
        return value if value in _ALLOWED_SET else ""

    def clean_keys(self, settings=None):
        settings = settings or self.repos.settings.get()
        raw = settings.get("keyboard_cycle_keys")
        raw = raw if isinstance(raw, dict) else {}
        cleaned, used = {}, set()
        for action in ACTIONS:
            candidate = self._normalize_input(raw.get(action)) or DEFAULT_KEYS[action]
            if candidate in used:
                candidate = DEFAULT_KEYS[action]
            if candidate in used:
                candidate = next(value for value in ALLOWED_INPUTS if value not in used)
            cleaned[action] = candidate
            used.add(candidate)
        return cleaned

    def current(self, settings=None):
        settings = settings or self.repos.settings.get()
        available = self.available_views()
        raw_views = settings.get("keyboard_cycle_views")
        if isinstance(raw_views, list):
            views = [str(value) for value in raw_views if str(value) in available]
        else:
            views = list(available)
        if not views:
            views = list(available[:1])
        return {"views": views, "keys": self.clean_keys(settings)}

    def save(self, body):
        body = body if isinstance(body, dict) else {}
        settings = self.repos.settings.get()
        available = self.available_views()
        if "views" in body:
            if not isinstance(body.get("views"), list):
                raise ValidationError("Screens must be a list.")
            selected = []
            for raw in body["views"]:
                value = str(raw)
                if value in available and value not in selected:
                    selected.append(value)
            if not selected:
                raise ValidationError("Select at least one screen.")
            settings["keyboard_cycle_views"] = selected
        if "keys" in body:
            raw_keys = body.get("keys")
            if not isinstance(raw_keys, dict):
                raise ValidationError("Map Keys must be an object.")
            current = self.clean_keys(settings)
            keys = {}
            for action in ACTIONS:
                value = self._normalize_input(raw_keys.get(action)) or current[action]
                if value not in _ALLOWED_SET:
                    raise ValidationError("Choose an input from the dropdown.")
                keys[action] = value
            if len(set(keys.values())) != len(keys):
                raise ValidationError("Each control must use a different input.")
            settings["keyboard_cycle_keys"] = keys
        self.repos.settings.save(settings)
        self.repos.meta.bump("settings_version")
        return self.current(settings)

    @staticmethod
    def _bounded(value, default, minimum, maximum):
        try:
            value = float(value)
        except Exception:
            value = float(default)
        return min(max(value, minimum), maximum)

    def qr_current(self, settings=None):
        settings = settings or self.repos.settings.get()
        return {
            "size": int(round(self._bounded(settings.get("qr_overlay_size"), QR_DEFAULT_SIZE, 36, 180))),
            "x": round(self._bounded(settings.get("qr_overlay_x"), QR_DEFAULT_X, 0, 100), 2),
            "y": round(self._bounded(settings.get("qr_overlay_y"), QR_DEFAULT_Y, 0, 100), 2),
        }

    def save_qr(self, body):
        body = body if isinstance(body, dict) else {}
        settings = self.repos.settings.get()
        current = self.qr_current(settings)
        config = {
            "size": int(round(self._bounded(body.get("size"), current["size"], 36, 180))),
            "x": round(self._bounded(body.get("x"), current["x"], 0, 100), 2),
            "y": round(self._bounded(body.get("y"), current["y"], 0, 100), 2),
        }
        settings["qr_overlay_size"] = config["size"]
        settings["qr_overlay_x"] = config["x"]
        settings["qr_overlay_y"] = config["y"]
        self.repos.settings.save(settings)
        self.repos.meta.bump("settings_version")
        return config
