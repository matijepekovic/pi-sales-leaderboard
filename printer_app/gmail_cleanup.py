"""Gmail IMAP retention adapter. Never expunge an entire folder or thread.

Gmail special-use LIST / X-GM-MSGID: developers.google.com/workspace/gmail/imap/imap-extensions
UID MOVE and targeted UID EXPUNGE: RFC 6851 / RFC 4315.
"""
from datetime import datetime, timedelta, timezone
from email import policy
from email.parser import BytesParser
import imaplib
import re
import ssl

from .gmail_client import header, message_identity, sexpr
from .retention_policy import ExpiredEmail

MONTHS = 'Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec'.split()


def quoted(value):
    if not value or any(c in value for c in '\r\n\x00'):
        raise ValueError('Invalid mailbox name')
    return '"' + value.replace('\\', '\\\\').replace('"', '\\"') + '"'


def internal_timestamp(value):
    match = re.fullmatch(r' ?(\d{1,2})-([A-Za-z]{3})-(\d{4}) (\d{2}):(\d{2}):(\d{2}) ([+-])(\d{2})(\d{2})', value)
    if not match:
        raise ValueError('Missing or invalid server receipt timestamp')
    day, month, year, hour, minute, second, sign, oh, om = match.groups()
    offset = timedelta(hours=int(oh), minutes=int(om)) * (1 if sign == '+' else -1)
    return datetime(int(year), MONTHS.index(month.title()) + 1, int(day), int(hour),
                    int(minute), int(second), tzinfo=timezone(offset)).timestamp()


