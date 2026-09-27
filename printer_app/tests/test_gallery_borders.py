"""Synthetic unequal-height forms only; no customer images committed."""
import pytest


def test_borders_not_thirds_preserve_space_until_next_box():
    cv2 = pytest.importorskip('cv2')
    np = pytest.importorskip('numpy')
    from printer_app.gallery.cropper import cut_forms
    image = np.full((1600, 1000, 3), 255, np.uint8)
    for top, bottom in ((50, 300), (450, 700), (940, 1300)):
        cv2.rectangle(image, (60, top), (940, bottom), (0, 0, 0), 3)
        for row in (top+40, top+90):
            cv2.line(image, (60, row), (940, row), (0, 0, 0), 2)
        cv2.line(image, (450, top), (450, bottom), (0, 0, 0), 2)
    image[370:385, 150:170] = (200, 0, 0)  # Overflow below first box.
    image[1510:1520, 150:170] = (0, 0, 200)  # Last crop reaches page edge.
    crops = list(cut_forms(image))
    assert len(crops) == 3
    assert all(c.shape[1] == 1000 for _, c in crops)
    assert abs(crops[0][1].shape[0] - 400) < 10
    assert abs(crops[1][1].shape[0] - 490) < 10
    assert abs(crops[2][1].shape[0] - 660) < 10
    assert ((crops[0][1] == [200, 0, 0]).all(axis=2)).any()
    assert ((crops[-1][1] == [0, 0, 200]).all(axis=2)).any()


def test_template_registration_trims_only_blank_tail_after_last_card():
    cv2 = pytest.importorskip('cv2')
    np = pytest.importorskip('numpy')
    from printer_app.gallery.cropper import cut_forms
    from printer_app.gallery.form_template import TEMPLATE_ASPECT_HEIGHT, TEMPLATE_HORIZONTAL

    image = np.full((1700, 1000, 3), 255, np.uint8)
    left, right = 50, 950
    width = right - left
    height = int(round(width * TEMPLATE_ASPECT_HEIGHT))
    tops = (40, 520, 1000)

    for top in tops:
        bottom = top + height
        cv2.line(image, (left, top), (right, top), (0, 0, 0), 3)
        cv2.line(image, (left, bottom), (right, bottom), (0, 0, 0), 3)
        cv2.line(image, (left, top), (left, bottom), (0, 0, 0), 3)
        cv2.line(image, (right, top), (right, bottom), (0, 0, 0), 3)
        for ratio in TEMPLATE_HORIZONTAL[1:-1]:
            y = top + int(round(ratio * height))
            cv2.line(image, (left, y), (right, y), (0, 0, 0), 2)
        # Strong header partition used by the same geometry contract as production.
        cv2.line(image, (430, top), (430, top + int(height * .20)), (0, 0, 0), 2)

    # Real handwriting below the final printed border must remain; empty page tail must not.
    final_bottom = tops[-1] + height
    cv2.putText(image, 'CALL BACK', (160, final_bottom + 55), cv2.FONT_HERSHEY_SIMPLEX,
                1.0, (0, 0, 0), 3, cv2.LINE_AA)

    crops = list(cut_forms(image))
    assert len(crops) == 3
    last = crops[-1][1]
    assert last.shape[0] < 600  # no blank run to the 1700px page edge
    assert last.shape[0] > height + 55  # handwriting below the form is retained


def test_large_template_page_uses_same_card_count_as_normal_scale():
    cv2 = pytest.importorskip('cv2')
    np = pytest.importorskip('numpy')
    from printer_app.gallery.cropper import cut_forms

    base = np.full((900, 700, 3), 255, np.uint8)
    for top in (30, 310, 590):
        bottom = min(860, top + 220)
        cv2.rectangle(base, (40, top), (660, bottom), (0, 0, 0), 3)
        cv2.line(base, (40, top + 45), (660, top + 45), (0, 0, 0), 2)
        cv2.line(base, (40, top + 95), (660, top + 95), (0, 0, 0), 2)
        cv2.line(base, (320, top), (320, bottom), (0, 0, 0), 2)

    large = cv2.resize(base, (2800, 3600), interpolation=cv2.INTER_NEAREST)
    assert len(list(cut_forms(base))) == len(list(cut_forms(large))) == 3


