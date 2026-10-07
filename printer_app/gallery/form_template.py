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
MAX_FORMS_PER_PAGE = 3
PAGE_MATCH_MIN_ROW_SCORE = 0.50
PAGE_MATCH_MIN_GEOMETRY = 0.48


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
    """One form cell in normalized outer-frame coordinates."""

    key: str
    label: str
    box: tuple
    label_box: tuple
    lead: bool = False
    date_candidate: bool = False


# Cell and printed-label rectangles measured from the blank template. All cells
# participate in geometric border detection; recognition owns which values are
# parsed. In particular, partial lower-form rules must not be mistaken for a
# neighboring full-width border, even when those lower cells are not parsed.
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


def _rule_band(mask, expected, span_start, span_stop, radius):
    """Locate the complete thickness of a nearby long rule.

    The first mask axis is perpendicular to the rule. A small amount of residual
    scan slope can spread one rule over several rows; coverage across that band
    must still span most of this cell. Short text strokes cannot supply a border.
    """
    import numpy as np

    length, across = mask.shape
    first = max(0, int(round(expected - radius)))
    last = min(length, int(round(expected + radius)) + 1)
    span_start = max(0, min(across, int(span_start)))
    span_stop = max(0, min(across, int(span_stop)))
    if last <= first or span_stop <= span_start:
        return None
    window = mask[first:last, span_start:span_stop]
    support = (window > 0).mean(axis=1)
    candidates = []
    for start, stop in _runs(support >= .10, np):
        # A partial/broken rule is useful only when enough of its horizontal
        # extent survives. Reject broad blocks and clipped search-window bands.
        if (stop - start > max(3, radius * .95)
                or (start == 0 and first > 0)
                or (stop == last - first and last < length)):
            continue
        coverage = (window[start:stop] > 0).any(axis=0).mean()
        if coverage < .65:
            continue
        a, b = first + int(start), first + int(stop)
        distance = abs((a + b - 1) / 2.0 - expected)
        candidates.append((distance, -float(coverage), a, b))
    if not candidates:
        return None
    _, _, start, stop = min(candidates)
    return start, stop


def _inside_rule(mask, expected, span_start, span_stop, radius, inward, fallback):
    band = _rule_band(mask, expected, span_start, span_stop, radius)
    if band is None:
        return expected + inward * fallback
    start, stop = band
    return stop if inward > 0 else start


