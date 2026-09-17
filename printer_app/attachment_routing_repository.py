"""Durable ingestion decisions and handoff diagnostics; only this owner writes them."""
import json
import time

from .attachment_routing import AttachmentRoute, AttachmentRouter


class AttachmentRoutingRepository:
    def __init__(self, db):
        self.db = db

    def for_message(self, message_id: int, proposed: AttachmentRouter) -> AttachmentRouter:
        # Freeze before MIME inspection too: a setting edit during an interrupted
        # inspection must not turn its previously excluded PDF into a print.
        with self.db.connect() as c:
            c.execute('INSERT OR IGNORE INTO email_routing_policies VALUES (?,?)',
                      (message_id, json.dumps(proposed.snapshot())))
            value = c.execute('SELECT policy FROM email_routing_policies WHERE message_id=?',
                              (message_id,)).fetchone()[0]
            return AttachmentRouter.restore(json.loads(value))

    def remember(self, message_id: int, part: str, filename: str, route: AttachmentRoute):
        # Commit BEFORE downloading/queueing. A failed gallery handoff cannot turn
        # into a print after restart, a setting change or a missing consumer.
        with self.db.connect() as c:
            c.execute("""INSERT OR IGNORE INTO email_attachment_routes
                (message_id,part,filename,print_document,import_document,updated)
                VALUES (?,?,?,?,?,?)""", (message_id, part, filename,
                int(route.print_document), int(route.import_document), time.time()))
            return dict(c.execute('SELECT * FROM email_attachment_routes WHERE message_id=? AND part=?',
                                  (message_id, part)).fetchone())

    def delivered(self, message_id: int, part: str):
        self.db.execute("""UPDATE email_attachment_routes SET gallery_delivered=1,error='',updated=?
            WHERE message_id=? AND part=?""", (time.time(), message_id, part))

    def failed(self, message_id: int, part: str, reason: str):
        # Callers supply fixed public diagnostics, never raw provider exceptions.
        self.db.execute('UPDATE email_attachment_routes SET error=?,updated=? WHERE message_id=? AND part=?',
                        (reason, time.time(), message_id, part))

    def resolved_structure(self, message_id: int):
        # A synthetic inspection failure is not an attachment. No job is removed.
        self.db.execute("DELETE FROM email_attachment_routes WHERE message_id=? AND part='mime-error'", (message_id,))

    def pending(self, message_id: int) -> bool:
        return bool(self.db.one("""SELECT 1 FROM email_attachment_routes
            WHERE message_id=? AND import_document=1 AND gallery_delivered=0 LIMIT 1""", (message_id,)))

    def failures(self):
        return self.db.rows("""SELECT r.filename,r.error,r.updated,m.subject FROM email_attachment_routes r
            JOIN processed_messages m ON m.id=r.message_id
            WHERE r.error!='' AND r.import_document=1 AND r.gallery_delivered=0
            ORDER BY r.updated DESC LIMIT 8""")
