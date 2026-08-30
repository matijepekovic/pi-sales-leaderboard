from __future__ import annotations

import re

from stats_core.theme.catalog import (
    ALLOWED_BASES, ASSETS, CLASSIC_COLORS, CORNER_ASSET_KEYS,
    DEFAULT_CORNER_SETTINGS, STARTER_COLORS, STARTER_FILES, UNDISPUTED_COLORS,
)

COLOR_RE = re.compile(r"^#[0-9a-fA-F]{6}$")


class ThemeConfigMixin:
    def prepare(self):
        self.applied.root.mkdir(parents=True, exist_ok=True)
        changed = self.ensure_all_applied_assets()
        self.repos.meta.set("theme_asset_store_status", f"Applied theme assets protected in {self.applied.root}")
        return changed

    def _teams(self, include_inactive=False):
        return {int(t["team_id"]): t for t in self.repos.organization.definitions(include_inactive=include_inactive)}

    def parse_scope(self, scope, allow_inactive=False):
        scope = str(scope or "").strip().lower()
        if scope == "office":
            raise ValueError("Whole Office inherits the theme of its #1 rep's team and cannot have its own theme.")
        if not scope.startswith("team-"):
            raise ValueError("Theme scope must be team-<id>.")
        try:
            team_id = int(scope.split("-", 1)[1])
        except Exception as exc:
            raise ValueError("Invalid team theme scope.") from exc
        team = self._teams(include_inactive=allow_inactive).get(team_id)
        if not team:
            raise ValueError("Team not found.")
        return f"team-{team_id}", team

    @staticmethod
    def base_colors(base):
        if base == "undisputed": return dict(UNDISPUTED_COLORS)
        if base == "starter": return dict(STARTER_COLORS)
        return dict(CLASSIC_COLORS)

    @staticmethod
    def bounded(value, default, low, high):
        try: value = float(value)
        except Exception: value = float(default)
        return round(min(max(value, low), high), 2)

    def clean_colors(self, incoming, base):
        colors = self.base_colors(base)
        if isinstance(incoming, dict):
            for key in colors:
                value = str(incoming.get(key) or "").strip()
                if COLOR_RE.match(value): colors[key] = value.lower()
        return colors

    def clean_corners(self, incoming):
        if not isinstance(incoming, dict): return {}
        out = {}
        for key in CORNER_ASSET_KEYS:
            row = incoming.get(key)
            if isinstance(row, dict):
                out[key] = {
                    "size": self.bounded(row.get("size"), 100, 50, 600),
                    "crop_x": self.bounded(row.get("crop_x"), 0, 0, 60),
                    "crop_y": self.bounded(row.get("crop_y"), 0, 0, 60),
                }
        return out

    def clean_stripe(self, incoming, colors):
        color = str((colors or {}).get("primary") or "#d8b34a").lower()
        strength = 0.0
        if isinstance(incoming, dict):
            candidate = str(incoming.get("color") or "").strip()
            if COLOR_RE.match(candidate): color = candidate.lower()
            strength = self.bounded(incoming.get("strength"), 0, 0, 100)
        return {"color": color, "strength": strength}

    def _starter_source(self, key):
        filename = STARTER_FILES.get(key)
        path = self.applied.theme_pack_root / "starter" / filename if filename else None
        return path if path and path.is_file() else None

    def _materialize(self, scope, team, config):
        result = dict(config or {})
        base = str(result.get("base") or "starter").lower()
        if base not in ALLOWED_BASES: base = "starter"
        result["base"] = base
        assets = dict(result.get("assets") or {}) if isinstance(result.get("assets"), dict) else {}
        changed = False
        for key in ASSETS:
            filename = self.applied.safe_filename(assets.get(key))
            destination = self.applied.path(scope, filename) if filename else None
            if destination and destination.exists(): continue
            if filename:
                legacy = self.applied.legacy_path(scope, filename)
                if legacy and legacy.exists():
                    self.applied.copy_verified(legacy, self.applied.root / scope / filename)
                    continue
            if base == "starter":
                source = self._starter_source(key)
                if source:
                    filename = f"{key}{source.suffix.lower()}"
                    self.applied.copy_verified(source, self.applied.root / scope / filename)
                    if assets.get(key) != filename:
                        assets[key] = filename; changed = True
        result["assets"] = assets
        return result, changed

    def ensure_all_applied_assets(self):
        settings = self.repos.settings.get(); store = self.theme_repo.store(settings); changed = False
        for team in self.repos.organization.definitions(include_inactive=True):
            tid = int(team["team_id"]); scope = f"team-{tid}"
            current = dict(store["teams"].get(str(tid), {}))
            materialized, touched = self._materialize(scope, team, current)
            if touched or store["teams"].get(str(tid)) != materialized:
                store["teams"][str(tid)] = materialized; changed = True
        if changed: self.theme_repo.save_store(store, settings)
        return changed

    def _stored(self, team, settings=None):
        return self.theme_repo.get(int(team["team_id"]), settings=settings)

    def _save(self, team, config, settings=None):
        scope = f"team-{int(team['team_id'])}"
        config, _ = self._materialize(scope, team, config)
        return self.theme_repo.save(int(team["team_id"]), config, settings=settings)

    def effective_theme(self, scope, settings=None, team=None):
        settings = settings or self.repos.settings.get()
        if team is None: _scope, team = self.parse_scope(scope, allow_inactive=True)
        config = self._stored(team, settings); config, changed = self._materialize(scope, team, config)
        if changed:
            self.theme_repo.save(int(team["team_id"]), config, settings=settings)
            settings = self.repos.settings.get()
        base = str(config.get("base") or "starter").lower()
        if base not in ALLOWED_BASES: base = "starter"
        colors = self.clean_colors(config.get("colors"), base)
        version = int(self.repos.meta.get("settings_version", "0") or 0)
        assets_cfg = config.get("assets") if isinstance(config.get("assets"), dict) else {}
        assets = {}
        for key in ASSETS:
            filename = assets_cfg.get(key); path = self.applied.path(scope, filename) if filename else None
            assets[key] = f"/api/theme-assets/{scope}/{key}?v={version}" if path and path.exists() else None
        corners = self.clean_corners(config.get("corner_settings"))
        return {
            "scope": scope, "base": base, "enabled": bool(config.get("enabled", base != "classic")),
            "colors": colors, "assets": assets,
            "corner_settings": {k: {**DEFAULT_CORNER_SETTINGS, **corners.get(k, {})} for k in CORNER_ASSET_KEYS},
            "hero_scale": self.bounded(config.get("hero_scale"), 100, 50, 200),
            "row_stripe": self.clean_stripe(config.get("row_stripe"), colors),
            "has_custom_assets": bool(assets_cfg),
        }

    def display_state(self, settings=None):
        self.ensure_all_applied_assets(); settings = settings or self.repos.settings.get()
        teams, by_name = {}, {}
        for team in self.repos.organization.definitions():
            tid = int(team["team_id"]); theme = self.effective_theme(f"team-{tid}", settings, team)
            theme.update({"team_id": tid, "team_name": team["name"]})
            teams[str(tid)] = theme; by_name[str(team["name"]).strip().lower()] = theme
        return {"teams": teams, "by_name": by_name}

    def manifest(self):
        return {
            "presets": [
                {"key": "starter", "label": "Starter"}, {"key": "classic", "label": "Plain"},
                {"key": "undisputed", "label": "UNDISPUTED (existing)"},
            ],
            "colors": [{"key": k, "label": l} for k, l in (
                ("primary","Primary"),("primary_bright","Primary Bright"),("primary_dark","Primary Dark"),
                ("secondary","Secondary"),("background","Background"),("panel","Panel"),
                ("text","Text"),("muted","Muted Text"),("champion_text","Champion Text"),
            )],
            "assets": [{"key": k, "label": v["label"], "adjustable": bool(v.get("adjustable"))} for k,v in ASSETS.items()],
            "corner_controls": {
                "size":{"min":50,"max":600,"step":5,"default":100},
                "crop_x":{"min":0,"max":60,"step":1,"default":0},
                "crop_y":{"min":0,"max":60,"step":1,"default":0},
            },
            "theme_controls": {
                "hero_scale":{"min":50,"max":200,"step":5,"default":100},
                "row_stripe_strength":{"min":0,"max":100,"step":5,"default":0},
            },
        }

    def public_teams(self):
        version = int(self.repos.meta.get("organization_version", "0") or 0)
        return [{
            "team_id": int(t["team_id"]), "name": t["name"],
            "logo_url": f"/api/teams/{int(t['team_id'])}/logo?v={version}" if t.get("logo_path") else None,
        } for t in self.repos.organization.definitions()]

    def save_theme(self, scope, incoming):
        normalized, team = self.parse_scope(scope); settings = self.repos.settings.get(); current = self._stored(team, settings)
        base = str(incoming.get("base") or current.get("base") or "starter").lower()
        if base not in ALLOWED_BASES: raise ValueError("Unknown theme preset.")
        current["base"] = base
        if isinstance(incoming.get("enabled"), bool): current["enabled"] = incoming["enabled"]
        else: current.setdefault("enabled", base != "classic")
        current["colors"] = self.clean_colors(incoming.get("colors", current.get("colors")), base)
        current.setdefault("assets", {})
        corners = self.clean_corners(current.get("corner_settings"))
        if isinstance(incoming.get("corner_settings"), dict): corners.update(self.clean_corners(incoming["corner_settings"]))
        current["corner_settings"] = corners
        current["hero_scale"] = self.bounded(incoming.get("hero_scale", current.get("hero_scale")), 100, 50, 200)
        current["row_stripe"] = self.clean_stripe(incoming.get("row_stripe", current.get("row_stripe")), current["colors"])
        version = self._save(team, current, settings)
        return version, self.effective_theme(normalized, self.repos.settings.get(), team)

    def reset_theme(self, scope):
        normalized, team = self.parse_scope(scope)
        config = {"base":"starter","enabled":True,"colors":dict(STARTER_COLORS),"assets":{},"corner_settings":{},"hero_scale":100.0,"row_stripe":{"color":STARTER_COLORS["primary"],"strength":0.0}}
        version = self._save(team, config)
        return version, self.effective_theme(normalized, self.repos.settings.get(), team)

