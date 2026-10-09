"""Independent scheduled Salesforce report-printing job contract.

No Gmail, Gallery, CUPS, or Salesforce-specific implementation dependencies.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from .print_options import PrintOptions, FIELDS


@dataclass(frozen=True)
class ScheduledReport:
    report_id: str
    name: str
    overrides: dict[str, str]

    def effective_options(self, defaults: PrintOptions) -> PrintOptions:
        return defaults.apply(self.overrides)


@dataclass(frozen=True)
class ReportPrintingJob:
    job_id: str
    name: str
    timezone: str
    hour: int
    minute: int
    weekdays: tuple[int, ...]
    defaults: PrintOptions
    reports: tuple[ScheduledReport, ...]
    enabled: bool = True

    def __post_init__(self):
        if not self.name.strip() or not self.name.isprintable():
            raise ValueError('Job name is required.')
        if not 0 <= self.hour <= 23 or not 0 <= self.minute <= 59:
            raise ValueError('Invalid scheduled time.')
        if not self.weekdays or any(type(day) is not int or day not in range(7) for day in self.weekdays):
            raise ValueError('Select at least one valid weekday.')
        ZoneInfo(self.timezone)
        if not self.reports:
            raise ValueError('Select at least one report.')
        ids = [r.report_id for r in self.reports]
        if len(ids) != len(set(ids)):
            raise ValueError('Duplicate report in printing job.')
        for report in self.reports:
            if not report.report_id or not report.name.strip():
                raise ValueError('Report ID and name are required.')
            if not set(report.overrides) <= FIELDS:
                raise ValueError('Unsupported report print override.')
            report.effective_options(self.defaults)

    def due_occurrences(self, since: datetime, until: datetime):
        """Return local scheduled dates after since, through until.

        Callers persist an occurrence key before execution, ensuring restarts
        cannot silently submit the same report twice.
        """
        zone = ZoneInfo(self.timezone)
        start = since.astimezone(zone).date()
        end = until.astimezone(zone).date()
        current = start
        while current <= end:
            if self.enabled and current.weekday() in self.weekdays:
                scheduled = datetime(current.year, current.month, current.day,
                                     self.hour, self.minute, tzinfo=zone)
                if since < scheduled <= until:
                    yield scheduled
            current += timedelta(days=1)
