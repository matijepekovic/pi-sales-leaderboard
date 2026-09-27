"""Fixed-width numeric recognition for Gallery work-order fields.

This module owns one job: turn an isolated printed numeric field into its digit
positions. It does not know Gallery workflow, repositories, dates, customer data
or any external source.

The parser never inserts or removes positions. It first finds visible glyph slots,
then asks the injected digit classifier to choose one of 0-9 for each slot. It has
no knowledge of work-order prefixes or any other business rule. Known OCR glyph
confusions are normalized only when parsing text produced by another OCR path.
"""
from __future__ import annotations

import re
import unicodedata


OCR_GLYPH_TRANSLATION = str.maketrans({
    'O': '0',
    'o': '0',
    'B': '8',
    'b': '8',
    '!': '1',
})


def normalize_numeric_token(value, *, length=8):
    """Normalize one complete OCR token without padding or shifting characters."""
    value = str(value or '').strip()
    if len(value) != length:
        return ''
    if any(char not in '0123456789OoBb!' for char in value):
        return ''
    normalized = value.translate(OCR_GLYPH_TRANSLATION)
    if not normalized.isascii() or not normalized.isdecimal():
        return ''
    return normalized


def numeric_tokens_from_text(
        value, *, length=8, allow_overflow=False, allow_separated=False):
    """Read independent numeric tokens without joining or shifting positions."""
    text = str(value or '')
    candidates = {}
    pattern = r'[0-9OoBb!]+'
    if allow_separated:
        pattern += r'(?:[ \t]+[0-9OoBb!]+)*'
    for match in re.finditer(pattern, text):
        before = text[match.start() - 1:match.start()]
        after = text[match.end():match.end() + 1]
        edges = before + after
        if not all(
            char.isspace() or unicodedata.category(char)[0] in 'PS'
            for char in edges
        ):
            continue
        tokens = match[0].split()
        if allow_separated and not all(len(token) == length for token in tokens):
            # OCR can put spaces between visible digits. Keep the complete run;
            # never select an eight-character subrun from nine or more glyphs.
            tokens = [''.join(tokens)]
        for token in tokens:
            token = token[:length] if allow_overflow else token
            candidate = normalize_numeric_token(token, length=length)
            if candidate:
                candidates.setdefault(candidate, None)
    return tuple(candidates)


def numeric_token_from_text(value, *, length=8, allow_overflow=False):
    """Read the first token for the existing normalized-text contract."""
    return next(iter(numeric_tokens_from_text(
        value, length=length, allow_overflow=allow_overflow)), '')


def _clean_mask(image):
    import cv2
    import numpy as np

    if image is None or not getattr(image, 'size', 0):
        return None
    gray = image if image.ndim == 2 else cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    height, width = gray.shape
    if height < 12 or width < 24:
        return None

    ink = cv2.threshold(
        gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU
    )[1]

    horizontal = cv2.morphologyEx(
        ink,
        cv2.MORPH_OPEN,
        np.ones((1, max(12, int(round(width * .18)))), np.uint8),
    )
    vertical = cv2.morphologyEx(
        ink,
        cv2.MORPH_OPEN,
        np.ones((max(10, int(round(height * .95))), 1), np.uint8),
    )
    ink[(horizontal > 0) | (vertical > 0)] = 0

    count, labels, stats, _ = cv2.connectedComponentsWithStats(
        (ink > 0).astype(np.uint8), 8
    )
    clean = np.zeros_like(ink)
    minimum_area = max(3, int(round(height * width * .00015)))
    minimum_height = max(2, int(round(height * .08)))
    for label in range(1, count):
        _, _, _, component_height, area = stats[label]
        if area >= minimum_area and component_height >= minimum_height:
            clean[labels == label] = 255
    return clean


