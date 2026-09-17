"""Gallery settings and normalized search/date rules, without IO or vendor data."""
from dataclasses import dataclass, replace
from datetime import date
import re

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
