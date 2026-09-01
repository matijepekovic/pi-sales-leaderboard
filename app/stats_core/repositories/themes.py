from __future__ import annotations


class ThemeRepository:
    def __init__(self, settings_repo, meta_repo):
        self.settings_repo = settings_repo
        self.meta_repo = meta_repo

    @staticmethod
    def _store_from(settings):
        raw = settings.get("theme_config")
        if not isinstance(raw, dict):
            raw = {}
        teams = raw.get("teams") if isinstance(raw.get("teams"), dict) else {}
        screens = raw.get("screens") if isinstance(raw.get("screens"), dict) else {}
        return {"teams": dict(teams), "screens": dict(screens)}

    def store(self, settings=None):
        settings = settings or self.settings_repo.get()
        return self._store_from(settings)

    def get(self, team_id, settings=None):
        return dict(self.store(settings)["teams"].get(str(int(team_id)), {}))

    def save(self, team_id, config, settings=None):
        settings = settings or self.settings_repo.get()
        store = self._store_from(settings)
        store["teams"][str(int(team_id))] = dict(config or {})
        settings["theme_config"] = store
        self.settings_repo.save(settings)
        return self.meta_repo.bump("settings_version")

    def get_screen(self, screen_id, settings=None):
        return dict(self.store(settings)["screens"].get(str(screen_id), {}))

    def save_screen(self, screen_id, config, settings=None):
        settings = settings or self.settings_repo.get()
        store = self._store_from(settings)
        store["screens"][str(screen_id)] = dict(config or {})
        settings["theme_config"] = store
        self.settings_repo.save(settings)
        return self.meta_repo.bump("settings_version")

    def delete_screen(self, screen_id, settings=None):
        settings = settings or self.settings_repo.get()
        store = self._store_from(settings)
        store["screens"].pop(str(screen_id), None)
        settings["theme_config"] = store
        self.settings_repo.save(settings)
        return self.meta_repo.bump("settings_version")

    def save_store(self, store, settings=None):
        settings = settings or self.settings_repo.get()
        settings["theme_config"] = {
            "teams": dict((store or {}).get("teams") or {}),
            "screens": dict((store or {}).get("screens") or {}),
        }
        self.settings_repo.save(settings)
        return self.meta_repo.bump("settings_version")
