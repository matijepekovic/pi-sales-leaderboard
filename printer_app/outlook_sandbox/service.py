"""Microsoft sign-in and sandbox-only email staging workflow."""
from __future__ import annotations

import imaplib
import threading
import time

import msal

from .adapter import OutlookImapAdapter
from .repository import OAuthRegistration, OutlookConfig, SandboxError, SandboxRepository

# MSAL adds openid/profile/offline_access automatically, including refresh-token support.
SCOPES = ['https://outlook.office.com/IMAP.AccessAsUser.All']


class OutlookSandboxService:
    """No production queue, background poller, deletion, or print API exists here."""

    def __init__(self, repository: SandboxRepository, adapter_type=OutlookImapAdapter):
        self.repository = repository
        self.adapter_type = adapter_type
        self._lock = threading.RLock()
        self._flow = None
        self._login = {'state': 'not_started'}

    def configuration(self) -> OutlookConfig | None:
        return self.repository.read_config()

    def configure(self, values: dict[str, str]) -> OutlookConfig:
        cfg = OutlookConfig.from_form(values)
        with self._lock:
            if cfg != self.configuration():
                if self._flow is not None:
                    self._flow['expires_at'] = 0
                    self._flow = None
                self.repository.save_config(cfg)
                self._login = {'state': 'not_started'}
        return cfg

    def disconnect(self) -> None:
        with self._lock:
            if self._flow is not None:
                self._flow['expires_at'] = 0
                self._flow = None
            self.repository.clear_tokens()
            self._login = {'state': 'not_started'}

    @staticmethod
    def _app(registration: OAuthRegistration, cache: msal.SerializableTokenCache):
        return msal.PublicClientApplication(
            registration.client_id,
            authority='https://login.microsoftonline.com/' + registration.tenant,
            token_cache=cache)

    def _cache(self) -> msal.SerializableTokenCache:
        cache = msal.SerializableTokenCache()
        raw = self.repository.read_tokens()
        if raw:
            try:
                cache.deserialize(raw)
            except (ValueError, TypeError, KeyError):
                raise SandboxError('Outlook authorization cache is unreadable. Disconnect and sign in again.') from None
        return cache

    def status(self) -> dict:
        with self._lock:
            cfg = self.configuration()
            registration = self.repository.registration()
            account = ''
            if cfg is not None and registration is not None:
                accounts = list(self._cache().search(msal.TokenCache.CredentialType.ACCOUNT))
                account = str(accounts[0].get('username', '')) if accounts else ''
            return dict(configured=cfg is not None,
                        app_ready=registration is not None,
                        signed_in=bool(account), account=account, **self._login)

    def start_login(self) -> dict:
        with self._lock:
            cfg = self.configuration()
            registration = self.repository.registration()
            if registration is None:
                raise SandboxError(
                    'Outlook needs one-time application approval. The printer administrator '
                    'must configure OUTLOOK_OAUTH_CLIENT_ID before sign-in can work.')
            if self._flow is not None:
                raise SandboxError('A Microsoft sign-in is already in progress.')
            self._login = {'state': 'starting'}
            # Hold the lock while initiating: repeated clicks cannot create two flows.
            try:
                cache = msal.SerializableTokenCache()
                client = self._app(registration, cache)
                flow = client.initiate_device_flow(scopes=SCOPES)
                if 'user_code' not in flow:
                    raise SandboxError('Microsoft declined to start sign-in. Ask IT to approve public-client OAuth and device-code flow.')
            except Exception as exc:
                self._login = {'state': 'failed', 'message': 'Microsoft sign-in could not start. Check application approval and IT consent.'}
                if isinstance(exc, SandboxError):
                    raise
                raise SandboxError(self._login['message']) from None
            self._flow = flow
            self._login = dict(state='pending',
                               code=flow['user_code'],
                               expires_at=time.time() + int(flow.get('expires_in', 900)))
            threading.Thread(target=self._complete_login, args=(cfg, client, cache, flow),
                             daemon=True, name='outlook-sandbox-oauth').start()
            return dict(self._login)

    def _complete_login(self, cfg, client, cache, flow) -> None:
        try:
            result = client.acquire_token_by_device_flow(flow)
            success = bool(result.get('access_token'))
            error = str(result.get('error', ''))
            messages = {
                'authorization_declined': 'Microsoft sign-in was declined.',
                'expired_token': 'The Microsoft sign-in code expired. Start again.',
                'access_denied': 'Microsoft/Okta or company policy denied this sign-in. Ask IT to approve the app.',
            }
            message = messages.get(error, 'Microsoft sign-in failed. Check company consent and Okta policy.')
        except Exception:
            success, message = False, 'Microsoft sign-in could not be completed.'
        with self._lock:
            if self._flow is not flow or cfg != self.configuration():
                return  # Disconnect or settings change must not resurrect a token.
            self._flow = None
            if success and cfg is None:
                # In the normal path the approved Microsoft login supplies the
                # mailbox identity; the user should not have to type an email.
                try:
                    claims = result.get('id_token_claims') or {}
                    usernames = [
                        claims.get('preferred_username'), claims.get('email'),
                        *[a.get('username') for a in list(
                            cache.search(msal.TokenCache.CredentialType.ACCOUNT))],
                    ]
                    identity = next(
                        (str(name) for name in usernames if name and '@' in str(name)), '')
                    discovered = OutlookConfig.from_form(
                        {'mailbox': identity, 'folder': 'Printer'})
                    self.repository.save_config(discovered)
                except (SandboxError, TypeError, ValueError, KeyError):
                    success = False
                    message = ('Microsoft authorized the app, but did not return an Outlook address. '
                               'Enter your work email below and reconnect.')
            if success:
                self.repository.write_tokens(cache.serialize())
                self._login = {'state': 'connected'}
            else:
                self._login = {'state': 'failed', 'message': message}

    def _adapter(self) -> OutlookImapAdapter:
        with self._lock:
            cfg = self.configuration()
            if cfg is None:
                raise SandboxError('Save your Outlook email and folder first.')
            registration = self.repository.registration()
            if registration is None:
                raise SandboxError('Microsoft app approval is not configured for this printer.')
            cache = self._cache()
            if not list(cache.search(msal.TokenCache.CredentialType.ACCOUNT)):
                raise SandboxError('Sign in to Microsoft before testing Outlook.')
            client = self._app(registration, cache)
            accounts = client.get_accounts()
            if not accounts:
                raise SandboxError('Outlook sign-in is no longer valid. Disconnect and sign in again.')
            token = client.acquire_token_silent(SCOPES, account=accounts[0])
            if cache.has_state_changed:
                self.repository.write_tokens(cache.serialize())
            if not token or not token.get('access_token'):
                raise SandboxError('Outlook authorization expired or was revoked. Disconnect and sign in again.')
            return self.adapter_type(cfg, token['access_token'])

    @staticmethod
    def _safe_imap(action):
        try:
            return action()
        except SandboxError:
            raise
        except (imaplib.IMAP4.error, OSError, TimeoutError):
            raise SandboxError('Secure Outlook IMAP connection failed. Check company IMAP permissions and folder access.') from None

    def folders(self) -> list[str]:
        return self._safe_imap(lambda: self._adapter().folders())

    def check(self) -> dict:
        return self._safe_imap(lambda: self._adapter().recent())

    def stage(self, uid: str) -> dict:
        adapter = self._adapter()
        validity, attachments = self._safe_imap(lambda: adapter.attachments(uid))
        stage_id = self.repository.stage_id(adapter.config, validity, uid)
        files = self.repository.save_attachments(stage_id, attachments)
        return {'id': stage_id, 'files': files}
