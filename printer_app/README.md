# Independent Raspberry Pi printer automation

A second application distributed in `matijepekovic/pi-sales-leaderboard`, branch
`main`. This is **not a Stats feature, Flask blueprint, plugin or background task**.

## Architecture and boundaries

`printer-app-web.service` serves its own Flask/Waitress UI on port **5055**.
`printer-app-worker.service` owns Gmail polling, workbook processing and CUPS
submission. The web process only records control commands in the printer database.
A kernel file lock permits exactly one worker. Both services run as **scoreboard**.
Neither service imports, calls, starts, stops or requires Stats. They share no
Stats database, authentication, scheduler, process or environment file.

The installed runtime is a content-addressed release under
`~/.local/lib/printer-app/releases/`, selected by `current`. Each release has its
own virtual environment. Running processes resolve the real release path before
Python starts. Repository pulls, Stats updates and source-folder replacement do
not replace modules, templates or dependencies underneath a running printer job.
Persistent state and credentials live outside both applications' source trees.

The only distribution coupling is the same GitHub repository and `main` branch.
The existing Stats installer, routes, source files, root requirements, VERSION and
service unit are unchanged. The existing Stats UI updater actually uses
VERSION-gated GitHub ZIP downloads; it is **not a Git checkout updater** and does
not install this second application. Use the standalone Git pull command below
for the printer. That pull also updates Stats *source* in the checkout; it does
not reinstall or restart the separate installed Stats runtime.

## Print policy — incoming PDF exception

| Input | Automatic action |
|---|---|
| Incoming valid `.pdf`, any page count | Submit the original PDF unchanged, using existing queue defaults. |
| `.xlsx`, `.xls`, `.xlsm` | Detect the main table, split dynamically by actual Sub Status values, create clean values-only workbooks and convert each separately. |
| Excel-generated PDF, exactly one page | Print that report on Tabloid media, landscape PDF layout. |
| Excel-generated PDF, two or more pages | Retain report preview but print **only a one-page error sheet** for that group. |
| Oversized attachment | Download the entire attachment and process normally; size alone is not an error. |
| Unsupported, corrupt, missing Sub Status, no data, unsafe input | Print a one-page error sheet. |
| One group fails | Continue all other groups. |
| Printer submission rejected or CUPS reports aborted/cancelled | Record the failure; replace the original with an error sheet and retry automatically. |
| CUPS unavailable | Retain durable pending jobs and retry; never claim physical output while offline. |

**Oversized attachments are downloaded, not rejected or truncated.** The existing
`MAX_ATTACHMENT_MB` setting is retained as a warning threshold only; existing env
files need no change. Each attachment is fetched individually in full and decoded
in memory, then saved atomically. This is intended for the small reports used by
this application, not arbitrary-size bulk transfers. MIME-structure and workbook
safety checks remain in place; they do not reject a file merely for exceeding the
attachment warning threshold. Failed network downloads remain pending for retry.

**The last requested rule takes precedence: a two-page incoming PDF prints both
pages. The one-page limit applies only to Excel-generated reports.** There is no
manual approval workflow. Held CUPS submissions are an internal crash-safety
transaction and are released automatically by the worker, not by an operator.

Sub Status values are never hardcoded. Header detection normalizes `Sub Status`,
`SubStatus` and punctuation/case variations. It searches the first 100 rows and
selects the largest unambiguous candidate table. The header and column order are
preserved. Blank rows are removed; rows missing their Sub Status produce a
separate error group rather than disappearing. Ambiguous tables fail explicitly.

Fresh workbooks use only values, a bounded used range, an explicit print area,
repeating header, 11x17 landscape, one page wide and unrestricted page height.
The actual resulting PDF page count decides whether the report prints. Long
content is not forced into one tiny-height page. `.xls` is read with xlrd;
`.xlsx`/`.xlsm` are read with openpyxl. Original Office files are never opened by
LibreOffice. Macros, hyperlinks, external links and formulas are not carried into
output. Formula cells need cached values from a previously saved source workbook;
missing cached values generate an error instead of printing silently blank data.

