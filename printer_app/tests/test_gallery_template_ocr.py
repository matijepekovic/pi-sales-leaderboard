"""Template OCR fast-path regressions; no printer/runtime dependencies."""
from pathlib import Path

import pytest

from printer_app.tests.gallery_form_fixture import form_image


def test_blank_template_geometry_is_removed_before_ocr():
    cv2 = pytest.importorskip('cv2')
    np = pytest.importorskip('numpy')
    from printer_app.gallery.recognition import template_ocr_canvas

    image, registration = form_image((cv2, np))

    canvas, segments = template_ocr_canvas(image, registration)
    assert canvas is None
    assert segments == []


def test_template_ocr_packs_only_populated_variable_fields():
    cv2 = pytest.importorskip('cv2')
    np = pytest.importorskip('numpy')
    from printer_app.gallery.form_template import TEMPLATE_FIELDS, map_box
    from printer_app.gallery.recognition import template_ocr_canvas

    image, registration = form_image((cv2, np))
    fields = {field.key: field for field in TEMPLATE_FIELDS}

    for key in ('work_order_number',):
        field = fields[key]
        left, top, right, bottom = map_box(registration, field.box)
        # Only the work-order value is sent to OCR.
        _, label_top, label_right, label_bottom = map_box(registration, field.label_box)
        x0 = label_right + 10
        y0 = label_top + 3
        y1 = min(label_bottom + 2, bottom - 8)
        cv2.rectangle(
            image,
            (x0, y0),
            (min(right - 20, x0 + 75), y1),
            0,
            -1,
        )

    canvas, segments = template_ocr_canvas(image, registration)
    keys = [key for key, _, _ in segments]
    assert canvas is not None
    assert keys == ['work_order_number']
    # Tesseract should see a tiny packed raster, not the full 1942x809 card.
    assert canvas.size < image.size * .20
    assert 'mod_notes' not in keys  # blank handwriting area never enters OCR


def test_non_work_order_fields_do_not_enter_template_ocr():
    cv2 = pytest.importorskip('cv2')
    np = pytest.importorskip('numpy')
    from printer_app.gallery.form_template import TEMPLATE_FIELDS, map_box
    from printer_app.gallery.recognition import template_ocr_canvas

    image, registration = form_image((cv2, np))
    for key in ('lead_name', 'address', 'local_scheduled_start_time', 'scheduled_start'):
        field = next(field for field in TEMPLATE_FIELDS if field.key == key)
        left, top, right, bottom = map_box(registration, field.box)
        cv2.rectangle(image, (left + 8, top + 8), (right - 8, bottom - 8), 0, -1)

    canvas, segments = template_ocr_canvas(image, registration)
    assert canvas is None
    assert segments == []


def test_template_search_contract_contains_work_order_only():
    from printer_app.gallery.recognition import _template_search_text

    values = {
        'work_order_number': '02275180',
        'local_scheduled_start_time': '2026-09-19 10:30 AM',
        'lead_name': 'JORDAN EXAMPLE',
        'address': '123 MAIN ST',
        'scheduled_start': '2026-09-19 10:30 AM',
    }
    assert _template_search_text(values) == 'Work Order Number: 02275180'


def test_template_and_ocr_owners_remain_replaceable():
    root = Path(__file__).resolve().parents[1]
    template = (root / 'gallery/form_template.py').read_text()
    recognition = (root / 'gallery/recognition.py').read_text()
    processing = (root / 'gallery/processing.py').read_text()

    assert 'subprocess' not in template and "['tesseract'" not in template.lower()
    assert 'sqlite3' not in template and 'flask' not in template
    assert 'TEMPLATE_FIELDS' in recognition
    assert 'TEMPLATE_FIELDS' not in processing
    assert "['tesseract'," not in processing.lower()  # no direct OCR-engine invocation
