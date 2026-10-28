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
    node = shutil.which('node')
    if node:
        result = subprocess.run(
            [node, '--check', str(path)], capture_output=True,
            text=True, timeout=15, check=False,
        )
        assert result.returncode == 0, result.stderr
