from dataclasses import dataclass


@dataclass
class Runtime:
    repos: object
    settings: object
    auth: object
    source: object
    reports: object
    report_updates: object
    filters: object
    groups: object
    fields: object
    table_presets: object
    widgets: object
    screens: object
    display: object
    theme: object
    version: object
    platform: object
    public_endpoints: set
