"""The exact notes write is bounded and contains no generated annotations."""
import sqlite3

import pytest

from printer_app.db import Database, SCHEMA, MOD_SUBMISSION_ITEMS_SCHEMA
from printer_app.mod_resulting.contract import mod_note_text, text_units


@pytest.mark.parametrize(('draft', 'expected'), [
    ({'notes': 'Call back', 'numbers': '25000\n17000'}, '25000\n17000\nCall back'),
    ({'notes': '25000\n17000\nCall back', 'numbers': '25000\n17000'},
     '25000\n17000\nCall back'),
    ({'notes': '25000', 'numbers': '25000'}, '25000'),
    ({'notes': 'Call back', 'redlines': 'Manual redline',
      'result_detail': 'Price Objection', 'dnr': True, 'dnr_reason': 'Roofing'},
     'Call back\nManual redline'),
    ({'notes': '100\nCall back\nManual redline', 'numbers': '100',
      'redlines': 'Manual redline'}, '100\nCall back\nManual redline'),
    ({'notes': ' First\r\nSecond ', 'numbers': ' 100\r\n200'}, '100\n200\n First\nSecond'),
])
def test_notes_and_numbers_are_sent_once_without_generated_text(draft, expected):
    assert mod_note_text(draft) == expected
    assert mod_note_text(dict(draft, notes=expected)) == expected


def test_counter_uses_the_same_units_for_emoji_and_line_breaks_as_browser():
    assert text_units('a\n\U0001f600') == 4
    assert text_units(mod_note_text({'numbers': '10', 'notes': '\U0001f600'})) == 5


def test_source_manual_notes_are_preserved_without_duplicate_red_pen_text():
    draft = {'numbers': '100', 'notes': 'Call back\nScope discussed',
             'redlines': 'Scope discussed',
             'note_origin': {'numbers': '100', 'prefix': '100'}}
    assert mod_note_text(draft) == '100\nCall back\nScope discussed'


def test_existing_submission_history_migrates_without_losing_receipts(tmp_path):
    path = tmp_path / 'printer.db'
    legacy = MOD_SUBMISSION_ITEMS_SCHEMA.replace(
        "'submitted','rejected','uncertain','not_submitted'", "'submitted','uncertain'")
    with sqlite3.connect(path) as conn:
        conn.executescript(SCHEMA.replace(MOD_SUBMISSION_ITEMS_SCHEMA, legacy))
        conn.execute("INSERT INTO mod_result_days(day) VALUES('2026-11-06')")
        conn.execute("INSERT INTO mod_result_submission_jobs(id,day,state,created_at) "
                     "VALUES(1,'2026-11-06','failed',123)")
        conn.execute("INSERT INTO mod_result_submission_items VALUES"
                     "(1,'work','00123',0,'uncertain','Keep this receipt')")
    db = Database(path)
    assert db.rows('SELECT * FROM mod_result_submission_items') == [{
        'job_id': 1, 'work_order_id': 'work', 'work_order_number': '00123',
        'position': 0, 'state': 'uncertain', 'error': 'Keep this receipt',
    }]
    db.execute("UPDATE mod_result_submission_items SET state='rejected'")
    Database(path)
    assert db.one('SELECT state FROM mod_result_submission_items')['state'] == 'rejected'
    with db.connect() as conn:
        assert conn.execute('PRAGMA foreign_key_check').fetchall() == []
        conn.execute('DELETE FROM mod_result_submission_jobs WHERE id=1')
    assert db.rows('SELECT * FROM mod_result_submission_items') == []