## Install on the Pi

Run from a **Git checkout on main**, as `scoreboard`, not root:

```bash
git pull --ff-only origin main
bash printer_app/install.sh
```

Setup requires Python 3.10+, installs a private venv and system packages for
LibreOffice/CUPS clients, verifies the existing `konicaa` queue, initializes the
private database, and enables both printer services at boot. `sudo` is limited
to package installation, installing printer unit files and service management.
Normal web, Gmail, conversion, SQLite and print operations are non-root.

**No lpadmin, driver installation, Account Track edits, printer PIN handling or
Konica filter modifications occur on the Pi.** Existing per-user CUPS settings
remain available to the scoreboard user's `lp` command.

The installer generates an independent UI password and signing key. It prints
the initial UI username/password **once to your terminal**, not to the journal.
Save the password. Existing credentials are preserved on reinstall/update.

Configure the private environment file:

```bash
nano ~/.config/printer-app/env
chmod 600 ~/.config/printer-app/env
sudo systemctl restart printer-app-worker.service
```

Set Gmail user/app password, mailbox and matching filters before enabling mail.
**First connection immediately processes matching messages in the lookback
window. Empty subject/sender filters match everything.** Start with a dedicated
mailbox or restrictive filters and a small lookback. Gmail credentials are never
configured in Stats or committed to Git. Without credentials, the worker stays
alive and the UI reports `NOT CONFIGURED`.

Open directly:

```text
http://<pi-ip>:5055/system/print-control
http://<pi-ip>:5055/
```

The UI provides printer/email state, Run Now, Pause, Resume, Test Print, Refresh,
recent jobs, source attachment download, PDF previews, conversion steps, request
IDs, command results and timestamps. Pause stops new inbox polling; already
queued work continues. Run Now performs one check even while paused. Previewing
never authorizes or changes a print decision.

HTTP is suitable only for a trusted local network. Do not port-forward 5055 to
the internet. Use an SSH tunnel or a separately configured HTTPS reverse proxy
on untrusted networks, and set `PRINTER_SECURE_COOKIE=1` when using HTTPS.

## Update, rollback and independent controls

From the same Git checkout:

```bash
bash scripts/update-printer-app.sh
```

The updater requires a clean `main` checkout, uses `git pull --ff-only origin
main`, and compares printer source content with the installed release. Unchanged
printer code means **no dependency installation and no printer restart**. Changed
code is prepared in a new private release, dependencies installed there, database
backed up/migrated, and only the two printer services restarted. A failed health
check restores the previous runtime release. Stats is never restarted by this
script. It works even when Stats is stopped or its database is missing.

After an already-completed Git pull, deploy without pulling Git again:

```bash
python3 printer_app/deploy.py update
```

Roll back only the printer runtime, not the Git branch or Stats:

```bash
python3 printer_app/deploy.py rollback
```

Rollback requires a previous successful release. It never restores an old
printer database: doing that could erase print receipts and cause duplicate
physical reports. A schema newer than the selected release supports is refused.
Old releases are retained for recovery; remove only unreferenced releases when
needed, never `current`/`previous` targets or the live state database.

To undo the first installation or stop printer automation entirely:

```bash
sudo systemctl disable --now printer-app-web.service printer-app-worker.service
```

Independent restart and logs:

```bash
sudo systemctl restart printer-app-web.service printer-app-worker.service
journalctl -u printer-app-web.service -u printer-app-worker.service -f
```

Reset the printer UI password without touching Stats:

```bash
cd ~/.local/lib/printer-app/current
.venv/bin/python -m printer_app.bootstrap set-password
sudo systemctl restart printer-app-web.service
```

## State, health and configuration

