"""Native formatted Salesforce report export contract tests."""
import io
import subprocess
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from printer_app.salesforce_sandbox.adapter import SalesforceCliAdapter, SalesforceAdapterError


def workbook():
    out = io.BytesIO()
    with zipfile.ZipFile(out, 'w') as z:
        z.writestr('[Content_Types].xml', '<Types/>')
        z.writestr('xl/workbook.xml', '<workbook/>')
    return out.getvalue()


class DownloadTests(unittest.TestCase):
    def test_download_uses_authenticated_native_excel_endpoint(self):
        expected = workbook()
        calls = []

        def runner(command, **kwargs):
            calls.append(command)
            Path(command[command.index('--stream-to-file') + 1]).write_bytes(expected)
            return subprocess.CompletedProcess(command, 0, '', '')

        adapter = SalesforceCliAdapter(runner=runner, executable='sf', target_org='work')
        self.assertEqual(adapter.download_formatted_report('00O123456789012'), expected)
        self.assertIn('--target-org', calls[0])
        self.assertIn('work', calls[0])
        self.assertIn('Accept: application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', calls[0])
        self.assertIn('/services/data/v60.0/analytics/reports/00O123456789012', calls[0])

    def test_rejects_non_excel_response(self):
        def runner(command, **kwargs):
            Path(command[command.index('--stream-to-file') + 1]).write_bytes(b'Unauthorized')
            return subprocess.CompletedProcess(command, 0, '', '')

        with self.assertRaises(SalesforceAdapterError):
            SalesforceCliAdapter(runner=runner).download_formatted_report('00O123456789012')

    def test_invalid_id_does_not_call_cli(self):
        with self.assertRaises(ValueError):
            SalesforceCliAdapter(runner=lambda *a, **k: self.fail('CLI invoked')).download_formatted_report('../bad')

    def test_cli_failure_does_not_return_file(self):
        def runner(command, **kwargs):
            return subprocess.CompletedProcess(command, 1, '', 'Export Reports permission required')

        with self.assertRaises(SalesforceAdapterError):
            SalesforceCliAdapter(runner=runner).download_formatted_report('00O123456789012')


if __name__ == '__main__':
    unittest.main()