def _field_rules(image, registration):
    """Observe shared printed rules once for rectangular and curved cell crops."""
    import cv2
    import numpy as np

    gray = image if image.ndim == 2 else (
        cv2.cvtColor(image, cv2.COLOR_RGBA2GRAY)
        if image.shape[2] == 4 else cv2.cvtColor(image, cv2.COLOR_RGB2GRAY)
    )
    height, width = gray.shape
    frame_width = max(1, registration.right - registration.left)
    frame_height = max(1, registration.bottom - registration.top)
    ink = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)[1]
    horizontal = cv2.morphologyEx(
        ink, cv2.MORPH_OPEN,
        np.ones((1, max(16, int(round(frame_width * .04)))), np.uint8),
    )
    vertical = cv2.morphologyEx(
        ink, cv2.MORPH_OPEN,
        np.ones((max(12, int(round(frame_width * .018))), 1), np.uint8),
    ).T
    fallback = max(1, int(round(frame_width * .001)))

    # Some rows divide only one side of the form. Vote over every cell sharing
    # a template row before refining individual segments, so a nearby partial
    # rule cannot masquerade as the full-width border above it. For example,
    # the Start Price/MOD Notes separator is not the bottom of Sub Source.
    rows = {}
    expected_boxes = [(field, map_box(registration, field.box)) for field in TEMPLATE_FIELDS]
    for field, (left, top, right, bottom) in expected_boxes:
        for ratio, edge in ((field.box[1], top), (field.box[3], bottom)):
            entry = rows.setdefault(ratio, [edge, left, right, []])
            entry[1] = min(entry[1], left)
            entry[2] = max(entry[2], right)
            entry[3].append(max(1, bottom - top))
    horizontal_bands = {}
    anchors = []
    for ratio, (edge, left, right, _) in sorted(rows.items()):
        if right - left < frame_width * .90:
            continue
        pad = max(2, int(round((right - left) * .025)))
        band = _rule_band(
            horizontal, edge, left + pad, right - pad,
            max(4, frame_height * .075),
        )
        horizontal_bands[ratio] = band
        if band is not None:
            anchors.append((ratio, (band[0] + band[1] - 1) / 2.0))
    for ratio, (edge, left, right, cell_heights) in rows.items():
        if ratio in horizontal_bands:
            continue
        # Renderer row heights can differ from the blank template. The observed
        # full-width rows provide a local y mapping for shorter, partial rules.
        if len(anchors) >= 2:
            edge = float(np.interp(ratio, [a[0] for a in anchors], [a[1] for a in anchors]))
        pad = max(2, int(round((right - left) * .025)))
        radius = max(3, min(frame_height * .075, min(cell_heights) * .42))
        horizontal_bands[ratio] = _rule_band(
            horizontal, edge, left + pad, right - pad, radius,
        )
    thicknesses = [band[1] - band[0] for band in horizontal_bands.values() if band]
    if thicknesses:
        # A broken edge still has the same printed stroke thickness as nearby
        # rules. Its fallback should exclude that stroke, not a fixed crop margin.
        fallback = max(fallback, int(np.ceil(np.median(thicknesses) / 2.0)))

    return horizontal, vertical, expected_boxes, horizontal_bands, fallback


def field_boxes(image, registration):
    """Return ordered template fields with observed, inside-the-rule bounds.

    Template coordinates identify each cell; shared rule masks refine its edges
    locally. Bounds use exclusive right/bottom coordinates. A missing rule keeps
    the expected edge with only a small stroke-width inset, rather than looking
    farther away and accidentally including a neighboring field. Labels belong
    to recognition and do not affect this geometric contract.
    """
    if image is None or not image.size:
        return [(field, (0, 0, 0, 0)) for field in TEMPLATE_FIELDS]
    horizontal, vertical, expected_boxes, horizontal_bands, fallback = _field_rules(image, registration)
    height, width = image.shape[:2]
    frame_width = max(1, registration.right - registration.left)

    result = []
    for field, (left, top, right, bottom) in expected_boxes:
        cell_width, cell_height = max(1, right - left), max(1, bottom - top)
        radius_x = max(3, min(frame_width * .04, cell_width * .30))
        across_pad = max(2, int(round(cell_width * .025)))
        edges = []
        for ratio, expected, inward in ((field.box[1], top, 1), (field.box[3], bottom, -1)):
            band = horizontal_bands[ratio]
            if band is None:
                edges.append(expected + inward * fallback)
                continue
            center = (band[0] + band[1] - 1) / 2.0
            # Follow only this identified row. Local thickness can differ, and
            # a slightly sloped scan may shift its segment by a few pixels.
            radius = max(5, band[1] - band[0] + frame_width * .003)
            local = _rule_band(
                horizontal, center, left + across_pad, right - across_pad, radius,
            ) or band
            edges.append(local[1] if inward > 0 else local[0])
        refined_top, refined_bottom = edges
        # Horizontal rules are excluded from the vertical vote, including cell
        # corners. This also lets a short cell retain all ink beside its rules.
        vertical_pad = max(1, int(round(cell_height * .025)))
        refined_left = _inside_rule(
            vertical, left, refined_top + vertical_pad,
            refined_bottom - vertical_pad, radius_x, 1, fallback,
        )
        refined_right = _inside_rule(
            vertical, right, refined_top + vertical_pad,
            refined_bottom - vertical_pad, radius_x, -1, fallback,
        )
        x0 = max(0, min(width, int(refined_left)))
        y0 = max(0, min(height, int(refined_top)))
        x1 = max(x0, min(width, int(refined_right)))
        y1 = max(y0, min(height, int(refined_bottom)))
        result.append((field, (x0, y0, x1, y1)))
    return result


