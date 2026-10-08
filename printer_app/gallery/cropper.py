"""Page cutting for Gallery work orders.

Rendered pages are normalized, then the template module returns zero to three
complete MOD-template registrations for the whole page. This module only expands
those independent bounds enough to retain pen overflow and cuts the images. OCR,
repositories and UI remain downstream.
"""
import cv2
import numpy as np

if __package__:
    from .form_template import find_form_registrations, template_geometry_score
else:
    from form_template import find_form_registrations, template_geometry_score


def _runs(mask):
    edges = np.flatnonzero(np.diff(np.r_[False, mask, False].astype(np.int8)))
    return list(zip(edges[::2], edges[1::2]))


def _gray(image):
    if image.ndim == 2:
        return image
    if image.shape[2] == 4:
        return cv2.cvtColor(image, cv2.COLOR_RGBA2GRAY)
    return cv2.cvtColor(image, cv2.COLOR_RGB2GRAY)


def _analysis_image(image, max_width=1400):
    """Return a bounded geometry raster plus exact x/y scale factors."""
    h, w = image.shape[:2]
    if w <= max_width:
        return image, 1.0, 1.0
    target_w = max_width
    target_h = max(1, int(round(h * target_w / w)))
    small = cv2.resize(image, (target_w, target_h), interpolation=cv2.INTER_AREA)
    return small, target_w / float(w), target_h / float(h)


def _rotate_bound(image, angle):
    """Rotate without clipping page corners; new space is white."""
    if abs(angle) < .05:
        return image
    h, w = image.shape[:2]
    center = (w / 2.0, h / 2.0)
    matrix = cv2.getRotationMatrix2D(center, float(angle), 1.0)
    cosine, sine = abs(matrix[0, 0]), abs(matrix[0, 1])
    out_w = max(1, int(round(h * sine + w * cosine)))
    out_h = max(1, int(round(h * cosine + w * sine)))
    matrix[0, 2] += out_w / 2.0 - center[0]
    matrix[1, 2] += out_h / 2.0 - center[1]
    border = 255 if image.ndim == 2 else tuple([255] * image.shape[2])
    return cv2.warpAffine(image, matrix, (out_w, out_h),
                          flags=cv2.INTER_LINEAR,
                          borderMode=cv2.BORDER_CONSTANT,
                          borderValue=border)


