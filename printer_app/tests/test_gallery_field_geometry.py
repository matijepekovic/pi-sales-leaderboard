"""Observed cell geometry without OCR, customer fixtures, or runtime services."""
import pytest

from printer_app.gallery.form_template import (
    FormRegistration, TEMPLATE_ASPECT_HEIGHT, TEMPLATE_FIELDS, field_boxes, map_box,
)


@pytest.fixture
def raster():
    return pytest.importorskip('cv2'), pytest.importorskip('numpy')


def _stroke_inset(stroke):
    # OpenCV's odd thick LINE_8 rules extend one extra pixel on each side.
    return 1 if stroke == 1 else stroke // 2 + 2


def _grid(raster, width=1900, stroke=3, row_positions=None):
    cv2, np = raster
    height = round(width * TEMPLATE_ASPECT_HEIGHT) if row_positions is None else 985
    registration = FormRegistration(1.0, 24, 24 + width, 24, 24 + height)
    image = np.full((height + 48, width + 48), 255, np.uint8)
    centers = {}
    for field in TEMPLATE_FIELDS:
        left, top, right, bottom = map_box(registration, field.box)
        if row_positions is not None:
            source_top = round(19 + field.box[1] * 767.5, 1)
            source_bottom = round(19 + field.box[3] * 767.5, 1)
            top = 24 + row_positions[source_top]
            bottom = 24 + row_positions[source_bottom]
        centers[field.key] = (left, top, right, bottom)
        cv2.rectangle(image, (left, top), (right, bottom), 0, stroke, cv2.LINE_8)
    return image, registration, centers


@pytest.mark.parametrize('width', [900, 1900, 2800])
@pytest.mark.parametrize('stroke', [1, 3, 7])
@pytest.mark.parametrize('registration_offset', [0, 5])
def test_observed_rules_define_every_cell_at_multiple_scales(
        raster, width, stroke, registration_offset):
    cv2, np = raster
    source, actual, centers = _grid(raster, width, stroke)
    inset = _stroke_inset(stroke)
    for left, top, right, bottom in centers.values():
        # A small mark just inside each upper-left corner must remain present;
        # the thick black rules and neighboring marks must remain outside.
        cv2.rectangle(source, (left + inset + 1, top + inset + 1),
                      (left + inset + 3, top + inset + 3), 80, -1)
    before = source.copy()
    registration = FormRegistration(
        actual.score, actual.left + registration_offset,
        actual.right + registration_offset, actual.top + registration_offset,
        actual.bottom + registration_offset,
    )

    boxes = field_boxes(source, registration)

    assert [field.key for field, _ in boxes] == [field.key for field in TEMPLATE_FIELDS]
    for field, bounds in boxes:
        left, top, right, bottom = centers[field.key]
        assert bounds == (left + inset, top + inset, right - inset + 1, bottom - inset + 1)
        x0, y0, x1, y1 = bounds
        crop = source[y0:y1, x0:x1]
        assert not np.any(crop == 0), field.key
        assert np.count_nonzero(crop == 80) == 9, field.key
    assert np.array_equal(source, before)


def test_nonuniform_rows_do_not_confuse_partial_rule_with_full_width_border(raster):
    _, np = raster
    # Synthetic rows deliberately have different heights from the blank form.
    # The next partial rule is closer to the old prediction than the actual
    # full-width boundary. A nearest-line search within one cell picks wrong.
    rows = {
        19.0: 0, 68.5: 59, 154.5: 162, 244.0: 269, 333.5: 375,
        383.0: 431, 473.0: 572, 554.5: 679, 605.5: 735,
        657.5: 791, 710.0: 858, 786.5: 985,
    }
    source, registration, centers = _grid(raster, width=2382, row_positions=rows)
    before = source.copy()
    sub_source = next(field for field in TEMPLATE_FIELDS if field.key == 'sub_source')
    expected_bottom = map_box(registration, sub_source.box)[3]
    actual_bottom = centers['sub_source'][3]
    next_partial_rule = centers['start_price'][3]
    assert abs(expected_bottom - next_partial_rule) < abs(expected_bottom - actual_bottom)

    boxes = {field.key: bounds for field, bounds in field_boxes(source, registration)}

    inset = _stroke_inset(3)
    for key in ('sub_source', 'lead_description', 'start_price', 'final_price', 'mod_notes'):
        left, top, right, bottom = centers[key]
        assert boxes[key] == (left + inset, top + inset, right - inset + 1, bottom - inset + 1)
        x0, y0, x1, y1 = boxes[key]
        assert not np.any(source[y0:y1, x0:x1] == 0), key
    assert boxes['sub_source'][3] < boxes['start_price'][1]
    assert boxes['start_price'][3] < boxes['mod_notes'][1]
    assert np.array_equal(source, before)


def test_missing_shared_edge_keeps_ownership_and_observed_stroke_inset(raster):
    cv2, np = raster
    source, registration, centers = _grid(raster, stroke=7)
    left, top, right, bottom = centers['lead_name']
    inset = _stroke_inset(7)
    # Remove the name/address divider between its surviving horizontal corners.
    source[top + inset:bottom - inset + 1, right - inset:right + inset + 1] = 255
    cv2.rectangle(source, (right + 7, top + 12), (right + 15, top + 20), 70, -1)
    cv2.rectangle(source, (left + 12, top + 12), (left + 20, top + 20), 80, -1)
    before = source.copy()

    boxes = {field.key: bounds for field, bounds in field_boxes(source, registration)}
    x0, y0, x1, y1 = boxes['lead_name']
    name = source[y0:y1, x0:x1]

    assert x1 <= right - inset + 1
    assert x0 >= left + inset and y0 >= top + inset and y1 <= bottom - inset + 1
    assert np.count_nonzero(name == 80) == 81
    assert not np.any(name == 70), 'A missing divider must not import the adjacent value.'
    assert not np.any(name == 0), 'Fallback must respect the observed thick-rule width.'
    assert np.array_equal(source, before)


def test_missing_grid_uses_bounded_fallback_and_clamps_partial_card(raster):
    _, np = raster
    source = np.full((800, 1900), 255, np.uint8)
    registration = FormRegistration(1.0, -8, 1908, -5, 805)
    before = source.copy()

    boxes = field_boxes(source, registration)

    for field, (x0, y0, x1, y1) in boxes:
        left, top, right, bottom = map_box(registration, field.box)
        assert 0 <= x0 <= x1 <= source.shape[1]
        assert 0 <= y0 <= y1 <= source.shape[0]
        assert x0 >= max(0, left) and y0 >= max(0, top)
        assert x1 <= min(source.shape[1], right) and y1 <= min(source.shape[0], bottom)
        assert x1 - x0 >= min(source.shape[1], right) - max(0, left) - 10
        assert y1 - y0 >= min(source.shape[0], bottom) - max(0, top) - 10
    assert np.array_equal(source, before)
