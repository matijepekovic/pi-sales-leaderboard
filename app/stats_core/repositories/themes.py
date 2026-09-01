from __future__ import annotations


class ThemeRepository:
    """Persistence for custom Screen themes."""

    def __init__(self, settings_repo, meta_repo):
        self.settings_repo = settings_repo
        self.meta_repo = meta_repo

    @staticmethod
    def _screens(settings):
        raw = settings.get("screen_themes")
        return dict(raw) if isinstance(raw, dict) else {}

    def get(self, screen_id, settings=None):
        settings = settings or self.settings_repo.get()
        return dict(self._screens(settings).get(str(screen_id), {}))

    def save(self, screen_id, config, settings=None):
        settings = settings or self.settings_repo.get()
        screens = self._screens(settings)
        screens[str(screen_id)] = dict(config or {})
        settings["screen_themes"] = screens
        self.settings_repo.save(settings)
        return self.meta_repo.bump("settings_version")

    def delete(self, screen_id, settings=None):
        settings = settings or self.settings_repo.get()
        screens = self._screens(settings)
        screens.pop(str(screen_id), None)
        settings["screen_themes"] = screens
        self.settings_repo.save(settings)
        return self.meta_repo.bump("settings_version")
