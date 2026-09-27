"""Fixed-width numeric recognition for Gallery work-order fields.

This module owns one job: turn an isolated printed numeric field into its digit
positions. It does not know Gallery workflow, Salesforce, repositories, dates or
customer data.

The parser never inserts or removes positions. It first finds eight visible glyph
slots, then asks the injected digit classifier to choose one of 0-9 for each slot.
Known OCR glyph confusions are normalized only when parsing text produced by the
whole-card fallback.
"""
from __future__ import annotations

import re


OCR_GLYPH_TRANSLATION = str.maketrans({
    'O': '0',
    'o': '0',
    'B': '8',
    'b': '8',
    '!': '1',
})


def normalize_numeric_token(value, *, length=8, prefix='02'):
    """Normalize one complete OCR token without padding or shifting characters."""
    value = str(value or '').strip()
    if len(value) != length:
        return ''
    if any(char not in '0123456789OoBb!' for char in value):
        return ''
    normalized = value.translate(OCR_GLYPH_TRANSLATION)
    if not normalized.isascii() or not normalized.isdecimal():
        return ''
    if prefix and not normalized.startswith(prefix):
        return ''
    return normalized


def numeric_token_from_text(value, *, length=8, prefix='02'):
    """Find one exact-length numeric-looking token in OCR text."""
    allowed = r'0-9OoBb!'
    matches = re.findall(
        rf'(?<![{allowed}])[{allowed}]{{{length}}}(?![{allowed}])',
        str(value or ''),
    )
    normalized = tuple(dict.fromkeys(
        candidate for token in matches
        if (candidate := normalize_numeric_token(token, length=length, prefix=prefix))
    ))
    return normalized[0] if len(normalized) == 1 else ''


