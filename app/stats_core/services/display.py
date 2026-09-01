"""Display playback over normalized screen definitions."""
from __future__ import annotations

import time

from stats_core.errors import ValidationError


class DisplayService:
    def __init__(self, repos, screens, temporary_date):
        self.repos = repos
        self.screens = screens
        self.temporary_date = temporary_date

    def prepare(self): return self.repos.display.ensure(self.repos.settings.get())

    def state(self):
        state = self.repos.display.get()
        return {**state, "current_screen_id": self.current_screen_id(state), "screens": self.screens.list(), "temporary_data": self.temporary_date.state()}

    def current_screen_id(self, state=None):
        state = state or self.repos.display.get()
        rotation = list(state.get("rotation_screen_ids") or [])
        if state.get("rotation_enabled") and rotation:
            seconds = max(5, int(state.get("rotation_seconds") or 15))
            return rotation[int(time.time() // seconds) % len(rotation)]
        return str(state.get("active_screen_id") or "builtin:whole_office")

    def save(self, incoming):
        incoming = incoming if isinstance(incoming, dict) else {}; current = self.repos.display.get()
        if "active_screen_id" in incoming:
            active = str(incoming.get("active_screen_id") or "").strip(); self.screens.get(active); current["active_screen_id"] = active
        if isinstance(incoming.get("rotation_screen_ids"), list):
            rotation = []
            for value in incoming["rotation_screen_ids"]:
                screen_id = str(value or "").strip()
                if not screen_id or screen_id in rotation: continue
                self.screens.get(screen_id); rotation.append(screen_id)
            current["rotation_screen_ids"] = rotation[:50]
        if "rotation_enabled" in incoming: current["rotation_enabled"] = bool(incoming.get("rotation_enabled"))
        if "rotation_seconds" in incoming:
            try: current["rotation_seconds"] = min(max(int(incoming.get("rotation_seconds") or 15), 5), 3600)
            except Exception: raise ValidationError("Rotation time must be between 5 and 3600 seconds.")
        saved = self.repos.display.save(current); self.repos.meta.bump("settings_version")
        return {**saved, "current_screen_id": self.current_screen_id(saved)}

    def render(self, screen_id=None, **kwargs):
        selected = str(screen_id or self.current_screen_id())
        return self.screens.render(selected, **kwargs)
