# Independent Raspberry Pi printer automation

A second application distributed in `matijepekovic/pi-sales-leaderboard`, on
`main`. It is not a Stats feature, blueprint, scheduler or shared service.

## Install and update using the existing leaderboard button

Open **Stats Settings → Software → Check for Updates → Update**. Install v134
or later. After the normal Stats restart, the Software section shows printer
installation progress. When ready, select **Open Print Control**.

No terminal, Git checkout, clone, second repository or separate install command
is needed for this flow. Setup requires Python 3.10+ and the scoreboard user's
existing non-interactive sudo authorization for systemd and package installation.
The updater never adds a sudoers rule or requests a root password in the browser.
Restricted setup permissions produce a visible error instead of a password hang.

Use **Show printer login** in the Software section to retrieve the printer's own
generated username/password. This setup-only handoff requires a set and unlocked
Stats Settings PIN. Save the login, then press **I saved the login** to remove
the temporary cleartext handoff. The printer uses its own password hash/session
secret, not the Stats PIN. Existing printer credentials are preserved on updates.
The initial password is never included in general status or service journals.

Installing the app does not copy or guess Gmail credentials. Until its private
email configuration is supplied, it stays online with Gmail `NOT CONFIGURED`.

## Operational independence

`printer-app-web.service` hosts its own Flask/Waitress UI on port **5055**.
`printer-app-worker.service` owns Gmail polling, conversion and CUPS submission.
Both run as **scoreboard**, start on boot and restart on failure. A kernel file
lock prevents duplicate workers. Neither imports, calls, starts, stops or requires
Stats. They share no database, authentication, scheduler, environment or process.

Each installed release has its own virtual environment under
`~/.local/lib/printer-app/releases/`, selected by `current`. Running processes
resolve that immutable release before Python starts. Replacing the repository or
Stats source does not replace modules/templates underneath a running printer job.

The intentional coupling is **distribution only**: same repository, `main`, and
leaderboard update controls. `app/update_delivery.py` is the packaging adapter.
It starts the printer's standalone setup CLI in **printer-app-install.service**,
a detached systemd job outside Stats' process/cgroup and source directory.
Installation continues even if Stats stops or its source folder is unavailable.

The old ZIP updater only copies `app/` and selected supporting files. The first
v134 startup therefore queues one setup handoff from that delivered directory.
The installer resolves main once, downloads the exact commit archive, verifies
the printer Git tree, then invokes its standalone install script. Later update
checks compare the printer tree independently from Stats VERSION: printer-only
updates do not reinstall/restart Stats; unchanged printer code does not reinstall
dependencies or restart printer services. Setup failures do not abort Stats
updates. Interrupted/failed setup is retried with the same Check/Update buttons.

Leaderboard behavior, its runtime service, database and root requirements remain
unchanged. Only update endpoints, Software controls and deployment packaging were
extended. No printer routes are mounted in Stats.

## Print policy

| Input | Automatic action |
|---|---|
| Valid incoming PDF, any page count | Print the original unchanged using existing queue defaults. |
| XLSX / XLS / XLSM | Find the main table and dynamically split by actual Sub Status values. |
| Excel-generated PDF, exactly one page | Print on Tabloid media with landscape PDF layout. |
| Excel-generated PDF, multiple pages | Retain preview; print only a one-page error sheet for that group. |
| Oversized attachment | Download in full and process normally; size is only a warning. |
| Unsupported/corrupt file, missing Sub Status, no data, conversion failure | Print a one-page error sheet. |
| One group fails | Continue the other groups independently. |
| CUPS unavailable | Keep durable pending jobs and retry; do not claim output while offline. |

There is no manual approval workflow. Incoming multi-page PDFs print normally;
the one-page rule applies only to Excel-generated reports. Status names are never
hardcoded. Headers and column order are preserved. Blank data area is removed.
Missing Sub Status values become explicit error groups rather than disappearing.