def deskew_page(image):
    """Align long printed rules while measuring skew on a bounded analysis copy.

    The rotation is still applied once to the full-resolution page, so saved crops
    lose no image detail. This removes most Hough/Canny pixels from the hot path.
    """
    analysis, _, _ = _analysis_image(image)
    h, w = analysis.shape[:2]
    if min(h, w) < 120:
        return image
    gray = _gray(analysis)
    edges = cv2.Canny(gray, 50, 150, apertureSize=3)
    min_length = max(100, int(min(h, w) * .24))
    lines = cv2.HoughLinesP(
        edges, 1, np.pi / 720, threshold=max(60, min_length // 3),
        minLineLength=min_length, maxLineGap=max(12, int(min(h, w) * .012)))
    if lines is None:
        return image

    angles, weights = [], []
    for line in lines[:, 0]:
        x1, y1, x2, y2 = map(float, line)
        dx, dy = x2 - x1, y2 - y1
        length = float(np.hypot(dx, dy))
        if length < min_length:
            continue
        angle = np.degrees(np.arctan2(dy, dx))
        skew = ((angle + 45.0) % 90.0) - 45.0
        # A real scan skew is small. Large diagonal graphics/signatures do not
        # get permission to rotate the whole source page.
        if abs(skew) <= 15.0:
            angles.append(skew)
            weights.append(length)
    if not angles:
        return image

    values = np.asarray(angles)
    weight = np.asarray(weights)
    order = np.argsort(values)
    values, weight = values[order], weight[order]
    cumulative = np.cumsum(weight)
    skew = float(values[np.searchsorted(cumulative, cumulative[-1] / 2.0)])
    return _rotate_bound(image, skew)


def is_dense_grid_page(image):
    """True for full-sheet reports/tables, using only a bounded analysis raster."""
    image, _, _ = _analysis_image(image)
    h, w = image.shape[:2]
    if min(h, w) < 120:
        return False
    gray = _gray(image)
    ink = cv2.threshold(gray, 0, 255,
                        cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)[1]
    vertical = cv2.morphologyEx(
        ink, cv2.MORPH_OPEN,
        np.ones((max(40, int(h * .18)), 1), np.uint8))
    horizontal = cv2.morphologyEx(
        ink, cv2.MORPH_OPEN,
        np.ones((1, max(50, int(w * .18))), np.uint8))

    if _repeated_report_rows(horizontal, minimum=20):
        return True

    vertical_rules = _runs((vertical > 0).mean(axis=0) > .42)
    horizontal_rules = _runs((horizontal > 0).mean(axis=1) > .42)
    if len(vertical_rules) < 14 or len(horizontal_rules) < 6:
        return False

    centers = np.array([(a + b) / 2 for a, b in vertical_rules], dtype=float)
    if len(centers) < 2:
        return False
    span = (centers[-1] - centers[0]) / max(1, w)
    median_gap = float(np.median(np.diff(centers))) / max(1, w)
    return span > .55 and median_gap < .10


def _rule_centers(runs):
    return np.asarray([(start + end) / 2.0 for start, end in runs], dtype=float)


def _repeated_report_rows(horizontal, minimum=8):
    """Recognize tightly repeated report rows even when column rules are faint.

    MOD forms have a short identity row followed by taller, irregular cells.
    Tabular reports repeat much smaller row pitches across most of their height;
    requiring both cadence and coverage avoids treating a few header rules as a
    report. Slanted or broken vertical lines do not remove that evidence.
    """
    h, w = horizontal.shape
    centers = _rule_centers(_runs((horizontal > 0).mean(axis=1) > .22))
    if len(centers) < minimum or centers[-1] - centers[0] < h * .60:
        return False
    gaps = np.diff(centers)
    return bool(np.median(gaps) < w * .025 and np.mean(gaps < w * .035) >= .80)


def is_work_order_form(image):
    """Legacy report rejection fallback, evaluated on a bounded analysis raster."""
    image, _, _ = _analysis_image(image)
    h, w = image.shape[:2]
    if min(h, w) < 120:
        return False

    gray = _gray(image)
    ink = cv2.threshold(gray, 0, 255,
                        cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)[1]

    # Shorter kernels than the page-level rejector intentionally see segmented
    # table rules too. This catches reports whose lines stop at section breaks.
    vertical = cv2.morphologyEx(
        ink, cv2.MORPH_OPEN,
        np.ones((max(28, int(h * .10)), 1), np.uint8))
    horizontal = cv2.morphologyEx(
        ink, cv2.MORPH_OPEN,
        np.ones((1, max(40, int(w * .16))), np.uint8))

    horizontal_rules = _runs((horizontal > 0).mean(axis=1) > .22)
    vertical_rules = _runs((vertical > 0).mean(axis=0) > .16)
    h_centers = _rule_centers(horizontal_rules)
    v_centers = _rule_centers(vertical_rules)

    if _repeated_report_rows(horizontal):
        return False

    # The existing top-border detector already proved this is a plausible form.
    # Only reject here when the candidate has strong report/table evidence.
    if len(h_centers) < 4 or len(v_centers) < 4:
        return True

    h_gaps = np.diff(h_centers)
    v_gaps = np.diff(v_centers)
    tight_rows = int(np.count_nonzero(h_gaps < max(5, h * .055)))
    tight_cols = int(np.count_nonzero(v_gaps < max(5, w * .055)))
    largest_row_gap = float(h_gaps.max()) / max(1, h) if len(h_gaps) else 1.0

    # Count actual crossings rather than merely counting detected rule bands.
    # A report grid produces far more crossings than the irregular work-order
    # layout, even when its rules are broken into several sections.
    h_cross = cv2.dilate(horizontal, np.ones((3, 1), np.uint8))
    v_cross = cv2.dilate(vertical, np.ones((1, 3), np.uint8))
    intersections = cv2.bitwise_and(h_cross, v_cross)
    labels, _ = cv2.connectedComponents((intersections > 0).astype(np.uint8))
    crossing_count = max(0, int(labels) - 1)

    dense_repetition = (
        len(h_centers) >= 16 and len(v_centers) >= 12 and
        tight_rows >= 10 and tight_cols >= 7 and crossing_count >= 70
    )
    no_large_work_area = (
        len(h_centers) >= 14 and len(v_centers) >= 12 and
        largest_row_gap < .11 and crossing_count >= 70
    )
    sideways_dense_report = (
        w < h * 1.05 and len(h_centers) >= 12 and len(v_centers) >= 12 and
        crossing_count >= 60
    )
    return not (dense_repetition or no_large_work_area or sideways_dense_report)


def _expanded_form_crop(image, registration, previous=None, following=None):
    """Crop one independently matched form with room for pen overflow and bad edges.

    Padding never enters a neighboring matched template. The blank gap between
    stacked cards may be retained by both crops so handwriting that crosses the
    printed border is not silently lost.
    """
    h, w = image.shape[:2]
    frame_width = max(1, registration.right - registration.left)
    frame_height = max(1, registration.bottom - registration.top)
    x_pad = max(8, int(round(frame_width * .020)))
    y_pad = max(10, int(round(frame_height * .085)))

    x0 = max(0, registration.left - x_pad)
    x1 = min(w, registration.right + x_pad)
    y0 = max(0, registration.top - y_pad)
    y1 = min(h, registration.bottom + y_pad)

    if previous is not None and previous.bottom < registration.top:
        y0 = max(y0, previous.bottom)
    if following is not None and registration.bottom < following.top:
        y1 = min(y1, following.top)

    if x1 <= x0 or y1 <= y0:
        raise ValueError('Invalid registered MOD template bounds')
    return image[y0:y1, x0:x1].copy()


def _template_orientation_evidence(image):
    """Return whole-template evidence for one page orientation."""
    registrations = find_form_registrations(image, max_forms=3)
    return (
        len(registrations),
        sum(template_geometry_score(image, registration)
            for registration in registrations),
    )


def orient_work_order_page(image):
    """Normalize right-angle page rotation only when the known form proves it.

    Evaluate all four right-angle orientations independently. Unrelated/legacy
    pages remain untouched when the template provides no evidence or when two
    orientations are too close to call.
    """
    # Orientation evidence needs only the bounded geometry raster. Rotate the
    # full-resolution page once, after a winner is proven, to keep Pi memory use
    # close to the previous two-orientation implementation.
    analysis, _, _ = _analysis_image(image)
    evidence = []
    for turns in (0, 1, 2, 3):
        candidate = analysis if turns == 0 else np.rot90(analysis, turns).copy()
        matches, score = _template_orientation_evidence(candidate)
        evidence.append((matches, score, turns))

    best = max(evidence, key=lambda item: (item[0], item[1], -item[2]))
    best_matches, _, best_turns = best
    if best_matches <= 0 or best_turns == 0:
        return image

    # One page has one scan orientation. The complete template geometry chooses
    # that orientation once; every card on the page inherits it.
    return np.rot90(image, best_turns).copy()


def cut_forms(image):
    """Detect the page's 0-3 complete MOD templates, then crop each independently."""
    if is_dense_grid_page(image):
        return

    registrations = find_form_registrations(image, max_forms=3)
    for index, registration in enumerate(registrations):
        previous = registrations[index - 1] if index else None
        following = registrations[index + 1] if index + 1 < len(registrations) else None
        crop = _expanded_form_crop(
            image, registration, previous=previous, following=following,
        )
        yield index + 1, crop
