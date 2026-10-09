"""Regression checks for report browser controls."""
import unittest
from pathlib import Path


class ReportBrowserTemplateTests(unittest.TestCase):
    def test_folder_browser_and_refresh(self):
        template = (Path(__file__).resolve().parents[1] / 'templates' / 'salesforce_reports.html').read_text()
        self.assertIn('aria-label="Report folders"', template)
        self.assertIn('Refresh current folder', template)
        self.assertIn('folder=folder, refresh=1', template)
        self.assertIn("salesforce_sandbox.download_report", template)
        self.assertIn('Downloading', template.replace('Download XLSX', 'Downloading'))


if __name__ == '__main__':
    unittest.main()