Default locations (the installed user's home is `/home/scoreboard`):

| Purpose | Location |
|---|---|
| Secrets | `~/.config/printer-app/env`, mode 0600 |
| Printer database | `~/.local/share/printer-app/printer_app.db` |
| Sources, generated workbooks, report/error PDFs | `~/.local/share/printer-app/attachments/` and `jobs/` |
| Database migration backups | `~/.local/share/printer-app/backups/` |
| Installed release, private venv | `~/.local/lib/printer-app/current/` |
| Logs | Separate systemd journals for web and worker |

SQLite uses WAL, FULL synchronization, parameterized statements and schema
versioning. Tables are `processed_messages`, `attachments`, `jobs`, `outputs`,
`print_attempts`, `steps`, `commands`, `meta`, and persistent login rate limits.
It records account/mailbox/UIDVALIDITY/UID, Message-ID, attachment SHA-256, source
name, Sub Status, output paths, PDF page count, errors, receipts and timestamps.
There is no automatic deletion of receipts or source/output files. Monitor free
space and archive old generated files as needed; retain the deduplication DB.

```bash
curl --fail http://127.0.0.1:5055/health
```

Health is intentionally unauthenticated and returns only four booleans: `web`,
`database`, `worker_running`, `cups_queue_known`. It returns HTTP 503 if any is
false. Queue/worker state comes from the worker's CUPS checks and heartbeat; no
credentials, email details or filesystem paths are exposed.

| Variable | Default / meaning |
|---|---|
| `EMAIL_USER` | Gmail login; empty leaves monitoring unconfigured. |
| `EMAIL_APP_PASSWORD` | Gmail app password; never a Stats secret. |
| `EMAIL_MAILBOX` | `INBOX` |
| `EMAIL_SUBJECT_CONTAINS` | Case-insensitive substring; empty matches all. |
| `EMAIL_FROM_CONTAINS` | Case-insensitive From-header substring; not sender authentication. |
| `EMAIL_LOOKBACK_DAYS` | `3`, allowed 1–3650. |
| `EMAIL_POLL_SECONDS` | `60`, minimum 10. |
| `PRINTER_QUEUE` | `konicaa` |
| `PRINTER_HOST` / `PRINTER_PORT` | `0.0.0.0` / `5055` |
| `PRINTER_UI_USER` | `admin` |
| `PRINTER_UI_PASSWORD_HASH` | Generated password hash; plaintext UI password is not stored. |
| `PRINTER_SECRET_KEY` | Generated independent session signing key. |
| `PRINTER_SECURE_COOKIE` | `0`; use `1` behind HTTPS. |
| `PRINTER_TIMEZONE` | `America/Los_Angeles` |
| `MAX_ATTACHMENT_MB` | `20`; legacy-named warning threshold only (configurable 1–100). Larger attachments are downloaded normally. |
| `CONVERSION_TIMEOUT_SECONDS` | `120`, allowed 10–600. |
| `PRINTER_RETRY_SECONDS` | `60`, allowed 10–3600. |
| `PRINTER_DATA_DIR` | `~/.local/share/printer-app`; rerun install after changing so unit write permissions update. |
| `LIBREOFFICE_BIN` | `/usr/bin/libreoffice` |
| `PRINTER_ENV_FILE` | Local CLI override; installed units always use the rendered private env path. |

## Crash safety and truthful print outcomes

The worker writes a unique attempt token, submits with `lp -H hold`, durably
stores the CUPS request ID, and then issues `lp -i <request-id> -H resume`.
After a crash it finds the already-held request by token or resumes monitoring
the saved ID. It does not blindly submit the original again. An attachment and
each Sub Status job have durable identities; completed work is skipped on restart.

`SUBMITTED` is not `PRINTED`. Only CUPS `job-completed` becomes `PRINTED` or
`ERROR PRINTED`. CUPS completion is the available acknowledgment, **not an
independent sensor proving sheets physically exited the Konica**. Offline paper
output cannot be guaranteed. Queued jobs persist and recover automatically.

If CUPS loses a released job's history, the outcome is ambiguous. The original
is never blindly reprinted; one diagnostic error sheet is prepared. If the error
sheet's own completion becomes unknowable, `PRINT UNKNOWN` remains visible rather
than generating an endless stream of error pages. A cancelled/aborted original
may have partially printed before failure. Exactly-once physical output cannot
be guaranteed across printer hardware failure, manually altered queues or lost
CUPS/database history. Do not clear spool/history or restore an old DB while
attempts are in flight.

## Tests

Run from repository root in a separate development environment:

```bash
python3 -m venv /tmp/printer-app-test-venv
/tmp/printer-app-test-venv/bin/pip install -r printer_app/requirements.txt pytest xlwt
/tmp/printer-app-test-venv/bin/python -m pytest printer_app/tests -v
```

The GitHub workflow installs LibreOffice and a disposable local CUPS file sink,
then tests the real held-receipt/release protocol and isolated systemd deployment
with no Stats service. No CI test connects to Gmail or a physical printer. Unit tests cover arbitrary status names, table/header errors,
missing formula cache, values-only workbooks, one/multi-page incoming PDFs,
per-group conversion/page failures, unsupported/corrupt files, one-page error
reports, duplicate UIDs/Message-IDs, restart recovery, held submission recovery,
printer outages, unknown completion, standalone auth, CSRF, rate limiting,
preview path confinement, secret exclusion and no Stats imports/service links.
Oversized-download regression tests cover declared and decoded size, all supported
transfer encodings, intact multi-page PDF bytes, restart deduplication and network
failure recovery without converting an oversized attachment into a size error.

### Hardware acceptance on your Pi (not implied by CI)

Record results for these checks after installation:

1. Stats is still serving its existing display/settings routes; compare its
   service unit and source with the pre-install copy.
2. Printer web and worker start independently; `/health` is healthy.
3. Stop `pi-tableau-leaderboard.service`; printer Test Print and Gmail still work.
4. Restart Stats, then stop both printer units; Stats remains usable. Restore both.
5. Email a one-page PDF: original prints once, preview and receipt appear.
6. Email a two-page PDF: **both original pages print**, per the PDF exception.
7. Email each supported Excel format and verify readable Tabloid landscape output.
8. Include several real Sub Status values; verify each separate output.
9. Include one overflowing group; only its one-page error sheet prints while
   other groups print normally. Inspect the retained multi-page preview.
10. Send an unsupported attachment; verify its physical one-page error.
11. Send a corrupt workbook, missing Sub Status header, and empty table; verify
    the correct physical error reasons.
12. Recheck the same email, restart the worker mid-job and recheck again; verify
    one original submission/request is reused, not duplicated. Send an attachment
    above `MAX_ATTACHMENT_MB` and verify it downloads intact without a size error.
13. Reboot; both printer units return automatically and completed jobs stay deduped.
14. Interrupt Gmail connectivity; UI/heartbeat remain alive and polling recovers.
15. Interrupt the printer/CUPS connection; failures are visible and pending output
    recovers without recursive error-sheet creation.
16. Confirm unauthenticated UI, controls and previews are blocked; Stats credentials
    do not unlock the printer UI.
17. Confirm env is mode 0600 and Git tracks no credential/data files.
18. Confirm Stats routes, service, SQLite state, requirements and VERSION remain
    unchanged by printer install/update/rollback.

## Upstream interfaces

- Python IMAP: https://docs.python.org/3/library/imaplib.html
- CUPS lp (hold/resume): https://www.cups.org/doc/man-lp.html
- LibreOffice CLI and isolated profile: https://help.libreoffice.org/latest/en-US/text/shared/guide/start_parameters.html
- openpyxl print settings: https://openpyxl.readthedocs.io/en/stable/print_settings.html
- Flask security: https://flask.palletsprojects.com/en/stable/web-security/
