"""Cleanup workflow. Remote identities are opaque; adapters own mail/files/SQL."""
import logging
import time

log = logging.getLogger(__name__)


class RetentionService:
    def __init__(self, cfg, repository, files, mail_factory, still_current=lambda: True):
        self.cfg, self.repository, self.files = cfg, repository, files
        self.mail_factory, self.still_current = mail_factory, still_current

    @property
    def signature(self):
        p = self.cfg.retention
        return [p.enabled, p.days, p.delete_emails, p.email_scope, self.cfg.email_user, self.cfg.mailbox]

    def due(self, now):
        state = self.repository.state()
        return self.cfg.retention.enabled and (state.get('signature') != self.signature
               or now >= state.get('next_run', 0))

    def run(self):
        now = time.time()
        policy = self.cfg.retention
        if not policy.enabled or not self.still_current():
            return
        cutoff = now - policy.days * 86400
        state = dict(signature=self.signature, started=now, next_run=now + 3600,
                     running=True, local_jobs=0, emails=0, backups=0, error='')
        self.repository.save_state(state)
        try:
            messages = self.repository.expired_messages(cutoff)
            tests = self.repository.expired_tests(cutoff)
            for message in messages:
                if not self.still_current():
                    break
                for category, ident in self.repository.message_files(message['id']):
                    self.files.remove(category, ident)
                state['local_jobs'] += self.repository.forget_message(message['id'], message['identity'])
            for job in tests:
                if not self.still_current():
                    break
                self.files.remove('jobs', job['id'])
                self.repository.forget_test(job['id'])
                state['local_jobs'] += 1
            if self.still_current():
                state['backups'] = self.files.prune_backups(cutoff)
                self.repository.prune_summaries(cutoff)
            if len(messages) == 100 or len(tests) == 100:
                state['next_run'] = now + 60  # Catch up in bounded batches.
        except Exception as exc:
            state['error'] = 'Local cleanup failed; unfinished records retained. See worker log.'
            state['next_run'] = now + 600
            log.warning('Local retention failure: %s', type(exc).__name__)
        try:
            if policy.mail_allowed(self.cfg.email_user, self.cfg.mailbox) and self.still_current():
                with self.mail_factory(self.cfg, self.still_current) as mail:
                    # Resume only this adapter's recorded identities, never the
                    # entire Trash. Persist intent BEFORE the first remote move.
                    pending = self.repository.pending_deletions(self.cfg.email_user, self.cfg.mailbox, cutoff)
                    candidates = pending or mail.expired(cutoff, limit=100)
                    for email in candidates:
                        if not self.still_current():
                            return
                        if self.repository.download_pending(email.local_identity):
                            continue  # Finish an interrupted download first.
                        self.repository.remember_deletion(self.cfg.email_user, self.cfg.mailbox, email)
                        deleted = mail.delete(email, cutoff)
                        self.repository.finish_deletion(self.cfg.email_user, self.cfg.mailbox, email.key)
                        state['emails'] += int(deleted)
                    if len(candidates) == 100:
                        state['next_run'] = now + 60
        except Exception as exc:
            state['error'] += (' ' if state['error'] else '') + 'Gmail cleanup failed; will retry. No whole-folder expunge is used.'
            state['next_run'] = now + 600
            log.warning('Gmail retention failure: %s', type(exc).__name__)
        finally:
            state.update(running=False, finished=time.time())
            self.repository.save_state(state)
            log.info('Cleanup: local_jobs=%s emails=%s backups=%s error=%s',
                     state['local_jobs'], state['emails'], state['backups'], bool(state['error']))