@pytest.mark.parametrize('turns', [1, 2, 3])
def test_right_angle_template_pages_are_normalized_before_cropping(turns):
    cv2 = pytest.importorskip('cv2')
    np = pytest.importorskip('numpy')
    from printer_app.gallery.cropper import cut_forms, orient_work_order_page
    from printer_app.tests.gallery_form_fixture import form_image

    form, _ = form_image((cv2, np), scale=0.45)
    margin = 28
    height, width = form.shape
    image = np.full((height * 2 + margin * 3, width + margin * 2), 255, np.uint8)
    image[margin:margin + height, margin:margin + width] = form
    second = margin * 2 + height
    image[second:second + height, margin:margin + width] = form

    assert len(list(cut_forms(image))) == 2

    rotated = np.rot90(image, turns).copy()
    corrected = orient_work_order_page(rotated)

    assert np.array_equal(corrected, image)
    assert len(list(cut_forms(corrected))) == 2

def test_template_registration_cannot_bypass_report_rejection(monkeypatch):
    np = pytest.importorskip('numpy')
    from printer_app.gallery import cropper
    from printer_app.gallery.form_template import FormRegistration

    image = np.full((700, 900, 3), 255, np.uint8)
    top = np.full(image.shape[1], 20, dtype=int)

    monkeypatch.setattr(cropper, 'form_tops', lambda image: [top])
    monkeypatch.setattr(
        cropper,
        'register_form',
        lambda crop: FormRegistration(1.0, 0, crop.shape[1], 0, min(crop.shape[0], 300)),
    )
    monkeypatch.setattr(cropper, 'is_work_order_form', lambda crop: False)

    assert list(cropper.cut_forms(image)) == []


def test_orientation_check_leaves_non_template_gallery_pages_unchanged():
    cv2 = pytest.importorskip('cv2')
    np = pytest.importorskip('numpy')
    from printer_app.gallery.cropper import orient_work_order_page

    image = np.full((700, 900, 3), 255, np.uint8)
    cv2.putText(
        image, 'LEGACY PAGE', (120, 350), cv2.FONT_HERSHEY_SIMPLEX,
        2.0, (0, 0, 0), 4, cv2.LINE_AA,
    )

    assert orient_work_order_page(image) is image


def test_shifted_outer_edges_do_not_hide_first_header_or_cut_its_value():
    cv2 = pytest.importorskip('cv2')
    np = pytest.importorskip('numpy')
    from printer_app.gallery.cropper import cut_forms
    from printer_app.tests.gallery_form_fixture import form_image
    from printer_app.gallery.form_template import TEMPLATE_FIELDS, map_box

    form, registration = form_image((cv2, np), scale=.45)
    field = next(field for field in TEMPLATE_FIELDS if field.key == 'work_order_number')
    left, top, right, bottom = map_box(registration, field.box)
    form[top + 7:bottom - 4, right - 35:right - 15] = 80
    height, width = form.shape
    page = np.full((height * 3 + 160, width + 160), 255, np.uint8)
    # Both first-card sides lie outside the strongest lower-card edge bands.
    for index, x in enumerate((80, 30, 30)):
        y = 30 + index * (height + 35)
        page[y:y + height, x:x + width] = form

    crops = list(cut_forms(page))

    assert len(crops) == 3
    expected = np.count_nonzero(form == 80)
    assert all(np.count_nonzero(crop == 80) == expected for _, crop in crops)


@pytest.mark.parametrize('slant', [0, 18])
def test_landscape_report_with_few_or_slanted_columns_is_rejected(slant):
    cv2 = pytest.importorskip('cv2')
    np = pytest.importorskip('numpy')
    from printer_app.gallery.cropper import is_dense_grid_page, cut_forms

    image = np.full((800, 1400), 255, np.uint8)
    for y in range(35, 750, 23):
        cv2.line(image, (10, y), (1380, y), 0, 2)
    # These reports have fewer columns than the older 12/14-column rejectors.
    for x in (10, 100, 210, 420, 680, 870, 1050, 1380):
        cv2.line(image, (x, 35), (x - slant, 748), 0, 2)
    for y in (242, 426, 610):
        cv2.rectangle(image, (10, y), (1380, y + 19), 60, -1)

    assert is_dense_grid_page(image)
    assert list(cut_forms(image)) == []
