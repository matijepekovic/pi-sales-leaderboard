"""Read-only Gmail IMAP. Download attachments individually without a size rejection."""
from __future__ import annotations

import base64
import hashlib
import imaplib
import logging
import quopri
import re
import ssl
import time
from datetime import datetime, timedelta, timezone
from email import policy
from email.header import decode_header, make_header
from email.message import Message
from email.parser import BytesParser
from pathlib import Path

from .config import Config, clean_text, safe_name
from .db import Database
from .retention_repository import RetentionRepository

log = logging.getLogger(__name__)


def header(value) -> str:
    try:
        return clean_text(str(make_header(decode_header(str(value or '')))), 2000)
    except (LookupError, UnicodeError):
        return clean_text(value or '', 2000)


def message_identity(account, mailbox, validity, uid, message_id):
    source = message_id or f'{mailbox}:{validity}:{uid}'
    return hashlib.sha256((account.casefold() + '\0' + source).encode()).hexdigest()


def sexpr(data: bytes):
    """Parse IMAP BODYSTRUCTURE, including quoted strings and RFC literals."""
    if len(data) > 1024 * 1024:
        raise ValueError('MIME STRUCTURE EXCEEDS SIZE LIMIT')
    index, nodes = 0, 0

    def read(depth=0):
        nonlocal index, nodes
        nodes += 1
        if depth > 40 or nodes > 20000:
            raise ValueError('MIME STRUCTURE TOO COMPLEX')
        while index < len(data) and data[index:index+1].isspace():
            index += 1
        if index >= len(data):
            raise ValueError('INCOMPLETE MIME STRUCTURE')
        c = data[index:index+1]
        if c == b'(':
            index += 1
            result = []
            while True:
                while index < len(data) and data[index:index+1].isspace():
                    index += 1
                if data[index:index+1] == b')':
                    index += 1
                    return result
                result.append(read(depth + 1))
        if c == b'"':
            index += 1
            result = bytearray()
            while index < len(data):
                c = data[index:index+1]
                index += 1
                if c == b'"':
                    return result.decode('utf-8', 'replace')
                if c == b'\\' and index < len(data):
                    c = data[index:index+1]
                    index += 1
                result.extend(c)
            raise ValueError('UNTERMINATED MIME STRING')
        if c == b'{':
            match = re.match(rb'\{(\d+)\}\r?\n', data[index:])
            if not match:
                raise ValueError('INVALID MIME LITERAL')
            index += match.end()
            size = int(match.group(1))
            if size > len(data) - index:
                raise ValueError('INCOMPLETE MIME LITERAL')
            value = data[index:index+size]
            index += size
            return value.decode('utf-8', 'replace')
        start = index
        while index < len(data) and not data[index:index+1].isspace() and data[index:index+1] not in (b'(', b')'):
            index += 1
        if index == start:
            raise ValueError('INVALID MIME ATOM')
        value = data[start:index].decode('ascii', 'replace')
        return None if value.upper() == 'NIL' else value
    return read()


def pairs(value) -> dict:
    if not isinstance(value, list):
        return {}
    return {str(value[i]).lower(): str(value[i+1] or '') for i in range(0, len(value)-1, 2)}


def attachment_parts(tree, prefix='', *, related_resource=False):
    """Select report attachments, not images used to display the email body.

    RFC 2387 related parts belong to one compound body, even when a resource
    carries an ATTACHMENT disposition. Keep its root; skip only image resources.
    No filename, image dimensions, or size heuristics identify a signature.
    """
    if not isinstance(tree, list) or not tree:
        raise ValueError('INVALID MIME STRUCTURE')
    if isinstance(tree[0], list):
        count = next((i for i, part in enumerate(tree) if not isinstance(part, list)), len(tree))
        related = count < len(tree) and str(tree[count]).upper() == 'RELATED'
        root = 0  # RFC 2387: first part unless the start parameter says otherwise.
        if related and len(tree) > count + 1:
            start = pairs(tree[count + 1]).get('start')
            if start:
                roots = [i for i, part in enumerate(tree[:count])
                         if len(part) > 3 and not isinstance(part[0], list)
                         and str(part[3] or '').strip() == start.strip()]
                # A missing/ambiguous root is not evidence for discarding images.
                root = roots[0] if len(roots) == 1 else None
        for index, child in enumerate(tree[:count]):
            section = f'{prefix}.{index + 1}' if prefix else str(index + 1)
            resource = related_resource or (related and root is not None and index != root)
            yield from attachment_parts(child, section, related_resource=resource)
        return
    if len(tree) < 7:
        raise ValueError('INCOMPLETE MIME BODY')
    major, minor = str(tree[0]).upper(), str(tree[1]).upper()
    disposition_index = 9 if major == 'TEXT' else 11 if (major, minor) == ('MESSAGE', 'RFC822') else 8
    disposition = tree[disposition_index] if len(tree) > disposition_index else None
    m = Message(policy=policy.default)
    m['Content-Type'] = f'{major}/{minor}'
    for k, v in pairs(tree[2]).items():
        m.set_param(k, v)
    if isinstance(disposition, list) and disposition:
        m['Content-Disposition'] = str(disposition[0])
        for k, v in pairs(disposition[1] if len(disposition) > 1 else None).items():
            m.set_param(k, v, header='Content-Disposition')
    filename = m.get_filename()
    if major == 'IMAGE' and (m.get_content_disposition() == 'inline' or related_resource):
        # Filter at the IMAP boundary, before downloading or creating queue/jobs.
        # Standalone image attachments still follow the unsupported-file policy.
        log.info('Skipped embedded email image: part=%s filename=%r',
                 prefix or '1', safe_name(header(filename)) if filename else '(unnamed)')
        return
    if filename or m.get_content_disposition() == 'attachment' or major == 'MESSAGE':
        section = prefix or '1'
        yield {'part': section, 'filename': safe_name(header(filename) or f'attachment-{section}'),
               'encoding': str(tree[5] or '').upper(), 'size': int(tree[6] or 0)}


