#!/usr/bin/env python3
"""Compatibility entrypoint for the restructured Stats application.

The application is composed in stats_core.bootstrap. This file intentionally
contains no feature business logic, route patching, scheduler setup, or
platform-specific behavior.
"""
from __future__ import annotations

from stats_core.bootstrap import create_app

app = create_app("windows")
runtime = app.extensions["stats_runtime"]
PUBLIC_ENDPOINTS = runtime.public_endpoints
PERSISTENT_DATA_DIR = runtime.platform.data_dir


def software_version():
    return runtime.version.current()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8765, threaded=True)
