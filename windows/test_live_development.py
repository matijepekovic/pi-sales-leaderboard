#!/usr/bin/env python3
"""Live-development serving behavior tests."""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent


class LiveDevelopmentTests(unittest.TestCase):
    def test_html_pages_poll_revision_and_reload(self):
        with tempfile.TemporaryDirectory() as temp:
            env = dict(os.environ)
            env["STATS_DATA_DIR"] = temp
            source = """
from pathlib import Path
from windows.dev_server import _watched_files, create_dev_app

watched = [Path(path) for path in _watched_files()]
assert any(path.name == 'data.js' for path in watched)
assert not any(path.name == 'remote-qr-v109.svg' for path in watched)
assert all(path.suffix.lower() in {'.css', '.html', '.js', '.mjs'} for path in watched)

app = create_dev_app()
client = app.test_client()

page = client.get('/settings')
assert page.status_code == 200
html = page.get_data(as_text=True)
assert 'id="stats-live-reload"' in html
assert 'window.location.reload()' in html
assert '/__stats_live_revision' in html
assert page.headers['Cache-Control'] == 'no-store'

revision = client.get('/__stats_live_revision')
assert revision.status_code == 200
assert revision.get_data(as_text=True).isdigit()
assert revision.headers['Cache-Control'] == 'no-store'

api = client.get('/api/system/version')
assert 'stats-live-reload' not in api.get_data(as_text=True)
"""
            subprocess.run(
                [sys.executable, "-c", source],
                cwd=ROOT,
                env=env,
                check=True,
            )


if __name__ == "__main__":
    unittest.main()
