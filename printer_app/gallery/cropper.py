"""Page geometry for gallery work orders.

Rendered pages are normalized before form detection: long printed rules establish
small scan/skew rotation, then the existing outer-edge cutter finds work orders.
Dense full-page report grids are rejected here because page geometry owns the
line-pattern distinction; OCR, repositories and UI do not.
"""
import cv2
import numpy as np


def _runs(mask):
    edges = np.flatnonzero(np.diff(np.r_[False, mask, False].astype(np.int8)))
    return list(zip(edges[::2], edges[1::2]))


def _gray(image):
    if image.ndim == 2:
        return image
    if image.shape[2] == 4:
        return cv2.cvtColor(image, cv2.COLOR_RGBA2GRAY)
    return cv2.cvtColor(image, cv2.COLOR_RGB2GRAY)


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
    """Align the dominant long printed rules to 0/90 degrees before cutting.

    Text and handwriting are too short to vote.  Every long line votes only for
    its deviation from the nearest horizontal/vertical axis, so both horizontal
    and vertical form rules agree on the same page-skew correction.
    """
    h, w = image.shape[:2]
    if min(h, w) < 120:
        return image
    gray = _gray(image)
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
    """True for full-sheet reports/tables, not stacked work-order forms.

    The unwanted report pages have many long vertical rules spanning much of the
    page and crossing many long horizontal rules. Work orders have only a small
    set of repeated vertical partitions even when several forms are stacked.
    """
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


def form_tops(image):
    """Return per-column top-border coordinates, excluding footer/empty frames.

    RETR_EXTERNAL on the whole grid is deliberately not used: a pen stroke can
    connect two outer rectangles. Instead, follow the outside vertical edges and
    validate their starts against the printed header grid. An open bottom edge
    is valid; a blank footer frame without a header grid is not a new form.
    """
    h, w = image.shape[:2]
    if w < 100 or h < 60:
        return []
    gray = _gray(image)
    ink = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)[1]
    vertical = cv2.morphologyEx(ink, cv2.MORPH_OPEN,
        np.ones((max(12, w // 65), 1), np.uint8))
    horizontal = cv2.morphologyEx(ink, cv2.MORPH_OPEN,
        np.ones((1, max(20, w // 40)), np.uint8))
    votes = vertical.sum(axis=0)
    left = int(votes[:w // 5].argmax())
    right = int(votes[4 * w // 5:].argmax()) + 4 * w // 5
    if right - left < .60 * w:
        return []
    starts = []
    band = max(6, round(w * .012))
    for x in (left, right):
        side = vertical[:, max(0, x-band):min(w, x+band+1)].any(axis=1)
        side = cv2.morphologyEx(side.astype(np.uint8)[:, None], cv2.MORPH_CLOSE,
                               np.ones((max(3, w // 200), 1), np.uint8)).ravel() > 0
        for top, bottom in _runs(side):
            if bottom - top >= .12 * w:
                starts.append((int(top), x))
    clusters = []
    for entry in sorted(starts):
        y = entry[0]
        if clusters and y - clusters[-1][-1][0] < .04 * w:
            clusters[-1].append(entry)
        else:
            clusters.append([entry])
    tops = []
    for cluster in clusters:
        # Trace the first long horizontal rule around this edge start.
        anchors = sorted((x, y) for y, x in cluster)
        xx = np.arange(left, right+1)
        expected = np.rint(np.interp(xx, [a[0] for a in anchors], [a[1] for a in anchors])).astype(int)
        radius = max(10, round(.02*w))
        yy = expected[None, :] + np.arange(-radius, radius+1)[:, None]
        region = (horizontal[np.clip(yy, 0, h-1), xx[None, :]] > 0) & (yy >= 0) & (yy < h)
        valid = region.any(axis=0)
        if valid.mean() < .65:
            continue
        xs = xx[valid]
        ys = expected[valid] - radius + region[:, valid].argmax(axis=0)
        top = np.rint(np.interp(np.arange(w), xs, ys)).astype(int)
        # Header rules must continue below this border.
        depth = min(round(.19 * w), h - int(top.max()) - 1)
        if depth < .08 * w:
            continue
        xx = np.arange(left, right + 1)
        yy = top[xx][None, :] + np.arange(depth)[:, None]
        rule_rows = (horizontal[yy, xx[None, :]] > 0).mean(axis=1) > .42
        internal = [(a, b) for a, b in _runs(rule_rows) if a > .008 * w]
        if len(internal) < 2:
            continue
        # The header also contains actual internal vertical partitions.
        y0, y1 = int(np.median(top) + .01*w), int(np.median(top) + .08*w)
        support = (vertical[max(0,y0):min(h,y1), left+band:right-band] > 0).mean(axis=0)
        if not np.any(support > .55):
            continue
        if not tops or np.median(top - tops[-1]) > .10 * w:
            tops.append(top)
    return tops


def cut_forms(image):
    h, w = image.shape[:2]
    tops = form_tops(image)
    for index, top in enumerate(tops):
        bottom = tops[index+1] if index+1 < len(tops) else np.full(w, h)
        if np.any(bottom <= top):
            raise ValueError('Ambiguous form boundaries; page needs a clearer scan')
        y0, y1 = int(top.min()), int(bottom.max())
        crop = image[y0:y1].copy()
        rows = np.arange(y0, y1)[:, None]
        crop[(rows < top[None, :]) | (rows >= bottom[None, :])] = 255
        yield index+1, crop