def _rule_trace(mask, band, span_start, span_stop, inward, fallback):
    """Trace a cell's inner edge along a selected rule, bridging only its gaps."""
    import numpy as np

    across = mask.shape[1]
    if band is None:
        return np.full(across, fallback, dtype=int)
    start, stop = band
    first, last = max(0, int(span_start)), min(across, int(span_stop))
    window = mask[start:stop, first:last] > 0
    valid = window.any(axis=0)
    if not np.any(valid):
        return np.full(across, fallback, dtype=int)
    positions = np.flatnonzero(valid) + first
    if inward > 0:
        edge = stop - window[::-1, valid].argmax(axis=0)
    else:
        edge = start + window[:, valid].argmax(axis=0)
    return np.rint(np.interp(np.arange(across), positions, edge)).astype(int)


def field_crop(image, registration, key):
    """Extract one observed cell, masking its curved borders without clipping ink.

    A sloped row has no rectangular interior that contains every printed digit.
    Keep the bounding envelope and whiten pixels outside each observed edge.
    Returned bounds are absolute, with exclusive right/bottom coordinates; the
    archived image is unchanged. Label removal remains the recognition owner's job.
    """
    import numpy as np

    if image is None or not image.size:
        return None, (0, 0, 0, 0)
    horizontal, vertical, expected, bands, fallback = _field_rules(image, registration)
    chosen = next(((field, box) for field, box in expected if field.key == key), None)
    if chosen is None:
        return None, (0, 0, 0, 0)
    field, (left, top, right, bottom) = chosen
    width = max(1, registration.right - registration.left)
    height = max(1, registration.bottom - registration.top)
    pad = max(2, int(round((right - left) * .025)))
    edges = []
    for ratio, expected_y, inward in ((field.box[1], top, 1), (field.box[3], bottom, -1)):
        shared = bands[ratio]
        center = (shared[0] + shared[1] - 1) / 2.0 if shared else expected_y
        radius = max(5, shared[1] - shared[0] + width * .003) if shared else max(4, height * .075)
        local = _rule_band(horizontal, center, left + pad, right - pad, radius)
        edges.append(_rule_trace(
            horizontal, local or shared, left + pad, right - pad, inward,
            expected_y + inward * fallback))
    upper, lower = edges
    span_left, span_right = max(0, left), min(image.shape[1], right)
    if span_right <= span_left:
        return None, (0, 0, 0, 0)
    y0 = max(0, int(upper[span_left:span_right].min()))
    y1 = min(image.shape[0], int(lower[span_left:span_right].max()))
    if y1 <= y0:
        return None, (0, 0, 0, 0)
    vertical_pad = max(1, int(round((bottom - top) * .025)))
    radius = max(3, min(width * .04, (right - left) * .30))
    left_trace = _rule_trace(
        vertical, _rule_band(vertical, left, y0 + vertical_pad, y1 - vertical_pad, radius),
        y0 + vertical_pad, y1 - vertical_pad, 1, left + fallback)
    right_trace = _rule_trace(
        vertical, _rule_band(vertical, right, y0 + vertical_pad, y1 - vertical_pad, radius),
        y0 + vertical_pad, y1 - vertical_pad, -1, right - fallback)
    x0 = max(0, int(left_trace[y0:y1].min()))
    x1 = min(image.shape[1], int(right_trace[y0:y1].max()))
    if x1 <= x0:
        return None, (0, 0, 0, 0)
    crop = image[y0:y1, x0:x1].copy()
    xx, yy = np.arange(x0, x1)[None, :], np.arange(y0, y1)[:, None]
    outside = ((yy < upper[x0:x1]) | (yy >= lower[x0:x1])
               | (xx < left_trace[y0:y1, None]) | (xx >= right_trace[y0:y1, None]))
    crop[outside] = 255
    return crop, (x0, y0, x1, y1)


