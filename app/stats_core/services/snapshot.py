"""Explicit display data snapshot selection.

Mapping preview has first priority, temporary date override second, stored reps
last. No module rewrites source_picker.preview_rows at runtime.
"""
from __future__ import annotations

import source_picker


class DataSnapshotService:
    def __init__(self, repos, temporary_date):
        self.repos = repos
        self.temporary_date = temporary_date

    def rows(self):
        preview = source_picker.preview_rows()
        if preview is not None:
            return self.repos.reps.apply_organization(preview), "mapping_preview"
        temporary = self.temporary_date.rep_rows()
        if temporary is not None:
            return self.repos.reps.apply_organization(temporary), "temporary_date"
        return self.repos.reps.list(), "stored"
