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
    from .form_template import (TEMPLATE_FIELDS, field_boxes, field_crop,
                                labelled_notes_crop, map_box, register_form)
    from .numeric_parser import numeric_tokens_from_text, parse_numeric_image
    from .policy import (REFERENCE_FIELD_LABELS, normalize_work_order_evidence,
                         scanned_work_order_candidates, work_order_fields,
                         work_order_schedule)
else:
    from form_template import (TEMPLATE_FIELDS, field_boxes, field_crop,
                               labelled_notes_crop, map_box, register_form)
    from numeric_parser import numeric_tokens_from_text, parse_numeric_image
    from policy import (REFERENCE_FIELD_LABELS, normalize_work_order_evidence,
                        scanned_work_order_candidates, work_order_fields,
                        work_order_schedule)

# The scan supplies the durable work-order identity. When readings disagree,
# literal printed header observations can corroborate one exact source match.
# Displayed customer, appointment and rep data still come from reference data.
_OCR_FIELD_KEYS = frozenset({'work_order_number'})
_EVIDENCE_FIELDS = ('lead_name', 'phone', 'local_scheduled_start_time', 'scheduled_start')


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
    return '\n'.join(' '.join(line) for line in lines.values())


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


def template_ocr_canvas(source, registration):
    """Return a generous Work Order Number search field for the numeric parser.

    The search starts before the measured label boundary so small registration
    errors cannot clip the first printed digit. The numeric parser, not this
    template adapter, owns locating the eight glyph positions inside the field.
    """
    field = next(field for field in TEMPLATE_FIELDS if field.key == 'work_order_number')
    cell, bounds = field_crop(source, registration, field.key)
    left, top, right, bottom = bounds
    if cell is None or right <= left or bottom <= top:
        return None, []

    frame_width = max(1, registration.right - registration.left)
    _, _, label_right, _ = map_box(registration, field.label_box)
    slack = max(8, int(round(frame_width * .015)))
    search_left = max(left, label_right - slack)
    if search_left >= right:
        return None, []

    canvas = cell[:, search_left - left:].copy()
    return canvas, [(field.key, 0, canvas.shape[0])]


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
        encoding='utf-8',
        timeout=120,
    )
    return tsv_words(result.stdout)


def _work_order_candidates(text, *, labeled=False):
    """Normalize observed glyphs, then apply the single scan-policy boundary."""
    fields = work_order_fields(text) if labeled else (text,)
    return tuple(dict.fromkeys(
        candidate
        for field in fields
        for token in numeric_tokens_from_text(field, allow_separated=True)
        for candidate in scanned_work_order_candidates(token)
    ))


