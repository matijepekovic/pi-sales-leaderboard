"""Gallery settings and normalized search/date rules, without IO or vendor data."""
from dataclasses import dataclass, replace
from datetime import date
import re
import unicodedata

FIELDS = {'GALLERY_ENABLED', 'GALLERY_SUBJECT_CONTAINS', 'GALLERY_FROM_CONTAINS',
          'GALLERY_KEEP_DAYS', 'GALLERY_MAX_MB', 'GALLERY_CROPS_PER_DAY',
          'GALLERY_FILENAME_CONTAINS', 'GALLERY_PRINT_MODE'}


@dataclass(frozen=True)
class GalleryOptions:
    enabled: bool = False
    subject: str = 'redlines'
    sender: str = ''
    days: int = 90
    max_mb: int = 2048
    crops_per_day: int = 0  # zero: use observed imports/day, clearly marked as an estimate

    filename: str = ''
    print_mode: str = 'gallery-only'

    def matches(self, subject, sender):
        """Envelope candidate; a filename-only rule still needs MIME inspection."""
        return (self.enabled and bool(self.subject.strip() or self.filename.strip())
                and self.subject.casefold() in subject.casefold()
                and self.sender.casefold() in sender.casefold())

    def matches_pdf(self, subject, sender, filename):
        return (self.matches(subject, sender) and filename.lower().endswith('.pdf')
                and self.filename.casefold() in filename.casefold())

    def apply(self, patch):
        values = {}
        for key, value in patch.items():
            if key == 'GALLERY_ENABLED':
                if value not in ('0', '1'):
                    raise ValueError('Invalid gallery switch')
                values['enabled'] = value == '1'
            elif key == 'GALLERY_PRINT_MODE':
                if value not in ('gallery-only', 'also-print'):
                    raise ValueError('Choose Gallery only or Also use normal print rules.')
                values['print_mode'] = value
            elif key in ('GALLERY_SUBJECT_CONTAINS', 'GALLERY_FROM_CONTAINS', 'GALLERY_FILENAME_CONTAINS'):
                attr = {'GALLERY_SUBJECT_CONTAINS': 'subject', 'GALLERY_FROM_CONTAINS': 'sender',
                        'GALLERY_FILENAME_CONTAINS': 'filename'}[key]
                values[attr] = value.strip()
            elif key in FIELDS:
                attr, low, high = {'GALLERY_KEEP_DAYS': ('days', 1, 3650),
                    'GALLERY_MAX_MB': ('max_mb', 64, 1048576),
                    'GALLERY_CROPS_PER_DAY': ('crops_per_day', 0, 100000)}[key]
                if not value.isascii() or not value.isdecimal() or not low <= int(value) <= high:
                    raise ValueError(f'{key} must be between {low} and {high}.')
                values[attr] = int(value)
            else:
                raise ValueError('Unsupported gallery setting')
        result = replace(self, **values)
        if result.enabled and not (result.subject or result.filename):
            raise ValueError('Set a gallery subject or PDF filename keyword before enabling imports.')
        return result

    def environment(self):
        return dict(GALLERY_ENABLED=str(int(self.enabled)), GALLERY_SUBJECT_CONTAINS=self.subject,
                    GALLERY_FROM_CONTAINS=self.sender, GALLERY_FILENAME_CONTAINS=self.filename,
                    GALLERY_PRINT_MODE=self.print_mode, GALLERY_KEEP_DAYS=str(self.days),
                    GALLERY_MAX_MB=str(self.max_mb), GALLERY_CROPS_PER_DAY=str(self.crops_per_day))


def search_expression(query):
    # Literal words/phrases only: never expose FTS operators or SQL to browser input.
    words = re.findall(r'"([^"\n]+)"|(\w+)', query[:300], flags=re.UNICODE)
    return ' AND '.join('"' + (phrase or word).replace('"', '""') + '"' + ('' if phrase else '*')
                        for phrase, word in words[:20])


def checked_date(value):
    parsed = date.fromisoformat(value)
    if parsed.year < 2000 or parsed.year > 2100:
        raise ValueError('Use the printed document date (2000–2100).')
    return parsed.isoformat()


def checked_date_filter(value):
    """Browsing only: empty means all dates; undated is never today's date."""
    if value in ('', 'undated'):
        return value
    if not isinstance(value, str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}', value):
        raise ValueError('Choose a date in YYYY-MM-DD format.')
    return checked_date(value)


