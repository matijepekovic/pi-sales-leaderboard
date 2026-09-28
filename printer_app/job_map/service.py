"""Business workflow for displaying mapped jobs and opening their MOD sheet."""
from __future__ import annotations

from math import asin, cos, isfinite, radians, sin, sqrt

from ..mod_sheet_contract import ModSheetSourceError
from .contract import JobMapSourceError, MapQuery


EXCLUDED_LEAD_STATUSES = frozenset({'new', 'scheduled', 'do not call'})
MAX_RADIUS_MILES = 5.0
_EARTH_RADIUS_MILES = 3958.7613


def _distance_miles(latitude, longitude, job):
    """Great-circle distance from the requested location to one normalized job."""
    lat1 = radians(latitude)
    lat2 = radians(job.latitude)
    delta_lat = lat2 - lat1
    delta_lon = radians(job.longitude - longitude)
    value = (
        sin(delta_lat / 2) ** 2
        + cos(lat1) * cos(lat2) * sin(delta_lon / 2) ** 2
    )
    return 2 * _EARTH_RADIUS_MILES * asin(sqrt(min(1.0, max(0.0, value))))


class JobMapService:
    def __init__(self, source, render_pdf):
        self.source = source
        self.render_pdf = render_pdf

    def jobs(self, latitude, longitude):
        """Return only map-eligible jobs within five miles of the caller."""
        try:
            latitude = float(latitude)
            longitude = float(longitude)
        except (TypeError, ValueError) as exc:
            raise ValueError('A valid current location is required.') from exc
        if (not isfinite(latitude) or not isfinite(longitude)
                or not -90 <= latitude <= 90 or not -180 <= longitude <= 180):
            raise ValueError('A valid current location is required.')

        query = MapQuery(
            latitude=latitude,
            longitude=longitude,
            radius_miles=MAX_RADIUS_MILES,
        )
        jobs = tuple(self.source.map_jobs(query))
        return tuple(sorted(
            (
                job for job in jobs
                if str(job.lead_status or '').strip().casefold() not in EXCLUDED_LEAD_STATUSES
                and _distance_miles(latitude, longitude, job) <= MAX_RADIUS_MILES
            ),
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