def template_geometry_score(image, registration):
    """Score the observed printed grid against the complete known MOD template.

    Horizontal and vertical cell segments both participate. Handwriting and
    field values are suppressed by long-line morphology, so orientation is
    decided by the form itself rather than OCR or page contents.
    """
    import cv2
    import numpy as np

    if image is None or not image.size:
        return 0.0
    frame_width = max(1, registration.right - registration.left)
    frame_height = max(1, registration.bottom - registration.top)
    if frame_width < 120 or frame_height < 60:
        return 0.0

    gray = image if image.ndim == 2 else (
        cv2.cvtColor(image, cv2.COLOR_RGBA2GRAY)
        if image.shape[2] == 4 else cv2.cvtColor(image, cv2.COLOR_RGB2GRAY)
    )
    ink = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)[1]
    horizontal = cv2.morphologyEx(
        ink, cv2.MORPH_OPEN,
        np.ones((1, max(18, int(round(frame_width * .025)))), np.uint8),
    )
    vertical = cv2.morphologyEx(
        ink, cv2.MORPH_OPEN,
        np.ones((max(14, int(round(frame_height * .035))), 1), np.uint8),
    )

    h_segments = set()
    v_segments = set()
    for field in TEMPLATE_FIELDS:
        left, top, right, bottom = map_box(registration, field.box)
        if right - left >= frame_width * .07:
            h_segments.add((left, right, top))
            h_segments.add((left, right, bottom))
        if bottom - top >= frame_height * .035:
            v_segments.add((top, bottom, left))
            v_segments.add((top, bottom, right))

    tolerance_y = max(2, int(round(frame_height * .006)))
    tolerance_x = max(2, int(round(frame_width * .004)))

    def horizontal_support(segment):
        left, right, expected = segment
        left, right = max(0, left), min(horizontal.shape[1], right)
        first = max(0, expected - tolerance_y)
        last = min(horizontal.shape[0], expected + tolerance_y + 1)
        if right <= left or last <= first:
            return 0.0
        return float((horizontal[first:last, left:right] > 0).mean(axis=1).max())

    def vertical_support(segment):
        top, bottom, expected = segment
        top, bottom = max(0, top), min(vertical.shape[0], bottom)
        first = max(0, expected - tolerance_x)
        last = min(vertical.shape[1], expected + tolerance_x + 1)
        if bottom <= top or last <= first:
            return 0.0
        return float((vertical[top:bottom, first:last] > 0).mean(axis=0).max())

    h_scores = [min(1.0, horizontal_support(segment) / .55) for segment in h_segments]
    v_scores = [min(1.0, vertical_support(segment) / .55) for segment in v_segments]
    if not h_scores or not v_scores:
        return 0.0
    return float(.35 * np.mean(h_scores) + .65 * np.mean(v_scores))


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
    # A bowed outer edge can occupy many columns while an internal partition
    # remains straight and wins the vertical vote. The endpoints of long printed
    # horizontal rules independently identify the outside frame in that case.
    # Broken horizontal rules can begin or end inside a valid vertical frame,
    # so this evidence may expand the frame but must never move it inward.
    joined = cv2.morphologyEx(horizontal, cv2.MORPH_CLOSE, np.ones((3, 9), np.uint8))
    count, _, stats, _ = cv2.connectedComponentsWithStats(joined)
    wide = [(x, x + width - 1) for x, y, width, height, area in stats[1:count]
            if width >= .60 * w and height < .08 * w]
    left_edges = [edge[0] for edge in wide if edge[0] < w * .20]
    right_edges = [edge[1] for edge in wide if edge[1] > w * .80]
    if len(left_edges) >= 3:
        left = min(left, int(round(float(np.median(left_edges)))))
    if len(right_edges) >= 3:
        right = max(right, int(round(float(np.median(right_edges)))))
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



