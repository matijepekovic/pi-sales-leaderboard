from dataclasses import dataclass


@dataclass
class Runtime:
    repos: object
    settings: object
    auth: object
    organization: object
    tableau: object
    pull_policy: object
    rep_refresh: object
    temporary_date: object
    product_refresh: object
    products: object
    preview: object
    snapshots: object
    leaderboard: object
    screens: object
    source: object
    controls: object
    scheduler: object
    theme: object
    version: object
    tv: object
    platform: object
    public_endpoints: set
