"""Reusable display Filter definitions.

Filters are semantic user-facing concepts such as Team, Office or Product.
They intentionally do not know report/source field names. Screens own the
mapping from a Filter to concrete fields in the pulled reports they display.
"""
from __future__ import annotations

import uuid

from stats_core.errors import ValidationError


class FilterService:
    def __init__(self, repos):
        self.repos = repos

    def list(self):
        return sorted(self.repos.filters.list(), key=lambda item: str(item.get("name") or "").casefold())

    def get(self, filter_id):
        item = self.repos.filters.get(str(filter_id or "").strip())
        if not item:
            raise ValidationError("Filter not found.")
        return item

    def save(self, incoming):
        incoming = incoming if isinstance(incoming, dict) else {}
        filter_id = str(incoming.get("id") or "").strip() or f"filter-{uuid.uuid4().hex[:12]}"
        name = str(incoming.get("name") or "").strip()[:120]
        if not name:
            raise ValidationError("Filter name is required.")
        for item in self.repos.filters.list():
            if str(item.get("id")) != filter_id and str(item.get("name") or "").strip().casefold() == name.casefold():
                raise ValidationError("A Filter with that name already exists.")
        saved = self.repos.filters.save({"id": filter_id, "name": name})
        self.repos.meta.bump("settings_version")
        return saved

    def delete(self, filter_id):
        filter_id = str(filter_id or "").strip()
        for screen in self.repos.screens.list():
            if filter_id in [str(value) for value in (screen.get("filter_ids") or [])]:
                raise ValidationError("This Filter is used by a Screen. Remove it from that Screen first.")
        if not self.repos.filters.delete(filter_id):
            raise ValidationError("Filter not found.")
        self.repos.meta.bump("settings_version")
        return True
