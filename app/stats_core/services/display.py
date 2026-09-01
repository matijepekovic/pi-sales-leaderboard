"""Display playback over screen definitions."""
from __future__ import annotations

from stats_core.errors import ValidationError


def screen_id_for_mode(raw):
    raw = str(raw or "whole_office").strip()
    if raw.startswith("per_team::"):
        return f"builtin:per_team:{raw.split('::', 1)[1]}"
    if raw in {"whole_office", "team_vs_team", "all_teams", "product_close"}:
        return f"builtin:{raw}"
    return "builtin:whole_office"


class DisplayService:
    def __init__(self, repos, screens, temporary_date):
        self.repos = repos
        self.screens = screens
        self.temporary_date = temporary_date

    def prepare(self):
        return self.repos.display.ensure(self.repos.settings.get())

    def state(self):
        state = self.repos.display.get()
        return {
            **state,
            "screens": self.screens.list(),
            "temporary_data": self.temporary_date.state(),
        }

    def save(self, incoming):
        incoming = incoming if isinstance(incoming, dict) else {}
        current = self.repos.display.get()
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
        saved = self.repos.display.save(current)
        self._project_builtin_active(saved["active_screen_id"])
        self.repos.meta.bump("settings_version")
        return saved

    def _project_builtin_active(self, screen_id):
        screen = self.screens.get(screen_id)
        if screen.get("kind") != "builtin":
            return
        settings = self.repos.settings.get()
        mode = str(screen.get("mode") or "whole_office")
        settings["active_mode"] = mode
        if mode.startswith("per_team::"):
            settings["per_team_selected"] = mode.split("::", 1)[1]
        self.repos.settings.save(settings)

    def sync_legacy_mode(self, raw_mode):
        screen_id = screen_id_for_mode(raw_mode)
        try:
            self.screens.get(screen_id)
        except ValidationError:
            screen_id = "builtin:whole_office"
        state = self.repos.display.get()
        state["active_screen_id"] = screen_id
        return self.repos.display.save(state)

    def render(self, screen_id=None, **kwargs):
        selected = str(screen_id or self.repos.display.get()["active_screen_id"])
        return self.screens.render(selected, **kwargs)
