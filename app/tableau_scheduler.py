#!/usr/bin/env python3
"""Compatibility facade for the restructured scheduler.

New runtime composition configures one SchedulerService. Legacy theme code may
still call start_tableau_scheduler(), but this module installs nothing and
never reaches into QR, controls, source, theme, or server internals.
"""
from __future__ import annotations

_SCHEDULER = None
_PRODUCT_SERVICE = None
_AUTOSTART_ENABLED = True


def configure(scheduler, product_service=None, autostart=True):
    global _SCHEDULER, _PRODUCT_SERVICE, _AUTOSTART_ENABLED
    _SCHEDULER = scheduler
    _PRODUCT_SERVICE = product_service
    _AUTOSTART_ENABLED = bool(autostart)


def start_tableau_scheduler():
    if not _AUTOSTART_ENABLED:
        return False
    return _SCHEDULER.start() if _SCHEDULER is not None else False


def refresh_product_close(settings):
    if _PRODUCT_SERVICE is None:
        return False
    return _PRODUCT_SERVICE.refresh(settings, raise_errors=False)
