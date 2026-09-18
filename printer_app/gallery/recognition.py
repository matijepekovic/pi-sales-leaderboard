"""Local OCR adapter. Only normalized text/header/date values leave this module.

Tesseract TSV is NOT quoted CSV: a printed quote must never absorb subsequent
rows. Word positions and the original rules isolate the Lead Name cell before
we flatten anything for search. The archived image is never modified.
"""
import csv
from datetime import date
import io
import json
from pathlib import Path
import re
import subprocess
import sys


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


def printed_date(words, height):
    header = ' '.join(w['text'] for w in words if w['top'] < height * .27 and w['conf'] >= 70)
    readings = []
    for m in re.finditer(r'\b(20\d{2})[.\-/](\d{1,2})[.\-/](\d{1,2})\b', header):
        try:
            readings.append(date(*map(int, m.groups())).isoformat())
        except ValueError:
            pass
    months = 'jan feb mar apr may jun jul aug sep oct nov dec'.split()
    for m in re.finditer(r'\b(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+(\d{1,2}),?\s+(20\d{2})\b', header, re.I):
        try:
            readings.append(date(int(m[3]), months.index(m[1].lower()) + 1, int(m[2])).isoformat())
        except ValueError:
            pass
    return (readings[0], 'printed') if len(readings) >= 2 and len(set(readings)) == 1 else (None, 'needs-date')


def document_date(words, height, known_date=None):
    """Use the PDF-level date when processing already established one."""
    if known_date:
        return known_date, 'printed'
    return printed_date(words, height)


def recognize(path, work, known_date=None):
    import cv2
    import numpy as np
    source = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
    if source is None:
        raise ValueError('Saved image cannot be read')
    h, w = source.shape
    ink = cv2.threshold(source, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)[1]
    rules = cv2.morphologyEx(ink, cv2.MORPH_OPEN, np.ones((1, max(30, w//25)), np.uint8))
    rules |= cv2.morphologyEx(ink, cv2.MORPH_OPEN, np.ones((max(30, min(h//12, w//25)), 1), np.uint8))
    disposable = source.copy()
    disposable[cv2.dilate(rules, np.ones((3, 3), np.uint8)) > 0] = 255
    ocr_copy = Path(work) / 'ocr.png'
    try:
        cv2.imwrite(str(ocr_copy), disposable)
        result = subprocess.run(['tesseract', str(ocr_copy), 'stdout', '-l', 'eng', '--psm', '6', 'tsv'],
                                check=True, capture_output=True, text=True, timeout=120)
        words = tsv_words(result.stdout)
        docdate, state = document_date(words, h, known_date)
        return dict(text=search_text(words), lead_text=lead_cell_text(words, source),
                    document_date=docdate, date_status=state)
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