class GmailClient:
    def __init__(self, cfg: Config, db: Database, stop=None):
        self.cfg, self.db, self.stop = cfg, db, stop

    def _fetch(self, client, uid: str, query: str):
        status, result = client.uid('fetch', uid, query)
        if status != 'OK' or not result or result == [None]:
            raise OSError('IMAP FETCH FAILED')
        return result

    @staticmethod
    def _literal(result) -> bytes:
        return b''.join(item[1] for item in result if isinstance(item, tuple) and isinstance(item[1], bytes))

    def _store(self, message: int, part: str, filename: str, payload: bytes = b'', error: str = '') -> None:
        row = self.db.one('SELECT * FROM attachments WHERE message_id=? AND part=?', (message, part))
        if row and row['state'] != 'DOWNLOADING':
            return
        if not row:
            self.db.execute('''INSERT OR IGNORE INTO attachments(message_id,part,filename,state,created)
              VALUES (?,?,?,'DOWNLOADING',?)''', (message, part, filename, time.time()))
            row = self.db.one('SELECT * FROM attachments WHERE message_id=? AND part=?', (message, part))
        directory = self.cfg.data_dir / 'attachments' / str(row['id'])
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        target = directory / safe_name(filename)
        if not error:
            temporary = target.with_name(target.name + '.partial')
            with temporary.open('wb') as stream:
                stream.write(payload)
                stream.flush()
                import os
                os.fsync(stream.fileno())
            temporary.replace(target)
        self.db.execute('''UPDATE attachments SET path=?,sha256=?,error=?,state='PENDING' WHERE id=?''',
            (str(target) if not error else '', hashlib.sha256(payload).hexdigest() if not error else '', error, row['id']))
        log.info('Attachment stored: id=%s filename=%r bytes=%s error=%r', row['id'], filename, len(payload), error)

    def poll(self) -> int:
        cfg = self.cfg
        if not cfg.email_user or not cfg.email_password:
            self.db.set('gmail_state', 'NOT CONFIGURED')
            return 0
        count = 0
        # One connection per bounded poll; socket timeout keeps network outages recoverable.
        with imaplib.IMAP4_SSL('imap.gmail.com', 993, ssl_context=ssl.create_default_context(), timeout=30) as client:
            client.login(cfg.email_user, cfg.email_password)
            if client.select('"' + cfg.mailbox.replace('\\', '\\\\').replace('"', '\\"') + '"', readonly=True)[0] != 'OK':
                raise OSError('IMAP MAILBOX SELECTION FAILED')
            uidvalidity = (client.response('UIDVALIDITY')[1] or [b''])[0]
            validity = uidvalidity.decode() if isinstance(uidvalidity, bytes) else str(uidvalidity)
            if not validity or not validity.isdigit():
                raise OSError('IMAP UIDVALIDITY MISSING')
            since = datetime.now(timezone.utc) - timedelta(days=cfg.lookback_days)
            months = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec']
            date = f'{since.day:02d}-{months[since.month-1]}-{since.year}'
            status, result = client.uid('search', None, 'SINCE', date)
            if status != 'OK':
                raise OSError('IMAP SEARCH FAILED')
            pending = self.db.rows('''SELECT uid FROM processed_messages WHERE account=? AND mailbox=?
                AND uidvalidity=? AND state='FETCHING' ''', (cfg.email_user, cfg.mailbox, validity))
            uids = {item.decode() for item in (result[0] or b'').split()} | {r['uid'] for r in pending}
            examined = 0
            for uid in sorted(uids, key=int):
                if self.stop is not None and self.stop.is_set():
                    return count
                known = self.db.one('''SELECT state FROM processed_messages WHERE account=? AND mailbox=?
                  AND uidvalidity=? AND uid=?''', (cfg.email_user, cfg.mailbox, validity, uid))
                if known and known['state'] == 'COMPLETE':
                    continue
                # Bound new-message work, not already-completed messages.
                if examined >= 100:
                    break
                raw_header = self._literal(self._fetch(client, uid, '(BODY.PEEK[HEADER.FIELDS (SUBJECT FROM MESSAGE-ID)])'))
                if len(raw_header) > 65536:
                    raise ValueError('EMAIL HEADER EXCEEDS SIZE LIMIT')
                msg = BytesParser(policy=policy.default).parsebytes(raw_header)
                subject, sender, message_id = header(msg['Subject']), header(msg['From']), header(msg['Message-ID'])
                identity = message_identity(cfg.email_user, cfg.mailbox, validity, uid, message_id)
                if RetentionRepository(self.db).seen(identity):
                    continue  # Expired history must not turn into another print.
                qualifies = cfg.subject_contains.casefold() in subject.casefold() and cfg.from_contains.casefold() in sender.casefold()
                self.db.execute('''INSERT OR IGNORE INTO processed_messages
                    (identity,account,mailbox,uidvalidity,uid,message_id,subject,sender,state,created)
                    VALUES (?,?,?,?,?,?,?,?,?,?)''',
                    (identity, cfg.email_user, cfg.mailbox, validity, uid, message_id, subject, sender,
                     'FETCHING' if qualifies else 'COMPLETE', time.time()))
                record = self.db.one('SELECT * FROM processed_messages WHERE identity=?', (identity,))
                if record['state'] == 'COMPLETE':
                    continue
                examined += 1
                log.info('Email detected: uid=%s subject=%r', uid, subject)
                try:
                    result = self._fetch(client, uid, '(BODYSTRUCTURE)')
                    raw = b' '.join(b''.join(item) if isinstance(item, tuple) else item for item in result if item)
                    match = re.search(rb'BODYSTRUCTURE\s+', raw, re.I)
                    if not match:
                        raise ValueError('EMAIL MIME STRUCTURE MISSING')
                    parts = list(attachment_parts(sexpr(raw[match.end():])))
                except ValueError as exc:
                    self._store(record['id'], 'mime-error', 'email-structure', error=clean_text(exc))
                    parts = []
                for part in parts:
                    if self.stop is not None and self.stop.is_set():
                        return count
                    saved = self.db.one('SELECT state FROM attachments WHERE message_id=? AND part=?', (record['id'], part['part']))
                    if saved and saved['state'] != 'DOWNLOADING':
                        continue
                    # Fetch the entire attachment, not a prefix capped by its size.
                    # MAX_ATTACHMENT_MB is retained as a warning threshold only.
                    result = self._fetch(client, uid, f'(BODY.PEEK[{part["part"]}])')
                    encoded = self._literal(result)
                    try:
                        if part['encoding'] == 'BASE64':
                            payload = base64.b64decode(re.sub(rb'\s+', b'', encoded), validate=True)
                        elif part['encoding'] == 'QUOTED-PRINTABLE':
                            payload = quopri.decodestring(encoded)
                        elif part['encoding'] in ('7BIT', '8BIT', 'BINARY', ''):
                            payload = encoded
                        else:
                            raise ValueError('UNSUPPORTED ATTACHMENT ENCODING')
                        if len(payload) > cfg.attachment_limit:
                            log.warning('Oversized attachment downloaded: uid=%s part=%s bytes=%s; continuing normally',
                                        uid, part['part'], len(payload))
                        self._store(record['id'], part['part'], part['filename'], payload)
                    except ValueError as exc:
                        self._store(record['id'], part['part'], part['filename'], error=clean_text(exc))
                self.db.execute("UPDATE processed_messages SET state='COMPLETE' WHERE id=?", (record['id'],))
                count += 1
            self.db.set('gmail_state', 'CONNECTED')
        return count


def test_connection(cfg: Config) -> tuple[bool, str]:
    """Check credentials and a read-only mailbox. Never search, fetch or print."""
    try:
        with imaplib.IMAP4_SSL('imap.gmail.com', 993,
                ssl_context=ssl.create_default_context(), timeout=10) as client:
            client.login(cfg.email_user, cfg.email_password)
            mailbox = '"' + cfg.mailbox.replace('\\', '\\\\').replace('"', '\\"') + '"'
            if client.select(mailbox, readonly=True)[0] != 'OK':
                return False, 'Gmail connected, but the mailbox could not be opened. Check its name.'
        return True, 'Connected to Gmail. Mailbox is accessible. Nothing was downloaded or printed.'
    except imaplib.IMAP4.error:
        return False, 'Gmail rejected the connection. Check the email address, Google app password, and mailbox.'
    except (OSError, TimeoutError):
        return False, 'Gmail could not be reached securely. Check the Pi network connection and try again.'
