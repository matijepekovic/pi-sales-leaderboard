"""Known work-order form geometry supplied by the blank single-card template.

This module owns only normalized template geometry/registration. Page cutting remains
in cropper.py and OCR remains in recognition.py. A future form can replace this
template contract without changing Gallery repositories, services, web or printing.
"""
from dataclasses import dataclass

# Measured from the supplied 1942x809 blank form. Coordinates are the printed outer
# frame, not image edges, so all OCR fields below remain stable across render sizes.
_SOURCE_LEFT = 26.0
_SOURCE_RIGHT = 1916.0
_SOURCE_TOP = 19.0
_SOURCE_BOTTOM = 786.5
TEMPLATE_WIDTH = _SOURCE_RIGHT - _SOURCE_LEFT
TEMPLATE_HEIGHT = _SOURCE_BOTTOM - _SOURCE_TOP
TEMPLATE_ASPECT_HEIGHT = TEMPLATE_HEIGHT / TEMPLATE_WIDTH


def _nx(value):
    return (float(value) - _SOURCE_LEFT) / TEMPLATE_WIDTH


def _ny(value):
    return (float(value) - _SOURCE_TOP) / TEMPLATE_HEIGHT


def _box(left, top, right, bottom):
    return (_nx(left), _ny(top), _nx(right), _ny(bottom))


# Major horizontal rules measured from the blank form. These are the irregular rows
# that distinguish this work order from generic reports/tables.
TEMPLATE_HORIZONTAL = tuple(_ny(value) for value in (
    19.0,
    68.5,
    154.5,
    244.0,
    333.5,
    383.0,
    473.0,
    554.5,
    605.5,
    710.0,
    786.5,
))
REGISTRATION_MIN_SCORE = 0.72
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


@dataclass(frozen=True)
class TemplateField:
    """One searchable variable region in normalized outer-frame coordinates."""

    key: str
    label: str
    box: tuple
    label_box: tuple
    lead: bool = False
    date_candidate: bool = False


