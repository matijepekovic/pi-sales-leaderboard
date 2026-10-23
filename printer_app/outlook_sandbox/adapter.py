"""Read-only Exchange Online IMAP transport; no Gmail, CUPS, or queue dependency."""
from __future__ import annotations

from email import policy
from email.parser import BytesHeaderParser, BytesParser
import imaplib
import re
import ssl

from .repository import OutlookConfig, SandboxError

IMAP_HOST = 'outlook.office365.com'
IMAP_PORT = 993
MAX_STAGE_MESSAGE = 60 * 1024 * 1024
MAX_STAGE_ATTACHMENTS = 40


def _literal(response) -> bytes:
    return b''.join(item[1] for item in response or []
                    if isinstance(item, tuple) and isinstance(item[1], bytes))


def _imap_quote(value: str) -> str:
    return '"' + value.replace('\\', '\\\\').replace('"', '\\"') + '"'


class OutlookImapAdapter:
    """The only code in this feature that knows Microsoft's IMAP protocol."""

    def __init__(self, config: OutlookConfig, access_token: str):
        self.config = config
        self.access_token = access_token

    def _connect(self):
        client = imaplib.IMAP4_SSL(IMAP_HOST, IMAP_PORT,
                                   ssl_context=ssl.create_default_context(), timeout=25)
        try:
            auth = f'user={self.config.mailbox}\x01auth=Bearer {self.access_token}\x01\x01'.encode('utf-8')
            client.authenticate('XOAUTH2', lambda challenge: auth)
        except BaseException:
            client.logout()
            raise
        return client

    @staticmethod
    def _select(client, folder: str) -> str:
        if client.select(_imap_quote(folder), readonly=True)[0] != 'OK':
            raise SandboxError('Outlook folder could not be opened. Check the folder name.')
        values = client.response('UIDVALIDITY')[1] or []
        validity = values[0].decode('ascii', 'ignore') if values and values[0] else ''
        if not validity.isdecimal():
            raise SandboxError('Outlook did not provide a stable mailbox UID.')
        return validity

    @staticmethod
    def _uids(client) -> list[str]:
        status, rows = client.uid('search', None, 'ALL')
        if status != 'OK':
            raise SandboxError('Outlook could not list messages in this folder.')
        return [part.decode('ascii') for part in (rows[0] if rows else b'').split()
                if part.isdigit()]

    def folders(self) -> list[str]:
        with self._connect() as client:
            status, rows = client.list()
            if status != 'OK':
                raise SandboxError('Outlook could not list its folders.')
            names = []
            for row in rows or []:
                if not isinstance(row, bytes):
                    continue
                match = re.search(rb'"((?:\\.|[^"])*)"\s*$|([^\s]+)\s*$', row)
                if match:
                    value = match.group(1) if match.group(1) is not None else match.group(2)
                    name = re.sub(rb'\\(["\\])', rb'\1', value).decode('ascii', 'replace')
                    if name and name.upper() != 'NIL':
                        names.append(name)
            return sorted(set(names), key=str.casefold)

    def recent(self, limit: int = 12) -> dict:
        with self._connect() as client:
            validity = self._select(client, self.config.folder)
            rows = []
            for uid in reversed(self._uids(client)[-min(max(limit, 1), 20):]):
                status, data = client.uid('fetch', uid,
                    '(BODY.PEEK[HEADER.FIELDS (SUBJECT FROM DATE MESSAGE-ID)])')
                if status != 'OK':
                    raise SandboxError('Could not read Outlook message headers.')
                raw = _literal(data)
                if not raw:
                    continue
                head = BytesHeaderParser(policy=policy.default).parsebytes(raw)
                rows.append({
                    'uid': uid,
                    'subject': str(head.get('Subject', ''))[:250],
                    'sender': str(head.get('From', ''))[:250],
                    'date': str(head.get('Date', ''))[:100],
                })
            return {'folder': self.config.folder, 'uidvalidity': validity, 'messages': rows}

    def attachments(self, uid: str) -> tuple[str, list[tuple[str, bytes]]]:
        if not re.fullmatch(r'[0-9]{1,20}', uid):
            raise SandboxError('Invalid message ID.')
        with self._connect() as client:
            validity = self._select(client, self.config.folder)
            status, data = client.uid('fetch', uid, '(BODY.PEEK[])')
            if status != 'OK':
                raise SandboxError('Could not download the test message.')
            raw = _literal(data)
            if not raw:
                raise SandboxError('The test message no longer exists in this folder.')
            if len(raw) > MAX_STAGE_MESSAGE:
                raise SandboxError('Test message exceeds the sandbox 60 MB safety limit.')
            message = BytesParser(policy=policy.default).parsebytes(raw)
            attachments = []
            for part in message.walk():
                if part.is_multipart() or not part.get_filename():
                    continue
                content = part.get_payload(decode=True)
                if not isinstance(content, bytes):
                    continue
                attachments.append((str(part.get_filename()), content))
                if len(attachments) > MAX_STAGE_ATTACHMENTS:
                    raise SandboxError('Test email contains too many attachments.')
            if not attachments:
                raise SandboxError('No downloadable attachments were found in this email.')
            return validity, attachments