The parser searches the first 100 rows for an unambiguous main table. XLS uses
xlrd; XLSX/XLSM use openpyxl. Original Office files never enter LibreOffice.
Fresh values-only workbooks contain no macros, formulas or external links. Source
formulas require cached values. Output uses a bounded print area, repeating
header, 11x17 landscape, one page wide and unrestricted page height. pypdf counts
the resulting pages; excessively long reports are not shrunk to unreadable height.

Oversized attachments are fetched individually, decoded in memory and saved
atomically. `MAX_ATTACHMENT_MB` is only a warning threshold. This is intended for
small reports, not arbitrary-size bulk transfers; MIME/workbook safety checks
still apply. Failed network downloads stay pending. The separate installer ZIP
size bound is not a Gmail attachment-size rejection.

## Gmail and configuration

All secrets belong in `~/.config/printer-app/env` (mode **0600**), never Git.
Configure the printer's own file, not Stats:

```bash
nano ~/.config/printer-app/env
chmod 600 ~/.config/printer-app/env
sudo systemctl restart printer-app-worker.service
```

Set matching filters before connecting Gmail. **The first scan automatically
processes qualifying emails in the lookback window. Empty subject/sender filters
match everything.** The sender substring is not sender authentication. Pause
stops new inbox polls; already downloaded work continues. Run Now checks once
even while paused. Previews never approve or change print decisions.

| Variable | Default / purpose |
|---|---|
| EMAIL_USER | Gmail login; initially empty. |
| EMAIL_APP_PASSWORD | Gmail app password; initially empty. |
| EMAIL_MAILBOX | INBOX |
| EMAIL_SUBJECT_CONTAINS | Case-insensitive substring; empty matches all. |
| EMAIL_FROM_CONTAINS | From-header substring; empty matches all. |
| EMAIL_LOOKBACK_DAYS | 3; range 1–3650. |
| EMAIL_POLL_SECONDS | 60; minimum 10. |
| PRINTER_QUEUE | konicaa |
| PRINTER_HOST / PRINTER_PORT | 0.0.0.0 / 5055 |
| PRINTER_UI_USER | admin |
| PRINTER_UI_PASSWORD_HASH | Generated independent password hash. |
| PRINTER_SECRET_KEY | Generated independent session signing key. |
| PRINTER_SECURE_COOKIE | 0; use 1 behind HTTPS. |
| PRINTER_TIMEZONE | America/Los_Angeles |
| MAX_ATTACHMENT_MB | 20; configurable warning threshold 1–100, not a rejection. |
| CONVERSION_TIMEOUT_SECONDS | 120; range 10–600. |
| PRINTER_RETRY_SECONDS | 60; range 10–3600. |
| PRINTER_DATA_DIR | ~/.local/share/printer-app; rerun install after changing unit write paths. |
| LIBREOFFICE_BIN | /usr/bin/libreoffice |
| PRINTER_ENV_FILE | Optional local CLI environment-file override. |

## URLs, state and logs

Open `http://<pi-ip>:5055/system/print-control` or `http://<pi-ip>:5055/`.
The UI provides status, Run Now, Pause, Resume, Test Print, Refresh, job history,
source downloads, PDF previews, processing steps, timestamps and CUPS receipts.
Use HTTP only on a trusted LAN; do not port-forward 5055. Use an SSH tunnel or
separately configured HTTPS reverse proxy on untrusted networks.

| Purpose | Default location |
|---|---|
| Secrets | ~/.config/printer-app/env |
| Printer database | ~/.local/share/printer-app/printer_app.db |
| Sources / generated files | ~/.local/share/printer-app/attachments/ and jobs/ |
| Migration backups | ~/.local/share/printer-app/backups/ |
| Installed runtime | ~/.local/lib/printer-app/current/ |
| Setup status / initial-login handoff | ~/.local/share/leaderboard-distribution/, private JSON files |

