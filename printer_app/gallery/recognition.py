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
    from .form_template import TEMPLATE_FIELDS, map_box, register_form
else:
    from form_template import TEMPLATE_FIELDS, map_box, register_form


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


def _clamp_box(box, width, height):
    left, top, right, bottom = box
    return (
        max(0, min(width, left)),
        max(0, min(height, top)),
        max(0, min(width, right)),
        max(0, min(height, bottom)),
    )


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


def template_ocr_canvas(source, registration):
    """Pack only populated variable regions into one small Tesseract image.

    Constant labels and grid rules never enter this raster. Empty fields, including
    empty large handwriting areas, cost only the cheap connected-component check.
    Returned segments preserve each field's ownership after OCR.
    """
    import numpy as np

    height, width = source.shape
    frame_width = max(1, registration.right - registration.left)
    frame_height = max(1, registration.bottom - registration.top)
    edge_x = max(4, int(round(frame_width * .006)))
    edge_y = max(4, int(round(frame_height * .010)))
    label_pad_x = max(3, int(round(frame_width * .004)))
    label_pad_y = max(3, int(round(frame_height * .006)))
    ink_pad = max(4, int(round(frame_width * .002)))
    minimum_area = max(4, int(round(frame_width / 1200.0)))

    active = []
    for field in TEMPLATE_FIELDS:
        left, top, right, bottom = _clamp_box(map_box(registration, field.box), width, height)
        left += edge_x
        right -= edge_x
        top += edge_y
        bottom -= edge_y
        if right <= left or bottom <= top:
            continue
        crop = source[top:bottom, left:right].copy()

        ll, lt, lr, lb = _clamp_box(map_box(registration, field.label_box), width, height)
        ll = max(left, ll - label_pad_x) - left
        lr = min(right, lr + label_pad_x) - left
        lt = max(top, lt - label_pad_y) - top
        lb = min(bottom, lb + label_pad_y) - top
        if lr > ll and lb > lt:
            crop[lt:lb, ll:lr] = 255

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
    for key, top, bottom in segments:
        selected = [word for word in words
                    if top <= word['top'] + word['height'] / 2.0 < bottom]
        value = ' '.join(search_text(selected).split())
        if value:
            values[key] = value
    return values


def _template_search_text(values):
    lines = []
    for field in TEMPLATE_FIELDS:
        value = values.get(field.key, '')
        if value:
            lines.append(f'{field.label}: {value}')
    return '\n'.join(lines)[:100000]


def _run_tesseract(image, ocr_copy):
    import cv2

    if not cv2.imwrite(str(ocr_copy), image):
        raise OSError('OCR working image cannot be written')
    result = subprocess.run(
        ['tesseract', str(ocr_copy), 'stdout', '-l', 'eng', '--psm', '6', 'tsv'],
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

    words = _run_tesseract(canvas, ocr_copy)
    values = _field_values(words, segments)
    lead = next((values.get(field.key, '') for field in TEMPLATE_FIELDS if field.lead), '')
    docdate, state = _template_document_date(values, known_date)
    return dict(
        text=_template_search_text(values),
        lead_text=('Lead Name: ' + lead) if lead else '',
        document_date=docdate,
        date_status=state,
    )


def _recognize_legacy(source, ocr_copy, known_date):
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
    docdate, state = document_date(words, h, known_date)
    return dict(
        text=search_text(words),
        lead_text=lead_cell_text(words, source),
        document_date=docdate,
        date_status=state,
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
