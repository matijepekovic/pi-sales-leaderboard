"""Workflow for the read-only Salesforce Sandbox MOD page."""
from __future__ import annotations

from dataclasses import dataclass, field

from ..mod_sheet_contract import SourceStatus
from .adapter import SalesforceAdapterError


@dataclass(frozen=True)
class SandboxSnapshot:
    status: SourceStatus
    records: tuple = field(default_factory=tuple)
    orgs: tuple = field(default_factory=tuple)
    selected_org: str = ''
    error: str = ''


class SalesforceSandboxService:
    def __init__(self, adapter):
        self.adapter = adapter

    def snapshot(self, target_org=''):
        orgs = tuple(self.adapter.orgs())
        selected = str(target_org or '').strip()
        if not selected:
            default = next((org for org in orgs if org.get('default')), None)
            if default:
                selected = str(default.get('value') or '')
        try:
            status = self.adapter.status(selected)
            records = tuple(self.adapter.mod_sheets_today(selected))
            return SandboxSnapshot(
                status=status,
                records=records,
                orgs=orgs,
                selected_org=selected,
            )
        except SalesforceAdapterError as exc:
            return SandboxSnapshot(
                status=SourceStatus(connected=False, detail=str(exc)),
                orgs=orgs,
                selected_org=selected,
                error=str(exc),
            )
