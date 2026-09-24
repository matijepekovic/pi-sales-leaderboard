"""Business workflow for displaying mapped jobs and opening their MOD sheet."""
from __future__ import annotations

from ..mod_sheet_contract import ModSheetSourceError
from .contract import JobMapSourceError


EXCLUDED_LEAD_STATUSES = frozenset({'new', 'scheduled', 'do not call'})


class JobMapService:
    def __init__(self, source, render_pdf):
        self.source = source
        self.render_pdf = render_pdf

    def jobs(self):
        """Return map-eligible jobs using the normalized source contract."""
        jobs = tuple(self.source.map_jobs())
        return tuple(sorted(
            (job for job in jobs
             if str(job.lead_status or '').strip().casefold() not in EXCLUDED_LEAD_STATUSES),
            key=lambda job: (str(job.lead_name or '').casefold(), job.work_order_number),
        ))

    def mod_sheet(self, work_order_number):
        """Render the current normalized MOD sheet for exactly one work order."""
        number = str(work_order_number or '').strip()
        if not number or len(number) > 255 or any(ord(char) < 32 for char in number):
            raise ValueError('A work-order number is required.')
        try:
            records = tuple(self.source.work_orders((number,)))
        except ModSheetSourceError as exc:
            raise JobMapSourceError(str(exc)) from exc
        matches = [record for record in records
                   if str(record.work_order_number or '').strip().casefold() == number.casefold()]
        if len(matches) != 1:
            raise LookupError('Work order was not found.')
        return self.render_pdf(matches)
