"""Derive Lead.Previous_Result__c from the immediately preceding appointment.

Never infer it from the Work Order currently being resulted, today's Dispo, or
LastModifiedDate. Salesforce WorkOrder.Lead__c and Appointment_Date_Time__c
were verified in the user's org. An unsupported historical result clears the
restricted Previous Result picklist instead of walking further back in time.
"""
from datetime import date, datetime, time
from zoneinfo import ZoneInfo

from .salesforce_adapter import ResultingSalesforceError, _require_id


# Exact active Lead.Previous_Result__c options confirmed by the user.
HISTORICAL_RESULTS = {
    'pns': 'Pitch No Sale',
    'pitch no sale': 'Pitch No Sale',
    'np': 'No Pitch',
    'no pitch': 'No Pitch',
    'nra': 'No Rep Available',
    'no rep available': 'No Rep Available',
}


def _appointment_start(work, zone):
    stamp = str(work.get('Appointment_Date_Time__c') or '').strip()
    if stamp:
        try:
            value = datetime.fromisoformat(stamp.replace('Z', '+00:00'))
        except ValueError as exc:
            raise ResultingSalesforceError(
                'Salesforce Work Order has an invalid appointment datetime.'
            ) from exc
        return (value.replace(tzinfo=zone) if value.tzinfo is None
                else value.astimezone(zone)), True
    raw_date = str(work.get('Appointment_Date__c') or '').strip()
    if raw_date:
        try:
            return datetime.combine(date.fromisoformat(raw_date), time.min,
                                    tzinfo=zone), False
        except ValueError as exc:
            raise ResultingSalesforceError(
                'Salesforce Work Order has an invalid appointment date.'
            ) from exc
    return None, False


def historical_previous_result(rows, current_id, *, timezone_name,
                               pending_dispositions=None):
    """Return one allowed Previous Result or None (intentionally clear).

    Current appointment is identified by Work Order Id, never by current
    disposition. The immediately preceding appointment wins even if unresulted.
    Blank or unsupported prior outcomes clear the field; never search farther
    back. Ambiguous dating still fails safely.
    """
    zone = ZoneInfo(timezone_name)
    current_id = _require_id(current_id)
    pending = pending_dispositions or {}
    by_id = {}
    for row in rows:
        ident = _require_id(str(row.get('Id') or ''))
        if ident in by_id:
            raise ResultingSalesforceError('Duplicate historical Work Order Id.')
        by_id[ident] = row
    current = by_id.get(current_id)
    if current is None:
        raise ResultingSalesforceError('Current Work Order is missing from Lead history.')

    current_start, current_precise = _appointment_start(current, zone)
    if current_start is None:
        raise ResultingSalesforceError(
            'Current Work Order has no appointment date for Previous Result.'
        )

    earlier = []
    for ident, row in by_id.items():
        if ident == current_id:
            continue
        result = str(pending.get(ident, row.get('Dispo__c')) or '').strip()
        start, precise = _appointment_start(row, zone)
        if start is None:
            # An undated result is ambiguous. An undated unresulted record
            # cannot contribute a Previous Result.
            if result:
                raise ResultingSalesforceError(
                    'A previously resulted Work Order has no appointment date.'
                )
            continue
        # Same-calendar-day date-only records cannot be reliably ordered
        # against a precise timestamp or another date-only record.
        if (start.date() == current_start.date()
                and (not precise or not current_precise)):
            raise ResultingSalesforceError(
                'A same-day Work Order has no appointment time for safe ordering.'
            )
        if start < current_start:
            earlier.append((start, ident, result))

    if not earlier:
        return None
    latest = max(earlier, key=lambda item: (item[0], item[1]))
    return HISTORICAL_RESULTS.get(latest[2].casefold()) if latest[2] else None