def _clean_mask(image):
    import cv2
    import numpy as np

    if image is None or not getattr(image, 'size', 0):
        return None
    gray = image if image.ndim == 2 else cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    height, width = gray.shape
    if height < 12 or width < 24:
        return None

    blurred = cv2.GaussianBlur(gray, (3, 3), 0)
    ink = cv2.threshold(
        blurred, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU
    )[1]

    horizontal = cv2.morphologyEx(
        ink,
        cv2.MORPH_OPEN,
        np.ones((1, max(12, int(round(width * .18)))), np.uint8),
    )
    vertical = cv2.morphologyEx(
        ink,
        cv2.MORPH_OPEN,
        np.ones((max(10, int(round(height * .65))), 1), np.uint8),
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
    """Return plausible equal-pitch glyph layouts, best first."""
    import cv2
    import numpy as np

    mask = _clean_mask(image)
    if mask is None:
        return (), None

    height, width = mask.shape
    component_count, _, stats, _ = cv2.connectedComponentsWithStats(
        (mask > 0).astype(np.uint8), 8
    )
    components = []
    for label in range(1, component_count):
        x, y, component_width, component_height, area = map(int, stats[label])
        if (component_height >= max(5, int(round(height * .25)))
                and area >= 5):
            components.append((x, y, component_width, component_height, area))
    if not components:
        return (), mask

    glyph_height = float(np.median([component[3] for component in components]))
    projection = (mask > 0).sum(axis=0).astype(float)
    pitch_min = max(5, int(round(glyph_height * .55)))
    pitch_max = max(pitch_min + 1, int(round(glyph_height * 1.15)))
    layouts = []

    for pitch in range(pitch_min, pitch_max + 1):
        window = count * pitch
        if window > width:
            continue
        for start in range(0, width - window + 1):
            areas = []
            center_penalty = 0.0
            valid = True
            for position in range(count):
                left = start + position * pitch
                right = left + pitch
                slot = mask[:, left:right] > 0
                area = int(slot.sum())
                areas.append(area)
                if area < max(8, int(round(glyph_height))):
                    valid = False
                    break
                _, xs = np.nonzero(slot)
                center_penalty += abs(float(xs.mean()) / pitch - .5)
            if not valid:
                continue

            cut_penalty = 0.0
            for position in range(1, count):
                boundary = start + position * pitch
                cut_penalty += float(
                    projection[max(0, boundary - 1):min(width, boundary + 2)].sum()
                )

            mean_area = float(np.mean(areas))
            area_variance = float(np.std(areas)) / (mean_area + 1.0)
            left_extra = float(projection[max(0, start - pitch):start].sum())
            right_edge = start + window
            right_extra = float(
                projection[right_edge:min(width, right_edge + pitch)].sum()
            )
            score = (
                float(sum(areas))
                - 4.0 * cut_penalty
                - 8.0 * center_penalty * mean_area
                - 2.0 * area_variance * mean_area
                - 2.0 * right_extra
                - .15 * left_extra
            )
            layouts.append((score, start, pitch))

    layouts.sort(reverse=True)
    unique = []
    for layout in layouts:
        _, start, pitch = layout
        if any(
            abs(start - other_start) <= 2 and abs(pitch - other_pitch) <= 1
            for _, other_start, other_pitch in unique
        ):
            continue
        unique.append(layout)
        if len(unique) >= 6:
            break
    return tuple(unique), mask


def _normalized_glyph(image, mask, left, right):
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
    return target


def _one_digit(words):
    candidates = []
    for word in words or ():
        text = ''.join(char for char in str(word.get('text') or '') if char.isdigit())
        if len(text) != 1:
            continue
        try:
            confidence = float(word.get('conf', -1))
        except (TypeError, ValueError):
            confidence = -1
        candidates.append((confidence, text))
    if not candidates:
        return '', -1.0
    confidence, digit = max(candidates)
    return digit, confidence


def _classify_glyph(glyph, position, read_words, prefix):
    attempts = []
    first_digit = ''
    first_confidence = -1.0

    for psm in (10, 13):
        words = read_words(glyph, psm)
        digit, confidence = _one_digit(words)
        attempts.append({
            'position': position + 1,
            'psm': psm,
            'digit': digit,
            'confidence': confidence,
        })

        if psm == 10:
            first_digit, first_confidence = digit, confidence

        if position < len(prefix):
            if digit == prefix[position]:
                return digit, tuple(attempts)
            continue

        if digit and confidence >= 55:
            return digit, tuple(attempts)

    if position < len(prefix):
        return '', tuple(attempts)

    valid = [
        (attempt['confidence'], attempt['digit'])
        for attempt in attempts if attempt['digit']
    ]
    if not valid:
        return '', tuple(attempts)
    confidence, digit = max(valid)
    if (first_digit and digit != first_digit
            and abs(confidence - first_confidence) < 10):
        return '', tuple(attempts)
    return digit, tuple(attempts)


def parse_numeric_image(image, read_words, *, length=8, prefix='02'):
    """Read one fixed-length printed number from an isolated search field.

    The read_words callback is the OCR-engine boundary. The parser controls
    segmentation and position; the engine only classifies one isolated glyph as
    one of ten digits. Missing positions are never padded.
    """
    layouts, mask = _slot_candidates(image, length)
    if mask is None:
        return {'candidate': '', 'positions': (), 'attempts': ()}

    all_attempts = []
    best_positions = ()
    for _, start, pitch in layouts[:4]:
        positions = []
        attempts = []
        failed = False
        for position in range(length):
            left = start + position * pitch
            right = left + pitch
            glyph = _normalized_glyph(image, mask, left, right)
            if glyph is None:
                positions.append('')
                failed = True
                break
            digit, reads = _classify_glyph(glyph, position, read_words, prefix)
            attempts.extend(reads)
            positions.append(digit)
            if not digit:
                failed = True
                break

        all_attempts.extend(attempts)
        if len(positions) > len(best_positions):
            best_positions = tuple(positions)
        if failed or len(positions) != length:
            continue

        candidate = ''.join(positions)
        if prefix and not candidate.startswith(prefix):
            continue
        return {
            'candidate': candidate,
            'positions': tuple(positions),
            'attempts': tuple(all_attempts),
        }

    return {
        'candidate': '',
        'positions': best_positions,
        'attempts': tuple(all_attempts),
    }
