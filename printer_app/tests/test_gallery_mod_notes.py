"""MOD Notes presence is template-owned and never OCR-read."""
from pathlib import Path

import pytest

from printer_app.gallery import recognition
from printer_app.gallery.form_template import (
    FormRegistration, TEMPLATE_FIELDS, map_box,
)
from printer_app.tests.gallery_form_fixture import form_image


@pytest.fixture
def raster():
    return pytest.importorskip('cv2'), pytest.importorskip('numpy')


def _notes_box(registration):
    field = next(item for item in TEMPLATE_FIELDS if item.key == 'mod_notes')
    return map_box(registration, field.box)


def test_blank_registered_mod_notes_box_is_blank(raster, tmp_path):
    source, registration = form_image(raster)

    assert recognition.mod_notes_present(
        source, registration, tmp_path / 'unused.png'
    ) is False


@pytest.mark.parametrize('kind', ['text', 'number', 'check', 'line'])
def test_any_meaningful_ink_in_registered_mod_notes_box_means_notes_present(
        raster, tmp_path, kind):
    cv2, _ = raster
    source, registration = form_image(raster)
    left, top, right, bottom = _notes_box(registration)

    if kind == 'text':
        cv2.putText(
            source, 'Call made', (left + 210, top + 90),
            cv2.FONT_HERSHEY_SIMPLEX, .8, 80, 2, cv2.LINE_AA,
        )
    elif kind == 'number':
        cv2.putText(
            source, '12', (left + 210, top + 70),
            cv2.FONT_HERSHEY_SIMPLEX, 1.0, 80, 2, cv2.LINE_AA,
        )
    elif kind == 'check':
        cv2.line(source, (left + 220, top + 65), (left + 235, top + 80), 80, 3)
        cv2.line(source, (left + 235, top + 80), (left + 265, top + 45), 80, 3)
    else:
        cv2.line(source, (left + 220, bottom - 80), (right - 100, bottom - 60), 80, 3)

    assert recognition.mod_notes_present(
        source, registration, tmp_path / 'unused.png'
    ) is True


def test_mod_notes_presence_does_not_call_tesseract(raster, tmp_path, monkeypatch):
    cv2, _ = raster
    source, registration = form_image(raster)
    left, top, _, _ = _notes_box(registration)
    cv2.putText(
        source, 'x', (left + 230, top + 75),
        cv2.FONT_HERSHEY_SIMPLEX, 1.0, 80, 3, cv2.LINE_AA,
    )

    def fail(*args, **kwargs):
        raise AssertionError('MOD Notes presence must not use OCR')

    monkeypatch.setattr(recognition, '_run_tesseract', fail)

    assert recognition.mod_notes_present(
        source, registration, tmp_path / 'unused.png'
    ) is True


def test_known_printed_mod_notes_label_and_cell_borders_do_not_count_as_notes(
        raster, tmp_path):
    source, registration = form_image(raster)

    # The synthetic template contains the printed MOD Notes label and all cell
    # borders. Those known template decorations alone must remain blank.
    assert recognition.mod_notes_present(
        source, registration, tmp_path / 'unused.png'
    ) is False


def test_neighboring_form_ink_cannot_make_mod_notes_present(raster, tmp_path):
    cv2, _ = raster
    source, registration = form_image(raster)
    field = next(item for item in TEMPLATE_FIELDS if item.key == 'lead_description')
    left, top, right, bottom = map_box(registration, field.box)
    cv2.putText(
        source, 'NEIGHBOR', (left + 60, top + 85),
        cv2.FONT_HERSHEY_SIMPLEX, 1.0, 80, 3, cv2.LINE_AA,
    )

    assert recognition.mod_notes_present(
        source, registration, tmp_path / 'unused.png'
    ) is False


def test_unregistered_form_keeps_mod_notes_unknown(raster, tmp_path):
    source, _ = form_image(raster)
    unknown = FormRegistration(0.0, 0, source.shape[1], 0, source.shape[0])

    assert recognition.mod_notes_present(
        source, unknown, tmp_path / 'unused.png'
    ) is None


def test_clipped_registered_mod_notes_box_keeps_result_unknown(raster, tmp_path):
    source, registration = form_image(raster)
    _, _, right, _ = _notes_box(registration)
    clipped = source[:, :right - 30].copy()

    assert recognition.mod_notes_present(
        clipped, registration, tmp_path / 'unused.png'
    ) is None


def test_tiny_scan_dust_does_not_count_as_notes(raster, tmp_path):
    _, np = raster
    source, registration = form_image(raster)
    left, top, _, _ = _notes_box(registration)
    source[top + 100:top + 102, left + 300:left + 302] = 0

    assert recognition.mod_notes_present(
        source, registration, tmp_path / 'unused.png'
    ) is False


def test_mod_notes_presence_implementation_has_no_ocr_or_label_rediscovery():
    root = Path(__file__).resolve().parents[1]
    recognition_source = (root / 'gallery/recognition.py').read_text()
    block = recognition_source.split('def mod_notes_present', 1)[1].split(
        'def _candidate_result', 1
    )[0]

    assert 'map_box(' in block
    assert '_run_tesseract' not in block
    assert '_notes_labels' not in block
    assert 'labelled_notes_crop' not in recognition_source

    template_source = (root / 'gallery/form_template.py').read_text()
    assert 'def labelled_notes_crop' not in template_source
