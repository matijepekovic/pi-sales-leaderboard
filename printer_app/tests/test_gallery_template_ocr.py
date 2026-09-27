"""Template/numeric-parser boundary regressions; no customer data."""
from pathlib import Path

import pytest

from printer_app.tests.gallery_form_fixture import form_image


def test_blank_template_exposes_only_the_work_order_search_field():
    cv2 = pytest.importorskip('cv2')
    np = pytest.importorskip('numpy')
    from printer_app.gallery.recognition import template_ocr_canvas

    image, registration = form_image((cv2, np))
    before = image.copy()

    canvas, segments = template_ocr_canvas(image, registration)

    assert canvas is not None
    assert [key for key, _, _ in segments] == ['work_order_number']
    assert canvas.size < image.size * .20
    assert np.array_equal(image, before)


def test_work_order_search_field_keeps_slack_left_of_measured_label_edge():
    cv2 = pytest.importorskip('cv2')
    np = pytest.importorskip('numpy')
    from printer_app.gallery.form_template import TEMPLATE_FIELDS, map_box
    from printer_app.gallery.recognition import template_ocr_canvas

    image, registration = form_image((cv2, np))
    field = next(field for field in TEMPLATE_FIELDS if field.key == 'work_order_number')
    _, _, label_right, _ = map_box(registration, field.label_box)
    _, _, _, bottom = map_box(registration, field.box)

    cv2.putText(
        image,
        '02285011',
        (label_right - 5, bottom - 7),
        cv2.FONT_HERSHEY_COMPLEX,
        .8,
        80,
        2,
        cv2.LINE_AA,
    )

    canvas, segments = template_ocr_canvas(image, registration)

    assert [key for key, _, _ in segments] == ['work_order_number']
    assert np.count_nonzero(canvas == 80) > 0


def test_non_work_order_fields_do_not_change_numeric_search_field():
    cv2 = pytest.importorskip('cv2')
    np = pytest.importorskip('numpy')
    from printer_app.gallery.form_template import TEMPLATE_FIELDS, map_box
    from printer_app.gallery.recognition import template_ocr_canvas

    image, registration = form_image((cv2, np))
    baseline, _ = template_ocr_canvas(image, registration)

    for key in ('lead_name', 'address', 'local_scheduled_start_time', 'scheduled_start'):
        field = next(field for field in TEMPLATE_FIELDS if field.key == key)
        left, top, right, bottom = map_box(registration, field.box)
        cv2.rectangle(image, (left + 8, top + 8), (right - 8, bottom - 8), 0, -1)

    canvas, segments = template_ocr_canvas(image, registration)

    assert [key for key, _, _ in segments] == ['work_order_number']
    assert np.array_equal(canvas, baseline)


def test_numeric_parser_and_template_owners_remain_replaceable():
    root = Path(__file__).resolve().parents[1]
    template = (root / 'gallery/form_template.py').read_text()
    numeric = (root / 'gallery/numeric_parser.py').read_text()
    recognition = (root / 'gallery/recognition.py').read_text()
    processing = (root / 'gallery/processing.py').read_text()

    assert 'subprocess' not in template and "['tesseract'" not in template.lower()
    assert 'sqlite3' not in template and 'flask' not in template
    assert 'salesforce' not in numeric.lower()
    assert 'sqlite3' not in numeric and 'flask' not in numeric
    assert 'parse_numeric_image' in recognition
    assert 'TEMPLATE_FIELDS' not in processing
    assert "['tesseract'," not in processing.lower()
