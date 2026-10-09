"""Report browser cache and per-folder refresh behavior."""
import unittest
from unittest.mock import patch

from printer_app.salesforce_sandbox.service import SalesforceSandboxService


class ReportFolderRefreshTests(unittest.TestCase):
    def test_refresh_selected_folder_only(self):
        calls = []
        initial = (
            dict(id='00O123456789012', name='A', folder='Sales'),
            dict(id='00O123456789013', name='B', folder='Ops'),
        )
        refreshed = (dict(id='00O123456789014', name='New A', folder='Sales'),)

        def source(adapter, term, folder=None):
            calls.append(folder)
            return initial if folder is None else refreshed

        with patch('printer_app.salesforce_sandbox.service.search_reports', source):
            service = SalesforceSandboxService(object())
            self.assertEqual(len(service.search_reports('')), 2)
            results = service.search_reports('', refresh=True, folder='Sales')
            self.assertEqual(calls, [None, 'Sales'])
            self.assertEqual({r['name'] for r in results}, {'New A', 'B'})
            self.assertEqual(len(service.search_reports('Ops')), 0)

    def test_all_refresh_reloads_everything(self):
        calls = []
        with patch('printer_app.salesforce_sandbox.service.search_reports',
                   side_effect=lambda adapter, term, folder=None: calls.append(folder) or ()):
            service = SalesforceSandboxService(object())
            service.search_reports('')
            service.search_reports('', refresh=True)
            self.assertEqual(calls, [None, None])


if __name__ == '__main__':
    unittest.main()