class GmailCleanup:
    def __init__(self, cfg, still_current):
        self.cfg, self.still_current = cfg, still_current
        self.client = None

    @staticmethod
    def ok(response):
        status, data = response
        if status != 'OK':
            raise OSError('Gmail retention command failed')
        return data or []

    def __enter__(self):
        if not self.cfg.retention.mail_allowed(self.cfg.email_user, self.cfg.mailbox):
            raise ValueError('Inbox deletion has not been enabled for this account and mailbox')
        self.client = imaplib.IMAP4_SSL('imap.gmail.com', 993,
            ssl_context=ssl.create_default_context(), timeout=30)
        try:
            self.ok(self.client.login(self.cfg.email_user, self.cfg.email_password))
            caps = b' '.join(self.ok(self.client.capability())).upper().split()
            if not {b'UIDPLUS', b'MOVE', b'X-GM-EXT-1'}.issubset(caps):
                raise OSError('Gmail does not advertise safe targeted deletion capabilities')
            trash, sources = [], []
            for row in self.ok(self.client.list()):
                raw = b''.join(row) if isinstance(row, tuple) else row
                fields = sexpr(b'(' + raw + b')')
                if len(fields) != 3 or not isinstance(fields[0], list) or not isinstance(fields[2], str):
                    raise ValueError('Unrecognized mailbox list; refusing cleanup')
                flags, _, name = fields
                flags = {str(f).lower() for f in flags}
                if '\\trash' in flags:
                    trash.append(name)
                if name == self.cfg.mailbox or name.upper() == self.cfg.mailbox.upper() == 'INBOX':
                    sources.append(name)
                    if flags & {'\\all', '\\trash', '\\junk', '\\sent', '\\drafts', '\\noselect'}:
                        raise ValueError('Cleanup source must be the inbox or an explicitly selected report label')
            if len(sources) != 1:
                raise ValueError('Configured cleanup mailbox was not unambiguously listed')
            if len(trash) != 1 or trash[0] == self.cfg.mailbox:
                raise ValueError('Could not identify a unique Gmail Trash mailbox safely')
            self.trash = trash[0]
            return self
        except Exception:
            self.__exit__(None, None, None)
            raise

    def __exit__(self, *args):
        if self.client is not None:
            try:
                self.client.logout()  # Never CLOSE: it can expunge unrelated mail.
            except (OSError, imaplib.IMAP4.error):
                pass

    def select(self, mailbox, readonly=True):
        self.ok(self.client.select(quoted(mailbox), readonly=readonly))
        values = self.client.response('UIDVALIDITY')[1] or []
        if len(values) != 1 or not isinstance(values[0], bytes) or not values[0].isdigit():
            raise ValueError('Mailbox identity unavailable; refusing deletion')
        return values[0].decode('ascii')

    def search(self, *criteria):
        data = self.ok(self.client.uid('SEARCH', None, *criteria))
        uids = b' '.join(p for p in data if isinstance(p, bytes)).split()
        if any(not u.isdigit() or int(u) < 1 for u in uids):
            raise ValueError('Invalid message identifiers')
        return [u.decode('ascii') for u in uids]

    def metadata(self, uids, validity):
        wanted = set(uids)
        # Fetch server metadata separately from user-authored MIME headers. This
        # avoids attribute-order/literal ambiguity and spoofed dates in headers.
        data = self.ok(self.client.uid('FETCH', ','.join(uids), '(UID INTERNALDATE X-GM-MSGID)'))
        result = []
        for meta in data:
            if meta is None:
                continue
            if not isinstance(meta, bytes):
                raise ValueError('Unexpected retention metadata')
            uid = re.search(rb'\bUID (\d+)\b', meta, re.I)
            key = re.search(rb'\bX-GM-MSGID (\d+)\b', meta, re.I)
            date = re.search(rb'\bINTERNALDATE "([^"]+)"', meta, re.I)
            if not uid or uid[1].decode() not in wanted:
                continue
            if not key or not date:
                raise ValueError('Incomplete retention metadata; message not deleted')
            result.append((uid[1].decode(), ExpiredEmail(key[1].decode(),
                           internal_timestamp(date[1].decode('ascii')), '')))
        return result

    def local_identity(self, uid, validity):
        data = self.ok(self.client.uid('FETCH', uid, '(BODY.PEEK[HEADER.FIELDS (MESSAGE-ID)])'))
        body = b''.join(row[1] for row in data if isinstance(row, tuple) and isinstance(row[1], bytes))
        if len(body) > 65536:
            raise ValueError('Retention header exceeds size limit')
        msg = BytesParser(policy=policy.default).parsebytes(body)
        return message_identity(self.cfg.email_user, self.cfg.mailbox, validity, uid, header(msg['Message-ID']))

    def expired(self, cutoff, limit=100):
        validity = self.select(self.cfg.mailbox)
        # BEFORE has day precision and uses the server's INTERNALDATE date.
        # Include the boundary day (+ offset slack), then check actual seconds.
        upper = datetime.fromtimestamp(cutoff, timezone.utc) + timedelta(days=2)
        date = f'{upper.day:02d}-{MONTHS[upper.month-1]}-{upper.year}'
        uids = self.search('BEFORE', date)
        result = []
        for offset in range(0, len(uids), 100):
            if not self.still_current():
                break
            for uid, email in self.metadata(uids[offset:offset+100], validity):
                if email.received_at < cutoff:
                    result.append(ExpiredEmail(email.key, email.received_at, self.local_identity(uid, validity)))
                    if len(result) == limit:
                        return result
        return result

    def find(self, key, validity, cutoff):
        if not re.fullmatch(r'[0-9]{1,20}', key):
            raise ValueError('Invalid remote deletion identity')
        uids = self.search('X-GM-MSGID', key)
        if not uids:
            return None
        records = self.metadata(uids, validity)
        if len(records) != 1 or records[0][1].key != key:
            raise ValueError('Ambiguous remote deletion identity')
        if records[0][1].received_at >= cutoff:
            raise ValueError('Message no longer satisfies the retention cutoff')
        return records[0][0]

    def check_current(self):
        if not self.still_current():
            raise OSError('Cleanup settings changed; no further deletion')

    def delete(self, email, cutoff):
        self.check_current()
        validity = self.select(self.cfg.mailbox, readonly=False)
        uid = self.find(email.key, validity, cutoff)
        if uid:
            self.check_current()
            self.ok(self.client.uid('MOVE', uid, quoted(self.trash)))
        # If interrupted after MOVE, retry by the same stable identity in Trash.
        # A message archived elsewhere is not sought out or deleted.
        validity = self.select(self.trash, readonly=False)
        uid = self.find(email.key, validity, cutoff)
        if not uid:
            return False
        self.check_current()
        self.ok(self.client.uid('STORE', uid, '+FLAGS.SILENT', '(\\Deleted)'))
        self.ok(self.client.uid('EXPUNGE', uid))
        if self.search('X-GM-MSGID', email.key):
            raise OSError('Gmail did not confirm deletion; receipt kept for retry')
        return True
