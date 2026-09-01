"""Display playback over normalized Screen definitions."""
from __future__ import annotations

import time

from stats_core.errors import ValidationError


class DisplayService:
    DEFAULT_SCREEN_ID = "builtin:whole_office"

    def __init__(self, repos, screens, temporary_date):
        self.repos = repos
        self.screens = screens
        self.temporary_date = temporary_date

    def prepare(self):
        self.repos.display.ensure()
        return self._state()

    def _state(self):
        state = self.repos.display.get()
        valid = {str(screen.get("id")) for screen in self.screens.list() if screen.get("id")}
        fallback = self.DEFAULT_SCREEN_ID if self.DEFAULT_SCREEN_ID in valid else next(iter(valid), self.DEFAULT_SCREEN_ID)
        active = str(state.get("active_screen_id") or fallback)
        rotation = [
            str(screen_id) for screen_id in (state.get("rotation_screen_ids") or [])
            if str(screen_id) in valid
        ]
        changed = False
        if active not in valid:
            active = fallback
            changed = True
        if rotation != list(state.get("rotation_screen_ids") or []):
            changed = True
        state["active_screen_id"] = active
        state["rotation_screen_ids"] = rotation
        if changed:
            state = self.repos.display.save(state)
        return state

    def state(self):
        state = self._state()
        return {
            **state,
            "current_screen_id": self.current_screen_id(state),
            "screens": self.screens.list(),
            "temporary_data": self.temporary_date.state(),
        }

    def current_screen_id(self, state=None):
        state = state or self._state()
        rotation = list(state.get("rotation_screen_ids") or [])
        if state.get("rotation_enabled") and rotation:
            seconds = max(5, int(state.get("rotation_seconds") or 15))
            return rotation[int(time.time() // seconds) % len(rotation)]
        return str(state.get("active_screen_id") or self.DEFAULT_SCREEN_ID)

    def save(self, incoming):
        incoming = incoming if isinstance(incoming, dict) else {}
        current = self._state()
        if "active_screen_id" in incoming:
            active = str(incoming.get("active_screen_id") or "").strip()
            self.screens.get(active)
            current["active_screen_id"] = active
        if isinstance(incoming.get("rotation_screen_ids"), list):
            rotation = []
            for value in incoming["rotation_screen_ids"]:
                screen_id = str(value or "").strip()
                if not screen_id or screen_id in rotation:
                    continue
                self.screens.get(screen_id)
                rotation.append(screen_id)
            current["rotation_screen_ids"] = rotation[:50]
        if "rotation_enabled" in incoming:
            current["rotation_enabled"] = bool(incoming.get("rotation_enabled"))
        if "rotation_seconds" in incoming:
            try:
                current["rotation_seconds"] = min(max(int(incoming.get("rotation_seconds") or 15), 5), 3600)
            except Exception:
                raise ValidationError("Rotation time must be between 5 and 3600 seconds.")
        saved = self.repos.display.save(current)
        self.repos.meta.bump("settings_version")
        return {**saved, "current_screen_id": self.current_screen_id(saved)}

    def render(self, screen_id=None, **kwargs):
        selected = str(screen_id or self.current_screen_id())
        return self.screens.render(selected, **kwargs)