def _slot_candidates(image, count):
    """Locate complete visible glyph groups without fitting a fixed-pitch grid."""
    import cv2
    import numpy as np

    mask = _clean_mask(image)
    if mask is None:
        return (), None

    height, _ = mask.shape
    component_count, _, stats, _ = cv2.connectedComponentsWithStats(
        (mask > 0).astype(np.uint8), 8
    )
    components = []
    for label in range(1, component_count):
        x, y, component_width, component_height, area = map(int, stats[label])
        if (component_height >= max(2, int(round(height * .06)))
                and area >= 5):
            components.append((x, y, component_width, component_height, area))
    if not components:
        return (), mask

    # A faded horizontal stroke can disconnect the top and bottom of a glyph.
    # Combine overlapping columns before measuring its complete visible height.
    joined = []
    for x, y, width, component_height, area in sorted(components):
        right, bottom = x + width, y + component_height
        if joined and x < joined[-1][2]:
            left, top, prior_right, prior_bottom = joined[-1]
            joined[-1] = (left, min(top, y), max(right, prior_right), max(bottom, prior_bottom))
        else:
            joined.append((x, y, right, bottom))
    glyph_height = float(np.median([bottom - top for _, top, _, bottom in joined]))
    intervals = []
    # Short label tails, punctuation and dust do not establish digit positions.
    # Smaller pieces inside a digit's eventual bounds remain in the source mask.
    for left, top, right, bottom in joined:
        if bottom - top < glyph_height * .8:
            continue
        intervals.append((left, right))

    projection = (mask > 0).sum(axis=0)
    visible = []
    minimum_width = max(3, int(round(glyph_height * .22)))
    for left, right in intervals:
        pending = [(left, right)]
        while pending:
            left, right = pending.pop(0)
            if right - left <= glyph_height * 1.1:
                visible.append((left, right))
                continue
            # Touching digits may form one component. Split only at an observed
            # low-ink valley, never into a requested number of equal-width slots.
            lower, upper = left + minimum_width, right - minimum_width
            if upper <= lower:
                return (), mask
            valley = lower + int(np.argmin(projection[lower:upper]))
            if projection[valley] > glyph_height * .3:
                visible = []
                break
            pending[0:0] = [(left, valley), (valley, right)]
        if not visible:
            return (), mask

    groups = []
    for bounds in visible:
        if not groups or bounds[0] - groups[-1][-1][1] > glyph_height * 1.2:
            groups.append([])
        groups[-1].append(bounds)

    layouts = []
    for group in groups:
        if len(group) != count:
            continue
        bounds = []
        for position, (left, right) in enumerate(group):
            left = (group[position - 1][1] + left) // 2 if position else max(0, left - 3)
            right = (right + group[position + 1][0]) // 2 if position + 1 < count else min(mask.shape[1], right + 3)
            bounds.append((left, right))
        layouts.append(tuple(bounds))
    return tuple(layouts), mask


def _normalized_glyph(image, mask, left, right, *, glyph_height=36):
    import cv2
    import numpy as np

    slot = mask[:, left:right] > 0
    ys, xs = np.nonzero(slot)
    if not len(xs):
        return None

    x0 = max(0, int(xs.min()) - 2)
    x1 = min(right - left, int(xs.max()) + 3)
    y0 = max(0, int(ys.min()) - 2)
    y1 = min(image.shape[0], int(ys.max()) + 3)
    glyph = image[y0:y1, left + x0:left + x1]
    if not glyph.size:
        return None

    target_height, target_width = 96, 80
    target = np.full((target_height, target_width), 255, np.uint8)
    scale = min(
        62.0 / max(1, glyph.shape[1]),
        72.0 / max(1, glyph.shape[0]),
    )
    resized_width = max(1, int(round(glyph.shape[1] * scale)))
    resized_height = max(1, int(round(glyph.shape[0] * scale)))
    resized = cv2.resize(
        glyph,
        (resized_width, resized_height),
        interpolation=cv2.INTER_CUBIC,
    )
    x = (target_width - resized_width) // 2
    y = (target_height - resized_height) // 2
    target[y:y + resized_height, x:x + resized_width] = resized
    # Keep consistent margins and antialiasing at each reading size.
    return cv2.resize(target, None, fx=glyph_height / 72.0, fy=glyph_height / 72.0,
                      interpolation=cv2.INTER_CUBIC)


