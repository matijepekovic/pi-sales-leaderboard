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
