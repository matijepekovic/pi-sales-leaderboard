"""Native browser regression for the actual MOD sandbox, not DOM-source assertions."""
from __future__ import annotations

import os
import threading

import pytest

from printer_app.app import create_app
from printer_app.config import Config
from printer_app.mod_sheet_contract import ModSheetRecord
from printer_app.tests.auth_helpers import browser_login


pytestmark = pytest.mark.skipif(
    os.environ.get('PRINTER_BROWSER_TESTS') != '1', reason='CI browser dependencies'
)

MOD = '005000000000001AAA'


class TestSource:
    def __init__(self, records):
        self.records_data = records

    def records(self, **kwargs):
        return tuple(self.records_data)


class TestWriter:
    def __init__(self):
        self.applied = []

    def mod_users(self):
        return [{'id':MOD,'name':'Sample MOD'}]

    def prepare(self, payload):
        return [[('sample',)] for _ in payload]

    def apply(self, plan):
        self.applied.append(plan)


@pytest.fixture(params=['chromium','webkit'])
def mod_browser(tmp_path, request):
    from playwright.sync_api import sync_playwright
    from werkzeug.serving import make_server

    env = tmp_path / 'env'
    env.write_text('EMAIL_ENABLED=0\n')
    app = create_app(Config(data_dir=tmp_path/'data', env_file=env,
                            secret_key='s'*64, email_enabled=False))
    app.testing = True
    source = TestSource([
        ModSheetRecord(source_id='0WO000000000001AAA',
            lead_name='Alex Example',work_order_number='00011111',product_interest='Roofing;Siding'),
        ModSheetRecord(source_id='0WO000000000002AAA',
            lead_name='Blair Sample',work_order_number='00022222',product_interest='Bath'),
    ])
    writer = TestWriter()
    service = app.extensions['mod_resulting']
    service.source = source
    service.writer = writer
    service.refresh(service.day())
    server = make_server('127.0.0.1', 0, app, threaded=True)
    thread = threading.Thread(target=server.serve_forever,daemon=True)
    thread.start()
    origin = f'http://127.0.0.1:{server.server_port}'
    try:
        with sync_playwright() as pw:
            browser = getattr(pw, request.param).launch(headless=True)
            context = browser.new_context(viewport={'width':1200,'height':820})
            try:
                page = context.new_page()
                errors = []
                page.on('pageerror',lambda err:errors.append(str(err)))
                browser_login(page,app,origin)
                yield page,service,writer,origin
                assert not errors
                db = app.extensions['printer_db']
                for table in ('jobs','print_attempts','commands','print_queue_releases'):
                    assert db.rows('SELECT * FROM '+table)==[]
            finally:
                context.close()
                browser.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_mod_sheets_render_as_full_sheets_and_are_searchable_by_name_only(mod_browser):
    from playwright.sync_api import expect

    page,service,writer,origin = mod_browser
    assert page.goto(origin+'/mod-resulting').status==200
    expect(page.locator('.mod-sheet')).to_have_count(2)
    assert page.locator('body > header,body > nav,body > footer').count()==0
    expect(page.locator('#nameSearch')).to_be_visible()
    first = page.locator('.mod-sheet').first
    expect(first.locator('[data-key=numbers]')).to_be_visible()
    expect(first.locator('[data-key=notes]')).to_be_visible()
    expect(first.locator('[data-key=redlines]')).to_be_visible()

    page.locator('#nameSearch').fill('alex')
    expect(page.locator('.mod-sheet:visible')).to_have_count(1)
    page.locator('#nameSearch').fill('00022222')
    expect(page.locator('.mod-sheet:visible')).to_have_count(0)
    page.locator('#nameSearch').fill('')
    expect(page.locator('.mod-sheet:visible')).to_have_count(2)

    first.locator('[data-key=dispo]').select_option('cxl')
    expect(first.locator('.cxl-panel')).to_be_visible()
    first.locator('[data-key=cxl_at_lead]').check()
    first.locator('[data-key=notes]').fill('Black comment')
    first.locator('[data-key=redlines]').fill('REDLINE')
    first.locator('[data-key=numbers]').fill('20000\n17000')
    page.locator('#hideCompleted').check()
    expect(page.locator('.mod-sheet:visible')).to_have_count(1)
    page.locator('#hideCompleted').uncheck()

    # Refresh flushes the changed draft to disk, then reloads Salesforce-owned data.
    page.locator('#refresh').click()
    expect(page.locator('.mod-sheet')).to_have_count(2)
    expect(page.locator('.mod-sheet').first.locator('[data-key=notes]')).to_have_value('Black comment')
    row = service.repository.sheets(service.day())[0]
    assert row['draft']['dispo']=='cxl'
    assert row['draft']['cxl_at_lead'] is True

    page.locator('#dailyMod').select_option(MOD)
    expect(page.locator('#notice')).to_contain_text('Sample MOD')
    assert service.repository.day(service.day())['mod_user_id']==MOD
    page.locator('#submitDay').click()
    expect(page.locator('#endConfirm')).to_be_visible()
    expect(page.locator('#reviewCount')).to_contain_text('1 sheet(s)')
    page.locator('#cancelEnd').click()
    assert not writer.applied