The setup receipt is a file-based distribution contract, never the Stats DB.
Neither running printer service reads it. SQLite print receipts, sources and
previews are retained; monitor disk space and retain the deduplication database.

```bash
journalctl -u printer-app-web.service -u printer-app-worker.service -f
journalctl -u printer-app-install.service -f
curl --fail http://127.0.0.1:5055/health
```

Health returns only `web`, `database`, `worker_running`, `cups_queue_known` booleans
and HTTP 503 when unhealthy. No credentials or email contents are exposed.

## Optional standalone administrator commands

These remain available without Stats; the normal install/update path is the UI.
Run as scoreboard, not root, in a Git checkout on main:

```bash
git pull --ff-only origin main
bash printer_app/install.sh
bash scripts/update-printer-app.sh
```

Interactive installation displays the initial login once in the terminal.
Non-interactive installation uses this explicit setup contract instead:

```text
install.sh --unattended --initial-login-file <private-path> --result-file <path>
```

The caller owns/protects those handoff paths. The result JSON contains `port` and
`changed`; existing env credentials are never reset. Sudo is limited to setup and
service management. No lpadmin, driver installation, filter modification, printer
PIN handling or Account Track changes occur on the Pi. The existing scoreboard
user's CUPS defaults remain available.

After a completed Git pull, deploy without pulling again, or roll back only the
printer runtime:

```bash
python3 printer_app/deploy.py update
python3 printer_app/deploy.py rollback
```

Rollback requires a previous successful release. It never restores an old printer
database (which could erase print receipts) and refuses an incompatible schema.
To stop automation or undo the first installation:

```bash
sudo systemctl disable --now printer-app-web.service printer-app-worker.service
```

Reset the independent printer password:

```bash
cd ~/.local/lib/printer-app/current
.venv/bin/python -m printer_app.bootstrap set-password
sudo systemctl restart printer-app-web.service
```

## Recovery and truthful outcomes

The worker submits with `lp -H hold`, durably saves the CUPS request ID, then
releases automatically. It recovers the existing request after a crash rather
than blindly reprinting the original. `SUBMITTED` is not `PRINTED`: only CUPS
completion becomes PRINTED / ERROR PRINTED. That acknowledgment is not a physical
paper-exit sensor. Offline output cannot be guaranteed.

Lost CUPS history produces a diagnostic rather than blindly repeating the report.
An error sheet with an unknowable outcome remains PRINT UNKNOWN instead of causing
an endless error-page loop. Hardware faults or cancellation may cause partial
output. Exactly-once physical printing cannot be guaranteed across lost history,
hardware failure or restored old databases. Preserve live receipts and spool state.

## Tests and Pi acceptance

In an isolated developer environment:

```bash
python3 -m venv /tmp/printer-tests
/tmp/printer-tests/bin/pip install -r printer_app/requirements.txt pytest xlwt
/tmp/printer-tests/bin/python -m pytest printer_app/tests tests/test_update_delivery.py -v
```

CI covers real LibreOffice rendering, a disposable CUPS file sink, old ZIP updater
compatibility, authentication, initial-login protection, oversized downloads,
deduplication, crash recovery and independent systemd deployment. It never uses a
real Gmail account or physical printer. The delivery smoke test runs real Stats,
stops/removes its source during printer setup, and verifies independent processes
and unchanged-update behavior. All new deployment boundaries have regression tests.

On the Pi verify: first install using the old leaderboard Update button (no Git
checkout); printer-only and unchanged updates; setup failures/retry; independent
Stats/printer stops; boot recovery; own UI authentication; initial-login secrecy
and acknowledgment; one/multi-page incoming PDFs; each Excel format; several real
Sub Status groups including one failing group; multi-page Excel error sheets;
unsupported/corrupt/missing-header/empty inputs; oversized intact downloads;
restart deduplication; Gmail and printer outages; existing Account Track behavior;
unchanged leaderboard data/routes/service and printer driver/filter settings.
