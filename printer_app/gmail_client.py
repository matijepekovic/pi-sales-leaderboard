"""Replaceable IMAP adapter. Read-only inbox access; never changes flags or deletes mail."""
from datetime import datetime, timedelta
from email import policy
from email.parser import BytesParser
import hashlib
import imaplib
import logging
from pathlib import Path
import ssl
import tempfile
from .contracts import Attachment, Message
from .files import check_disk, store_attachment

log = logging.getLogger(__name__)
CHUNK = 1024 * 1024


def literal(response):
    return b''.join(part[1] for part in response if isinstance(part, tuple) and isinstance(part[1], bytes))


def fetch(client, uid, fields):
    status, data = client.uid('fetch', uid, fields)
    if status != 'OK':
        raise RuntimeError('IMAP download failed; the message will be retried')
    return literal(data)


class GmailClient:
    def __init__(self, config, factory=imaplib.IMAP4_SSL):
        self.config = config
        self.factory = factory

    def messages(self, already_seen):
        cfg = self.config
        if not cfg.email_user or not cfg.email_password:
            raise RuntimeError('Gmail credentials are not configured')
        scope = hashlib.sha256((cfg.email_user.casefold() + '\0' + cfg.mailbox).encode()).hexdigest()
        client = self.factory('imap.gmail.com', 993, ssl_context=ssl.create_default_context(), timeout=30)
        try:
            client.login(cfg.email_user, cfg.email_password)
            mailbox = '"' + cfg.mailbox.replace('\\', '\\\\').replace('"', '\\"') + '"'
            status, _ = client.select(mailbox, readonly=True)
            if status != 'OK':
                raise RuntimeError('Configured mailbox could not be opened')
            _, validity_data = client.response('UIDVALIDITY')
            if not validity_data or not validity_data[0]:
                raise RuntimeError('IMAP did not supply UIDVALIDITY; refusing unsafe deduplication')
            validity = validity_data[0].decode('ascii')
            since = datetime.now().astimezone() - timedelta(days=cfg.lookback_days)
            month = ('Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec')[since.month - 1]
            status, ids = client.uid('search', None, 'SINCE', f'{since.day:02d}-{month}-{since.year}')
            if status != 'OK':
                raise RuntimeError('IMAP search failed')
            for uid_bytes in (ids[0] or b'').split():
                uid = uid_bytes.decode('ascii')
                source_key = f'{scope}:{validity}:{uid}'
                if already_seen(source_key):
                    continue
                headers = BytesParser(policy=policy.default).parsebytes(fetch(client, uid, '(BODY.PEEK[HEADER.FIELDS (SUBJECT FROM MESSAGE-ID)])'))
                subject, sender = str(headers.get('Subject', '')), str(headers.get('From', ''))
                if cfg.subject_contains.casefold() not in subject.casefold() or cfg.from_contains.casefold() not in sender.casefold():
                    continue
                log.info('Email detected uid=%s', uid)
                check_disk(cfg.data_dir, cfg.disk_reserve_mb)
                work = cfg.data_dir / 'work'
                work.mkdir(parents=True, exist_ok=True, mode=0o700)
                # No attachment-size rejection. Even oversized messages are downloaded in chunks.
                with tempfile.TemporaryFile(dir=work) as raw:
                    offset = 0
                    while True:
                        check_disk(cfg.data_dir, cfg.disk_reserve_mb)
                        chunk = fetch(client, uid, f'(BODY.PEEK[]<{offset}.{CHUNK}>)')
                        raw.write(chunk)
                        offset += len(chunk)
                        if len(chunk) < CHUNK:
                            break
                    raw.seek(0)
                    message = BytesParser(policy=policy.default).parse(raw)
                attachments = []
                for index, part in enumerate(message.walk()):
                    if part.is_multipart():
                        continue
                    filename = part.get_filename()
                    if filename is None and part.get_content_disposition() != 'attachment':
                        continue
                    filename = filename or f'attachment-{index}'
                    payload = part.get_payload(decode=True) or b''
                    if len(payload) > cfg.attachment_warn_mb * 1024 * 1024:
                        log.warning('Downloading oversized attachment uid=%s bytes=%d (warning only)', uid, len(payload))
                    check_disk(cfg.data_dir, cfg.disk_reserve_mb)
                    path, digest = store_attachment(cfg.data_dir, source_key, index, filename, payload)
                    attachments.append(Attachment(filename, path, digest, len(payload)))
                    log.info('Attachment downloaded uid=%s bytes=%d sha256=%s', uid, len(payload), digest)
                yield Message(source_key, scope, uid, validity, str(headers.get('Message-ID', '')).strip(), subject, sender, tuple(attachments))
        finally:
            try:
                client.logout()
            except Exception:
                pass
