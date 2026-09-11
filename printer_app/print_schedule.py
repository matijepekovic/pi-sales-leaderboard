"""Print timing contract and weekly calendar arithmetic. No IO or scheduler runtime."""
from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, time, timedelta
import json
import re
from typing import Mapping
from zoneinfo import ZoneInfo

DAYS = (('mon', 'Monday'), ('tue', 'Tuesday'), ('wed', 'Wednesday'),
        ('thu', 'Thursday'), ('fri', 'Friday'), ('sat', 'Saturday'), ('sun', 'Sunday'))
MODES = (('immediate', 'Print as emails arrive'),
         ('weekly', 'Queue emails until my weekly schedule'),
         ('hold', 'Collect emails only — hold the print queue'))
FIELDS = {'PRINT_SCHEDULE_MODE', 'PRINT_SCHEDULE_DAYS', 'PRINT_SCHEDULE_TIME'}


@dataclass(frozen=True)
class PrintSchedule:
    mode: str = 'immediate'
    days: tuple[str, ...] = ('mon', 'tue', 'wed', 'thu', 'fri')
    at: str = '09:00'

    def __post_init__(self):
        if self.mode not in dict(MODES):
            raise ValueError('Choose a valid print timing mode.')
        if (not isinstance(self.days, tuple) or any(d not in dict(DAYS) for d in self.days)
                or len(set(self.days)) != len(self.days)):
            raise ValueError('Choose valid, nonduplicated print days.')
        if self.mode == 'weekly' and not self.days:
            raise ValueError('Select at least one day for scheduled printing.')
        if not isinstance(self.at, str) or not re.fullmatch(r'(?:[01][0-9]|2[0-3]):[0-5][0-9]', self.at):
            raise ValueError('Print time must be a valid time in HH:MM format.')

    def apply(self, patch: Mapping[str, str]) -> 'PrintSchedule':
        if set(patch) - FIELDS:
            raise ValueError('Unsupported print schedule setting.')
        values = {}
        if 'PRINT_SCHEDULE_MODE' in patch:
            values['mode'] = patch['PRINT_SCHEDULE_MODE']
        if 'PRINT_SCHEDULE_TIME' in patch:
            values['at'] = patch['PRINT_SCHEDULE_TIME']
        if 'PRINT_SCHEDULE_DAYS' in patch:
            days = tuple(patch['PRINT_SCHEDULE_DAYS'].split(',')) if patch['PRINT_SCHEDULE_DAYS'] else ()
            if len(set(days)) != len(days) or any(day not in dict(DAYS) for day in days):
                raise ValueError('Choose valid, nonduplicated print days.')
            values['days'] = tuple(day for day, _ in DAYS if day in days)
        return replace(self, **values)

    def environment(self) -> dict[str, str]:
        return {'PRINT_SCHEDULE_MODE': self.mode, 'PRINT_SCHEDULE_DAYS': ','.join(self.days),
                'PRINT_SCHEDULE_TIME': self.at}

    def signature(self, timezone: str) -> str:
        return json.dumps([self.mode, self.days, self.at, timezone], separators=(',', ':'))

    def _occurrences(self, stamp: float, timezone: str, offsets):
        zone = ZoneInfo(timezone)
        today = datetime.fromtimestamp(stamp, zone).date()
        hour, minute = map(int, self.at.split(':'))
        for offset in offsets:
            day = today + timedelta(days=offset)
            if DAYS[day.weekday()][0] in self.days:
                # fold=0 runs once at the first occurrence of a repeated clock
                # time. A nonexistent spring-forward time moves forward by the
                # clock gap (e.g. 02:30 -> 03:30), rather than silently vanishing.
                yield datetime.combine(day, time(hour, minute), zone).replace(fold=0).timestamp()

    def next_after(self, stamp: float, timezone: str) -> float | None:
        if self.mode != 'weekly':
            return None
        return min(t for t in self._occurrences(stamp, timezone, range(15)) if t > stamp)

    def latest_due(self, stamp: float, timezone: str) -> float:
        if self.mode != 'weekly':
            raise ValueError('Only a weekly schedule has due occurrences.')
        return max(t for t in self._occurrences(stamp, timezone, range(-14, 1)) if t <= stamp)

    def description(self, timezone: str) -> str:
        if self.mode == 'weekly':
            names = ', '.join(label for key, label in DAYS if key in self.days)
            return f'{names} at {self.at} ({timezone})'
        return dict(MODES)[self.mode]
