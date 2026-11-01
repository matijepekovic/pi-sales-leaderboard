"""SQLite owner for Olympia cover edits and background PDF generation jobs."""
from __future__ import annotations

import json
import time


class ModPdfRepository:
    def __init__(self, db):
        self.db = db

    def edits(self, day):
        row = self.db.one("SELECT edits,revision FROM mod_cover_edits WHERE day=?", (day,))
        return (json.loads(row["edits"]), row["revision"]) if row else ({}, 0)

    def enqueue(self, day, base_cover, sheets, edits, color_code):
        now = time.time()
        with self.db.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            job_id = conn.execute("""INSERT INTO mod_result_pdf_jobs
                 (day,state,created,updated,base_cover,edits,sheets,color_code)
                 VALUES (?,'queued',?,?,?,?,?,?)""",
                 (day, now, now, json.dumps(base_cover), json.dumps(edits),
                  json.dumps(sheets), int(bool(color_code)))).lastrowid
        return job_id

    def job(self, day, job_id):
        row = self.db.one(
            "SELECT * FROM mod_result_pdf_jobs WHERE day=? AND id=?",
            (day, job_id))
        if row is None:
            raise LookupError("PDF job not found for this day.")
        return self._decode(row)

    def job_any(self, job_id):
        row = self.db.one("SELECT * FROM mod_result_pdf_jobs WHERE id=?", (job_id,))
        if row is None:
            raise LookupError("PDF job no longer exists.")
        return self._decode(row)

    @staticmethod
    def _decode(row):
        entry = dict(row)
        for key in ("base_cover", "edits", "sheets"):
            entry[key] = json.loads(entry[key])
        return entry

    def confirm(self, day, job_id, edits, revision):
        """Update report-only data even during Salesforce End of Day."""
        now = time.time()
        with self.db.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute("""SELECT revision,state FROM mod_result_pdf_jobs
                WHERE day=? AND id=?""", (day, job_id)).fetchone()
            if row is None:
                raise LookupError("PDF job not found.")
            if row["revision"] != revision:
                raise ValueError("Cover was edited elsewhere. Reload the cover.")
            # Keep work already running, but invalidate any published PDF.
            new_state = (
                "pending_finalize" if row["state"] in
                ("awaiting_confirmation", "pending_finalize", "finalizing", "ready")
                else row["state"]
            )
            if new_state == "failed":
                raise ValueError("PDF generation failed. Start a new PDFs job.")
            conn.execute("""UPDATE mod_result_pdf_jobs
                SET edits=?,confirmed=1,revision=revision+1,state=?,updated=?
                WHERE day=? AND id=?""",
                (json.dumps(edits), new_state, now, day, job_id))
            conn.execute("""INSERT INTO mod_cover_edits(day,edits,revision)
                VALUES (?,?,1) ON CONFLICT(day) DO UPDATE SET
                edits=excluded.edits,revision=mod_cover_edits.revision+1""",
                (day, json.dumps(edits)))
            return revision + 1

    def recover(self):
        """Rendered PDFs are safe to recreate after an interrupted worker."""
        with self.db.connect() as conn:
            conn.execute("UPDATE mod_result_pdf_jobs SET state='queued',stage='restarting'"
                         " WHERE state='rendering'")
            conn.execute("""UPDATE mod_result_pdf_jobs
                SET state='pending_finalize',stage='restarting'
                WHERE state='finalizing'""")

    def has_pending(self):
        return self.db.one(
            "SELECT id FROM mod_result_pdf_jobs WHERE state IN ('queued','pending_finalize')"
            " ORDER BY id LIMIT 1") is not None

    def claim(self):
        with self.db.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute("""SELECT * FROM mod_result_pdf_jobs
                WHERE state IN ('queued','pending_finalize')
                ORDER BY id LIMIT 1""").fetchone()
            if row is None:
                return None
            state = "rendering" if row["state"] == "queued" else "finalizing"
            conn.execute("""UPDATE mod_result_pdf_jobs
                SET state=?,stage=?,updated=? WHERE id=?""",
                (state, "cover" if state == "rendering" else "finalizing",
                 time.time(), row["id"]))
            data = self._decode(row)
            data["state"] = state
            return data

    def progress(self, job_id, stage):
        with self.db.connect() as conn:
            conn.execute("""UPDATE mod_result_pdf_jobs SET stage=?,updated=?
                WHERE id=? AND state='rendering'""",
                (stage, time.time(), job_id))

    def finished_render(self, job_id):
        """Transition from background preparation; confirmation may race it."""
        with self.db.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute("SELECT confirmed FROM mod_result_pdf_jobs WHERE id=?"
                               " AND state='rendering'", (job_id,)).fetchone()
            if row is None:
                raise ValueError("PDF job changed while rendering.")
            target = "pending_finalize" if row["confirmed"] else "awaiting_confirmation"
            conn.execute("""UPDATE mod_result_pdf_jobs SET state=?,stage=?,updated=?
                WHERE id=?""",
                (target, "finalizing" if row["confirmed"] else "cover_confirmation",
                 time.time(), job_id))
            return bool(row["confirmed"])

    def begin_finalize(self, job_id):
        with self.db.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute("SELECT * FROM mod_result_pdf_jobs WHERE id=?",
                               (job_id,)).fetchone()
            if row is None or not row["confirmed"] or row["state"] != "pending_finalize":
                return None
            conn.execute("""UPDATE mod_result_pdf_jobs SET state='finalizing',
                stage='finalizing',updated=? WHERE id=?""", (time.time(), job_id))
            return self._decode(row)

    def mark_ready(self, job_id, revision):
        with self.db.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            result = conn.execute("""UPDATE mod_result_pdf_jobs
                SET state='ready',stage='complete',updated=?
                WHERE id=? AND state='finalizing' AND revision=?""",
                (time.time(), job_id, revision))
            if not result.rowcount:
                # An editor confirmed new values during rendering; redo only
                # the small cover/merge, not the MOD sheets.
                conn.execute("""UPDATE mod_result_pdf_jobs
                    SET state='pending_finalize',stage='cover_changed',updated=?
                    WHERE id=? AND state='finalizing'""", (time.time(), job_id))
            return bool(result.rowcount)

    def fail(self, job_id, error):
        with self.db.connect() as conn:
            conn.execute("""UPDATE mod_result_pdf_jobs SET
                state='failed',stage='failed',error=?,updated=?
                WHERE id=?""", (str(error)[:500], time.time(), job_id))
