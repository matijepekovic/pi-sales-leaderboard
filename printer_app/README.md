# Independent Raspberry Pi printer automation

This is a second application distributed inside `matijepekovic/pi-sales-leaderboard`.
It is not a Stats feature, Flask blueprint, scheduler task, or database module.

## Independence

`printer-app-web.service` serves the printer control UI on port **5055**.
`printer-app-worker.service` owns Gmail polling, workbook processing, PDF creation,
and CUPS submission. Both run as `scoreboard` and have their own lifecycle, data,
environment, logs, and dependencies.

Neither service imports or requires Stats. Stopping Stats must not stop printer
automation, and stopping printer automation must not stop Stats.

Persistent printer state lives outside the repository under the scoreboard user's
home directory. Runtime releases are installed under
`~/.local/lib/printer-app/releases/` and selected through `current`.

## Web UI

Open directly:

```text
http://<pi-ip>:5055/system/print-control
```

or:

```text
http://<pi-ip>:5055/
```

**There is no printer login page.** The control UI opens directly on the trusted
local network. It does not use or depend on the Stats PIN or Stats authentication.
State-changing controls still use a private session token to reject forged POSTs.

Because the UI is intentionally unauthenticated, keep port 5055 on a trusted LAN.
Do not expose it directly to the public internet. If it is later placed behind
HTTPS, `PRINTER_SECURE_COOKIE=1` can be enabled.

The UI shows printer state, Gmail/worker state, Run Now, Pause, Resume, Test Print,
recent jobs, generated files, previews, processing steps, CUPS request results,
and timestamps. Previews are monitoring only; there is no approval workflow.

## Print rules

| Input | Automatic action |
|---|---|
| Incoming valid `.pdf`, any page count | Print the original PDF unchanged using the existing queue defaults. |
| `.xlsx`, `.xls`, `.xlsm` | Detect the main table, discover actual Sub Status values, split into groups, create clean values-only workbooks, and convert each independently. |
| Excel-generated PDF, exactly one page | Print the report as Tabloid 11x17 landscape. |
| Excel-generated PDF, two or more pages | Keep the preview and print only a one-page physical error report for that group. |
| Oversized attachment | Download the entire attachment and process normally; size alone is not an error. |
| Unsupported, corrupt, missing Sub Status, empty, or unsafe input | Print a one-page physical error report. |
| One group fails | Continue every other group. |

Sub Status values are never hardcoded. `.xlsm` files are read as data only; macros
are not executed or preserved in generated output. LibreOffice receives only a
rebuilt values-only workbook, never the original Office file.

Incoming PDFs are not subject to the one-page Excel rule. A multi-page PDF received
by email prints all of its pages.

## Existing printer setup

The application uses the existing CUPS queue:

```text
konicaa
```

It does not install or modify the Konica driver, filter, printer PIN, Account Track,
or queue configuration. Existing CUPS settings remain the source of truth.

## Gmail

Gmail access uses IMAP and the printer app's own environment file:

```text
~/.config/printer-app/env
```

Credentials are not stored in Stats and must not be committed to Git.

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

`MAX_ATTACHMENT_MB` is retained only as a warning threshold. Larger attachments
are still downloaded and processed normally.

The first successful Gmail connection processes matching messages in the configured
lookback window. Empty sender and subject filters match everything, so configure
filters deliberately before enabling mail on a busy mailbox.

## Install

Run as `scoreboard`, not root:

```bash
git pull --ff-only origin main
bash printer_app/install.sh
```

The installer verifies Python, installs the printer app's own Python/system
dependencies, verifies queue `konicaa`, initializes the separate database, installs
its two systemd units, enables them at boot, and starts them.

Normal runtime operations are non-root. `sudo` is used only for system package and
systemd setup.

## Update

From a clean `main` checkout:

```bash
bash scripts/update-printer-app.sh
```

The script pulls `main` and deploys a new printer release only when printer code
changed. It never restarts Stats.

After a pull has already happened:

```bash
python3 printer_app/deploy.py update
```

## Rollback

```bash
python3 printer_app/deploy.py rollback
```

Rollback changes only the printer runtime release. The printer database is not
rolled back because doing so could lose deduplication receipts and cause duplicate
physical output.

## Locations

| Purpose | Default location |
|---|---|
| Environment / secrets | `~/.config/printer-app/env` |
| Database | `~/.local/share/printer-app/printer_app.db` |
| Attachments | `~/.local/share/printer-app/attachments/` |
| Generated jobs/PDFs | `~/.local/share/printer-app/jobs/` |
| Database backups | `~/.local/share/printer-app/backups/` |
| Installed runtime | `~/.local/lib/printer-app/current/` |

The printer database is completely separate from the Stats database.

## Health and logs

```bash
curl --fail http://127.0.0.1:5055/health
```

Health reports only:

```text
web
database
worker_running
cups_queue_known
```

Logs:

```bash
journalctl -u printer-app-web.service -u printer-app-worker.service -f
```

## Crash safety and duplicate prevention

The worker stores durable email/attachment/job identities in its own SQLite DB.
For a new physical output it creates a held CUPS request, records the request ID,
and then releases the job. After a worker crash it reconciles the saved CUPS
request instead of blindly submitting the same report again.

CUPS completion is the available software acknowledgment; it is not an independent
paper-exit sensor. If CUPS history becomes ambiguous, the application surfaces an
unknown/error state rather than automatically duplicating an original report.

## Tests

```bash
python3 -m venv /tmp/printer-app-test-venv
/tmp/printer-app-test-venv/bin/pip install -r printer_app/requirements.txt pytest xlwt
/tmp/printer-app-test-venv/bin/python -m pytest printer_app/tests -v
```

CI covers dynamic Sub Status grouping, incoming multi-page PDFs, Excel conversion,
physical error-page generation, oversize downloads, deduplication, CUPS recovery,
printer/Gmail outages, direct no-login UI access, CSRF protection, path confinement,
secret exclusion, real headless LibreOffice conversion, a disposable CUPS sink,
and independent systemd deployment with no Stats service installed.
