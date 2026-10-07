"""Gallery page segmentation is owned by complete MOD-template matches."""
import pytest


def _form_page(raster, count, *, scale=.45, gap=55, margin=35, x_shifts=()):
    cv2, np = raster
    from printer_app.tests.gallery_form_fixture import form_image

    form, registration = form_image(raster, scale=scale)
    height, width = form.shape
    if count == 0:
        return np.full((height + margin * 2, width + margin * 2), 255, np.uint8), form, registration, []

    starts = []
    page = np.full(
        (margin * 2 + height * count + gap * max(0, count - 1),
         width + margin * 2 + 30),
        255,
        np.uint8,
    )
    for index in range(count):
        top = margin + index * (height + gap)
        shift = x_shifts[index] if index < len(x_shifts) else 0
        left = margin + shift
        page[top:top + height, left:left + width] = form
        starts.append((left, top))
    return page, form, registration, starts


@pytest.fixture
def raster():
    return pytest.importorskip('cv2'), pytest.importorskip('numpy')


@pytest.mark.parametrize('count', [0, 1, 2, 3])
def test_page_first_detects_zero_to_three_complete_mod_templates(raster, count):
    from printer_app.gallery.cropper import cut_forms
    from printer_app.gallery.form_template import find_form_registrations

    page, _, _, _ = _form_page(raster, count)

    registrations = find_form_registrations(page)
    crops = list(cut_forms(page))

    assert len(registrations) == count
    assert len(crops) == count
    assert [part for part, _ in crops] == list(range(1, count + 1))


def test_internal_rows_without_the_whole_template_are_not_cards(raster):
    cv2, np = raster
    from printer_app.gallery.form_template import (
        TEMPLATE_FIELDS, find_form_registrations, map_box,
    )
    from printer_app.gallery.cropper import cut_forms
    from printer_app.tests.gallery_form_fixture import form_image

    form, registration = form_image(raster, scale=.50)
    lead = next(field for field in TEMPLATE_FIELDS if field.key == 'lead_description')
    _, internal_top, _, _ = map_box(registration, lead.box)

    # This contains the exact strong lower grid that previously became a fake
    # second card, but not the complete MOD template.
    fragment = form[max(0, internal_top - 8):].copy()
    page = np.full((fragment.shape[0] + 80, form.shape[1] + 80), 255, np.uint8)
    page[40:40 + fragment.shape[0], 40:40 + fragment.shape[1]] = fragment

    assert find_form_registrations(page) == ()
    assert list(cut_forms(page)) == []


def test_one_destroyed_card_does_not_change_neighbor_matches(raster):
    cv2, np = raster
    from printer_app.gallery.cropper import cut_forms
    from printer_app.gallery.form_template import find_form_registrations

    page, form, _, starts = _form_page(raster, 3, gap=70)
    left, top = starts[1]
    page[top:top + form.shape[0], left:left + form.shape[1]] = 255

    registrations = find_form_registrations(page)
    crops = list(cut_forms(page))

    assert len(registrations) == 2
    assert len(crops) == 2
    assert registrations[0].top < starts[1][1]
    assert registrations[1].top > starts[1][1] + form.shape[0]


def test_crop_keeps_pen_overflow_around_registered_card(raster):
    cv2, np = raster
    from printer_app.gallery.cropper import cut_forms

    page, form, registration, starts = _form_page(raster, 2, gap=100)
    left, top = starts[0]

    # Ink just outside the printed bottom and left edges must survive cropping.
    below_y = top + registration.bottom + 18
    page[below_y:below_y + 8, left + 180:left + 220] = 80
    outside_x = left + registration.left - 10
    page[top + 100:top + 125, outside_x:outside_x + 6] = 80

    crops = list(cut_forms(page))

    assert len(crops) == 2
    assert np.count_nonzero(crops[0][1] == 80) >= (8 * 40) + (25 * 6)


def test_overflow_padding_never_enters_next_printed_template(raster):
    cv2, np = raster
    from printer_app.gallery.cropper import cut_forms
    from printer_app.gallery.form_template import find_form_registrations

    page, _, _, _ = _form_page(raster, 2, gap=30)
    registrations = find_form_registrations(page)
    crops = list(cut_forms(page))

    assert len(registrations) == len(crops) == 2
    first_height = crops[0][1].shape[0]
    # The first crop may keep the whole blank gap but cannot cross into card 2.
    assert first_height <= registrations[1].top - max(
        0, registrations[0].top - round(
            (registrations[0].bottom - registrations[0].top) * .085
        )
    ) + 3


