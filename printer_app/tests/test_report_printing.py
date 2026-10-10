"""Focused tests for the independent Salesforce printing feature."""
from datetime import datetime, timezone
import os
import importlib.util
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
                self.has_folder_list = False

            def handle_starttag(self, tag, attrs):
                attributes = dict(attrs)
                if tag == 'details' and attributes.get('id') == 'search-dialog':
                    self.details_depth = 1
                elif self.details_depth and tag == 'summary' and attributes.get('id') == 'add-report':
                    self.has_summary = True
                elif self.details_depth and attributes.get('id') == 'folder-results':
                    self.has_folder_list = True

            def handle_endtag(self, tag):
                if tag == 'details':
                    self.details_depth = 0

        markup = (Path(__file__).resolve().parents[1] / 'templates' / 'report_printing.html').read_text()
        parser = SelectorParser()
        parser.feed(markup)
        self.assertTrue(parser.has_summary)
        self.assertTrue(parser.has_folder_list)
        self.assertNotIn('id="folder-search"', markup)
        self.assertNotIn('id="report-search"', markup)
        self.assertNotIn("searchDialog.showModal()", markup)

    @unittest.skipUnless(importlib.util.find_spec('flask'), 'Flask not installed in contract-only CI')
    def test_folder_first_search_and_id_persistence(self):
        from flask import Flask, g
        from types import SimpleNamespace
        from printer_app.report_printing_web import blueprint

        records = [
            {'id': '00O123456789012', 'name': 'Daily Sales', 'folder': 'Sales'},
            {'id': '00O123456789013', 'name': 'Weekly Sales', 'folder': 'Sales'},
            {'id': '00O123456789014', 'name': 'Operations', 'folder': 'Operations'},
        ]

        class Source:
            def search_reports(self, term, **kwargs):
                return [record for record in records if term.lower() in record['name'].lower()]

            def refresh_report_folder(self, folder):
                return [record for record in records if record['folder'] == folder]

        class Repository:
            saved = None

            def list(self):
                return [self.saved] if self.saved else []

            def runs(self):
                return []

            def save(self, job):
                self.saved = job

        repo = Repository()
        app = Flask(__name__, template_folder=str(Path(__file__).resolve().parents[1] / 'templates'))
        app.secret_key = 'test'
        app.register_blueprint(blueprint(repo, Source()))

        @app.before_request
        def config():
            g.printer_config = SimpleNamespace(timezone='UTC')

        client = app.test_client()
        self.assertEqual(client.get('/report-printing/search?q=Daily').status_code, 400)
        folders = client.get('/report-printing/folders?q=sal').json
        self.assertEqual(folders['folders'], ['Sales'])
        found = client.get('/report-printing/search?folder=Sales&q=Daily').json
        self.assertEqual([r['id'] for r in found['reports']], ['00O123456789012'])
        self.assertEqual(client.get('/report-printing/search?folder=Operations').json['total'], 1)

        response = client.post('/report-printing/save', data={
            'name': 'Morning reports', 'time': '08:30', 'weekday': '0',
            'enabled': 'on', 'report_id': '00O123456789012',
            'report_name_00O123456789012': 'Daily Sales',
        })
        self.assertEqual(response.status_code, 302)
        self.assertEqual(repo.saved.reports[0].report_id, '00O123456789012')
        self.assertEqual(repo.saved.reports[0].name, 'Daily Sales')
        self.assertEqual(repo.saved.hour, 8)
        self.assertEqual(repo.saved.minute, 30)

    @unittest.skipUnless(importlib.util.find_spec('flask'), 'Flask not installed')
    def test_open_folder_refreshes_source_every_time(self):
        from flask import Flask
        from printer_app.report_printing_web import blueprint

        class Source:
            calls = []
            def refresh_report_folder(self, folder):
                self.calls.append(folder)
                count = len(self.calls)
                return [{'id': '00O123456789012', 'name': 'Sales ' + str(count),
                         'folder': folder}]

        class Repository:
            def list(self):
                return []
            def runs(self):
                return []

        source = Source()
        app = Flask(__name__)
        app.register_blueprint(blueprint(Repository(), source))
        client = app.test_client()
        first = client.get('/report-printing/search?folder=Sales')
        second = client.get('/report-printing/search?folder=Sales')
        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(first.json['reports'][0]['name'], 'Sales 1')
        self.assertEqual(second.json['reports'][0]['name'], 'Sales 2')
        self.assertEqual(source.calls, ['Sales', 'Sales'])

    @unittest.skipUnless(importlib.util.find_spec('flask'), 'Flask not installed')
    def test_real_app_accepts_multiple_reports_and_weekdays(self):
        from werkzeug.datastructures import MultiDict
        from printer_app.app import create_app
        from printer_app.config import Config
        from printer_app.tests.auth_helpers import login_admin

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            env = root / 'env'
            env.write_text('EMAIL_ENABLED=0\\n')
            app = create_app(Config(data_dir=root / 'data', env_file=env,
                                    secret_key='s' * 64, email_enabled=False))
            app.testing = True
            client = app.test_client()
            csrf = login_admin(client)
            fields = MultiDict([
                ('csrf', csrf),
                ('name', 'Morning reports'),
                ('time', '08:00'),
                ('weekday', '0'),
                ('weekday', '1'),
                ('enabled', 'on'),
                ('report_id', '00O123456789012'),
                ('report_name_00O123456789012', 'Daily'),
                ('report_id', '00O123456789013'),
                ('report_name_00O123456789013', 'Weekly'),
            ])
            response = client.post('/report-printing/save', data=fields)
            self.assertEqual(response.status_code, 302, response.get_data(as_text=True)[:300])
            from printer_app.report_printing_repository import ReportPrintingRepository
            saved = ReportPrintingRepository(app.extensions['printer_db']).list()
            self.assertEqual(len(saved), 1)
            self.assertEqual(saved[0].weekdays, (0, 1))
            self.assertEqual([r.report_id for r in saved[0].reports],
                             ['00O123456789012', '00O123456789013'])

            duplicate_name = MultiDict(list(fields.items(multi=True)) + [('name', 'Injected')])
            denied = client.post('/report-printing/save', data=duplicate_name)
            self.assertEqual(denied.status_code, 400)
            self.assertIn('Duplicate form field', denied.get_data(as_text=True))

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
    def test_folder_picker_full_browser_flow(self):
        """Real rendered page, real HTTP requests, both browser engines, persisted ID."""
        import threading
        from types import SimpleNamespace
        from flask import Flask, g, session
        from jinja2 import ChoiceLoader, DictLoader, FileSystemLoader
        from playwright.sync_api import sync_playwright, expect
        from werkzeug.serving import make_server
        from printer_app.report_printing_web import blueprint

        records = (
            {'id': '00O123456789012', 'name': 'Daily Sales', 'folder': 'Sales'},
            {'id': '00O123456789013', 'name': 'Weekly Sales', 'folder': 'Sales'},
            {'id': '00O123456789014', 'name': 'Operations Report', 'folder': 'Operations'},
        )

        class Source:
            def search_reports(self, term, **kwargs):
                return tuple(r for r in records if term.casefold() in r['name'].casefold())

            def refresh_report_folder(self, folder):
                return tuple(r for r in records if r['folder'] == folder)

        class Repository:
            saved = None
            def list(self):
                return [self.saved] if self.saved else []
            def runs(self):
                return []
            def save(self, job):
                self.saved = job

        repo = Repository()
        printer_dir = Path(__file__).resolve().parents[1]
        app = Flask(__name__, static_folder=str(printer_dir / 'static'), static_url_path='/static')
        app.secret_key = 'test-secret'
        template_dir = printer_dir / 'templates'
        app.jinja_loader = ChoiceLoader([
            DictLoader({'base.html': '<!doctype html><html><body>{% block content %}{% endblock %}</body></html>'}),
            FileSystemLoader(str(template_dir)),
        ])
        app.register_blueprint(blueprint(repo, Source()))

        @app.before_request
        def setup_request():
            g.printer_config = SimpleNamespace(timezone='UTC')
            session.setdefault('csrf', 'browser-token')

        @app.after_request
        def real_security_policy(response):
            response.headers['Content-Security-Policy'] = ("default-src 'self'; script-src 'self' https://unpkg.com; "
                "style-src 'self' https://unpkg.com; img-src 'self' data:; object-src 'none'")
            return response

        server = make_server('127.0.0.1', 0, app, threaded=True)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        origin = 'http://127.0.0.1:' + str(server.server_port)
        try:
            with sync_playwright() as pw:
                for engine in (pw.chromium, pw.webkit):
                    browser = engine.launch(headless=True)
                    try:
                        page = browser.new_page()
                        errors = []
                        page.on('pageerror', lambda error: errors.append(str(error)))
                        page.goto(origin + '/report-printing/')
                        expect(page.locator('script[src*="report_printing.js"]')).to_have_count(1)
                        expect(page.locator('#folder-results')).not_to_be_visible()
                        page.locator('#add-report').click()
                        expect(page.locator('#folder-results .picker-item')).to_have_count(2)
                        expect(page.locator('#folder-search')).to_have_count(0)
                        page.get_by_role('button', name='Sales', exact=False).first.click()
                        expect(page.locator('#search-results .picker-item')).to_have_count(2)
                        expect(page.locator('#report-search')).to_have_count(0)
                        page.get_by_role('button', name='+ Daily Sales').click()
                        expect(page.locator('#report-list .report-row')).to_have_count(1)
                        self.assertEqual(page.locator('#report-list input[name="report_id"]').input_value(),
                                         '00O123456789012')
                        page.locator('input[name="name"]').fill('Morning Reports')
                        page.locator('#job-form button[type="submit"]').click()
                        expect(page.get_by_text('Morning Reports').first).to_be_visible()
                        self.assertEqual(repo.saved.reports[0].report_id, '00O123456789012')
                        self.assertEqual(repo.saved.reports[0].name, 'Daily Sales')
                        self.assertFalse(errors, errors)
                    finally:
                        browser.close()
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)


if __name__ == '__main__':
    unittest.main()
