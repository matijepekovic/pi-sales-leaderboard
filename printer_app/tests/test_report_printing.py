"""Focused tests for the independent Salesforce printing feature."""
from datetime import datetime, timezone
import os
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

    def test_add_report_opens_without_javascript(self):
        """The Add Report control must not rely on a JS event handler."""
        from html.parser import HTMLParser

        class SelectorParser(HTMLParser):
            def __init__(self):
                super().__init__()
                self.details_depth = 0
                self.has_summary = False
                self.has_search = False

            def handle_starttag(self, tag, attrs):
                attributes = dict(attrs)
                if tag == 'details' and attributes.get('id') == 'search-dialog':
                    self.details_depth = 1
                elif self.details_depth and tag == 'summary' and attributes.get('id') == 'add-report':
                    self.has_summary = True
                elif self.details_depth and tag == 'input' and attributes.get('id') == 'report-search':
                    self.has_search = True

            def handle_endtag(self, tag):
                if tag == 'details':
                    self.details_depth = 0

        markup = (Path(__file__).resolve().parents[1] / 'templates' / 'report_printing.html').read_text()
        parser = SelectorParser()
        parser.feed(markup)
        self.assertTrue(parser.has_summary)
        self.assertTrue(parser.has_search)
        self.assertNotIn("searchDialog.showModal()", markup)

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

    @unittest.skipUnless(os.environ.get('PRINTER_BROWSER_TESTS') == '1', 'Browser test dependencies')
    def test_add_report_click_opens_search_in_real_browser(self):
        from playwright.sync_api import sync_playwright, expect
        markup = (Path(__file__).resolve().parents[1] / 'templates' / 'report_printing.html').read_text()
        start = markup.index('<details id="search-dialog">')
        end = markup.index('</details>', start) + len('</details>')
        selector = markup[start:end]
        with sync_playwright() as pw:
            for browser_type in (pw.chromium, pw.webkit):
                browser = browser_type.launch(headless=True)
                try:
                    page = browser.new_page()
                    page.set_content(selector)
                    search = page.locator('#report-search')
                    expect(search).not_to_be_visible()
                    page.locator('#add-report').click()
                    expect(search).to_be_visible()
                    search.fill('Daily Sales')
                    expect(search).to_have_value('Daily Sales')
                finally:
                    browser.close()


if __name__ == '__main__':
    unittest.main()
