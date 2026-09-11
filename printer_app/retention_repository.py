"""All retention SQL: finished work, minimal dedup receipts and deletion outbox."""
from .db import Database
from .retention_policy import ExpiredEmail

# Never expire waiting, retrying, interrupted, or ambiguous print outcomes.
DONE = "('PRINTED','ERROR PRINTED')"


class RetentionRepository:
    def __init__(self, db: Database):
        self.db = db

    def seen(self, identity):
        return bool(self.db.one('SELECT 1 FROM retained_message_receipts WHERE identity=?', (identity,)))

    def state(self):
        return self.db.get('cleanup_state', {})

    def save_state(self, state):
        self.db.set('cleanup_state', state)

    def expired_messages(self, cutoff, limit=100):
        return self.db.rows(f'''SELECT m.id,m.identity FROM processed_messages m
            WHERE m.state='COMPLETE' AND m.created<? AND NOT EXISTS (
                SELECT 1 FROM attachments a WHERE a.message_id=m.id AND
                (a.state!='DONE' OR a.created>=? OR EXISTS (SELECT 1 FROM jobs j
                 WHERE j.attachment_id=a.id AND (j.status NOT IN {DONE}
                 OR j.completed IS NULL OR j.completed>=?)))) ORDER BY m.id LIMIT ?''',
            (cutoff, cutoff, cutoff, limit))

    def message_files(self, mid):
        attachments = self.db.rows('SELECT id FROM attachments WHERE message_id=?', (mid,))
        jobs = self.db.rows('''SELECT j.id FROM jobs j JOIN attachments a ON a.id=j.attachment_id
            WHERE a.message_id=?''', (mid,))
        return [('jobs', j['id']) for j in jobs] + [('attachments', a['id']) for a in attachments]

    @staticmethod
    def _delete_job(conn, jid):
        for table in ('outputs', 'steps', 'print_attempts'):
            conn.execute(f'DELETE FROM {table} WHERE job_id=?', (jid,))
        conn.execute('DELETE FROM meta WHERE key=?', ('job_print_settings:' + str(jid),))
        conn.execute('DELETE FROM jobs WHERE id=?', (jid,))

    def forget_message(self, mid, identity):
        # Files have already been removed while their IDs were still allocated.
        # A crash before this commit leaves a retryable, already-expired record.
        with self.db.connect() as conn:
            conn.execute('BEGIN IMMEDIATE')
            conn.execute('INSERT OR IGNORE INTO retained_message_receipts(identity) VALUES (?)', (identity,))
            aids = [r['id'] for r in conn.execute('SELECT id FROM attachments WHERE message_id=?', (mid,))]
            count = 0
            for aid in aids:
                for row in list(conn.execute('SELECT id FROM jobs WHERE attachment_id=?', (aid,))):
                    self._delete_job(conn, row['id'])
                    count += 1
                conn.execute('DELETE FROM print_queue_releases WHERE attachment_id=?', (aid,))
                conn.execute('DELETE FROM attachments WHERE id=?', (aid,))
            conn.execute('DELETE FROM processed_messages WHERE id=?', (mid,))
            return count

    def expired_tests(self, cutoff):
        return self.db.rows(f'''SELECT id FROM jobs WHERE attachment_id IS NULL
            AND status IN {DONE} AND completed<? ORDER BY id LIMIT 100''', (cutoff,))

    def forget_test(self, jid):
        with self.db.connect() as conn:
            self._delete_job(conn, jid)

    def download_pending(self, identity):
        return bool(self.db.one("SELECT 1 FROM processed_messages WHERE identity=? AND state='FETCHING'", (identity,)))

    def remember_deletion(self, account, mailbox, email: ExpiredEmail):
        self.db.execute('''INSERT OR IGNORE INTO mail_cleanup_outbox
            (account,mailbox,message_key,received_at,local_identity) VALUES (?,?,?,?,?)''',
            (account.casefold(), mailbox, email.key, email.received_at, email.local_identity))

    def pending_deletions(self, account, mailbox, cutoff):
        return [ExpiredEmail(r['message_key'], r['received_at'], r['local_identity'])
                for r in self.db.rows('''SELECT * FROM mail_cleanup_outbox
                WHERE account=? AND mailbox=? AND received_at<? ORDER BY received_at LIMIT 100''',
                (account.casefold(), mailbox, cutoff))]

    def finish_deletion(self, account, mailbox, key):
        self.db.execute('DELETE FROM mail_cleanup_outbox WHERE account=? AND mailbox=? AND message_key=?',
                        (account.casefold(), mailbox, key))

    def prune_summaries(self, cutoff):
        last = self.db.get('last_printer_error')
        if last and last.get('at', 0) < cutoff:
            self.db.set('last_printer_error', None)
        last = self.db.get('last_successful_print')
        if last and last < cutoff:
            self.db.set('last_successful_print', None)
        # SQLite reuses freed pages; do not VACUUM a live print queue or replace
        # its database. PASSIVE never waits on readers or discards active WAL.
        with self.db.connect() as conn:
            conn.execute('PRAGMA wal_checkpoint(PASSIVE)')
