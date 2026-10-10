"""Real HTTP protections, saved settings and browser controls for report notes."""
from io import BytesIO
import json
import os
from pathlib import Path
import shutil
import tempfile
import threading
import unittest
from unittest.mock import patch

from pypdf import PdfReader
from werkzeug.datastructures import MultiDict

from printer_app.config import Config
from printer_app.print_options import PrintOptions
from printer_app.report_notes_contract import ReportNotesOptions
from printer_app.report_printing_repository import ReportPrintingRepository
from printer_app.tests.test_report_notes_integration import REPORT_ID, Source


class NotesWebTests(unittest.TestCase):
    def setUp(self):
        from printer_app.app import create_app
        from printer_app.tests.auth_helpers import login_admin
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        env = root / 'env'
        env.write_text('EMAIL_ENABLED=0\n')
        self.cfg = Config(data_dir=root / 'data', env_file=env, secret_key='s' * 64, email_enabled=False)
        self.app = create_app(self.cfg)
        self.app.testing = True
        self.client = self.app.test_client()
        self.csrf = login_admin(self.client)
        self.repository = ReportPrintingRepository(self.app.extensions['printer_db'])
        self.notes = ReportNotesOptions(True, ('Job', 'Customer'), 14, 12.5, 3.5)
        self.source = Source()
        source_patch = patch.object(self.app.extensions['salesforce_sandbox'],
                                    'download_formatted_report', self.source.download_formatted_report)
        source_patch.start()
        self.addCleanup(source_patch.stop)

    def save_data(self):
        return MultiDict([
            ('csrf', self.csrf), ('name', 'Morning'), ('time', '08:00'), ('weekday', '0'),
            ('weekday', '1'), ('enabled', 'on'), ('report_id', REPORT_ID),
            ('report_name_' + REPORT_ID, 'Daily jobs'),
            ('notes_' + REPORT_ID, json.dumps(self.notes.snapshot())),
            ('report_id', '00O123456789013'), ('report_name_00O123456789013', 'No overlay'),
        ])

    def preview_data(self, kind='columns'):
        options = PrintOptions(paper='letter', excel_scale='fit-width', page_policy='all', margins='narrow')
        return dict(csrf=self.csrf, report_id=REPORT_ID, kind=kind,
                    options=json.dumps(options.environment()), notes=json.dumps(self.notes.snapshot()))

    def test_save_reopen_preserve_and_disable_per_report(self):
        fields = self.save_data()
        response = self.client.post('/report-printing/save', data=fields)
        self.assertEqual(response.status_code, 302, response.get_data(as_text=True))
        job = self.repository.list()[0]
        self.assertEqual(job.reports[0].notes, self.notes)
        self.assertFalse(job.reports[1].notes.enabled)
        page = self.client.get('/report-printing/?edit=' + job.job_id)
        self.assertEqual(page.status_code, 200)
        self.assertIn('notes_' + REPORT_ID, page.get_data(as_text=True))
        fields['job_id'] = job.job_id
        del fields['notes_' + REPORT_ID]
        self.assertEqual(self.client.post('/report-printing/save', data=fields).status_code, 302)
        self.assertEqual(self.repository.list()[0].reports[0].notes, self.notes)
        fields['notes_' + REPORT_ID] = json.dumps(dict(self.notes.snapshot(), enabled=False))
        self.assertEqual(self.client.post('/report-printing/save', data=fields).status_code, 302)
        self.assertFalse(self.repository.list()[0].reports[0].notes.enabled)

    def test_reject_bad_notes_without_saving(self):
        for bad in (dict(enabled=True), dict(enabled=True, columns=['Job'], font_size=float('nan')),
                    dict(enabled=True, columns=['Job'], row_spacing_mm=-1), dict(columns='Job')):
            fields = self.save_data()
            fields['notes_' + REPORT_ID] = json.dumps(bad)
            self.assertEqual(self.client.post('/report-printing/save', data=fields).status_code, 400)
        self.assertEqual(self.repository.list(), [])

    def test_preview_obeys_admin_csrf_origin_and_duplicate_guards(self):
        fields = self.preview_data()
        bad = dict(fields, csrf='incorrect')
        self.assertEqual(self.client.post('/report-printing/preview', data=bad).status_code, 400)
        duplicate = MultiDict([*fields.items(), ('report_id', '00O000000000000')])
        self.assertEqual(self.client.post('/report-printing/preview', data=duplicate).status_code, 400)
        self.assertEqual(self.client.post('/report-printing/preview', data=fields,
                         headers={'Origin': 'https://untrusted.example'}).status_code, 403)
        anonymous = self.app.test_client()
        anonymous.get('/report-printing/')
        with anonymous.session_transaction() as session:
            token = session['csrf']
        denied = anonymous.post('/report-printing/preview', data=dict(fields, csrf=token))
        self.assertIn(denied.status_code, (302, 401, 403))
        self.assertEqual(self.source.calls, [])

    @unittest.skipUnless(shutil.which('libreoffice'), 'LibreOffice not installed')
    def test_real_preview_returns_columns_and_pdf_but_never_prints(self):
        response = self.client.post('/report-printing/preview', data=self.preview_data())
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        self.assertEqual(response.json['columns'], ['Customer', 'Job', 'Product'])
        response = self.client.post('/report-printing/preview', data=self.preview_data('pdf'))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.mimetype, 'application/pdf')
        self.assertEqual(response.headers['Cache-Control'], 'no-store')
        self.assertEqual(response.headers['X-Notes-Rows'], '2')
        self.assertIn('Updates', PdfReader(BytesIO(response.data)).pages[0].extract_text())
        self.assertEqual(self.repository.runs(), [])
        from printer_app.print_queue_repository import PrintQueueRepository
        self.assertEqual(PrintQueueRepository(self.app.extensions['printer_db']).recent_activity(), [])

    def test_preview_does_not_expose_source_exceptions(self):
        with patch.object(self.app.extensions['salesforce_sandbox'], 'download_formatted_report',
                          side_effect=RuntimeError('secret credentials and customer contents')):
            response = self.client.post('/report-printing/preview', data=self.preview_data())
        self.assertEqual(response.status_code, 503)
        self.assertNotIn('secret', response.get_data(as_text=True))


