"""Printed corroboration stays separate from candidate discovery and source values."""
from types import SimpleNamespace
import subprocess

import pytest

from printer_app.gallery import recognition


def words(text):
    return [dict(text=text, page_num=1, block_num=1, par_num=1, line_num=1,
                 top=10, left=10, width=80, height=10)]


def test_labelled_header_evidence_keeps_wrapped_names_and_stops_before_notes():
    result = recognition._printed_evidence(
        'Lead Name: ALEX & MORGAN\nEXAMPLE\nAddress: 100 Test Street\n'
        'Phone: (206) 555-1234\nPower Questions:\n'
        'Local Scheduled Start Time: Sep 24 2026 03:30 PM\n'
        'Scheduled Start: 2026.09.24\n03:30:00 PM\n'
        'Work Type: Test\nMOD Notes: Lead Name: Another Person\nPhone: 2535559999'
    )
    assert result == {
        'names': ('alex & morgan example',), 'dates': ('2026-09-24',),
        'times': ('15:30',), 'phones': ('2065551234',),
    }


def test_isolated_name_cell_keeps_wrapping_when_its_label_is_misread():
    result = recognition._printed_evidence('Leed Name: Alex (PREFER AL)\nExample', key='lead_name')
    assert result['names'] == ('alex (prefer al) example',)
    assert recognition._printed_evidence('Alex Example', key='lead_name')['names'] == ()


def test_date_and_time_evidence_never_invents_unread_digits_or_meridiem():
    result = recognition._printed_evidence(
        'Local Scheduled Start Time: Sep ?? 2026 03:30\n'
        'Scheduled Start: 2026.09.24\n03:30'
    )
    assert result['dates'] == ('2026-09-24',)
    assert result['times'] == ()


def test_explicit_meridiem_can_touch_observed_clock_digits():
    result = recognition._printed_evidence('Scheduled Start: 2026.09.24 03:30:00PM')
    assert result['times'] == ('15:30',)


def test_ambiguous_field_evidence_preserves_independent_reads_and_source_pixels(monkeypatch, tmp_path):
    cv2 = pytest.importorskip('cv2')
    np = pytest.importorskip('numpy')
    source = np.full((80, 160), 255, np.uint8)
    before = source.copy()
    crops = []

    def crop(image, registration, key):
        assert image is source
        crops.append(key)
        return np.full((20, 100), 255, np.uint8), (0, 0, 100, 20)

    outputs = iter([
        'Lead Name: Alex\nExample', 'Lead Name: Alec\nExample',
        'Phone: 2065551234', 'Phone: 2535554321',
        'Local Scheduled Start Time: Sep 24 2026 03:30 PM',
        'Local Scheduled Start Time: Sep 24 2026 03:00 PM',
        'Scheduled Start: 2026.09.24\n03:30:00 PM',
        'Scheduled Start: 2026.09.24\n03:30:00 PM',
    ])
    shapes = []

    def read(image, path, **kwargs):
        assert kwargs == {'psm': 6}
        shapes.append(image.shape)
        return words(next(outputs))

    monkeypatch.setattr(recognition, 'field_crop', crop)
    monkeypatch.setattr(recognition, '_run_tesseract', read)
    result = recognition._recognize_evidence(
        source, SimpleNamespace(matched=True), tmp_path / 'ocr.png', '2026-09-24',
        {'names': ('Earlier Example',), 'dates': (), 'times': (), 'phones': ()},
    )
    assert crops == ['lead_name', 'phone', 'local_scheduled_start_time', 'scheduled_start']
    assert shapes == [(20, 100), (40, 200)] * 4
    assert result == {
        'names': ('earlier example', 'alex example', 'alec example'),
        'dates': ('2026-09-24',), 'times': ('15:30', '15:00'),
        'phones': ('2065551234', '2535554321'),
    }
    assert np.array_equal(source, before)


def test_unregistered_card_uses_labelled_legacy_evidence_without_guessed_field_crops(monkeypatch, tmp_path):
    pytest.importorskip('cv2')
    monkeypatch.setattr(recognition, 'field_crop', lambda *args: pytest.fail('unregistered crop'))
    result = recognition._recognize_evidence(
        None, SimpleNamespace(matched=False), tmp_path / 'ocr.png', '2026-09-24',
        {'names': ('Alex Example',), 'phones': ('2065551234',)},
    )
    assert result['names'] == ('alex example',)
    assert result['phones'] == ('2065551234',)
    assert result['dates'] == ('2026-09-24',)


