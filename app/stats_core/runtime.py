from dataclasses import dataclass


@dataclass
class Runtime:
    repos: object
    settings: object
    auth: object
    organization: object
    tableau: object
    rep_refresh: object
    temporary_date: object
    products: object
    snapshots: object
    leaderboard: object
    source: object
    controls: object
    scheduler: object
    theme: object
    version: object
    tv: object
    platform: object
    public_endpoints: set
