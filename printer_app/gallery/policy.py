"""Gallery settings and normalized search/date rules, without IO or vendor data."""
from dataclasses import dataclass, replace
from datetime import date
import re
import unicodedata

FIELDS = {'GALLERY_ENABLED', 'GALLERY_SUBJECT_CONTAINS', 'GALLERY_FROM_CONTAINS',
          'GALLERY_KEEP_DAYS', 'GALLERY_MAX_MB', 'GALLERY_CROPS_PER_DAY'}


@dataclass(frozen=True)
class GalleryOptions:
    enabled: bool = False
    subject: str = 'redlines'
    sender: str = ''
    days: int = 90
    max_mb: int = 2048
    crops_per_day: int = 0  # zero: use observed imports/day, clearly marked as an estimate

    def matches(self, subject, sender):
        return self.enabled and bool(self.subject.strip()) and self.subject.casefold() in subject.casefold() and self.sender.casefold() in sender.casefold()

    def apply(self, patch):
        values = {}
        for key, value in patch.items():
            if key == 'GALLERY_ENABLED':
                if value not in ('0', '1'):
                    raise ValueError('Invalid gallery switch')
                values['enabled'] = value == '1'
            elif key in ('GALLERY_SUBJECT_CONTAINS', 'GALLERY_FROM_CONTAINS'):
                values['subject' if key == 'GALLERY_SUBJECT_CONTAINS' else 'sender'] = value.strip()
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
        if result.enabled and not result.subject:
            raise ValueError('Set a gallery subject keyword before enabling imports.')
        return result

    def environment(self):
        return dict(GALLERY_ENABLED=str(int(self.enabled)), GALLERY_SUBJECT_CONTAINS=self.subject,
                    GALLERY_FROM_CONTAINS=self.sender, GALLERY_KEEP_DAYS=str(self.days),
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


def checked_lead_name(value):
    """Literal, user-confirmable name; never infer identity from notes or filenames."""
    if not isinstance(value, str) or len(value) > 160 or any(not c.isprintable() for c in value):
        raise ValueError('Use a single-line lead name of at most 160 characters.')
    return ' '.join(value.split())


def lead_key(value):
    value = unicodedata.normalize('NFKC', checked_lead_name(value))
    value = value.translate(str.maketrans({'’': "'", '‘': "'", '‐': '-', '‑': '-'}))
    return ' '.join(value.casefold().split())


def printed_lead(text):
    """Index an explicit Lead Name header in existing OCR, never OCR/crop here.

    Full-text search still covers every printed word. Related lookup uses only
    this field so reps, notes and partial-name matches cannot mix unrelated cards.
    Ambiguous or absent names remain empty and can be corrected in card details.
    """
    names = []
    for line in text.splitlines():
        match = re.match(r'^[\s|]*Lead\s+Name\s*[:;]\s*(.+)$', line, re.I)
        if not match:
            continue
        value = re.split(r'\s+(?:Address|Phone|Power\s+Questions|Scheduled\s+Start|'
                         r'Local\s+Scheduled\s+Start\s+Time|Canvass\s+Set\s+By)\s*:',
                         match[1], maxsplit=1, flags=re.I)[0]
        value = value.split('|', 1)[0].strip()
        if not value or len(value) > 160 or not any(c.isalpha() for c in value):
            return ''
        if any(not (c.isalpha() or c.isspace() or c in ".'’‘‐‑-,") for c in value):
            return ''
        names.append(' '.join(value.split()))
    return names[0] if names and len({lead_key(n) for n in names}) == 1 else ''