def _one_digit(words):
    words = tuple(words or ())
    if len(words) != 1:
        return '', -1.0
    digit = str(words[0].get('text') or '').strip()
    if len(digit) != 1 or digit not in '0123456789':
        return '', -1.0
    try:
        confidence = float(words[0].get('conf', -1))
    except (TypeError, ValueError):
        confidence = -1.0
    return digit, confidence if 0 <= confidence <= 100 else -1.0


def _classify_glyph(glyph, position, read_words, *, psm, layout, scale, angle):
    """Keep one view's observed digit and confidence; never vote across views."""
    digit, confidence = _one_digit(read_words(glyph, psm))
    attempt = dict(position=position + 1, psm=psm, digit=digit,
                   confidence=confidence, layout=layout, scale=scale, angle=angle)
    return (digit if confidence >= 40 else ''), attempt


def parse_numeric_image(image, read_words, *, length=8):
    """Read one fixed-length printed number from an isolated search field.

    The read_words callback is the OCR-engine boundary. The parser controls
    segmentation and position; the engine only classifies one isolated glyph as
    one of ten digits. Missing positions are never padded. Regions expose the
    complete observed groups in source-image coordinates for independent reads.
    """
    import cv2
    import numpy as np

    layouts, mask = _slot_candidates(image, length)
    if mask is None:
        return {'candidate': '', 'candidates': (), 'positions': (), 'attempts': (), 'regions': ()}

    all_attempts = []
    best_positions = ()
    candidates = []
    regions = []
    # Each complete answer uses one consistent view of all observed positions.
    # Do not manufacture an answer by combining different passes' best digits.
    for layout, bounds in enumerate(layouts):
        left, right = bounds[0][0], bounds[-1][1]
        ys, _ = np.nonzero(mask[:, left:right])
        regions.append((left, max(0, int(ys.min()) - 2),
                        right, min(image.shape[0], int(ys.max()) + 3)))
        passes = [(36, 10, 0.0), (48, 10, 0.0), (36, 13, 0.0)]
        baseline = []
        for left, right in bounds:
            ys, _ = np.nonzero(mask[:, left:right])
            baseline.append(((left + right) / 2, float(np.percentile(ys, 95))))
        if len(baseline) >= 3:
            slope = np.polyfit(*zip(*baseline), 1)[0]
            angle = float(np.degrees(np.arctan(slope)))
            if .75 < abs(angle) <= 5:
                passes.append((48, 10, angle))
        for scale, psm, angle in passes:
            positions = []
            for position, (left, right) in enumerate(bounds):
                glyph = _normalized_glyph(image, mask, left, right, glyph_height=scale)
                if glyph is None:
                    positions.append('')
                    continue
                if angle:
                    height, width = glyph.shape
                    transform = cv2.getRotationMatrix2D((width / 2, height / 2), angle, 1)
                    glyph = cv2.warpAffine(glyph, transform, (width, height),
                                          flags=cv2.INTER_CUBIC, borderValue=255)
                digit, attempt = _classify_glyph(
                    glyph, position, read_words, psm=psm, layout=layout, scale=scale, angle=angle)
                all_attempts.append(attempt)
                positions.append(digit)
            if sum(bool(value) for value in positions) > sum(bool(value) for value in best_positions):
                best_positions = tuple(positions)
            if len(positions) == length and all(positions):
                candidate = ''.join(positions)
                if candidate not in candidates:
                    candidates.append(candidate)
    return {
        'candidate': candidates[0] if len(candidates) == 1 else '',
        'candidates': tuple(candidates),
        'positions': tuple(candidates[0]) if len(candidates) == 1 else best_positions,
        'attempts': tuple(all_attempts),
        'regions': tuple(regions),
    }
