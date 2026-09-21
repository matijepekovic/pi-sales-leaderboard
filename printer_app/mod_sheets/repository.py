"""Persistence for permanent daily MOD-sheet settings and run state."""
from __future__ import annotations

from dataclasses import asdict

from ..mod_sheet_contract import ModSheetRecord
from .policy import ModSheetAutomationSettings


SETTINGS_KEY = 'daily_mod_sheet_settings'
STATE_KEY = 'daily_mod_sheet_state'
TEST_STATE_KEY = 'daily_mod_sheet_test_state'
REFERENCE_OUTBOX_KEY = 'daily_mod_sheet_reference_outbox'
FINAL_REFERENCE_STATE_KEY = 'daily_mod_sheet_final_reference_state'
REFERENCE_BACKFILL_KEY = 'gallery_reference_backfill_complete'
REFERENCE_BACKFILL_CONTRACT = 'full-card-search'


class ModSheetAutomationRepository:
    def __init__(self, db):
        self.db = db

    def settings(self) -> ModSheetAutomationSettings | None:
        value = self.db.get(SETTINGS_KEY)
        if not isinstance(value, dict):
            return None
        try:
            return ModSheetAutomationSettings.from_dict(value)
        except (TypeError, ValueError):
            return None

    def save_settings(self, settings: ModSheetAutomationSettings) -> None:
        self.db.set(SETTINGS_KEY, settings.as_dict())

    def state(self) -> dict:
        value = self.db.get(STATE_KEY, {})
        return dict(value) if isinstance(value, dict) else {}

    def save_state(self, state: dict) -> dict:
        value = dict(state)
        self.db.set(STATE_KEY, value)
        return value


    def test_state(self) -> dict:
        value = self.db.get(TEST_STATE_KEY, {})
        return dict(value) if isinstance(value, dict) else {}

    def save_test_state(self, state: dict) -> dict:
        value = dict(state)
        self.db.set(TEST_STATE_KEY, value)
        return value


    def _reference_outbox(self):
        value = self.db.get(REFERENCE_OUTBOX_KEY, {})
        return dict(value) if isinstance(value, dict) else {}

    def save_morning_reference(self, day, records, captured_at, pdf_path=None):
        outbox = self._reference_outbox()
        outbox[day] = {
            'day': day,
            'captured_at': float(captured_at),
            'records': [asdict(record) for record in records],
            'pdf_path': str(pdf_path) if pdf_path is not None else '',
            'job_id': None,
            'delivered_at': None,
        }
        # Keep a bounded recovery window; lexical ISO dates sort chronologically.
        for old_day in sorted(outbox)[:-14]:
            outbox.pop(old_day, None)
        self.db.set(REFERENCE_OUTBOX_KEY, outbox)

    def bind_morning_reference_job(self, day, job_id):
        outbox = self._reference_outbox()
        value = outbox.get(day)
        if value is None:
            return
        value = dict(value)
        value['job_id'] = int(job_id)
        outbox[day] = value
        self.db.set(REFERENCE_OUTBOX_KEY, outbox)

    def pending_morning_references(self):
        result = []
        for day, value in sorted(self._reference_outbox().items()):
            if value.get('delivered_at') is not None or not value.get('job_id'):
                continue
            records = tuple(
                ModSheetRecord(
                    **dict(
                        record,
                        assigned_service_resources=tuple(
                            record.get('assigned_service_resources', ())
                        ),
                    )
                )
                for record in value.get('records', ())
            )
            result.append(dict(value, day=day, records=records))
        return result

    def mark_morning_reference_delivered(self, day, at):
        outbox = self._reference_outbox()
        value = outbox.get(day)
        if value is None:
            return
        value = dict(value)
        value['delivered_at'] = float(at)
        outbox[day] = value
        self.db.set(REFERENCE_OUTBOX_KEY, outbox)

    def final_reference_state(self):
        value = self.db.get(FINAL_REFERENCE_STATE_KEY, {})
        return dict(value) if isinstance(value, dict) else {}

    def save_final_reference_state(self, state):
        value = dict(state)
        self.db.set(FINAL_REFERENCE_STATE_KEY, value)
        return value

    def reference_backfill_complete(self):
        return self.db.get(REFERENCE_BACKFILL_KEY) == REFERENCE_BACKFILL_CONTRACT

    def complete_reference_backfill(self):
        self.db.set(REFERENCE_BACKFILL_KEY, REFERENCE_BACKFILL_CONTRACT)
