"""Known work-order form geometry supplied by the blank single-card template.

This module owns only normalized template geometry/registration. Page cutting remains
in cropper.py and OCR remains in recognition.py. A future form can replace this
template contract without changing Gallery repositories, services, web or printing.
"""
from dataclasses import dataclass

# Measured from the supplied blank template's printed outer frame:
# left=21.5, right=1092.5, top=6.5, bottom=448.5 on a 1112x476 source.
TEMPLATE_WIDTH = 1071.0
TEMPLATE_HEIGHT = 442.0
TEMPLATE_ASPECT_HEIGHT = TEMPLATE_HEIGHT / TEMPLATE_WIDTH

# Major horizontal rules, normalized inside the printed outer frame. Partial rules
# are included because the form's irregular spacing is a strong registration signal.
TEMPLATE_HORIZONTAL = (
    0.0,
    25.0 / TEMPLATE_HEIGHT,
    73.0 / TEMPLATE_HEIGHT,
    120.5 / TEMPLATE_HEIGHT,
    168.0 / TEMPLATE_HEIGHT,
    193.5 / TEMPLATE_HEIGHT,
    257.0 / TEMPLATE_HEIGHT,
    304.5 / TEMPLATE_HEIGHT,
    330.0 / TEMPLATE_HEIGHT,
    386.0 / TEMPLATE_HEIGHT,
    1.0,
)
REGISTRATION_MIN_SCORE = 0.64
ANALYSIS_WIDTH = 1200


@dataclass(frozen=True)
class FormRegistration:
    score: float
    left: int
    right: int
    top: int
    bottom: int

    @property
    def matched(self):
        return self.score >= REGISTRATION_MIN_SCORE


def _runs(mask, np):
    edges = np.flatnonzero(np.diff(np.r_[False, mask, False].astype(np.int8)))
    return list(zip(edges[::2], edges[1::2]))


def register_form(image):
    """Register one already-deskewed card to the known template.

    Registration deliberately uses a small analysis raster and only printed rules.
    Handwriting/field values therefore do not define geometry. The returned coordinates
    are in the original image space. A low score means callers must use the legacy
    geometry path instead of trusting this template.
    """
    import cv2
    import numpy as np

    if image is None or min(image.shape[:2]) < 80:
        return FormRegistration(0.0, 0, 0, 0, image.shape[0] if image is not None else 0)

    original_h, original_w = image.shape[:2]
    scale = min(1.0, ANALYSIS_WIDTH / float(original_w))
    if scale < 1.0:
        small = cv2.resize(
            image,
            (max(1, int(round(original_w * scale))), max(1, int(round(original_h * scale)))),
            interpolation=cv2.INTER_AREA,
        )
    else:
        small = image

    if small.ndim == 2:
        gray = small
    elif small.shape[2] == 4:
        gray = cv2.cvtColor(small, cv2.COLOR_RGBA2GRAY)
    else:
        gray = cv2.cvtColor(small, cv2.COLOR_RGB2GRAY)

    h, w = gray.shape
    ink = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)[1]
    vertical = cv2.morphologyEx(
        ink,
        cv2.MORPH_OPEN,
        np.ones((max(12, w // 65), 1), np.uint8),
    )
    horizontal = cv2.morphologyEx(
        ink,
        cv2.MORPH_OPEN,
        np.ones((1, max(20, w // 40)), np.uint8),
    )

    votes = vertical.sum(axis=0)
    left = int(votes[:max(1, w // 5)].argmax())
    right_start = max(0, 4 * w // 5)
    right = int(votes[right_start:].argmax()) + right_start
    printed_width = right - left
    if printed_width < 0.60 * w:
        return FormRegistration(0.0, 0, original_w, 0, original_h)

    rows = _runs((horizontal > 0).mean(axis=1) > 0.24, np)
    centers = np.asarray([(a + b) / 2.0 for a, b in rows], dtype=float)
    if len(centers) < 5:
        return FormRegistration(0.0, 0, original_w, 0, original_h)

    # The first long rule near the candidate top is the template origin.
    max_top = max(8.0, printed_width * 0.08)
    near_top = centers[centers <= max_top]
    if not len(near_top):
        return FormRegistration(0.0, 0, original_w, 0, original_h)
    top = float(near_top[0])
    expected_height = printed_width * TEMPLATE_ASPECT_HEIGHT
    tolerance = max(4.0, expected_height * 0.025)

    matches = []
    for ratio in TEMPLATE_HORIZONTAL:
        expected = top + ratio * expected_height
        distance = float(np.min(np.abs(centers - expected)))
        matches.append(distance <= tolerance)

    score = sum(matches) / len(matches)

    expected_bottom = top + expected_height
    bottom_candidates = centers[np.abs(centers - expected_bottom) <= tolerance * 1.6]
    bottom = float(bottom_candidates[-1]) if len(bottom_candidates) else expected_bottom
    bottom = min(float(h), max(top + 1.0, bottom))

    inverse = 1.0 / scale
    return FormRegistration(
        score=float(score),
        left=max(0, int(round(left * inverse))),
        right=min(original_w, int(round(right * inverse))),
        top=max(0, int(round(top * inverse))),
        bottom=min(original_h, int(round(bottom * inverse))),
    )


def trim_last_form(image, registration):
    """Trim only blank tail below the final card while preserving real pen ink.

    Earlier cards still stop at the next card's top border. For the last card, the
    known template locates the printed bottom, then meaningful ink below it extends
    the crop. Once that ink ends, blank scanner tail is removed.
    """
    import cv2
    import numpy as np

    if image is None or not registration.matched:
        return image
    h, w = image.shape[:2]
    printed_bottom = min(h, max(1, registration.bottom))
    if printed_bottom >= h:
        return image

    gray = image if image.ndim == 2 else (
        cv2.cvtColor(image, cv2.COLOR_RGBA2GRAY)
        if image.shape[2] == 4 else cv2.cvtColor(image, cv2.COLOR_RGB2GRAY)
    )
    x0 = max(0, registration.left - max(4, int(w * 0.01)))
    x1 = min(w, registration.right + max(4, int(w * 0.01)))
    tail = gray[printed_bottom:h, x0:x1]
    if not tail.size:
        return image[:printed_bottom].copy()

    # Ignore isolated scan dust but retain normal pen strokes/printed overflow.
    binary = (tail < 225).astype(np.uint8)
    count, _, stats, _ = cv2.connectedComponentsWithStats(binary, 8)
    minimum_area = max(10, int((x1 - x0) * 0.003))
    bottoms = []
    for label in range(1, count):
        x, y, cw, ch, area = stats[label]
        if area >= minimum_area and (cw >= 2 or ch >= 3):
            bottoms.append(y + ch)

    margin = max(8, int(w * 0.012))
    end = printed_bottom + (max(bottoms) if bottoms else 0) + margin
    end = min(h, max(printed_bottom + 2, end))
    return image[:end].copy()