def test_one_failed_field_read_does_not_erase_other_printed_evidence(monkeypatch, tmp_path):
    pytest.importorskip('cv2')
    np = pytest.importorskip('numpy')
    monkeypatch.setattr(recognition, 'field_crop', lambda image, registration, key:
                        (np.full((20, 80), 255, np.uint8), (0, 0, 80, 20))
                        if key == 'phone' else (None, (0, 0, 0, 0)))
    attempts = iter([None, 'Phone: 2065551234'])

    def read(*args, **kwargs):
        value = next(attempts)
        if value is None:
            raise subprocess.TimeoutExpired('tesseract', 120)
        return words(value)

    monkeypatch.setattr(recognition, '_run_tesseract', read)
    result = recognition._recognize_evidence(None, SimpleNamespace(matched=True),
                                             tmp_path / 'ocr.png', None)
    assert result['phones'] == ('2065551234',)


def test_legacy_evidence_retains_both_reads_without_replacing_candidate_discovery(monkeypatch, tmp_path):
    pytest.importorskip('cv2')
    np = pytest.importorskip('numpy')
    outputs = iter([
        'Work Order Number: 02012345\nLead Name: Alex Example\nPhone: 2065551234',
        'Work Order Number: 02012348\nLead Name: Alec Example\nPhone: 2535554321',
    ])
    monkeypatch.setattr(recognition, '_run_tesseract', lambda *args, **kwargs: words(next(outputs)))
    monkeypatch.setattr(recognition, 'document_date', lambda *args: (None, 'needs-date'))
    monkeypatch.setattr(recognition, 'lead_cell_text', lambda *args: '')
    result = recognition._recognize_legacy(np.full((120, 240), 255, np.uint8),
                                           tmp_path / 'ocr.png', None)
    assert result['work_order_candidates'] == ('02012345', '02012348')
    assert result['work_order_evidence']['names'] == ('alex example', 'alec example')
    assert result['work_order_evidence']['phones'] == ('2065551234', '2535554321')


@pytest.mark.parametrize('matched', [False, True])
def test_unreadable_note_labels_cannot_make_body_text_corroboration(monkeypatch, tmp_path, matched):
    pytest.importorskip('cv2')
    np = pytest.importorskip('numpy')
    header = words('Work Order Number: 02012345\nLead Name: Alex Example')
    lower = words('W0rk Typ?\nM0D N0tes\nLead Name: Another Person\nPhone: 2535559999')
    lower[0].update(top=90, line_num=2)
    monkeypatch.setattr(recognition, '_run_tesseract', lambda *args, **kwargs: header + lower)
    monkeypatch.setattr(recognition, 'document_date', lambda *args: (None, 'needs-date'))
    monkeypatch.setattr(recognition, 'lead_cell_text', lambda *args: '')
    monkeypatch.setattr(recognition, 'field_crop', lambda *args: (None, (0, 0, 240, 35)))
    result = recognition._recognize_legacy(
        np.full((120, 240), 255, np.uint8), tmp_path / 'ocr.png', None,
        SimpleNamespace(matched=matched),
    )
    assert result['work_order_candidates'] == ('02012345',)
    assert result['work_order_evidence']['names'] == ('alex example',)
    assert result['work_order_evidence']['phones'] == ()


@pytest.mark.parametrize('candidates', [(), ('02012345',), ('02012345', '02012348')])
def test_only_ambiguous_final_candidates_trigger_extra_field_ocr(monkeypatch, tmp_path, candidates):
    cv2 = pytest.importorskip('cv2')
    np = pytest.importorskip('numpy')
    path = tmp_path / 'card.png'
    cv2.imwrite(str(path), np.full((80, 160), 255, np.uint8))
    monkeypatch.setattr(recognition, 'register_form', lambda *args: SimpleNamespace(matched=True))
    monkeypatch.setattr(recognition, 'mod_notes_present', lambda *args: True)
    monkeypatch.setattr(recognition, '_recognize_template', lambda *args, **kwargs:
                        {'work_order_candidates': candidates, 'work_order_reads': ()})
    monkeypatch.setattr(recognition, '_recognize_legacy', lambda *args:
                        {'work_order_candidates': (), 'work_order_reads': (),
                         'work_order_evidence': {'names': ('Alex Example',)}})
    calls = []

    def evidence(*args):
        calls.append(args)
        return {'names': ('alex example',), 'dates': (), 'times': (), 'phones': ()}

    monkeypatch.setattr(recognition, '_recognize_evidence', evidence)
    result = recognition.recognize(path, tmp_path, known_date='2026-09-24')
    assert result['work_order_candidates'] == candidates
    assert len(calls) == int(len(candidates) > 1)
    assert ('work_order_evidence' in result) == (len(candidates) > 1)