# Cell and printed-label rectangles measured from the blank template. Recognition
# removes only these constant labels, then OCRs the remaining variable ink. Large
# free-form cells stay represented here too, so populated notes remain searchable;
# blank cells are skipped cheaply before Tesseract sees them.
TEMPLATE_FIELDS = (
    TemplateField('work_order_number', 'Work Order Number',
                  _box(26, 19, 594, 68.5), _box(37, 34, 324, 56)),
    TemplateField('local_scheduled_start_time', 'Local Scheduled Start Time',
                  _box(594, 19, 1347, 68.5), _box(605, 34, 975, 56), date_candidate=True),
    TemplateField('canvass_set_by', 'Canvass Set By',
                  _box(1347, 19, 1916, 68.5), _box(1358, 34, 1566, 62)),
    TemplateField('lead_name', 'Lead Name',
                  _box(26, 68.5, 594, 154.5), _box(38, 85, 194, 107), lead=True),
    TemplateField('address', 'Address',
                  _box(594, 68.5, 1347, 154.5), _box(604, 85, 718, 107)),
    TemplateField('phone', 'Phone',
                  _box(1347, 68.5, 1710.5, 154.5), _box(1359, 85, 1447, 107)),
    TemplateField('power_questions', 'Power Questions',
                  _box(1710.5, 68.5, 1916, 154.5), _box(1723, 85, 1901, 147)),
    TemplateField('scheduled_start', 'Scheduled Start',
                  _box(26, 154.5, 407, 244), _box(39, 171, 253, 193), date_candidate=True),
    TemplateField('assigned_service_resource', 'Assigned Service Resource',
                  _box(407, 154.5, 1347, 244), _box(418, 171, 774, 199)),
    TemplateField('set_by', 'Set By',
                  _box(1347, 154.5, 1710.5, 244), _box(1360, 171, 1451, 199)),
    TemplateField('t_close', 'T Close',
                  _box(1710.5, 154.5, 1916, 244), _box(1721, 171, 1828, 193)),
    TemplateField('work_type', 'Work Type',
                  _box(26, 244, 407, 333.5), _box(38, 260, 194, 288)),
    TemplateField('product_interest', 'Product Interest',
                  _box(407, 244, 969, 333.5), _box(418, 260, 637, 282)),
    TemplateField('source', 'Source',
                  _box(969, 244, 1347, 333.5), _box(981, 260, 1077, 282)),
    TemplateField('sub_source', 'Sub Source',
                  _box(1347, 244, 1710.5, 333.5), _box(1359, 260, 1514, 282)),
    TemplateField('hover_flir', 'Hover / Flir',
                  _box(1710.5, 244, 1916, 333.5), _box(1723, 260, 1884, 282)),
    TemplateField('lead_description', 'Lead Description',
                  _box(26, 333.5, 791, 473), _box(38, 349, 271, 376)),
    TemplateField('start_price', 'Start Price',
                  _box(791, 333.5, 1156, 383), _box(804, 348, 953, 370)),
    TemplateField('final_price', 'Final Price',
                  _box(1156, 333.5, 1536, 383), _box(1169, 349, 1319, 370)),
    TemplateField('deposit_payment', 'Deposit/Payment',
                  _box(1536, 333.5, 1916, 383), _box(1548, 349, 1778, 376)),
    TemplateField('mod_notes', 'MOD Notes',
                  _box(791, 383, 1916, 786.5), _box(804, 400, 964, 421)),
    TemplateField('fin_checklist', 'Fin Checklist',
                  _box(26, 473, 238.5, 554.5), _box(38, 489, 211, 511)),
    TemplateField('bid_sheets', 'Bid Sheets',
                  _box(238.5, 473, 547, 554.5), _box(250, 489, 386, 512)),
    TemplateField('pictures', 'Pictures',
                  _box(547, 473, 791, 554.5), _box(561, 489, 665, 511)),
    TemplateField('dispo', 'Dispo',
                  _box(26, 554.5, 791, 605.5), _box(38, 570, 121, 598)),
    TemplateField('call_1', 'Call 1',
                  _box(26, 605.5, 238.5, 657.5), _box(39, 621, 123, 642)),
    TemplateField('call_2', 'Call 2',
                  _box(26, 657.5, 238.5, 710), _box(39, 673, 122, 695)),
    TemplateField('need', 'Need',
                  _box(238.5, 605.5, 791, 710), _box(250, 621, 323, 643)),
    TemplateField('90_min', '90 Min',
                  _box(26, 710, 238.5, 786.5), _box(38, 726, 138, 747)),
    TemplateField('want', 'Want',
                  _box(238.5, 710, 791, 786.5), _box(250, 726, 329, 747)),
)


def map_box(registration, box):
    """Map a normalized template box into one registered crop's pixel space."""
    width = max(1, registration.right - registration.left)
    height = max(1, registration.bottom - registration.top)
    left, top, right, bottom = box
    return (
        registration.left + int(round(left * width)),
        registration.top + int(round(top * height)),
        registration.left + int(round(right * width)),
        registration.top + int(round(bottom * height)),
    )


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

    # The outer top/bottom rules define y-scale directly. This is more robust than
    # assuming a renderer's x/y scaling is perfectly isotropic.
    max_top = max(8.0, printed_width * 0.08)
    near_top = centers[centers <= max_top]
    if not len(near_top):
        return FormRegistration(0.0, 0, original_w, 0, original_h)
    top = float(near_top[0])
    candidate_bottoms = centers[
        (centers - top >= printed_width * 0.34)
        & (centers - top <= min(h - top, printed_width * 0.48))
    ]
    if not len(candidate_bottoms):
        return FormRegistration(0.0, 0, original_w, 0, original_h)

    best = None
    for bottom in candidate_bottoms:
        expected_height = float(bottom - top)
        tolerance = max(4.0, expected_height * 0.03)
        distances = []
        for ratio in TEMPLATE_HORIZONTAL:
            expected = top + ratio * expected_height
            distances.append(float(np.min(np.abs(centers - expected))))
        score = sum(distance <= tolerance for distance in distances) / len(distances)
        residual = sum(min(distance / expected_height, 0.10) for distance in distances) / len(distances)
        rank = (score, -residual, -abs(expected_height / printed_width - TEMPLATE_ASPECT_HEIGHT))
        if best is None or rank > best[0]:
            best = (rank, score, float(bottom))

    _, score, bottom = best
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