def checked_lead_name(value):
    """Literal, user-confirmable name; never infer identity from notes or filenames."""
    if not isinstance(value, str) or len(value) > 160 or any(not c.isprintable() for c in value):
        raise ValueError('Use a single-line lead name of at most 160 characters.')
    return ' '.join(value.split())


def lead_key(value):
    value = unicodedata.normalize('NFKC', checked_lead_name(value))
    value = value.translate(str.maketrans({'’': "'", '‘': "'", '‐': '-', '‑': '-'}))
    return ' '.join(value.casefold().split())


ADDRESS_BOUNDARY = (
    r'(?=\s*(?:\||\n)|\s+(?:Phone|Power\s+Questions|Scheduled\s+Start|'
    r'Assigned\s+Service\s+Resource|Set\s+By|Work\s+Type|Product\s+Interest|'
    r'Source|Sub\s+Source|Hover\s*/\s*Flir|Lead\s+Description|Start\s+Price|'
    r'Final\s+Price|Deposit\s*/\s*Payment)\s*:?[ \t]*|$)'
)


def printed_address(text):
    """Read the explicit Address field from normalized OCR text."""
    readings = []
    for match in re.finditer(r'\bAddress\s*[:;]?[ \t]*([^\n|]+?)' + ADDRESS_BOUNDARY,
                             str(text or ''), re.I):
        value = ' '.join(match[1].split())
        if not value or len(value) > 240 or not any(c.isalnum() for c in value):
            continue
        readings.append(value)
    if not readings:
        return ''
    keys = {address_key(value) for value in readings}
    return readings[0] if len(keys) == 1 else ''


def address_key(value):
    """Case/punctuation/spacing normalization only; no address synonym expansion."""
    value = unicodedata.normalize('NFKC', str(value or '')).casefold()
    return ' '.join(re.findall(r'[a-z0-9]+', value))


def related_name_key(value):
    """Letters-only identity key for Related; ignore digits, punctuation and symbols."""
    value = unicodedata.normalize('NFKD', lead_key(value)).casefold()
    return ''.join(c for c in value if unicodedata.category(c).startswith('L'))


def _within_one_character(left, right):
    """True only for exact equality or one insertion/deletion/substitution."""
    if not left or not right:
        return False
    if left == right:
        return True
    if abs(len(left) - len(right)) > 1:
        return False
    if len(left) > len(right):
        left, right = right, left
    if len(left) == len(right):
        return sum(a != b for a, b in zip(left, right)) <= 1
    # right is exactly one character longer.
    i = j = differences = 0
    while i < len(left) and j < len(right):
        if left[i] == right[j]:
            i += 1
            j += 1
            continue
        differences += 1
        if differences > 1:
            return False
        j += 1
    return True


def related_identity(reference_name, reference_address, candidate_name, candidate_address):
    """Related when name letters differ by <=1 OR normalized address is exactly equal."""
    reference_name = related_name_key(reference_name)
    candidate_name = related_name_key(candidate_name)
    reference_address = address_key(reference_address)
    candidate_address = address_key(candidate_address)
    name_match = _within_one_character(reference_name, candidate_name)
    address_match = bool(reference_address) and reference_address == candidate_address
    return name_match or address_match


def printed_lead(text):
    """Read explicit labels in saved OCR, including legacy flattened TSV text.

    Do not derive a name from filenames, notes or assigned representatives.
    Multiple different Lead Name headers indicate a bad combined crop, not one
    person's identity. Names may contain digits and printable symbols; the next
    known field label, especially Address, owns the boundary instead of a symbol
    whitelist. No interactive name prompt is needed for readable headers.
    """
    names = []
    boundary = (r'(?=\s*(?:\||\n)|\s+Address\b|\s+(?:Phone|Power\s+Questions|Scheduled\s+Start|'
                r'Local\s+Scheduled\s+Start\s+Time|Canvass\s+Set\s+By)\s*:|$)')
    for match in re.finditer(r'\bLead\s+Name\s*[:;]\s*([^\n|]+?)' + boundary, text, re.I):
        value = ' '.join(match[1].split())
        if not value or len(value) > 160 or not any(c.isalnum() for c in value):
            return ''
        if any(not c.isprintable() for c in value):
            return ''
        names.append(value)
    return names[0] if names and len({lead_key(n) for n in names}) == 1 else ''