def test_crumbling_outer_edges_still_leave_three_full_template_matches(raster):
    cv2, np = raster
    from printer_app.gallery.cropper import cut_forms
    from printer_app.gallery.form_template import find_form_registrations
    from printer_app.tests.gallery_form_fixture import form_image

    form, registration = form_image(raster, scale=.50)
    damaged = form.copy()
    left, right = registration.left, registration.right
    top, bottom = registration.top, registration.bottom

    # Remove chunks from all four outside edges while preserving the internal
    # template. The detector must reconstruct placement from surviving rows/cells.
    cv2.rectangle(damaged, (left + 80, top - 4), (left + 250, top + 5), 255, -1)
    cv2.rectangle(damaged, (right - 320, bottom - 5), (right - 100, bottom + 4), 255, -1)
    cv2.rectangle(damaged, (left - 4, top + 80), (left + 5, top + 190), 255, -1)
    cv2.rectangle(damaged, (right - 5, top + 230), (right + 4, top + 330), 255, -1)

    height, width = damaged.shape
    gap, margin = 65, 40
    page = np.full((height * 3 + gap * 2 + margin * 2, width + 110), 255, np.uint8)
    for index, shift in enumerate((15, -8, 12)):
        y = margin + index * (height + gap)
        x = 50 + shift
        page[y:y + height, x:x + width] = damaged

    assert len(find_form_registrations(page)) == 3
    assert len(list(cut_forms(page))) == 3



def test_low_quality_resampled_scan_still_detects_all_cards(raster):
    cv2, np = raster
    from printer_app.gallery.cropper import cut_forms
    from printer_app.gallery.form_template import find_form_registrations

    page, _, _, _ = _form_page(
        raster, 3, scale=.45, gap=55, margin=35, x_shifts=(8, -6, 5),
    )
    small = cv2.resize(
        page, None, fx=.58, fy=.58, interpolation=cv2.INTER_AREA,
    )
    degraded = cv2.resize(
        small, (page.shape[1], page.shape[0]), interpolation=cv2.INTER_LINEAR,
    )
    degraded = cv2.GaussianBlur(degraded, (3, 3), 0)

    assert len(find_form_registrations(degraded)) == 3
    assert len(list(cut_forms(degraded))) == 3


def test_large_template_page_uses_same_card_count_as_normal_scale(raster):
    cv2, np = raster
    from printer_app.gallery.cropper import cut_forms

    base, _, _, _ = _form_page(raster, 3, scale=.32, gap=30, margin=24)
    large = cv2.resize(
        base,
        (base.shape[1] * 4, base.shape[0] * 4),
        interpolation=cv2.INTER_NEAREST,
    )

    assert len(list(cut_forms(base))) == len(list(cut_forms(large))) == 3


@pytest.mark.parametrize('turns', [1, 2, 3])
def test_right_angle_template_pages_are_normalized_before_cropping(raster, turns):
    _, np = raster
    from printer_app.gallery.cropper import cut_forms, orient_work_order_page

    page, _, _, _ = _form_page(raster, 2, gap=55, margin=28)
    rotated = np.rot90(page, turns).copy()
    corrected = orient_work_order_page(rotated)

    assert corrected.shape == page.shape
    assert len(list(cut_forms(corrected))) == 2


def test_orientation_check_leaves_non_template_gallery_pages_unchanged(raster):
    cv2, np = raster
    from printer_app.gallery.cropper import orient_work_order_page

    image = np.full((700, 900, 3), 255, np.uint8)
    cv2.putText(
        image, 'LEGACY PAGE', (120, 350), cv2.FONT_HERSHEY_SIMPLEX,
        2.0, (0, 0, 0), 4, cv2.LINE_AA,
    )

    assert orient_work_order_page(image) is image


@pytest.mark.parametrize('slant', [0, 18])
def test_landscape_report_with_few_or_slanted_columns_is_rejected(raster, slant):
    cv2, np = raster
    from printer_app.gallery.cropper import is_dense_grid_page, cut_forms

    image = np.full((800, 1400), 255, np.uint8)
    for y in range(35, 750, 23):
        cv2.line(image, (10, y), (1380, y), 0, 2)
    for x in (10, 100, 210, 420, 680, 870, 1050, 1380):
        cv2.line(image, (x, 35), (x - slant, 748), 0, 2)
    for y in (242, 426, 610):
        cv2.rectangle(image, (10, y), (1380, y + 19), 60, -1)

    assert is_dense_grid_page(image)
    assert list(cut_forms(image)) == []


def test_cropper_has_no_header_or_next_top_segmentation_path():
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    source = (root / 'gallery/cropper.py').read_text()

    assert '_form_tops_native' not in source
    assert '_template_confirmed_tops_native' not in source
    assert 'bottom = tops[index+1]' not in source
    assert 'find_form_registrations' in source
