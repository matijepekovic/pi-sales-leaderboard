"""One source-neutral refresh path for the rep performance report."""
from __future__ import annotations

import time


class RepRefreshService:
    def __init__(self, repos, pull_policy):
        self.repos = repos
        self.pull_policy = pull_policy

    def prepare(self, current_scope=None):
        return self.pull_policy.prepare(current_scope)

    def pull(self, adapter, app_settings, source, report):
        result = adapter.pull_reps(app_settings, source, report)
        rows = self.pull_policy.apply(result.get("scope") or {}, result.get("rows") or [])
        return rows, result

    def refresh(self, adapter, app_settings, source, report):
        rows, result = self.pull(adapter, app_settings, source, report)
        source_name = str(source.get("name") or "Source")
        if not rows:
            self.repos.meta.set("source_status", f"{source_name} returned no matching people")
            return {
                "ok": False,
                "error": f"{source_name} returned no people for this selection. Check the report filters and date range.",
                "total_rows": int(result.get("total_rows") or 0),
                "offices": list(result.get("offices") or []),
            }
        self.repos.reps.replace(rows)
        start = str(result.get("start") or "")
        end = str(result.get("end") or "")
        collapsed = list(result.get("collapsed") or [])
        office = str(result.get("office") or "")
        status = (
            f"{source_name} — {len(rows)} people, {start} to {end}"
            + (f", office {office}" if office else ", all offices")
            + (
                f" — {len(collapsed)} repeated measure(s) counted once: " + ", ".join(collapsed[:6])
                if collapsed else ""
            )
        )
        self.repos.meta.set("source_status", status)
        self.repos.meta.set("last_source_refresh", time.strftime("%Y-%m-%d %H:%M:%S"))
        self.repos.meta.bump("data_version")
        return {
            "ok": True,
            "rows": len(rows),
            "total_rows": int(result.get("total_rows") or 0),
            "offices": list(result.get("offices") or []),
            "start": start,
            "end": end,
            "message": status,
        }
