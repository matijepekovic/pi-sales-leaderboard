"""Regression checks for report browser controls."""
import unittest
from pathlib import Path


class ReportBrowserTemplateTests(unittest.TestCase):
    def test_folder_browser_and_refresh(self):
        template = (Path(__file__).resolve().parents[1] / 'templates' / 'salesforce_reports.html').read_text()
        self.assertIn('aria-label="Report folders"', template)
        self.assertIn('Refresh current folder', template)
        self.assertIn('folder=name, refresh=1', template)
        self.assertIn('report-folder-list', template)
        self.assertIn('report-pagination', template)
        self.assertIn('salesforce_reports.css', template)
        self.assertIn("salesforce_sandbox.download_report", template)
        self.assertIn('Download XLSX', template)
        self.assertIn('<th>Report ID</th>', template)
        self.assertIn('class="report-id">{{ report.id }}</code>', template)
        self.assertIn('colspan="4"', template)


if __name__ == '__main__':
    unittest.main()