def _without_form_rules(source):
    """Suppress long printed rules in a disposable whole-image OCR copy."""
    import cv2
    import numpy as np

    height, width = source.shape
    ink = cv2.threshold(source, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)[1]
    rules = cv2.morphologyEx(
        ink, cv2.MORPH_OPEN, np.ones((1, max(30, width // 25)), np.uint8),
    )
    rules |= cv2.morphologyEx(
        ink, cv2.MORPH_OPEN,
        np.ones((max(30, min(height // 12, width // 25)), 1), np.uint8),
    )
    disposable = source.copy()
    disposable[cv2.dilate(rules, np.ones((3, 3), np.uint8)) > 0] = 255
    return disposable


def _notes_labels(words, offset):
    """Return literal printed MOD Notes label bounds, without fuzzy text guesses."""
    normalize = lambda value: re.sub(r'[^a-z0-9]', '', value.lower())
    labels = []
    for index, word in enumerate(words):
        group = []
        if normalize(word['text']) == 'modnotes':
            group = [word]
        elif normalize(word['text']) == 'mod' and index + 1 < len(words):
            following = words[index + 1]
            size = max(word['height'], following['height'])
            if (normalize(following['text']) == 'notes'
                    and abs(word['top'] - following['top']) <= size
                    and 0 <= following['left'] - word['left'] - word['width'] <= size * 2):
                group = [word, following]
        if group:
            labels.append((
                min(item['left'] for item in group) + offset[0],
                min(item['top'] for item in group) + offset[1],
                max(item['left'] + item['width'] for item in group) + offset[0],
                max(item['top'] + item['height'] for item in group) + offset[1],
            ))
    return labels


def mod_notes_present(source, registration, ocr_copy):
    """Check only an observed, bordered MOD Notes cell; uncertainty stays None."""
    import cv2
    import numpy as np

    if source is None or not source.size:
        return None
    # A template crop is a cheap label-search proposal, never proof of the cell.
    # Screenshots can register while placing its edge inside neighboring fields.
    proposed, bounds = field_crop(source, registration, 'mod_notes')
    probes = []
    if proposed is not None and proposed.size:
        height, width = proposed.shape
        for fraction_y, fraction_x, psm in ((.10, .25, 6), (.20, .30, 6), (.20, .30, 11)):
            probes.append((proposed[:round(height * fraction_y), :round(width * fraction_x)],
                           bounds[:2], psm))
    height, width = source.shape
    top = round(min(height * .15, width * .08))
    stop = round(min(height * .75, width * .60))
    # A clipped screenshot can leave the label in the right half while nearby
    # printed cells confuse whole-region line grouping. Keep both bounded views.
    for fraction in (.50, .30):
        left = round(width * fraction)
        for psm in (11, 6):
            probes.append((source[top:stop, left:], (left, top), psm))

    crop = None
    for suppress_rules in (False, True):
        # Some OCR versions join the bordering rule to MOD and read IMOD.
        # Retry the same literal-label probes without long rules only after
        # every original view fails. Whole-image rule lengths protect glyphs.
        disposable = _without_form_rules(source) if suppress_rules else None
        for original, (x, y), psm in probes:
            if not original.size:
                continue
            image = original
            if disposable is not None:
                h, w = original.shape
                image = disposable[y:y+h, x:x+w].copy()
                image[original == 255] = 255  # Preserve the existing cell mask.
            padded = cv2.copyMakeBorder(image, 12, 12, 12, 12, cv2.BORDER_CONSTANT, value=255)
            try:
                words = _run_tesseract(padded, ocr_copy, psm=psm)
            except subprocess.SubprocessError:
                continue
            labels = _notes_labels(words, (x - 12, y - 12))
            if len(labels) != 1:
                continue
            label = labels[0]
            crop, bounds = labelled_notes_crop(source, label)
            if crop is not None:
                break
        if crop is not None:
            break
    if crop is None:
        return None
    # Mask the observed printed glyphs, not a template-sized rectangle whose
    # location can drift into the blank area or nearby handwriting.
    left, top = bounds[:2]
    x0, y0 = max(0, label[0] - left - 1), max(0, label[1] - top - 1)
    x1 = min(crop.shape[1], label[2] - left + 1)
    y1 = min(crop.shape[0], label[3] - top + 1)
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
    # Independent systems keep independent answers. Source validation gets every
    # unique candidate; one parser is never allowed to erase another parser's read.
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


def _printed_field_values(text, key, *, isolated=False):
    """Keep labelled observations, including every wrapped line in a name cell."""
    field = next(field for field in TEMPLATE_FIELDS if field.key == key)
    label = re.escape(field.label).replace(r'\ ', r'\s*')
    boundary = '|'.join(re.escape(value).replace(r'\ ', r'\s+')
                        for value in sorted(REFERENCE_FIELD_LABELS, key=len, reverse=True))
    original = str(text or '')
    values = []
    for match in re.finditer(r'\b' + label + r'\s*[:;]\s*', original, re.I):
        value = re.split(r'\b(?:' + boundary + r')\b', original[match.end():],
                         maxsplit=1, flags=re.I)[0]
        values.append(' '.join(value.split()).strip(' |'))
    if not values and isolated and key in ('lead_name', 'phone'):
        # Geometry already proves which cell this is. OCR can misread its label
        # (for example Leed Name), while the printed colon still marks the value.
        match = re.match(r'^[^:\n]{1,32}:\s*(.+)$', original, re.S)
        if match:
            value = re.split(r'\b(?:' + boundary + r')\b', match[1],
                             maxsplit=1, flags=re.I)[0]
            values.append(' '.join(value.split()).strip(' |'))
    return tuple(value for value in values if value)


def _printed_evidence(text, *, key=None):
    """Turn literal header reads into normalized, independent corroboration."""
    observed = {name: [] for name in ('names', 'dates', 'times', 'phones')}
    if key is None:
        # Label-like handwriting in MOD Notes must never supply identity.
        text = re.split(r'\b(?:Work\s+Type|Lead\s+Description|MOD\s+Notes)\s*:',
                        str(text or ''), maxsplit=1, flags=re.I)[0]
    for field in (key,) if key else _EVIDENCE_FIELDS:
        for value in _printed_field_values(text, field, isolated=key is not None):
            if field == 'lead_name':
                observed['names'].append(value)
            elif field == 'phone':
                observed['phones'].append(value)
            else:
                observed['dates'].extend(_date_readings(value))
                day, time = work_order_schedule(value)
                if day:
                    observed['dates'].append(day)
                if time and re.search(r'(?<![A-Za-z])(?:AM|PM)\b', value, re.I):
                    observed['times'].append(time)
    return normalize_work_order_evidence(observed)


def _recognize_evidence(source, registration, ocr_copy, known_date, previous=None):
    """Read only the printed cells needed to distinguish competing WO numbers."""
    import cv2

    observed = {key: list(values) for key, values in
                normalize_work_order_evidence(previous).items()}
    if known_date:
        observed['dates'].append(known_date)
    if registration.matched:
        for key in _EVIDENCE_FIELDS:
            cell, _ = field_crop(source, registration, key)
            if cell is None:
                continue
            enlarged = cv2.resize(cell, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)
            for image in (cell, enlarged):
                try:
                    raw = search_text(_run_tesseract(image, ocr_copy, psm=6))
                except subprocess.SubprocessError:
                    continue
                for name, values in _printed_evidence(raw, key=key).items():
                    observed[name].extend(values)
    return normalize_work_order_evidence(observed)


def _recognize_template(source, registration, ocr_copy, known_date, debug_path=None):
    """Run independent recognition systems against the same work-order field."""
    import cv2

    canvas, _ = template_ocr_canvas(source, registration)
    if canvas is None:
        return _candidate_result((), known_date)

    if debug_path is not None and not cv2.imwrite(str(debug_path), canvas):
        raise OSError('OCR diagnostic image cannot be written')

    candidates = []
    reads = []

    # System 1: locate eight visible slots, then classify each glyph independently.
    def read_digit(glyph, psm):
        try:
            return _run_tesseract(glyph, ocr_copy, digits_only=True, psm=psm)
        except subprocess.SubprocessError:
            return ()

    parsed = parse_numeric_image(canvas, read_digit)
    positions = tuple(parsed.get('positions') or ())
    parsed_text = ''.join(value or '?' for value in positions)
    parsed_candidates = tuple(dict.fromkeys(
        candidate
        for token in (parsed.get('candidates') or (parsed.get('candidate', ''),))
        for candidate in scanned_work_order_candidates(token)
    ))
    psms = sorted({attempt.get('psm') for attempt in parsed.get('attempts', ())
                   if attempt.get('psm')})
    for candidate in parsed_candidates or ('',):
        reads.append(dict(
            label='Numerical parser',
            psm='/'.join(map(str, psms)) if psms else '',
            text=parsed_text,
            candidate=candidate,
            ok=bool(candidate),
        ))
    candidates.extend(parsed_candidates)

    # Systems 2-4: whole-field OCR. They see the same field but use independent
    # preprocessing/page-segmentation choices; each answer remains available to
    # source validation instead of being voted away.
    enlarged = cv2.resize(canvas, None, fx=2.0, fy=2.0, interpolation=cv2.INTER_CUBIC)
    thresholded = cv2.threshold(
        enlarged, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU
    )[1]
    passes = [
        ('Whole field', canvas, 7),
        ('2x whole field', enlarged, 13),
        ('Thresholded whole field', thresholded, 6),
    ]
    for left, top, right, bottom in parsed.get('regions', ()):
        # Segmentation supplies only observed ink bounds, independently of its
        # digit answers. This reader sees the original gray pixels as one number.
        tight = cv2.resize(canvas[top:bottom, left:right], None,
                           fx=1.5, fy=1.5, interpolation=cv2.INTER_CUBIC)
        tight = cv2.copyMakeBorder(tight, 10, 10, 10, 10,
                                   cv2.BORDER_CONSTANT, value=255)
        passes.append(('Tight whole field', tight, 7))
    for label, image, psm in passes:
        try:
            words = _run_tesseract(image, ocr_copy, digits_only=True, psm=psm)
            raw = ' '.join(search_text(words).split())
            found = _work_order_candidates(raw)
            for candidate in found or ('',):
                reads.append(dict(
                    label=label, psm=psm, text=raw[:128], candidate=candidate, ok=True,
                ))
            candidates.extend(found)
        except subprocess.SubprocessError:
            reads.append(dict(label=label, psm=psm, text='', candidate='', ok=False))

    # System 5: unrestricted text OCR on the same field. This can recover glyph
    # confusions such as O/0, B/8 or !/1 that a digits-only pass may drop.
    try:
        words = _run_tesseract(canvas, ocr_copy, digits_only=False, psm=7)
        raw = ' '.join(search_text(words).split())
        found = _work_order_candidates(raw)
        for candidate in found or ('',):
            reads.append(dict(
                label='Text field', psm=7, text=raw[:128], candidate=candidate, ok=True,
            ))
        candidates.extend(found)
    except subprocess.SubprocessError:
        reads.append(dict(label='Text field', psm=7, text='', candidate='', ok=False))

    return _candidate_result(candidates, known_date, reads)


def _recognize_legacy(source, ocr_copy, known_date, registration=None):
    """Fallback OCR the whole isolated card so other identity fields can match it."""
    h, w = source.shape
    registration = registration if registration is not None else register_form(source)
    header_bottom = min(h * .27, w * .15)
    if registration.matched:
        _, bounds = field_crop(source, registration, 'scheduled_start')
        if bounds[3] > bounds[1]:
            header_bottom = bounds[3]
    disposable = _without_form_rules(source)

    candidates = []
    reads = []
    best = None
    evidence = {name: [] for name in ('names', 'dates', 'times', 'phones')}
    labels = ('Work Order', 'Lead Name', 'Address', 'Phone', 'Scheduled Start', 'MOD Notes')
    for psm in (6, 11):
        label = 'Fallback whole card'
        try:
            words = _run_tesseract(disposable, ocr_copy, psm=psm)
        except subprocess.SubprocessError:
            reads.append(dict(label=label, psm=psm, text='', candidate='', ok=False))
            continue
        raw = search_text(words)
        header = [word for word in words
                  if 0 <= word.get('top', -1)
                  and word.get('height', 0) > 0
                  and word['top'] + word['height'] <= header_bottom]
        for name, values in _printed_evidence(search_text(header)).items():
            evidence[name].extend(values)
        found = _work_order_candidates(raw, labeled=True)
        compact = ' '.join(raw.split())[:256]
        for number in found or ('',):
            reads.append(dict(label=label, psm=psm, text=compact, candidate=number, ok=True))
        candidates.extend(found)
        day, date_status = document_date(words, h, known_date)
        lead_text = lead_cell_text(words, source)
        score = sum(1 for value in labels if value.casefold() in raw.casefold())
        score += int(bool(lead_text)) + int(bool(day))
        candidate = (score, len(raw), raw[:100000], lead_text, day, date_status)
        if best is None or candidate[:2] > best[:2]:
            best = candidate

    result = _candidate_result(candidates, known_date, reads)
    result['work_order_evidence'] = normalize_work_order_evidence(evidence)
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
        notes_present = mod_notes_present(source, registration, ocr_copy)
        template = _recognize_template(
            source, registration, ocr_copy, known_date, debug_path=debug_path,
        )
        template_candidates = tuple(template.get('work_order_candidates', ()))
        numerical_candidates = {
            read.get('candidate') for read in template.get('work_order_reads', ())
            if read.get('label') == 'Numerical parser' and read.get('candidate')
        }
        if (registration.matched and len(template_candidates) == 1
                and numerical_candidates == set(template_candidates)):
            template['mod_notes_present'] = notes_present
            return template

        # An incomplete numerical reading cannot make another reader's lone
        # answer definitive. Keep the independent whole-card readings available
        # before source validation, even when one field reader found a candidate.
        legacy = _recognize_legacy(source, ocr_copy, known_date, registration)
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
        if len(result['work_order_candidates']) > 1:
            result['work_order_evidence'] = _recognize_evidence(
                source, registration, ocr_copy, known_date,
                legacy.get('work_order_evidence'),
            )
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
