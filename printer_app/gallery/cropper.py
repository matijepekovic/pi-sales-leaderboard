"""Outer-edge starts identify forms, even when handwriting joins adjacent boxes.

No OCR, equal-height division, or configurable margins. Preserve page width and
original pixels from a form's top border until the next form's top border.
"""
import cv2
import numpy as np


def _runs(mask):
    edges = np.flatnonzero(np.diff(np.r_[False, mask, False].astype(np.int8)))
    return list(zip(edges[::2], edges[1::2]))


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
    gray = cv2.cvtColor(image, cv2.COLOR_RGB2GRAY)
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
        # Trace the first long horizontal rule around this edge start. This
        # follows a bowed/skewed border rather than cutting off its highest point.
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
        # Header rules must continue BELOW this border; a blank/footer frame or
        # lone underline is not a work order. Evaluate relative to the traced top
        # so skew does not make a real header disappear from a row histogram.
        depth = min(round(.19 * w), h - int(top.max()) - 1)
        if depth < .08 * w:
            continue
        xx = np.arange(left, right + 1)
        yy = top[xx][None, :] + np.arange(depth)[:, None]
        rule_rows = (horizontal[yy, xx[None, :]] > 0).mean(axis=1) > .42
        internal = [(a, b) for a, b in _runs(rule_rows) if a > .008 * w]
        if len(internal) < 2:
            continue
        # The header also contains actual internal vertical partitions. Reject
        # blank space containing unrelated horizontal marks/page numbers.
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
