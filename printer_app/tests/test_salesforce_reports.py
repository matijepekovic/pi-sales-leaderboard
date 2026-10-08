"""Contract tests for Salesforce report discovery (no live credentials required)."""
import unittest

from printer_app.salesforce_sandbox.reports import search_reports


class FakeCli:
    def __init__(self, records):
        self.records = records
        self.calls = []

    def _target_args(self):
        return ['--target-org', 'work']

    def _run(self, args, timeout=30):
        self.calls.append(args)
        return {'records': self.records}


class ReportSearchTests(unittest.TestCase):
    def test_search_uses_existing_org_and_returns_normalized_reports(self):
        cli = FakeCli([{'Id': '00O123456789012', 'Name': 'Morning Print',
                        'FolderName': 'Private Reports'}])
        result = search_reports(cli, 'Morning')
        self.assertEqual(result[0]['folder'], 'Private Reports')
        self.assertIn('--target-org', cli.calls[0])
        self.assertIn('work', cli.calls[0])

    def test_rejects_control_characters(self):
        with self.assertRaises(ValueError):
            search_reports(FakeCli([]), 'bad\nquery')

    def test_escapes_single_quote(self):
        cli = FakeCli([])
        search_reports(cli, "Bob's")
        self.assertIn("Bob\\'s", cli.calls[0][3-1])

    def test_invalid_id_is_rejected(self):
        with self.assertRaises(Exception):
            search_reports(FakeCli([{'Id': 'not-a-report', 'Name': 'x'}]), '')


if __name__ == '__main__':
    unittest.main()
