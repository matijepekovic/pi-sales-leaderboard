"""Local OCR adapter. Only normalized text/header/date values leave this module.

Known work-order cards use template geometry to OCR only variable ink. Nonmatching
images retain the legacy whole-card path. Tesseract TSV is NOT quoted CSV: a printed
quote must never absorb subsequent rows. The archived image is never modified.
"""
import csv
from datetime import date
import io
import json
from pathlib import Path
import re
import subprocess
import sys

if __package__:
    from .form_template import TEMPLATE_FIELDS, field_boxes, map_box, register_form
    from .policy import printed_work_order_number
else:
    from form_template import TEMPLATE_FIELDS, field_boxes, map_box, register_form
    from policy import printed_work_order_number

# The scan supplies only the durable work-order identity. Customer, address,
# appointment and rep data come from the existing normalized reference data.
_OCR_FIELD_KEYS = frozenset({'work_order_number'})
_WRAPPED_FIELD_KEYS = frozenset()


def tsv_words(value):
    words = []
    for row in csv.DictReader(io.StringIO(value), delimiter='\t', quoting=csv.QUOTE_NONE):
        try:
            if int(row['level']) != 5 or not 0 <= float(row['conf']) <= 100:
                continue
            word = {key: int(row[key]) for key in
                    ('page_num', 'block_num', 'par_num', 'line_num', 'left', 'top', 'width', 'height')}
            if min(word.values()) < 0 or not word['width'] or not word['height']:
                continue
            text = row['text'].strip()
            if text:
                words.append(dict(word, text=text, conf=float(row['conf'])))
        except (KeyError, TypeError, ValueError):
            continue
    return words


def search_text(words):
    lines = {}
    for word in words:
        key = tuple(word[k] for k in ('page_num', 'block_num', 'par_num', 'line_num'))
        lines.setdefault(key, []).append(word['text'])
    return '\n'.join(' '.join(line) for line in lines.values())[:100000]


