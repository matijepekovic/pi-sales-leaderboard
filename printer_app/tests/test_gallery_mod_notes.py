"""Notes identity is proved by its printed label and observed cell borders."""
from io import BytesIO
import shutil
import subprocess

import pytest

from printer_app.gallery import recognition
from printer_app.gallery.form_template import (
    FormRegistration, TEMPLATE_FIELDS, labelled_notes_crop, map_box, register_form,
)


@pytest.fixture
def raster():
    return pytest.importorskip('cv2'), pytest.importorskip('numpy')


@pytest.mark.parametrize('text', ['MODNotes1', 'MODNotes12', 'MOD1Notes'])
def test_notes_label_never_absorbs_appended_numbers(text):
    word = dict(text=text, left=10, top=10, width=140, height=20)
    assert recognition._notes_labels([word], (0, 0)) == []
    assert recognition._notes_labels([
        dict(word, text='MOD', width=45),
        dict(word, text='Notes12', left=60, width=90),
    ], (0, 0)) == []


@pytest.mark.parametrize('merged', [False, True])
def test_numeric_note_merged_with_label_cannot_be_erased(raster, tmp_path, monkeypatch, merged):
    from printer_app.tests.gallery_form_fixture import form_image

    cv2, _ = raster
    source, registration = form_image(raster)
    field = next(item for item in TEMPLATE_FIELDS if item.key == 'mod_notes')
    label = map_box(registration, field.label_box)
    cv2.putText(source, '12', (label[2] + 2, label[3]),
                cv2.FONT_HERSHEY_SIMPLEX, 1.1, 0, 2)
    _, bounds = recognition.field_crop(source, registration, 'mod_notes')
    word = dict(
        text='MODNotes12' if merged else 'MODNotes',
        left=label[0] - bounds[0] + 12,
        top=label[1] - bounds[1] + 12 - (5 if merged else 0),
        width=label[2] - label[0] + (50 if merged else 0),
        height=label[3] - label[1] + (7 if merged else 0),
    )
    monkeypatch.setattr(recognition, '_run_tesseract', lambda *args, **kwargs: [word])
    result = recognition.mod_notes_present(source, registration, tmp_path / 'notes.png')
    assert result is (None if merged else True)


@pytest.mark.parametrize('edge', ['left', 'right', 'top', 'bottom'])
def test_notes_cell_requires_each_observed_border(raster, edge):
    from printer_app.tests.gallery_form_fixture import form_image

    cv2, _ = raster
    source, registration = form_image(raster)
    field = next(item for item in TEMPLATE_FIELDS if item.key == 'mod_notes')
    label = map_box(registration, field.label_box)
    crop, _ = labelled_notes_crop(source, label)
    assert crop is not None
    left, top, right, bottom = map_box(registration, field.box)
    if edge in ('left', 'right'):
        x = left if edge == 'left' else right
        cv2.rectangle(source, (x - 7, top - 5), (x + 7, bottom + 5), 255, -1)
    else:
        y = top if edge == 'top' else bottom
        cv2.rectangle(source, (left - 5, y - 7), (right + 5, y + 7), 255, -1)
    assert labelled_notes_crop(source, label) == (None, (0, 0, 0, 0))


def test_notes_crop_excludes_neighbor_cells_and_follows_observed_label(raster):
    from printer_app.tests.gallery_form_fixture import form_image

    cv2, _ = raster
    source, registration = form_image(raster)
    field = next(item for item in TEMPLATE_FIELDS if item.key == 'mod_notes')
    label = map_box(registration, field.label_box)
    cv2.putText(source, 'NEIGHBOR', (450, 600), cv2.FONT_HERSHEY_SIMPLEX, 1, 0, 3)
    crop, bounds = labelled_notes_crop(source, label)
    assert crop is not None
    assert bounds[0] < label[0] < bounds[2]
    assert bounds[0] > 700
    # The only ink remaining in this blank cell is its label.
    left, top = bounds[:2]
    crop[label[1] - top - 2:label[3] - top + 2,
         label[0] - left - 2:label[2] - left + 2] = 255
    assert int((crop < 225).sum()) == 0


def test_screenshot_clipping_requires_both_horizontal_rules_at_image_edge(raster):
    from printer_app.tests.gallery_form_fixture import form_image

    cv2, _ = raster
    source, registration = form_image(raster)
    field = next(item for item in TEMPLATE_FIELDS if item.key == 'mod_notes')
    label = map_box(registration, field.label_box)
    source = source[:, :1550].copy()
    crop, bounds = labelled_notes_crop(source, label)
    assert crop is not None and bounds[2] == source.shape[1]
    # Whitespace between a missing border and the physical image edge is not
    # evidence of a clipped cell, even when the label and other sides survive.
    source[:, -10:] = 255
    assert labelled_notes_crop(source, label) == (None, (0, 0, 0, 0))


@pytest.mark.parametrize('clipped', [False, True])
def test_long_underline_cannot_hide_notes_below_it(raster, clipped):
    from printer_app.tests.gallery_form_fixture import form_image

    cv2, _ = raster
    source, registration = form_image(raster)
    field = next(item for item in TEMPLATE_FIELDS if item.key == 'mod_notes')
    label = map_box(registration, field.label_box)
    left, _, right, bottom = map_box(registration, field.box)
    cv2.line(source, (left, 530), (right, 530), 0, 3)
    cv2.putText(source, 'Call made', (left + 100, 650), cv2.FONT_HERSHEY_SIMPLEX, 1, 80, 2)
    if clipped:
        source = source[:, :1550]
    crop, bounds = labelled_notes_crop(source, label)
    assert crop is not None and bounds[3] >= bottom - 5
    assert (crop == 80).any()