@unittest.skipUnless(os.environ.get('PRINTER_BROWSER_TESTS') == '1', 'Browser test dependencies')
class NotesBrowserTests(unittest.TestCase):
    def test_columns_order_spacing_preview_save_reload_cancel_both_engines(self):
        from flask import Flask, g, session
        from jinja2 import ChoiceLoader, DictLoader, FileSystemLoader
        from playwright.sync_api import sync_playwright, expect
        from werkzeug.serving import make_server
        from printer_app.db import Database
        from printer_app.report_printing_contract import ReportPrintingJob, ScheduledReport
        from printer_app.report_printing_web import blueprint
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            cfg = Config(data_dir=root / 'data', email_enabled=False)
            source = Source()
            repository = ReportPrintingRepository(Database(cfg.db_path))
            options = PrintOptions(paper='letter', excel_scale='fit-width', margins='narrow', page_policy='all')
            job = ReportPrintingJob('browser', 'Morning', 'UTC', 8, 0, (0,), options,
                                   (ScheduledReport(REPORT_ID, 'Daily jobs', {}),))
            printer = Path(__file__).resolve().parents[1]
            app = Flask(__name__, static_folder=str(printer / 'static'), static_url_path='/static')
            app.secret_key = 'test-only'
            app.jinja_loader = ChoiceLoader([
                DictLoader({'base.html': '<!doctype html><html><head>{% block head %}{% endblock %}</head><body>{% block content %}{% endblock %}</body></html>'}),
                FileSystemLoader(str(printer / 'templates'))])
            app.register_blueprint(blueprint(repository, source))
            @app.before_request
            def config():
                g.printer_config = cfg
                session.setdefault('csrf', 'browser-token')
            @app.after_request
            def security(response):
                response.headers['Content-Security-Policy'] = "default-src 'self'; script-src 'self'; style-src 'self'; object-src 'none'"
                return response
            server = make_server('127.0.0.1', 0, app, threaded=True)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            origin = 'http://127.0.0.1:' + str(server.server_port)
            try:
                with sync_playwright() as pw:
                    for engine in (pw.chromium, pw.webkit):
                        repository.save(job)
                        browser = engine.launch(headless=True)
                        try:
                            page = browser.new_page(viewport={'width': 430, 'height': 850})
                            errors = []
                            page.on('pageerror', lambda e: errors.append(str(e)))
                            page.goto(origin + '/report-printing/?edit=browser')
                            page.locator('.edit-override').click()
                            page.locator('#notes-enabled').check()
                            page.locator('#notes-load-columns').click()
                            expect(page.locator('#notes-columns input')).to_have_count(3, timeout=90000)
                            page.locator('#notes-columns').get_by_label('Customer', exact=True).check()
                            page.locator('#notes-columns').get_by_label('Job', exact=True).check()
                            page.get_by_role('button', name='Move Job up', exact=True).click()
                            page.locator('#notes-font-size').fill('14')
                            page.locator('#notes-row-spacing').fill('12.5')
                            page.locator('#notes-table-gap').fill('3.5')
                            page.locator('#notes-preview').click()
                            expect(page.locator('#notes-preview-link')).to_be_visible(timeout=90000)
                            expect(page.locator('#notes-status')).to_contain_text('2 job rows')
                            page.locator('#override-save').click()
                            page.locator('#job-form button[type="submit"]').click()
                            expect(page.locator('h1')).to_have_text('Salesforce Report Printing')
                            page.goto(origin + '/report-printing/?edit=browser')
                            page.locator('.edit-override').click()
                            expect(page.locator('#notes-enabled')).to_be_checked()
                            expect(page.locator('#notes-row-spacing')).to_have_value('12.5')
                            saved = repository.list()[0].reports[0].notes
                            self.assertEqual(saved, ReportNotesOptions(True, ('Job', 'Customer'), 14, 12.5, 3.5))
                            page.locator('#notes-row-spacing').fill('30')
                            page.locator('#override-cancel').click()
                            page.locator('.edit-override').click()
                            expect(page.locator('#notes-row-spacing')).to_have_value('12.5')
                            page.locator('#notes-enabled').uncheck()
                            page.locator('#override-save').click()
                            page.locator('#job-form button[type="submit"]').click()
                            page.wait_for_url(origin + '/report-printing/')
                            self.assertFalse(repository.list()[0].reports[0].notes.enabled)
                            self.assertEqual(repository.runs(), [])
                            self.assertEqual(errors, [])
                        finally:
                            browser.close()
            finally:
                server.shutdown(); server.server_close(); thread.join(timeout=5)


if __name__ == '__main__':
    unittest.main()
