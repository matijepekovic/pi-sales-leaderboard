"""Prevent invalid/doubled browser code from reaching the MOD interface."""
from pathlib import Path
import shutil
import subprocess


def test_mod_sheet_javascript_syntax_and_single_binding():
    path = Path(__file__).resolve().parents[1] / 'static' / 'mod_resulting' / 'sheet.js'
    source = path.read_text(encoding='utf-8')
    for anchor in (
        'function redraw()',
        'function setup(sheet)',
        'function syncPricePreviews()',
        'const priceDialog =',
    ):
        assert source.count(anchor) == 1, (anchor, source.count(anchor))
    for removed in ('const leadDialog =', 'function syncDnrLeadStatus()',
                    'mobile-call-actions', 'data-lead-trigger'):
        assert removed not in source, removed
    assert source.rstrip().endswith('})();')
    # User redlines are a separate editor, not an ink-mode monkey patch.
    for removed in ('function changedNoteRuns(', 'redInk = !redInk',
                    'const noteMirror =', 'syncNoteMode()'):
        assert removed not in source, removed
    for owner in ('function manualRedlinePreview(', 'function numericExtremes(',
                  'function fitSalePreview(', 'function buildSelection(',
                  'function submitBatch('):
        assert source.count(owner) == 1, owner
    assert 'MOD for today:' not in source
    assert "if (!sheet.hidden) fitSalePreview(sheet);" in source
    assert "String(notes || '').matchAll(" in source
    assert "display.dataset.saleFit = String(level);" in source
    node = shutil.which('node')
    if node:
        result = subprocess.run(
            [node, '--check', str(path)], capture_output=True,
            text=True, timeout=15, check=False,
        )
        assert result.returncode == 0, result.stderr


def test_salesforce_refresh_and_clear_keep_explicit_module_boundaries():
    root = Path(__file__).resolve().parents[1]
    repo = (root/'mod_resulting/repository.py').read_text()
    svc = (root/'mod_resulting/service.py').read_text()
    web = (root/'mod_resulting/web.py').read_text()
    adapter = (root/'mod_resulting/salesforce_adapter.py').read_text()
    mapper = (root/'mod_resulting/salesforce_drafts.py').read_text()

    # Salesforce-specific field paths stay behind the replaceable adapter,
    # never in the web layer, repository, or normalized Stats contracts.
    assert 'from .salesforce_adapter' not in repo
    assert "from .salesforce_adapter" not in svc
    assert "from .salesforce_adapter" not in web
    assert "WO = {" in adapter
    assert 'ranked_results' in mapper
    assert "draft['dispo'] = dispo" in mapper
    assert 'clear_local=clear_local' in svc
    assert 'return self.refresh(day, clear_local=True)' in svc
    assert 'service.clear_local(service.day())' in web
    assert "def clear_local(self, day)" in svc
    assert "def refresh(self, day, records," in repo
    assert "local.get('redlines')" in repo
    assert "mod_result_sf_notes:" in repo
    assert 'repo.writer' not in repo


def test_selected_submission_and_salesforce_field_boundaries_remain_isolated():
    root = Path(__file__).resolve().parents[1]
    repo = (root/'mod_resulting/repository.py').read_text()
    svc = (root/'mod_resulting/service.py').read_text()
    adapter = (root/'mod_resulting/salesforce_adapter.py').read_text()
    html = (root/'templates/mod_resulting.html').read_text()
    assert 'def begin_submit(self, day, work_order_ids=None):' in repo
    assert 'def submitted_sheets(self, day):' in repo
    assert 'self.repository.begin_submit(day, work_order_ids)' in svc
    assert 'self.repository.submitted_sheets(day)' in svc
    assert 'deposit_payment=deposit_payment_text(draft)' in svc
    assert "payload['deposit_payment']" in adapter
    assert "'deposit': ('string', 'textarea')" in adapter
    assert 'Deposit_Payment__c' not in svc
    assert 'Deposit_Payment__c' not in repo
    assert 'Deposit_Payment__c' not in html
    for dialog in ('endConfirm', 'endMethod', 'endSelect'):
        assert html.count('id="' + dialog + '"') == 1
