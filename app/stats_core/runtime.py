from dataclasses import dataclass


@dataclass
class Runtime:
    repos: object
    settings: object
    auth: object
    source: object
    reports: object
    filters: object
    screens: object
    display: object
    theme: object
    version: object
    platform: object
    public_endpoints: set
