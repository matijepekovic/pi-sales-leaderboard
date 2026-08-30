"""Explicit display data snapshot selection."""
from __future__ import annotations


class DataSnapshotService:
    def __init__(self, repos, preview, temporary_date):
        self.repos = repos
        self.preview = preview
        self.temporary_date = temporary_date

    def rows(self):
        preview_rows = self.preview.rows()
        if preview_rows is not None:
            return self.repos.reps.apply_organization(preview_rows), "mapping_preview"
        temporary = self.temporary_date.rep_rows()
        if temporary is not None:
            return self.repos.reps.apply_organization(temporary), "temporary_date"
        return self.repos.reps.list(), "stored"