def lead_cell_text(words, gray):
    """Read an explicitly labelled header cell; never names in notes/rep fields."""
    import cv2
    import numpy as np
    height, width = gray.shape
    ink = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)[1]
    header = [w for w in words if w['top'] < min(height * .45, width * .20)]
    label = lambda w: re.sub(r'[^a-z]', '', w['text'].lower())
    readings = []
    for lead in header:
        if label(lead) != 'lead':
            continue
        names = [w for w in header if label(w) == 'name' and
                 0 <= w['left'] - (lead['left'] + lead['width']) < lead['height'] * 3 and
                 abs(w['top'] - lead['top']) <= max(w['height'], lead['height']) * .6]
        if len(names) != 1:
            continue
        name = names[0]
        x = name['left'] + name['width']
        y, size = min(lead['top'], name['top']), max(lead['height'], name['height'])
        vertical = cv2.morphologyEx(ink, cv2.MORPH_OPEN, np.ones((max(12, size * 2), 1), np.uint8))
        support = (vertical[max(0,y-size//2):min(height,y+size*2)] > 0).mean(axis=0)
        candidates = np.flatnonzero(support > .55)
        candidates = candidates[(candidates > x + 2) & (candidates < width * .70)]
        # Without a detected cell edge, a recognized neighboring Address label
        # is an explicit boundary. Do not guess an arbitrary number of name words.
        right = int(candidates[0]) if len(candidates) else None
        addresses = [w['left'] for w in header if label(w) == 'address' and w['left'] > x and
                     abs(w['top']-y) < size]
        if addresses:
            right = min([right] + addresses) if right is not None else min(addresses)
        if right is None:
            continue
        horizontal = cv2.morphologyEx(ink, cv2.MORPH_OPEN,
                                     np.ones((1, max(20, width//35)), np.uint8))
        occupied = (horizontal[:, max(0,lead['left']):right] > 0).mean(axis=1)
        below = np.flatnonzero(occupied > .65)
        below = below[(below > y+size) & (below < y+size*4)]
        bottom = int(below[0]) if len(below) else y+size*1.5
        values = [w for w in words if w['left'] >= x-1 and
                  w['left']+w['width']/2 < right and
                  y-size*.5 <= w['top']+w['height']/2 < bottom]
        values.sort(key=lambda w: (round((w['top']-y)/max(1,size)), w['left']))
        readings.append('Lead Name: ' + ' '.join(w['text'] for w in values))
    # Multiple header labels mean that the crop is not one unambiguous record.
    return readings[0] if len(readings) == 1 else ''


def _date_readings(text):
    readings = []
    for match in re.finditer(r'\b(20\d{2})[.\-/](\d{1,2})[.\-/](\d{1,2})\b', text):
        try:
            readings.append(date(*map(int, match.groups())).isoformat())
        except ValueError:
            pass
    # The local appointment box uses M/D/YYYY; the other box uses YYYY.MM.DD.
    # Normalize both formats before requiring independent agreeing readings.
    for match in re.finditer(r'\b(\d{1,2})/(\d{1,2})/(20\d{2})\b', text):
        try:
            month, day, year = map(int, match.groups())
            readings.append(date(year, month, day).isoformat())
        except ValueError:
            pass
    months = 'jan feb mar apr may jun jul aug sep oct nov dec'.split()
    for match in re.finditer(
            r'\b(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+'
            r'(\d{1,2}),?\s+(20\d{2})\b', text, re.I):
        try:
            readings.append(
                date(int(match[3]), months.index(match[1].lower()) + 1, int(match[2])).isoformat()
            )
        except ValueError:
            pass
    return readings


def printed_date(words, height):
    header = ' '.join(w['text'] for w in words if w['top'] < height * .27 and w['conf'] >= 70)
    readings = _date_readings(header)
    return (readings[0], 'printed') if len(readings) >= 2 and len(set(readings)) == 1 else (None, 'needs-date')


def document_date(words, height, known_date=None):
    """Use the PDF-level date when processing already established one."""
    if known_date:
        return known_date, 'printed'
    return printed_date(words, height)


def _template_document_date(values, known_date=None):
    if known_date:
        return known_date, 'printed'
    per_field = []
    for field in TEMPLATE_FIELDS:
        if not field.date_candidate:
            continue
        readings = _date_readings(values.get(field.key, ''))
        unique = set(readings)
        if len(unique) == 1:
            per_field.append(next(iter(unique)))
    return (per_field[0], 'printed') if len(per_field) >= 2 and len(set(per_field)) == 1 else (None, 'needs-date')


def _meaningful_bbox(image, minimum_area):
    """Cheap blank/dust test; return the bounding box of real variable ink."""
    import cv2
    import numpy as np

    binary = (image < 225).astype(np.uint8)
    count, _, stats, _ = cv2.connectedComponentsWithStats(binary, 8)
    kept = []
    for label in range(1, count):
        x, y, width, height, area = stats[label]
        if area >= minimum_area and (width >= 2 or height >= 3):
            kept.append((x, y, width, height))
    if not kept:
        return None
    left = min(value[0] for value in kept)
    top = min(value[1] for value in kept)
    right = max(value[0] + value[2] for value in kept)
    bottom = max(value[1] + value[3] for value in kept)
    return left, top, right, bottom


def _ink_runs(mask):
    import numpy as np

    edges = np.flatnonzero(np.diff(np.r_[False, mask, False].astype(np.int8)))
    return list(zip(edges[::2], edges[1::2]))


def _label_extent(crop, field, registration):
    """Find the label exclusion area without another OCR-engine call.

    The template only seeds a local search. Printed pixels determine the end of
    the label and its line height. Clearance uses only the surrounding blank ink
    gap. Only fields that can wrap regain the full width underneath their label.
    An unreadable colon leaves the line intact rather than guessing into a value.
    """
    import cv2
    import numpy as np

    height, width = crop.shape
    expected = map_box(registration, field.box)
    label = map_box(registration, field.label_box)
    expected_end = min(width, max(1, label[2] - expected[0]))
    letter_height = max(6, label[3] - label[1])
    tolerance = max(5, int(round(letter_height * 1.4)))
    search_right = min(width, expected_end + tolerance)
    search_bottom = min(height, max(int(letter_height * 3),
                                    label[3] - expected[1]))
    ink = crop[:search_bottom, :search_right] < 225

    # Join tiny raster gaps within letters, but never join separate text lines.
    occupied = ink[:, :min(width, expected_end)].any(axis=1)
    for start, end in _ink_runs(~occupied):
        if start and end < len(occupied) and end - start <= 1:
            occupied[start:end] = True
    lines = [(int(top), int(bottom)) for top, bottom in _ink_runs(occupied)
             if bottom - top >= max(3, letter_height * .25)
             and int(ink[top:bottom, :expected_end].sum()) >= letter_height * 2]
    if not lines:
        return 0, 0
    top, bottom = lines[0]
    mask_bottom = bottom
    label_end = None

    count, _, stats, _ = cv2.connectedComponentsWithStats(
        ink[top:bottom].astype(np.uint8), 8
    )
    dots = []
    for x, y, cw, ch, area in stats[1:count]:
        if (area >= 1 and cw <= letter_height * .4 and ch <= letter_height * .4
                and expected_end * .40 <= x + cw <= expected_end + tolerance):
            dots.append((int(x), int(y), int(cw), int(ch), int(area)))
    candidates = []
    for upper in dots:
        for lower in dots:
            x, y, cw, ch, area = upper
            lx, ly, lw, lh, larea = lower
            if not (y + ch < ly and ly + lh - y <= letter_height * 1.1):
                continue
            if abs((x + cw / 2) - (lx + lw / 2)) > max(1.5, letter_height * .1):
                continue
            if not (.5 <= cw / lw <= 2 and .5 <= ch / lh <= 2
                    and .4 <= area / larea <= 2.5):
                continue
            end = max(x + cw, lx + lw)
            # A time in the value can contain another colon. Require the
            # printed label's words before it, not extra value words.
            prefix = ink[top:bottom, :min(x, lx)].any(axis=0)
            for start, stop in _ink_runs(~prefix):
                if start and stop < len(prefix) and stop - start < letter_height * .25:
                    prefix[start:stop] = True
            if len(_ink_runs(prefix)) != len(field.label.split()):
                continue
            candidates.append(end)
    if candidates:
        label_end = min(candidates)

    if label_end is None:
        # An uncertain boundary must not eat the first value character.
        # Retain the line; exact known labels are removed from OCR text below.
        return 0, 0

    # Put the cut in the whitespace between the label and value, keeping room
    # on both sides. Never extend a label mask into even a single value pixel.
    padding = max(2, int(round(letter_height * .25)))
    wraps = field.key in _WRAPPED_FIELD_KEYS
    label_rows = mask_bottom if wraps else height
    right_ink = np.flatnonzero((crop[:label_rows, label_end:] < 225).any(axis=0))
    right_gap = int(right_ink[0]) if len(right_ink) else width - label_end
    label_end += min(padding, right_gap // 2)
    if not wraps:
        return min(width, label_end), height

    below_ink = np.flatnonzero((crop[mask_bottom:, :label_end] < 225).any(axis=1))
    below_gap = int(below_ink[0]) if len(below_ink) else height - mask_bottom
    mask_bottom += min(padding, below_gap // 2)
    return min(width, label_end), min(height, mask_bottom)


def template_ocr_canvas(source, registration):
    """Return only the known Work Order Number value area.

    The MOD template already owns this field. Do not rediscover the printed label
    from scan pixels: that was clipping leading digits on some cards and leaving
    the whole label on others. The template's measured label boundary is the
    single source of truth for where numeric OCR begins.
    """
    import numpy as np

    frame_width = max(1, registration.right - registration.left)
    frame_height = max(1, registration.bottom - registration.top)
    ink_pad = max(4, int(round(frame_width * .002)))
    minimum_area = max(4, int(round(frame_width / 1200.0)))

    active = []
    for field, (left, top, right, bottom) in field_boxes(source, registration):
        if field.key not in _OCR_FIELD_KEYS or right <= left or bottom <= top:
            continue

        _, _, label_right, _ = map_box(registration, field.label_box)
        # A tiny positive inset keeps the colon/label out while leaving far more
        # than enough room before the first printed digit on the known template.
        value_left = max(left, min(right, label_right + max(1, int(round(frame_width * .001)))))
        if value_left >= right:
            continue
        crop = source[top:bottom, value_left:right].copy()

        box = _meaningful_bbox(crop, minimum_area)
        if box is None:
            continue
        x0, y0, x1, y1 = box
        x0 = max(0, x0 - ink_pad)
        x1 = min(crop.shape[1], x1 + ink_pad)
        y0 = max(0, y0 - ink_pad)
        y1 = min(crop.shape[0], y1 + ink_pad)
        active.append((field, crop[y0:y1, x0:x1]))

    if not active:
        return None, []

    gap = max(12, int(round(frame_height * .012)))
    margin = gap
    canvas_width = max(crop.shape[1] for _, crop in active) + margin * 2
    canvas_height = sum(crop.shape[0] for _, crop in active) + gap * (len(active) - 1) + margin * 2
    canvas = np.full((canvas_height, canvas_width), 255, np.uint8)
    segments = []
    y = margin
    for field, crop in active:
        canvas[y:y + crop.shape[0], margin:margin + crop.shape[1]] = crop
        segments.append((field.key, y, y + crop.shape[0]))
        y += crop.shape[0] + gap
    return canvas, segments


def _field_values(words, segments):
    values = {}
    fields = {field.key: field for field in TEMPLATE_FIELDS}
    for key, top, bottom in segments:
        if key not in _OCR_FIELD_KEYS:
            continue
        selected = [word for word in words
                    if top <= word['top'] + word['height'] / 2.0 < bottom]
        value = ' '.join(search_text(selected).split())
        # When the printed colon/boundary was unreadable, retain the pixels and
        # remove only an exact recognized label prefix, not arbitrary name text.
        label = fields[key].label
        value = re.sub(r'^' + re.escape(label) + r'\s*:\s*', '', value, flags=re.I)
        if value:
            values[key] = value
    return values


def _template_search_text(values):
    lines = []
    for field in TEMPLATE_FIELDS:
        if field.key not in _OCR_FIELD_KEYS:
            continue
        value = values.get(field.key, '')
        if value:
            lines.append(f'{field.label}: {value}')
    return '\n'.join(lines)[:100000]


def _run_tesseract(image, ocr_copy, *, digits_only=False, psm=None):
    import cv2

    if not cv2.imwrite(str(ocr_copy), image):
        raise OSError('OCR working image cannot be written')
    command = [
        'tesseract', str(ocr_copy), 'stdout', '-l', 'eng',
        '--psm', str(psm if psm is not None else (7 if digits_only else 6)),
    ]
    if digits_only:
        command.extend(['-c', 'tessedit_char_whitelist=0123456789'])
    command.append('tsv')
    result = subprocess.run(
        command,
        check=True,
        capture_output=True,
        text=True,
        timeout=120,
    )
    return tsv_words(result.stdout)


def _first_work_order_candidate(text):
    match = next(re.finditer(r'[0-9]{8,}', str(text or '')), None)
    return match[0][:8] if match else ''


def mod_notes_present(source, registration):
    """Return whether the known MOD Notes cell contains meaningful variable ink.

    None means the card could not be registered confidently enough to judge it;
    callers must retain those cards rather than guessing.
    """
    import cv2
    import numpy as np

    if source is None or not registration.matched:
        return None
    field = next(field for field in TEMPLATE_FIELDS if field.key == 'mod_notes')
    boxes = dict((item.key, bounds) for item, bounds in field_boxes(source, registration))
    left, top, right, bottom = boxes.get(field.key, (0, 0, 0, 0))
    if right <= left or bottom <= top:
        return None
    crop = source[top:bottom, left:right].copy()

    # Remove only the printed MOD Notes label. The rest of the cell, including
    # handwriting beneath the label, remains available for the emptiness check.
    label_left, label_top, label_right, label_bottom = map_box(registration, field.label_box)
    x0 = max(0, label_left - left - 3)
    y0 = max(0, label_top - top - 3)
    x1 = min(crop.shape[1], label_right - left + 5)
    y1 = min(crop.shape[0], label_bottom - top + 5)
    if x1 > x0 and y1 > y0:
        crop[y0:y1, x0:x1] = 255

    ink = cv2.threshold(crop, 225, 255, cv2.THRESH_BINARY_INV)[1]
    # Eliminate residual printed rules before judging handwriting/notes.
    h, w = crop.shape
    horizontal = cv2.morphologyEx(
        ink, cv2.MORPH_OPEN, np.ones((1, max(18, w // 12)), np.uint8)
    )
    vertical = cv2.morphologyEx(
        ink, cv2.MORPH_OPEN, np.ones((max(14, h // 8), 1), np.uint8)
    )
    variable = ink.copy()
    variable[(horizontal > 0) | (vertical > 0)] = 0

    count, _, stats, _ = cv2.connectedComponentsWithStats((variable > 0).astype(np.uint8), 8)
    meaningful = sum(
        int(stats[label, cv2.CC_STAT_AREA])
        for label in range(1, count)
        if stats[label, cv2.CC_STAT_AREA] >= 4
    )
    return meaningful >= max(40, int(round(crop.size * .0004)))


def _candidate_result(candidates, known_date, reads=()):
    unique = tuple(dict.fromkeys(value for value in candidates if value))
    number = unique[0] if len(unique) == 1 else ''
    return dict(
        text=('Work Order Number: ' + number) if number else '',
        lead_text='',
        document_date=known_date,
        date_status='printed' if known_date else 'needs-date',
        work_order_candidates=unique,
        work_order_reads=tuple(reads),
    )


def _recognize_template(source, registration, ocr_copy, known_date, debug_path=None):
    """Read the same masked work-order value several independent ways.

    When requested, persist the exact field canvas used by the first OCR pass.
    Diagnostic pass results are normalized data; callers never need Tesseract TSV.
    """
    import cv2

    canvas, segments = template_ocr_canvas(source, registration)
    if canvas is None:
        return _candidate_result((), known_date)

    if debug_path is not None and not cv2.imwrite(str(debug_path), canvas):
        raise OSError('OCR diagnostic image cannot be written')

    enlarged = cv2.resize(canvas, None, fx=2.0, fy=2.0, interpolation=cv2.INTER_CUBIC)
    thresholded = cv2.threshold(enlarged, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)[1]
    candidates = []
    reads = []
    passes = (
        ('Original field', canvas, 7),
        ('2× enlarged', enlarged, 13),
        ('Thresholded', thresholded, 6),
    )
    for label, image, psm in passes:
        try:
            words = _run_tesseract(image, ocr_copy, digits_only=True, psm=psm)
        except subprocess.SubprocessError:
            reads.append(dict(label=label, psm=psm, text='', candidate='', ok=False))
            continue
        raw = ' '.join(search_text(words).split())[:128]
        candidate = _first_work_order_candidate(raw)
        reads.append(dict(
            label=label, psm=psm, text=raw, candidate=candidate, ok=True,
        ))
        if candidate:
            candidates.append(candidate)
    return _candidate_result(candidates, known_date, reads)


def _recognize_legacy(source, ocr_copy, known_date):
    """Fallback OCR the whole isolated card so other identity fields can match it."""
    import cv2
    import numpy as np

    h, w = source.shape
    ink = cv2.threshold(source, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)[1]
    rules = cv2.morphologyEx(ink, cv2.MORPH_OPEN, np.ones((1, max(30, w//25)), np.uint8))
    rules |= cv2.morphologyEx(
        ink, cv2.MORPH_OPEN, np.ones((max(30, min(h//12, w//25)), 1), np.uint8)
    )
    disposable = source.copy()
    disposable[cv2.dilate(rules, np.ones((3, 3), np.uint8)) > 0] = 255

    candidates = []
    reads = []
    best = None
    labels = ('Work Order', 'Lead Name', 'Address', 'Phone', 'Scheduled Start', 'MOD Notes')
    for psm in (6, 11):
        label = 'Fallback whole card'
        try:
            words = _run_tesseract(disposable, ocr_copy, psm=psm)
        except subprocess.SubprocessError:
            reads.append(dict(label=label, psm=psm, text='', candidate='', ok=False))
            continue
        raw = search_text(words)[:100000]
        number = printed_work_order_number(raw)
        compact = ' '.join(raw.split())[:256]
        reads.append(dict(label=label, psm=psm, text=compact, candidate=number, ok=True))
        if number:
            candidates.append(number)
        day, date_status = document_date(words, h, known_date)
        lead_text = lead_cell_text(words, source)
        score = sum(1 for value in labels if value.casefold() in raw.casefold())
        score += int(bool(lead_text)) + int(bool(day))
        candidate = (score, len(raw), raw, lead_text, day, date_status)
        if best is None or candidate[:2] > best[:2]:
            best = candidate

    result = _candidate_result(candidates, known_date, reads)
    if best is not None:
        _, _, raw, lead_text, day, date_status = best
        result['text'] = raw
        result['lead_text'] = lead_text
        result['document_date'] = day
        result['date_status'] = date_status
    return result


def recognize(path, work, known_date=None, debug_path=None):
    import cv2

    source = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
    if source is None:
        raise ValueError('Saved image cannot be read')
    ocr_copy = Path(work) / 'ocr.png'
    try:
        registration = register_form(source)
        notes_present = mod_notes_present(source, registration)
        template = _recognize_template(
            source, registration, ocr_copy, known_date, debug_path=debug_path,
        )
        template_candidates = tuple(template.get('work_order_candidates', ()))
        if registration.matched and len(template_candidates) == 1:
            template['mod_notes_present'] = notes_present
            return template

        # If the dedicated work-order cell does not produce one clear result,
        # OCR the whole isolated card once. Name/address/phone/date text then
        # remains available for normalized source matching before manual review.
        legacy = _recognize_legacy(source, ocr_copy, known_date)
        result = _candidate_result(
            (*template_candidates, *legacy.get('work_order_candidates', ())),
            legacy.get('document_date') or known_date,
            (*template.get('work_order_reads', ()),
             *legacy.get('work_order_reads', ())),
        )
        if legacy.get('text'):
            result['text'] = legacy['text']
        result['lead_text'] = legacy.get('lead_text', '')
        result['document_date'] = legacy.get('document_date')
        result['date_status'] = legacy.get('date_status', 'needs-date')
        result['mod_notes_present'] = notes_present
        return result
    finally:
        ocr_copy.unlink(missing_ok=True)


if __name__ == '__main__':
    # Worker-owned repair of one saved PNG. No PDF, print job, or date mutation.
    import os
    import cv2
    os.environ['OMP_THREAD_LIMIT'] = '1'
    cv2.setNumThreads(1)
    result = recognize(Path(sys.argv[1]), Path(sys.argv[2]))
    (Path(sys.argv[2]) / 'recognition.json').write_text(json.dumps(result), encoding='utf-8')
