"""Template OCR fast-path regressions; no printer/runtime dependencies."""
from pathlib import Path

import pytest


def test_blank_template_geometry_is_removed_before_ocr():
    cv2 = pytest.importorskip('cv2')
    np = pytest.importorskip('numpy')
    from printer_app.gallery.form_template import FormRegistration, TEMPLATE_FIELDS, map_box
    from printer_app.gallery.recognition import template_ocr_canvas

    image = np.full((809, 1942), 255, np.uint8)
    registration = FormRegistration(1.0, 26, 1916, 19, 787)

    # Synthetic constant form ink: cell borders plus every known printed label.
    for field in TEMPLATE_FIELDS:
        left, top, right, bottom = map_box(registration, field.box)
        cv2.rectangle(image, (left, top), (right, bottom), 0, 4)
        left, top, right, bottom = map_box(registration, field.label_box)
        cv2.rectangle(image, (left, top), (right, bottom), 0, -1)

    canvas, segments = template_ocr_canvas(image, registration)
    assert canvas is None
    assert segments == []


def test_template_ocr_packs_only_populated_variable_fields():
    cv2 = pytest.importorskip('cv2')
    np = pytest.importorskip('numpy')
    from printer_app.gallery.form_template import FormRegistration, TEMPLATE_FIELDS, map_box
    from printer_app.gallery.recognition import template_ocr_canvas

    image = np.full((809, 1942), 255, np.uint8)
    registration = FormRegistration(1.0, 26, 1916, 19, 787)
    fields = {field.key: field for field in TEMPLATE_FIELDS}

    # Keep the same constant-form noise as the real blank template.
    for field in TEMPLATE_FIELDS:
        left, top, right, bottom = map_box(registration, field.box)
        cv2.rectangle(image, (left, top), (right, bottom), 0, 4)
        left, top, right, bottom = map_box(registration, field.label_box)
        cv2.rectangle(image, (left, top), (right, bottom), 0, -1)

    for key in ('lead_name', 'address', 'local_scheduled_start_time', 'scheduled_start'):
        left, top, right, bottom = map_box(registration, fields[key].box)
        # Variable ink deliberately lives away from the constant label rectangle.
        x0 = left + int((right - left) * .62)
        y0 = top + int((bottom - top) * .62)
        cv2.rectangle(
            image,
            (x0, y0),
            (min(right - 20, x0 + 75), min(bottom - 12, y0 + 12)),
            0,
            -1,
        )

    canvas, segments = template_ocr_canvas(image, registration)
    keys = [key for key, _, _ in segments]
    assert canvas is not None
    assert set(keys) == {
        'lead_name', 'address', 'local_scheduled_start_time', 'scheduled_start'
    }
    # Tesseract should see a tiny packed raster, not the full 1942x809 card.
    assert canvas.size < image.size * .20
    assert 'mod_notes' not in keys  # blank handwriting area never enters OCR


def test_template_search_contract_keeps_fields_lead_date_and_each_cards_time():
    from printer_app.gallery.recognition import _template_document_date, _template_search_text

    values = {
        'local_scheduled_start_time': '2026-09-19 10:30 AM',
        'lead_name': 'JORDAN EXAMPLE',
        'address': '123 MAIN ST',
        'scheduled_start': '2026-09-19 10:30 AM',
        'product_interest': 'WINDOWS',
    }
    text = _template_search_text(values)
    assert 'Lead Name: JORDAN EXAMPLE' in text
    assert 'Address: 123 MAIN ST' in text
    assert 'Product Interest: WINDOWS' in text
    assert text.count('10:30 AM') == 2
    assert _template_document_date(values) == ('2026-09-19', 'printed')

    # Reusing a PDF date does not replace or invent a card's time text.
    different_time = dict(values, local_scheduled_start_time='2026-09-19 2:15 PM')
    assert '2:15 PM' in _template_search_text(different_time)
    assert _template_document_date(different_time, '2026-09-19') == ('2026-09-19', 'printed')


def test_template_and_ocr_owners_remain_replaceable():
    root = Path(__file__).resolve().parents[1]
    template = (root / 'gallery/form_template.py').read_text()
    recognition = (root / 'gallery/recognition.py').read_text()
    processing = (root / 'gallery/processing.py').read_text()

    assert 'subprocess' not in template and "['tesseract'" not in template.lower()
    assert 'sqlite3' not in template and 'flask' not in template
    assert 'TEMPLATE_FIELDS' in recognition
    assert 'TEMPLATE_FIELDS' not in processing
    assert 'tesseract' not in processing.lower()
