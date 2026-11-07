"""The exact notes write is bounded and contains no generated annotations."""
from copy import deepcopy
import json
from pathlib import Path
import shutil
import sqlite3
import subprocess

import pytest

from printer_app.db import Database, SCHEMA, MOD_SUBMISSION_ITEMS_SCHEMA
from printer_app.mod_resulting.contract import (
    clean_draft, mod_note_text, text_units, user_redline_text,
)
from printer_app.mod_resulting.repository import ResultingRepository
from printer_app.mod_resulting.service import ResultingService
from printer_app.mod_sheet_contract import ModSheetRecord


@pytest.mark.parametrize(('draft', 'expected'), [
    ({'notes': 'Call back', 'numbers': '25000\n17000'}, '25000\n17000\nCall back'),
    ({'notes': '25000\n17000\nCall back', 'numbers': '25000\n17000'},
     '25000\n17000\nCall back'),
    ({'notes': '25000', 'numbers': '25000'}, '25000'),
    ({'notes': 'Call back', 'redlines': 'Manual redline',
      'result_detail': 'Price Objection', 'dnr': True, 'dnr_reason': 'Roofing'},
     'Call back'),
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


def test_only_proven_legacy_red_runs_leave_the_mod_note_write_and_draft_is_unchanged():
    draft = clean_draft({
        'numbers': '25000\n17000',
        'notes': 'Original black note\nLegacy red annotation\nFinal black note',
        'note_runs': [
            {'text': 'Original black note', 'red': False},
            {'text': '\nLegacy red annotation', 'red': True},
            {'text': '\nFinal black note', 'red': False},
        ],
        'redlines': 'Separate manual annotation',
        'result_detail': 'Price Objection', 'dnr': True, 'dnr_reason': 'Roofing',
    })
    before = deepcopy(draft)
    assert mod_note_text(draft) == '25000\n17000\nOriginal black note\nFinal black note'
    assert user_redline_text(draft) == 'Legacy red annotation\nSeparate manual annotation'
    assert draft == before


def test_all_red_legacy_note_is_excluded_but_numbers_and_source_prefix_remain():
    draft = clean_draft({
        'numbers': '25000\n17000', 'notes': 'Legacy red annotation',
        'note_runs': [{'text': 'Legacy red annotation', 'red': True}],
        'note_origin': {'numbers': '25000\n17000', 'prefix': '$25,000\n17,000.00'},
    })
    assert mod_note_text(draft) == '$25,000\n17,000.00'
    assert user_redline_text(draft) == 'Legacy red annotation'


@pytest.mark.parametrize('runs', [
    [{'text': 'A different note', 'red': True}],
    [{'text': 'Original black note', 'red': 'yes'}],
    [{'text': 'Original black note'}],
])
def test_invalid_or_mismatched_legacy_runs_cannot_delete_plain_notes(runs):
    draft = {'numbers': '100', 'notes': 'Original black note', 'note_runs': runs}
    assert mod_note_text(draft) == '100\nOriginal black note'


def test_manual_redline_does_not_consume_the_mod_notes_character_limit():
    draft = clean_draft({'notes': 'B' * 250, 'redlines': 'R' * 1000})
    assert text_units(mod_note_text(draft)) == 250
    assert user_redline_text(draft) == 'R' * 1000


def test_legacy_ink_and_newer_redline_keep_the_same_comment_after_editor_migration():
    original = clean_draft({
        'numbers': '100', 'notes': 'Black\nKnown red ink\r\nSecond old line',
        'note_runs': [
            {'text': 'Black', 'red': False},
            {'text': '\nKnown red ink\r\nSecond old line', 'red': True},
        ],
        'redlines': '\r\n New redline\r\nSecond new line \r\n',
        'note_origin': {'numbers': '100', 'prefix': '$100.00'},
    })
    comment = 'Known red ink\nSecond old line\nNew redline\nSecond new line'
    migrated = clean_draft(dict(original, notes='Black', note_runs=[], redlines=comment))
    assert user_redline_text(original) == user_redline_text(migrated) == comment
    assert mod_note_text(original) == mod_note_text(migrated) == '$100.00\nBlack'


def test_editor_autosave_preserves_trusted_source_prefix_through_legacy_red_migration(tmp_path):
    day = '2026-11-06'
    ident = '0WO000000000001AAA'
    repo = ResultingRepository(Database(tmp_path / 'printer.db'))
    repo.refresh(day, [ModSheetRecord(source_id=ident, product_interest='Roofing')])
    service = ResultingService(repo, None, None, None, 'UTC')
    original = clean_draft({
        'dispo': 'pns', 'numbers': '100', 'notes': 'Black\nKnown red ink',
        'note_runs': [{'text': 'Black', 'red': False}, {'text': '\nKnown red ink', 'red': True}],
        'redlines': 'New redline',
        'note_origin': {'numbers': '100', 'prefix': '$100.00'},
    })
    revision = repo.save_draft(day, ident, original, 0)
    incoming = clean_draft(dict(original, notes='Black', note_runs=[],
                                redlines='Known red ink\nNew redline'))
    incoming.pop('note_origin')  # A browser edit cannot invent source metadata.
    service.save(day, ident, incoming, revision)
    saved = repo.sheets(day)[0]['draft']
    assert saved['note_origin'] == original['note_origin']
    assert saved['notes'] == 'Black'
    assert saved['note_runs'] == []
    assert mod_note_text(saved) == mod_note_text(original) == '$100.00\nBlack'
    assert user_redline_text(saved) == user_redline_text(original) == 'Known red ink\nNew redline'


def test_browser_counter_matches_the_destination_for_authored_red_text():
    node = shutil.which('node')
    if node is None:
        pytest.skip('Node is required to exercise the actual browser counter function.')
    cases = [
        {'numbers': '100', 'notes': 'B' * 240, 'redlines': 'R' * 1000},
        {'numbers': '100', 'notes': 'Black\nRed',
         'note_runs': [{'text': 'Black', 'red': False}, {'text': '\nRed', 'red': True}]},
        {'numbers': '100', 'notes': 'Only red',
         'note_runs': [{'text': 'Only red', 'red': True}],
         'note_origin': {'numbers': '100', 'prefix': '$100.00'}},
        {'numbers': '100', 'notes': 'Black\r\n\U0001f600', 'redlines': 'Red\r\n\U0001f600'},
        {'numbers': '100', 'notes': 'Black\nShared words', 'redlines': 'Shared words',
         'note_origin': {'numbers': '100', 'prefix': '100'}},
        {'numbers': '100', 'notes': 'Black',
         'note_runs': [{'text': 'Different red text', 'red': True}]},
    ]
    source = (Path(__file__).resolve().parents[1] / 'static/mod_resulting/sheet.js').read_text()
    function = source.split('  function modNotesText(draft) {', 1)[1].split(
        '  function updateModNotesCounter(sheet) {', 1)[0]
    script = (
        'const fs = require("node:fs");\n'
        'function modNotesText(draft) {' + function + '\n'
        'const drafts = JSON.parse(fs.readFileSync(0, "utf8"));\n'
        'process.stdout.write(JSON.stringify(drafts.map(draft => {\n'
        '  const text = modNotesText(draft); return {text, count:text.length};\n'
        '})));'
    )
    result = subprocess.run([node, '-e', script], input=json.dumps(cases), encoding='utf-8',
                            capture_output=True, check=True, timeout=10)
    assert json.loads(result.stdout) == [
        {'text': mod_note_text(draft), 'count': text_units(mod_note_text(draft))}
        for draft in cases
    ]


def test_existing_submission_history_migrates_without_losing_receipts(tmp_path):
    path = tmp_path / 'printer.db'
    legacy = MOD_SUBMISSION_ITEMS_SCHEMA.replace(
        "'submitted','rejected','uncertain','not_submitted','pdf_only'",
        "'submitted','uncertain'")
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