@pytest.mark.parametrize('gap_bottom', [588, 610, 700])
def test_broken_side_below_underline_cannot_hide_later_notes(raster, gap_bottom):
    from printer_app.tests.gallery_form_fixture import form_image

    cv2, _ = raster
    source, registration = form_image(raster)
    field = next(item for item in TEMPLATE_FIELDS if item.key == 'mod_notes')
    label = map_box(registration, field.label_box)
    left, _, right, _ = map_box(registration, field.box)
    cv2.line(source, (left, 560), (right, 560), 0, 3)
    cv2.putText(source, 'Call made', (left + 100, 650), cv2.FONT_HERSHEY_SIMPLEX, 1, 80, 2)
    cv2.rectangle(source, (left - 4, 564), (left + 4, gap_bottom), 255, -1)
    source = source[:, :1550]
    crop, _ = labelled_notes_crop(source, label)
    # Uncertain geometry may be reviewed, but must never produce an apparently
    # blank crop that silently excludes the note below the damaged underline.
    assert crop is None or (crop == 80).any()


@pytest.fixture(scope='module')
def rendered_blank(tmp_path_factory):
    missing = [tool for tool in ('pdftoppm', 'tesseract') if not shutil.which(tool)]
    if missing:
        pytest.skip('Native PDF/OCR tools unavailable: ' + ', '.join(missing))
    cv2 = pytest.importorskip('cv2')
    np = pytest.importorskip('numpy')
    image_module = pytest.importorskip('PIL.Image')
    pytest.importorskip('reportlab')
    from printer_app.gallery.cropper import cut_forms, deskew_page, orient_work_order_page
    from printer_app.mod_sheet_contract import ModSheetRecord
    from printer_app.mod_sheets.pdf_renderer import render_mod_pdf

    directory = tmp_path_factory.mktemp('blank-notes')
    pdf = directory / 'blank.pdf'
    pdf.write_bytes(render_mod_pdf((ModSheetRecord(
        source_id='synthetic-notes', work_order_number='02012345',
        lead_name='Alex Example', address='100 Test Street', phone='2065551234',
        local_scheduled_start_time='9/26/2026 1:00 PM',
        scheduled_start='2026.09.26 ; 01:00:00 PM',
        lead_description='Synthetic ordinary appointment',
    ),), color_code=False))
    result = subprocess.run(
        ['pdftoppm', '-f', '1', '-l', '1', '-singlefile', '-scale-to', '3300',
         '-png', str(pdf)], capture_output=True, check=True, timeout=60,
    )
    page = np.asarray(image_module.open(BytesIO(result.stdout)).convert('RGB'))
    cards = list(cut_forms(orient_work_order_page(deskew_page(page))))
    assert len(cards) == 1
    return cv2.cvtColor(cards[0][1], cv2.COLOR_RGB2GRAY)


@pytest.mark.parametrize('registration_kind', ['actual', 'misaligned', 'unknown'])
def test_app_rendered_blank_notes_rejects_printed_fields_and_ui_decorations(
        rendered_blank, registration_kind, tmp_path, raster):
    cv2, _ = raster
    source = cv2.copyMakeBorder(rendered_blank, 0, 150, 0, 0,
                               cv2.BORDER_CONSTANT, value=255)
    cv2.putText(source, 'Refresh   Print', (1200, source.shape[0] - 45),
                cv2.FONT_HERSHEY_SIMPLEX, 1.2, 0, 3)
    height, width = source.shape
    registration = register_form(source)
    if registration_kind != 'actual':
        registration = FormRegistration(
            1 if registration_kind == 'misaligned' else 0, 0, width, 0, height,
        )
    assert recognition.mod_notes_present(source, registration, tmp_path / 'notes.png') is False


@pytest.mark.parametrize('position', ['beside', 'below'])
def test_notes_near_printed_label_are_retained(rendered_blank, position, tmp_path, raster):
    cv2, _ = raster
    source = rendered_blank.copy()
    registration = register_form(source)
    crop, (left, top, _, _) = recognition.field_crop(source, registration, 'mod_notes')
    assert crop is not None
    origin = (left + 225, top + 35) if position == 'beside' else (left + 10, top + 65)
    cv2.putText(source, 'Call made', origin, cv2.FONT_HERSHEY_SIMPLEX, .8, 0, 2)
    assert recognition.mod_notes_present(source, registration, tmp_path / 'notes.png') is True


def test_blank_screenshot_clipped_right_still_excludes_footer(rendered_blank, tmp_path, raster):
    cv2, _ = raster
    source = rendered_blank[:, :round(rendered_blank.shape[1] * .80)].copy()
    bottom = register_form(rendered_blank).bottom
    cv2.rectangle(source, (0, bottom + 80), (source.shape[1] - 1, bottom + 130), 0, -1)
    cv2.putText(source, 'Next card', (500, 1400), cv2.FONT_HERSHEY_SIMPLEX, 1.2, 0, 3)
    assert recognition.mod_notes_present(
        source, register_form(source), tmp_path / 'notes.png',
    ) is False


@pytest.mark.parametrize('failure', ['unreadable', 'ocr-error'])
def test_unreadable_notes_label_stays_unknown(rendered_blank, tmp_path, monkeypatch, failure):
    def read(*args, **kwargs):
        if failure == 'ocr-error':
            raise subprocess.SubprocessError('label OCR failed')
        return []

    monkeypatch.setattr(recognition, '_run_tesseract', read)
    assert recognition.mod_notes_present(
        rendered_blank, register_form(rendered_blank), tmp_path / 'notes.png',
    ) is None
