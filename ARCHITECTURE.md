# Stats runtime architecture

The Windows production runtime is composed by `app/stats_core/bootstrap.py`.
Feature modules do not install or mutate unrelated feature modules.

## Ownership

- `stats_core/repositories.py` — persistence adapters over the existing database/schema.
- `services/settings.py` — settings validation, public settings, feature access.
- `services/auth.py` — PIN/security.
- `services/organization.py` — teams, leaders, assignments, team logos.
- `services/tableau.py` — Tableau runtime configuration/source construction.
- `services/rep_refresh.py` — rep refresh and missing-rep/source-organization policy.
- `services/source.py` — Tableau discovery, preview, test and manual refresh.
- `services/temporary_date.py` — temporary rep/product date snapshots.
- `services/product.py` — Product Close Rates data, markets and refresh.
- `services/snapshot.py` — display snapshot priority: mapping preview → temporary → stored.
- `services/leaderboard.py` — leaderboard calculations and screen payloads.
- `services/controls.py` — screen rotation, keyboard/mouse mappings and QR position.
- `services/scheduler.py` — timing only; calls refresh services.
- `services/theme.py` — one boundary around the existing theme engine/extensions.
- `services/tv.py` — platform-neutral TV control intent.
- `platform/windows.py` — Windows restart/fullscreen/updater/Tableau-login/theme-transform integration.
- `web/*` — thin Flask HTTP adapters only.
- `windows/server_entry.py` — process entrypoint only.

## Composition rule

`bootstrap.py` is the only composition root. Scheduler must not install routes.
QR must not install product/theme/control features. Feature services must not
replace functions in other modules at runtime.

## Releases

Production pushes build and test Windows artifacts. Publishing a public release
is a separate explicit workflow-dispatch action; changing production code does
not create a new public version automatically.
