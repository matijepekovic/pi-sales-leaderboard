"""Permanent daily MOD-sheet settings and fixed weekday schedule."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from ..print_options import PrintOptions


WEEKDAYS = frozenset({0, 1, 2, 3, 4})
DAILY_PRINT_TIME = time(7, 0)
RETRY_DELAY_SECONDS = 120


@dataclass(frozen=True)
class ModSheetAutomationSettings:
    market_segment: str = ''
    product_category: str = 'All'
    source_type: str = 'All'
    assigned_service_resource: str = ''
    remove_canceled: bool = True
    remove_unconfirmed: bool = True
    color_code: bool = True
    print_options: PrintOptions = field(default_factory=PrintOptions)

    def __post_init__(self):
        for value in (
            self.market_segment, self.product_category, self.source_type,
            self.assigned_service_resource,
        ):
            if not isinstance(value, str) or len(value) > 128 or any(not c.isprintable() for c in value):
                raise ValueError('MOD Sheet settings must be short single-line values.')
        if not isinstance(self.print_options, PrintOptions):
            raise ValueError('MOD Sheet print settings are invalid.')

    def as_dict(self):
        value = asdict(self)
        value['print_options'] = self.print_options.snapshot()
        return value

    @classmethod
    def from_dict(cls, value):
        if not isinstance(value, dict):
            raise ValueError('MOD Sheet settings are invalid.')
        data = dict(value)
        raw_print = data.pop('print_options', None)
        print_options = PrintOptions(**raw_print) if isinstance(raw_print, dict) else PrintOptions()
        return cls(print_options=print_options, **data)


@dataclass(frozen=True)
class DailyOccurrence:
    day: str
    display_date: str
    scheduled_for: float


class DailyModSheetSchedule:
    def __init__(self, timezone: str):
        self.timezone = timezone
        self.zone = ZoneInfo(timezone)

    def occurrence_due(self, stamp: float) -> DailyOccurrence | None:
        local = datetime.fromtimestamp(stamp, self.zone)
        if local.weekday() not in WEEKDAYS:
            return None
        scheduled = datetime.combine(local.date(), DAILY_PRINT_TIME, self.zone)
        if local < scheduled:
            return None
        return DailyOccurrence(
            day=local.date().isoformat(),
            display_date=local.date().strftime('%-m/%-d/%Y'),
            scheduled_for=scheduled.timestamp(),
        )

    def next_after(self, stamp: float) -> float:
        local = datetime.fromtimestamp(stamp, self.zone)
        for offset in range(8):
            day = local.date() + timedelta(days=offset)
            if day.weekday() not in WEEKDAYS:
                continue
            candidate = datetime.combine(day, DAILY_PRINT_TIME, self.zone)
            if candidate.timestamp() > stamp:
                return candidate.timestamp()
        raise RuntimeError('Could not resolve the next weekday MOD Sheet run.')

    def description(self) -> str:
        return f'Monday through Friday at 7:00 AM ({self.timezone})'
