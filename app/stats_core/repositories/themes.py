from __future__ import annotations


class ThemeRepository:
    """Persistence for owner-specific Theme values and shared Theme layout."""

    def __init__(self, settings_repo, meta_repo):
        self.settings_repo = settings_repo
        self.meta_repo = meta_repo

    def list_named(self, settings=None):
        settings = settings or self.settings_repo.get()
        raw = settings.get("named_themes")
        return [dict(item) for item in raw if isinstance(item, dict)] if isinstance(raw, list) else []

    def get_named(self, theme_id, settings=None):
        return next((item for item in self.list_named(settings) if str(item.get("id")) == str(theme_id)), None)

    def save_named(self, theme, settings=None):
        settings = settings or self.settings_repo.get()
        settings["named_themes"] = [item for item in self.list_named(settings) if item.get("id") != theme.get("id")] + [dict(theme)]
        self.settings_repo.save(settings)
        return self.meta_repo.bump("settings_version")

    def delete_named(self, theme_id):
        settings = self.settings_repo.get()
        settings["named_themes"] = [item for item in self.list_named(settings) if str(item.get("id")) != str(theme_id)]
        self.settings_repo.save(settings)
        return self.meta_repo.bump("settings_version")

    @staticmethod
    def _screens(settings):
        raw = settings.get("screen_themes")
        return dict(raw) if isinstance(raw, dict) else {}

    def get(self, screen_id, settings=None):
        settings = settings or self.settings_repo.get()
        return dict(self._screens(settings).get(str(screen_id), {}))

    def get_layout(self, settings=None):
        settings = settings or self.settings_repo.get()
        value = settings.get("theme_layout")
        return dict(value) if isinstance(value, dict) else {}

    def save(self, screen_id, config, settings=None, layout=None):
        settings = settings or self.settings_repo.get()
        screens = self._screens(settings)
        screens[str(screen_id)] = dict(config or {})
        settings["screen_themes"] = screens
        if layout is not None:
            settings["theme_layout"] = dict(layout)
        self.settings_repo.save(settings)
        return self.meta_repo.bump("settings_version")

    def delete(self, screen_id, settings=None):
        settings = settings or self.settings_repo.get()
        screens = self._screens(settings)
        screens.pop(str(screen_id), None)
        settings["screen_themes"] = screens
        self.settings_repo.save(settings)
        return self.meta_repo.bump("settings_version")

    @staticmethod
    def _groups(settings):
        raw = settings.get("group_themes")
        return dict(raw) if isinstance(raw, dict) else {}

    def get_group(self, group_id, settings=None):
        settings = settings or self.settings_repo.get()
        return dict(self._groups(settings).get(str(group_id), {}))

    def save_group(self, group_id, config, settings=None, layout=None):
        settings = settings or self.settings_repo.get()
        groups = self._groups(settings)
        groups[str(group_id)] = dict(config or {})
        settings["group_themes"] = groups
        if layout is not None:
            settings["theme_layout"] = dict(layout)
        self.settings_repo.save(settings)
        return self.meta_repo.bump("settings_version")

    def delete_group(self, group_id, settings=None):
        settings = settings or self.settings_repo.get()
        groups = self._groups(settings)
        groups.pop(str(group_id), None)
        settings["group_themes"] = groups
        self.settings_repo.save(settings)
        return self.meta_repo.bump("settings_version")
