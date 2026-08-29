"""Tableau source discovery, preview and manual refresh."""
from __future__ import annotations

import threading

import source_picker
from database import METRIC_DEFS
from sources.tableau import resolve_dates
from stats_core.errors import BusyError, ValidationError
from stats_core.services.tableau import TableauService

SOURCE_FIELDS = (
    "server", "site", "pat_name", "workbook", "sheet", "filters",
    "date_start_field", "date_end_field", "mapping", "row_filter", "export",
)


class SourceService:
    def __init__(self, repos, rep_refresh, tableau=None):
        self.repos = repos; self.rep_refresh = rep_refresh
        self.tableau = tableau or TableauService(); self._refresh_lock = threading.Lock()

    @staticmethod
    def overrides(body):
        body = body if isinstance(body, dict) else {}
        keys = SOURCE_FIELDS + source_picker.DATE_KEYS
        return {key: body[key] for key in keys if key in body}

    def options(self):
        reps = self.repos.reps.list()
        offices = sorted({str(rep.get("home_branch") or "").strip() for rep in reps if str(rep.get("home_branch") or "").strip()})
        names = sorted({str(rep.get("rep_name") or "").strip() for rep in reps if rep.get("rep_name")}, key=str.lower)
        settings = self.tableau.normalized_settings(self.repos.settings.get())
        start, end = resolve_dates(settings)
        return {
            "offices": offices, "names": names, "effective_start": start, "effective_end": end,
            "source_status": self.repos.meta.get("source_status", ""),
            "last_source_refresh": self.repos.meta.get("last_source_refresh", ""),
            "scheduled_tableau_status": self.repos.meta.get("scheduled_tableau_status", ""),
            "scheduled_tableau_last_attempt": self.repos.meta.get("scheduled_tableau_last_attempt", ""),
        }

    def test_connection(self):
        preview = self.tableau.source(self.repos.settings.get()).preview()
        return {
            "start": preview["start"], "end": preview["end"], "total_rows": preview["total_rows"],
            "selected_rows": preview["selected_rows"], "offices": preview["offices"], "names": preview["names"],
            "message": f"Connected. {preview['total_rows']} people in {preview['start']} to {preview['end']}; {preview['selected_rows']} match your selection.",
        }

    def refresh(self):
        if not self._refresh_lock.acquire(blocking=False): raise BusyError("A refresh is already running.")
        try: return self.rep_refresh.refresh(self.repos.settings.get())
        finally: self._refresh_lock.release()

    def _configured_settings(self):
        runtime = self.tableau.normalized_settings(self.repos.settings.get()); source = runtime.get("source") or {}
        missing = [label for label, key in (("Server", "server"), ("Site", "site"), ("PAT token name", "pat_name")) if not str(source.get(key) or "").strip()]
        if missing: raise ValidationError(f"Enter {', '.join(missing)} in Tableau Login first.")
        return runtime

    def report(self):
        runtime = self.tableau.normalized_settings(self.repos.settings.get()); config = dict(runtime.get("source") or {})
        return {
            "row_filter_columns": [{"key": key, "label": label} for key, label, typ in METRIC_DEFS if typ == "text"],
            "workbook": str(config.get("workbook") or ""), "sheet": str(config.get("sheet") or "").rsplit("/", 1)[-1],
            "is_default": False, "default_workbook": "", "default_sheet": "",
            "server": str(config.get("server") or ""), "site": str(config.get("site") or ""), "pat_name": str(config.get("pat_name") or ""),
            "filters": config.get("filters") or [], "date_start_field": str(config.get("date_start_field") or "Start"),
            "date_end_field": str(config.get("date_end_field") or "End"), "row_filter": config.get("row_filter") or {},
            "mapping": config.get("mapping") or {}, "export": str(config.get("export") or "auto"),
            "defaults": {"server": "", "site": "", "pat_name": "", "workbook": "", "sheet": "", "export": "auto", "filters": [], "date_start_field": "Start", "date_end_field": "End", "mapping": {}, "row_filter": {}},
        }

    def workbooks(self): return source_picker.list_workbooks(self._configured_settings())
    def all_views(self): return source_picker.list_all_views(self._configured_settings())
    def views(self, workbook): return source_picker.list_views(self._configured_settings(), workbook)
    def columns(self, body): return source_picker.read_columns(self._configured_settings(), self.overrides(body))

    def preview(self, body):
        body = body if isinstance(body, dict) else {}; overrides = self.overrides(body); on_tv = bool(body.get("on_tv"))
        configured = self._configured_settings()
        start, end, rows, notes = source_picker.preview_pull(configured, overrides)
        if not rows: raise ValidationError("That pull came back with no people, so there is nothing to preview. Check the column mapped to the rep name.")
        config = source_picker.trial_config(configured, overrides)
        if on_tv: source_picker.start_preview(rows, f"{config['workbook']} / {config['sheet']}")
        return {"start": start, "end": end, "reps": len(rows), "notes": notes, "on_tv": on_tv, "preview": source_picker.preview_state(), "rows": self.repos.reps.apply_organization([dict(row) for row in rows])}

    @staticmethod
    def stop_preview():
        source_picker.stop_preview(); return source_picker.preview_state()

    def test_view(self, body): return source_picker.test_source(self._configured_settings(), self.overrides(body))
