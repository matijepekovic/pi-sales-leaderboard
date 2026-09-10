# Independent Raspberry Pi printer automation

A second application distributed in `matijepekovic/pi-sales-leaderboard` on
`main`. It is not a Stats feature, blueprint, scheduler, database module, or
shared runtime service.

## Install and update using the leaderboard button

Use **Stats Settings → Software → Check for Updates → Update**. Stats v134 and
later treat `printer_app` as an independently deployable bundle. The same Update
button performs first installation and later printer-only updates.

No Git checkout, second repository, or separate printer install command is
required for the normal appliance flow. Printer-only changes do not reinstall or
restart Stats. Unchanged printer code does not reinstall dependencies or restart
printer services.

When installation is ready, the Software section exposes **Open Print Control**.

## Printer control UI

Open:

```text
http://<pi-ip>:5055/system/print-control
```

or:

```text
http://<pi-ip>:5055/
```

**There is no printer login page.** Print Control opens directly on the trusted
local network. It does not use or depend on the Stats PIN or Stats authentication.
State-changing buttons still use an independent session token to reject forged
POST requests.

Because the UI is intentionally unauthenticated, keep port 5055 on a trusted LAN.
Do not expose it directly to the public internet.

Existing v134 installs may still contain the old `PRINTER_UI_USER` and
`PRINTER_UI_PASSWORD_HASH` lines in their private environment file. They are
ignored by the UI. The old password hash is read only for defensive log redaction
and can remain in place without affecting behavior.

## Operational independence

`printer-app-web.service` hosts its own Flask/Waitress UI on port **5055**.
`printer-app-worker.service` owns Gmail polling, conversion, and CUPS submission.
Both run as **scoreboard**, start on boot, and restart on failure.

Neither service imports, calls, starts, stops, or requires Stats. They share no
Stats database, authentication, scheduler, environment, or process lifecycle.

Each installed printer release has its own virtual environment under
`~/.local/lib/printer-app/releases/`, selected by `current`. Persistent printer
state and credentials live outside both source trees.

The intentional coupling is distribution only: same repository, `main`, and the
leaderboard update controls. `app/update_delivery.py` is the packaging boundary.
It launches the printer's standalone installer in a detached systemd setup job.
No printer runtime runs inside the Stats process.

The v134 delivery adapter still passes the former `--initial-login-file` argument
during an upgrade. The no-login printer installer accepts that argument only for
v134 compatibility and deletes any stale handoff file. It never creates a new
printer password.

## Print policy

| Input | Automatic action |
|---|---|
| Valid incoming PDF, any page count | Print the original unchanged using existing queue defaults. |
| XLSX / XLS / XLSM | Find the main table and dynamically split by actual Sub Status values. |
| Excel-generated PDF, exactly one page | Print on Tabloid 11x17 landscape. |
| Excel-generated PDF, multiple pages | Retain preview; print only a one-page error sheet for that group. |
| Oversized attachment | Download in full and process normally; size is only a warning. |
| Unsupported/corrupt file, missing Sub Status, no data, conversion failure | Print a one-page error sheet. |
| One group fails | Continue the other groups independently. |
| CUPS unavailable | Keep durable pending jobs and retry; do not claim output while offline. |

There is no manual approval workflow. Incoming multi-page PDFs print normally;
the one-page rule applies only to Excel-generated reports. Sub Status values are
never hardcoded.

The parser preserves headers and column order and removes irrelevant blank area.
XLS uses xlrd; XLSX/XLSM use openpyxl. Original Office files never enter
LibreOffice. Generated workbooks are values-only and do not preserve macros,
formulas, external links, or Office automation.

Excel output uses a bounded print area, repeating header, 11x17 landscape, one
page wide, and unrestricted page height. The actual rendered PDF page count makes
the print decision.

## Gmail and configuration

All secrets belong in:

```text
~/.config/printer-app/env
```

The printer app never stores Gmail credentials in Stats or Git.

Important variables:

```text
EMAIL_USER=
EMAIL_APP_PASSWORD=
EMAIL_MAILBOX=INBOX
EMAIL_SUBJECT_CONTAINS=
EMAIL_FROM_CONTAINS=
EMAIL_LOOKBACK_DAYS=3
EMAIL_POLL_SECONDS=60
PRINTER_QUEUE=konicaa
PRINTER_HOST=0.0.0.0
PRINTER_PORT=5055
PRINTER_SECRET_KEY=
PRINTER_TIMEZONE=America/Los_Angeles
PRINTER_SECURE_COOKIE=0
MAX_ATTACHMENT_MB=20
CONVERSION_TIMEOUT_SECONDS=120
PRINTER_RETRY_SECONDS=60
```

`MAX_ATTACHMENT_MB` is a warning threshold only. Larger email attachments are
still downloaded and processed normally.

The first successful Gmail scan processes qualifying messages in the configured
lookback window. Empty subject and sender filters match everything, so configure
filters deliberately before enabling a busy mailbox.

## Existing printer setup

The application uses the existing CUPS queue:

```text
konicaa
```

It does not install or modify the Konica driver, `KMbeuEmpPS.pl`, Account Track,
printer PIN, or queue configuration.

## State and logs

| Purpose | Default location |
|---|---|
| Private environment | `~/.config/printer-app/env` |
| Printer database | `~/.local/share/printer-app/printer_app.db` |
| Attachments | `~/.local/share/printer-app/attachments/` |
| Generated jobs / PDFs | `~/.local/share/printer-app/jobs/` |
| Migration backups | `~/.local/share/printer-app/backups/` |
| Installed runtime | `~/.local/lib/printer-app/current/` |
| Distribution status | `~/.local/share/leaderboard-distribution/` |

Logs:

```bash
journalctl -u printer-app-web.service -u printer-app-worker.service -f
journalctl -u printer-app-install.service -f
```

Health:

```bash
curl --fail http://127.0.0.1:5055/health
```

Health returns only `web`, `database`, `worker_running`, and `cups_queue_known`.

## Optional standalone administrator commands

The normal install/update path is the leaderboard UI. These remain available for
administration from a clean Git checkout on `main`:

```bash
bash printer_app/install.sh
bash scripts/update-printer-app.sh
python3 printer_app/deploy.py rollback
```

Normal printer runtime is non-root. Setup uses sudo only for system packages and
systemd service management. No printer driver or Account Track changes occur.

## Crash safety

The worker creates a held CUPS request, records the request ID durably, then
releases the job automatically. After a crash it reconciles the existing request
instead of blindly submitting the original again.

CUPS completion is the available software acknowledgment, not a physical paper
sensor. Ambiguous CUPS history is surfaced rather than causing automatic duplicate
reports.

## Testing

CI covers direct no-login UI access, CSRF protection, dynamic Sub Status grouping,
PDF and Excel processing, oversized downloads, deduplication, real LibreOffice
rendering, a disposable CUPS sink, restart recovery, printer/Gmail outages, v133
old-ZIP upgrade compatibility, v134 printer delivery compatibility, and independent
systemd lifecycle tests with Stats stopped.

The architectural invariant remains: the printer module can be replaced without
rewriting unrelated Stats code; only its distribution adapter knows how to deploy
it.
