"""Gallery settings and normalized search/date rules, without IO or vendor data."""
from dataclasses import dataclass, replace
from datetime import date
from difflib import SequenceMatcher
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
    r'Final\s+Price|Deposit\s*/\s*Payment)\s*:|$)'
)


def printed_address(text):
    """Read the explicit Address field from normalized OCR text."""
    readings = []
    for match in re.finditer(r'\bAddress\s*[:;]\s*([^\n|]+?)' + ADDRESS_BOUNDARY,
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
    value = unicodedata.normalize('NFKC', str(value or '')).casefold()
    tokens = re.findall(r'[a-z0-9]+', value)
    aliases = {
        'street':'st','avenue':'ave','road':'rd','boulevard':'blvd','drive':'dr',
        'lane':'ln','court':'ct','place':'pl','highway':'hwy','parkway':'pkwy',
        'north':'n','south':'s','east':'e','west':'w','northeast':'ne',
        'northwest':'nw','southeast':'se','southwest':'sw',
    }
    return ' '.join(aliases.get(token, token) for token in tokens)


def _fuzzy_identity(left, right, threshold):
    if not left or not right:
        return False
    if left == right:
        return True
    if min(len(left), len(right)) < 4:
        return False
    if SequenceMatcher(None, left, right).ratio() >= threshold:
        return True
    a, b = set(left.split()), set(right.split())
    common = a & b
    return len(common) >= 2 and len(common) / max(1, min(len(a), len(b))) >= .8


def related_identity(reference_name, reference_address, candidate_name, candidate_address):
    """Related if either normalized name or address is a close match."""
    name_match = _fuzzy_identity(lead_key(reference_name), lead_key(candidate_name), .80)
    address_match = _fuzzy_identity(address_key(reference_address), address_key(candidate_address), .72)
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