def find_form_registrations(image, max_forms=MAX_FORMS_PER_PAGE):
    """Find zero to three complete MOD templates on one already-deskewed page.

    Page segmentation is decided by the whole known template, never by a header,
    an internal row, or the next candidate's position. Horizontal template rows
    propose an affine placement; the complete horizontal/vertical cell geometry
    confirms it. Missing outer-edge pieces may therefore be reconstructed from
    surviving internal rules on worn or crumpled scans.
    """
    import cv2
    import numpy as np

    if image is None or not image.size:
        return ()
    limit = min(MAX_FORMS_PER_PAGE, max(0, int(max_forms)))
    if not limit or min(image.shape[:2]) < 80:
        return ()

    original_h, original_w = image.shape[:2]
    scale = min(1.0, ANALYSIS_WIDTH / float(original_w))
    if scale < 1.0:
        small = cv2.resize(
            image,
            (max(1, int(round(original_w * scale))),
             max(1, int(round(original_h * scale)))),
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

    height, width = gray.shape
    ink = cv2.threshold(
        gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU
    )[1]
    horizontal = cv2.morphologyEx(
        ink,
        cv2.MORPH_OPEN,
        np.ones((1, max(20, width // 40)), np.uint8),
    )

    row_runs = _runs((horizontal > 0).mean(axis=1) > .10, np)
    centers = np.asarray([(start + stop) / 2.0 for start, stop in row_runs], dtype=float)
    if len(centers) < 5:
        return ()

    # Estimate one form's printed width from long surviving rules on the page.
    # Use several rows so a torn/bowed outside edge cannot own the estimate.
    joined = cv2.morphologyEx(
        horizontal, cv2.MORPH_CLOSE, np.ones((3, 9), np.uint8)
    )
    count, _, stats, _ = cv2.connectedComponentsWithStats(joined)
    components = [
        tuple(map(int, values))
        for values in stats[1:count]
        if values[2] >= width * .42 and values[3] < width * .08
    ]
    long_widths = [values[2] for values in components]
    estimated_width = (
        float(np.percentile(long_widths, 75))
        if long_widths else width * .90
    )
    estimated_width = float(np.clip(estimated_width, width * .65, width))
    estimated_height = estimated_width * TEMPLATE_ASPECT_HEIGHT
    if estimated_height < 60:
        return ()

    ratios = np.asarray(TEMPLATE_HORIZONTAL, dtype=float)
    proposal_tolerance = max(5.0, estimated_height * .045)
    proposals = {}

    def matched_rows(top, form_height, tolerance):
        expected = top + ratios * form_height
        pairs = []
        used = set()
        for ratio, target in zip(ratios, expected):
            distances = np.abs(centers - target)
            index = int(np.argmin(distances))
            if distances[index] <= tolerance and index not in used:
                used.add(index)
                pairs.append((float(ratio), float(centers[index])))
        return pairs

    # Every surviving template row may vote for the form's top. A real card
    # creates a dense cluster because many different rows predict the same top;
    # an isolated internal line does not.
    for center in centers:
        for ratio in ratios:
            top = float(center - ratio * estimated_height)
            if top < -estimated_height * .12 or top > height - estimated_height * .20:
                continue
            pairs = matched_rows(top, estimated_height, proposal_tolerance)
            if len(pairs) < 5:
                continue

            # Fit y = top + ratio * height from all surviving rules. This lets
            # missing outer top/bottom pieces be inferred from the intact inside.
            matrix = np.asarray([[1.0, ratio] for ratio, _ in pairs], dtype=float)
            observed = np.asarray([value for _, value in pairs], dtype=float)
            fitted_top, fitted_height = np.linalg.lstsq(
                matrix, observed, rcond=None
            )[0]
            if not (estimated_height * .76 <= fitted_height <= estimated_height * 1.24):
                continue

            tolerance = max(5.0, fitted_height * .035)
            pairs = matched_rows(fitted_top, fitted_height, tolerance)
            if len(pairs) < 5:
                continue
            matrix = np.asarray([[1.0, ratio] for ratio, _ in pairs], dtype=float)
            observed = np.asarray([value for _, value in pairs], dtype=float)
            fitted_top, fitted_height = np.linalg.lstsq(
                matrix, observed, rcond=None
            )[0]
            if not (estimated_height * .76 <= fitted_height <= estimated_height * 1.24):
                continue

            expected = fitted_top + np.asarray([pair[0] for pair in pairs]) * fitted_height
            residual = float(np.mean(np.abs(observed - expected))) / max(1.0, fitted_height)
            row_score = len(pairs) / float(len(TEMPLATE_HORIZONTAL))
            bucket = max(4.0, fitted_height * .035)
            key = int(round(fitted_top / bucket))
            rank = (row_score, -residual)
            current = proposals.get(key)
            if current is None or rank > current[0]:
                proposals[key] = (rank, float(fitted_top), float(fitted_height), row_score)

    candidates = []
    for _, fitted_top, fitted_height, row_score in proposals.values():
        top = fitted_top
        bottom = fitted_top + fitted_height
        if bottom <= 0 or top >= height:
            continue

        # Recover x bounds from the longest rules belonging to this one vertical
        # template placement. Several rules vote so chipped corners are harmless.
        local = []
        window_top = top - fitted_height * .08
        window_bottom = bottom + fitted_height * .08
        for x, y, component_width, component_height, _ in components:
            center_y = y + component_height / 2.0
            if window_top <= center_y <= window_bottom:
                local.append((component_width, x, x + component_width - 1))
        local.sort(reverse=True)
        selected = local[:min(8, len(local))]
        if selected:
            left = int(round(float(np.median([entry[1] for entry in selected]))))
            right = int(round(float(np.median([entry[2] for entry in selected]))))
        else:
            left = int(round((width - estimated_width) / 2.0))
            right = int(round(left + estimated_width))

        left = max(0, left)
        right = min(width, right)
        top_i = max(0, int(round(top)))
        bottom_i = min(height, int(round(bottom)))
        if right - left < width * .55 or bottom_i - top_i < 50:
            continue

        registration = FormRegistration(
            score=float(row_score),
            left=left,
            right=right,
            top=top_i,
            bottom=bottom_i,
        )
        geometry = template_geometry_score(small, registration)
        if (row_score < PAGE_MATCH_MIN_ROW_SCORE
                or geometry < PAGE_MATCH_MIN_GEOMETRY):
            continue
        confidence = row_score * .45 + geometry * .55
        candidates.append((confidence, geometry, registration))

    # Many rows on one real form generate equivalent placements. Keep one best
    # full-template match for each physical card, then cap the page contract at 3.
    chosen = []
    for candidate in sorted(candidates, key=lambda value: (value[0], value[1]), reverse=True):
        registration = candidate[2]
        duplicate = False
        for _, _, existing in chosen:
            vertical = max(
                0,
                min(registration.bottom, existing.bottom)
                - max(registration.top, existing.top),
            )
            horizontal_overlap = max(
                0,
                min(registration.right, existing.right)
                - max(registration.left, existing.left),
            )
            min_height = max(
                1,
                min(registration.bottom - registration.top,
                    existing.bottom - existing.top),
            )
            min_width = max(
                1,
                min(registration.right - registration.left,
                    existing.right - existing.left),
            )
            if vertical / min_height >= .45 and horizontal_overlap / min_width >= .60:
                duplicate = True
                break
        if duplicate:
            continue
        chosen.append(candidate)
        if len(chosen) >= limit:
            break

    chosen.sort(key=lambda value: (value[2].top, value[2].left))
    inverse = 1.0 / scale
    result = []
    for _, _, registration in chosen:
        result.append(FormRegistration(
            score=registration.score,
            left=max(0, int(round(registration.left * inverse))),
            right=min(original_w, int(round(registration.right * inverse))),
            top=max(0, int(round(registration.top * inverse))),
            bottom=min(original_h, int(round(registration.bottom * inverse))),
        ))
    return tuple(result)


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
