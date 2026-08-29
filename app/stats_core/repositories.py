"""Repository boundaries over the existing persistent SQLite implementation.

The database schema is intentionally unchanged. These adapters give each
service a narrow dependency so storage can be reorganized later without
putting SQL/database helpers back into route handlers.
"""
from __future__ import annotations

from pathlib import Path

import database


class MetaRepository:
    def get(self, key, default=""):
        return database.get_meta(key, default)

    def set(self, key, value):
        return database.set_meta(key, value)

    def bump(self, key):
        try:
            value = int(self.get(key, "0") or 0) + 1
        except Exception:
            value = 1
        self.set(key, value)
        return value


class SettingsRepository:
    def get(self):
        return database.get_settings()

    def save(self, settings):
        return database.save_settings(settings)


class RepRepository:
    def list(self):
        return database.list_reps()

    def replace(self, rows):
        return database.replace_reps(rows)

    def apply_organization(self, rows):
        return database.apply_team_overlay(rows)


class OrganizationRepository:
    def list_team_names(self):
        return database.list_teams()

    def definitions(self, include_inactive=False):
        return database.get_team_definitions(include_inactive=include_inactive)

    def save_builder(self, team_id, name, leader_name, leader_role, member_rep_keys):
        return database.save_team_builder(
            team_id, name, leader_name, leader_role, member_rep_keys
        )

    def create(self, name):
        return database.create_team(name)

    def rename(self, team_id, name):
        return database.rename_team(team_id, name)

    def delete(self, team_id, reassignments):
        return database.delete_team(team_id, reassignments)

    def set_leader(self, team_id, name, role):
        return database.set_team_lead(team_id, name, role)

    def delete_leader(self, lead_id):
        return database.delete_team_lead(lead_id)

    def assign_reps(self, assignments):
        return database.set_rep_team_assignments(assignments)

    def set_logo(self, team_id, path):
        return database.set_team_logo(team_id, path)


class ProductRepository:
    def list(self):
        return database.get_product_close()

    def replace(self, rows):
        return database.replace_product_close(rows)


class Repositories:
    def __init__(self):
        self.meta = MetaRepository()
        self.settings = SettingsRepository()
        self.reps = RepRepository()
        self.organization = OrganizationRepository()
        self.products = ProductRepository()


def persistent_data_dir() -> Path:
    return Path.home() / ".local" / "share" / "pi-tableau-leaderboard"
