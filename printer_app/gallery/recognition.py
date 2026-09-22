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
    """Pack the work-order field into one OCR image.

    Measured black borders bound every field. The two first-row fields use a
    straight cut after the colon; name, address and Scheduled Start keep the full
    width below their labels. Segments preserve each field's ownership after OCR.
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

        crop = source[top:bottom, left:right].copy()
        label_end, label_bottom = _label_extent(crop, field, registration)
        crop[:label_bottom, :label_end] = 255

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


def _run_tesseract(image, ocr_copy, *, digits_only=False):
    import cv2

    if not cv2.imwrite(str(ocr_copy), image):
        raise OSError('OCR working image cannot be written')
    command = [
        'tesseract', str(ocr_copy), 'stdout', '-l', 'eng',
        '--psm', '7' if digits_only else '6',
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


def _recognize_template(source, registration, ocr_copy, known_date):
    canvas, segments = template_ocr_canvas(source, registration)
    if canvas is None:
        docdate, state = _template_document_date({}, known_date)
        return dict(text='', lead_text='', document_date=docdate, date_status=state)

    words = _run_tesseract(canvas, ocr_copy, digits_only=True)
    values = _field_values(words, segments)
    raw = values.get('work_order_number', '')
    number = next((match[0][:8] for match in re.finditer(r'[0-9]{8,}', raw)), '')
    return dict(
        text=('Work Order Number: ' + number) if number else '',
        lead_text='',
        document_date=known_date,
        date_status='printed' if known_date else 'needs-date',
    )


def _recognize_legacy(source, ocr_copy, known_date):
    """Fallback localization may inspect the card, but only work-order identity leaves OCR."""
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
    words = _run_tesseract(disposable, ocr_copy)
    number = printed_work_order_number(search_text(words))
    return dict(
        text=('Work Order Number: ' + number) if number else '',
        lead_text='',
        document_date=known_date,
        date_status='printed' if known_date else 'needs-date',
    )


def recognize(path, work, known_date=None):
    import cv2

    source = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
    if source is None:
        raise ValueError('Saved image cannot be read')
    ocr_copy = Path(work) / 'ocr.png'
    try:
        registration = register_form(source)
        if registration.matched:
            return _recognize_template(source, registration, ocr_copy, known_date)
        return _recognize_legacy(source, ocr_copy, known_date)
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
