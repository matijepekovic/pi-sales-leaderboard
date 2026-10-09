"""Focused tests for the independent Salesforce printing feature."""
from datetime import datetime, timezone
from pathlib import Path
import tempfile
import unittest

from printer_app.db import Database
from printer_app.print_options import PrintOptions
from printer_app.report_printing_contract import ReportPrintingJob, ScheduledReport
from printer_app.report_printing_repository import ReportPrintingRepository


class ReportPrintingTests(unittest.TestCase):
    def job(self, **patch):
        values = dict(job_id='job-1', name='Morning', timezone='UTC',
                      hour=8, minute=0, weekdays=(0, 1, 2, 3, 4),
                      defaults=PrintOptions(paper='letter'),
                      reports=(ScheduledReport('00O123456789012', 'Daily', {'PRINT_PAPER': 'tabloid'}),))
        values.update(patch)
        return ReportPrintingJob(**values)

    def test_override_does_not_mutate_default(self):
        job = self.job()
        self.assertEqual(job.reports[0].effective_options(job.defaults).paper, 'tabloid')
        self.assertEqual(job.defaults.paper, 'letter')

    def test_weekdays_and_occurrences(self):
        job = self.job()
        start = datetime(2026, 10, 9, 0, tzinfo=timezone.utc)
        end = datetime(2026, 10, 12, 9, tzinfo=timezone.utc)
        self.assertEqual(len(list(job.due_occurrences(start, end))), 2)

    def test_repository_and_atomic_claim(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Database(Path(tmp) / 'printer.db')
            repository = ReportPrintingRepository(db)
            job = self.job()
            repository.save(job)
            self.assertEqual(repository.list(), [job])
            self.assertTrue(repository.claim('report-run-1'))
            self.assertFalse(repository.claim('report-run-1'))
            repository.finish('report-run-1', 'QUEUED', queued_job_id=4)
            self.assertEqual(repository.runs()[0]['state'], 'QUEUED')

    def test_reject_invalid_override(self):
        with self.assertRaises(ValueError):
            self.job(reports=(ScheduledReport('a', 'Daily', {'PRINT_PAPER': 'unsupported'}),))


if __name__ == '__main__':
    unittest.main()
