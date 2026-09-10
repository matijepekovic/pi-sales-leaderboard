# Independent Raspberry Pi printer automation

This directory is a **second application**, not a Stats feature. Its web server, worker, authentication, environment, virtual environments, SQLite database, artifacts, logs and systemd units are all independent. It imports no Stats modules. Stats can be stopped, crashed, updated or removed without stopping an installed printer release, and vice versa. Both applications share only repository distribution. No existing Stats file, route, service, dependency, VERSION or database is modified.

## Printing behavior

**Received PDFs print directly**, including multi-page PDFs. They are checked for readable, non-encrypted PDF content, but are not converted, reformatted or subjected to the Excel one-page rule. Existing queue defaults are retained.

**Oversized attachments are downloaded**, not rejected because of size. `ATTACHMENT_WARN_MB` is a warning only. IMAP downloads use one-megabyte chunks to disk; subsequent MIME decoding still uses memory. The worker has its own memory limit. Low free disk space leaves mail unacknowledged for retry rather than silently losing it. ZIP expansion and cell-count safeguards apply to workbook parsing, not downloading, and produce a processing-error sheet.

Excel `.xlsx`, `.xls` and `.xlsm` files are read as cached values. The largest unambiguous table with a `Sub Status` header is detected. Outer blank area is removed; headers, column order and number formats are preserved. Actual Sub Status values determine the groups; **no status names are hardcoded**. Blank values form a `(blank)` group and are not discarded. Equally sized main-table candidates cause an explicit parser error instead of a guess.

Each group becomes a new **values-only, macro-free workbook** with a defined print area and Tabloid (11×17 inch) landscape layout. Fit-to-width is enabled; height is not forced into one unreadable page. LibreOffice runs headlessly with an isolated profile and a timeout that terminates its complete process group. It never opens the original untrusted workbook. Formula strings remain literal text; cached formulas are not executed. Missing cached formula values cause a clear error rather than printing an incorrect blank result.

The resulting PDF is measured using pypdf. Exactly one page prints the report. Two or more pages print a **one-page physical error sheet instead**, retaining the rejected report for preview/download. Unsupported input, corruption, missing Sub Status, empty tables and conversion failures also produce error sheets. Each rendered group succeeds or fails independently. The error sheet includes filename, email subject, sender, Sub Status, reason, local timestamp and job ID. Long fields are bounded to retain one-page output; full details remain in the UI.

There is **no approval workflow**. Previews are for monitoring only.

## Ownership and replaceability

| Owner | Responsibility |
| --- | --- |
| `bootstrap.py` | This application's sole composition root |
| `config.py`, `.env.example` | Printer-only configuration |
| `db.py` | Connections, schema, migrations, consistent backups |
| `repository.py` | All business-data SQL |
| `contracts.py` | Normalized mail, report, conversion-error and printer contracts |
| `gmail_client.py` | Replaceable read-only IMAP source adapter |
| `parser.py` | Cached-value table detection and dynamic status splitting |
| `converter.py` | Replaceable LibreOffice renderer |
| `printer.py` | Replaceable CUPS adapter |
| `pdfs.py`, `error_pages.py` | Renderer-independent preflight and error-sheet generation |
| `processes.py` | Shared child-process secret-exclusion policy |
| `services.py` | Printing workflows and web-facing monitoring/control contract |
| `worker.py` | Polling, durable commands, single-worker process lock and heartbeat |
| `web.py`, `templates/`, `static/` | Independent HTTP, authentication and UI |
| `deploy.py`, shell scripts, `systemd/` | Printer-only installation and deployment |

Neither the printer adapter nor the workflow nor the error-sheet renderer imports the LibreOffice adapter. Removing or replacing that adapter does not require rewriting them. The printer composition root has no relationship to Stats' composition root. CI checks these boundaries in both directions.

## Installation on the Pi

Inside the repository checkout on **main**, run as **scoreboard**, not root:

```bash
git pull --ff-only origin main
bash printer_app/install.sh
```

Python 3.10+ is required. The installer uses sudo only for system packages and installing/enabling the two printer service units. It installs independent Python dependencies into a new printer-only venv and verifies LibreOffice, `lp`, and existing queue `konicaa`.

**It does not run lpadmin, replace the Konica driver/filter, change Account Track or queue defaults, or modify Stats.** The working Konica Minolta bizhub C360i driver and `KMbeuEmpPS.pl` setup remain outside this application's responsibilities.

First setup asks for a printer UI password of at least 12 characters. There is no default password. The username defaults to `admin`. The private environment file is created outside the repository.

Configure Gmail and filters on the Pi:

```bash
nano ~/.config/printer-app/env
chmod 600 ~/.config/printer-app/env
sudo systemctl restart printer-app-web.service printer-app-worker.service
```

Set `EMAIL_USER`, `EMAIL_APP_PASSWORD`, and the sender/subject filters before enabling real mailbox access. With missing or invalid Gmail credentials, the web and worker stay up but Email Monitor reports an error. Never commit the real environment file or paste credentials into source code.

**The first successful scan prints qualifying attachments within the lookback window, including previously read emails.** Pick filters and `EMAIL_LOOKBACK_DAYS` deliberately before connecting the account. Mail is accessed read-only: no message deletion, flag changes or marking mail as read. Named inline MIME files are treated as attachments; normal email body text is not printed. The rolling lookback window is searched on every poll. After an outage longer than that window, increase it to catch older unprocessed mail.

## Web interface and controls

```text
http://<pi-ip>:5055/system/print-control
```

The root `/` opens the same page. This URL is not added to the Stats menu. The UI has its own login, hashed password, signed cookie, login throttling and CSRF protection. It provides queue status, last print/error, Gmail state, last/next check, Run Now, Pause, Resume, Test Print, Refresh, recent jobs, generated-file downloads, PDF previews, timestamps, processing steps and print-command results.

**Pause stops automatic email polling only.** Already downloaded work, physical error sheets and CUPS reconciliation continue. Run Now performs one email scan even while paused; Test Print submits one local test sheet. To stop this application's processing completely, stop its worker service. Existing jobs already accepted into the CUPS spool are owned by CUPS.

Direct HTTP is for a **trusted LAN only**, not the public internet. Do not port-forward port 5055. Use HTTPS or a trusted VPN for untrusted networks; set `COOKIE_SECURE=1` when the UI is served over HTTPS. The application never exposes Gmail secrets, UI password hashes or arbitrary filesystem paths through its UI. File retrieval uses recorded output IDs and path containment checks.

Unauthenticated basic health contains only four booleans:

```bash
curl -fsS http://127.0.0.1:5055/health
```

Fields are `web_alive`, `database_accessible`, `worker_running`, and `cups_queue_known`. Healthy returns HTTP 200; degraded returns 503. The worker heartbeat is independent of slow email/conversion work. Gmail connection details require login. Queue online/offline status is CUPS-reported, not a separate physical-device probe.

## Services, paths and logs

| Item | Default |
| --- | --- |
| Web unit | `printer-app-web.service` |
| Worker unit | `printer-app-worker.service` |
| Environment | `/home/scoreboard/.config/printer-app/env` |
| Database | `/home/scoreboard/.local/share/printer-app/data/printer_app.db` |
| Attachments and previews | `.../printer-app/data/attachments/` and `.../data/outputs/` |
| Immutable printer code and venvs | `.../printer-app/releases/<content-hash>/` |
| Active / previous release | `.../printer-app/current` and `.../printer-app/previous` |
| Database backups | `.../printer-app/backups/` |

```bash
systemctl status printer-app-web.service printer-app-worker.service
journalctl -u printer-app-web.service -u printer-app-worker.service -f
sudo systemctl restart printer-app-worker.service
```

Both units run as `scoreboard`, start at boot and restart on failure. They have their own working directory, environment, journal identifiers and resource limits. Neither has a Requires/PartOf/BindsTo relationship with Stats or with the other printer unit. The web stays up when the worker is unavailable; the worker continues if the web is stopped. A process lock prevents two workers using the same printer database.

Normal operation needs no root access. Systemd allows writes only under the printer state root. Never point `PRINTER_DATA_DIR` at Stats storage. A custom data location outside that root requires modifying only these printer units' sandbox permissions.

## Update and rollback

From the checkout, as scoreboard:

```bash
bash printer_app/update.sh
```

This refuses a non-main branch or modified tracked files, runs `git pull --ff-only origin main`, and compares printer source content with the active release. Unchanged printer code means **no dependency installation and no printer restart**. Changed printer code is staged into a new independent venv, its database is backed up and migrated, its release symlink is switched, only the two printer units are restarted, and health is checked. A failed activation switches back to the previous printer code. Stats is never stopped or restarted by this command.

Already pulled? Deploy just the printer files:

```bash
python3 printer_app/deploy.py deploy
```

Rollback only printer code without resetting main or reverting unrelated application changes:

```bash
python3 printer_app/deploy.py rollback
```

A previous installed printer release is required. For a first-install undo, disable and stop only the printer units:

```bash
sudo systemctl disable --now printer-app-web.service printer-app-worker.service
```

Rollback **retains the live print ledger**. Do not routinely restore an older print database: forgetting completed jobs risks duplicates. Schema version 1 is used; future migrations must retain rollback compatibility or document explicit recovery. Old code/venvs are deployment snapshots outside the checkout, not duplicate source implementations. They keep running code insulated from Git pulls or Stats updates. Previews and old releases are retained; monitor disk use and archive/remove unneeded data deliberately.

**Important updater distinction:** the current Stats in-app updater is a VERSION-gated ZIP installer that copies only Stats paths. It remains unchanged and its button does not deploy this app. A raw Git pull delivers files but cannot restart services by itself. The printer update command above is the Git-pull-and-deploy entrypoint. Updated Stats files remain subject to Stats' own deployment/restart policy. There is no runtime call from either application into the other.

## Environment variables

| Variable | Default / purpose |
| --- | --- |
| `EMAIL_USER` | Gmail account; required to poll |
| `EMAIL_APP_PASSWORD` | Gmail app password; required to poll |
| `EMAIL_MAILBOX` | `INBOX` |
| `EMAIL_SUBJECT_CONTAINS` | Empty; case-insensitive substring filter |
| `EMAIL_FROM_CONTAINS` | Empty; case-insensitive substring filter, not sender authentication |
| `EMAIL_LOOKBACK_DAYS` | `1`; rolling search window |
| `EMAIL_POLL_SECONDS` | `60`; minimum 10 |
| `ATTACHMENT_WARN_MB` | `25`; warning only, larger files still download |
| `DISK_RESERVE_MB` | `128`; defer mail below this free-space threshold |
| `CONVERSION_TIMEOUT_SECONDS` | `90` |
| `PRINTER_QUEUE` | `konicaa` |
| `PRINTER_HOST` / `PRINTER_PORT` | `0.0.0.0` / `5055` |
| `PRINTER_DATA_DIR` | Separate printer directory listed above |
| `UI_USER` | `admin` |
| `UI_PASSWORD_HASH` | Generated by configure; required |
| `SESSION_SECRET` | Generated random secret; required |
| `COOKIE_SECURE` | `0` for direct LAN HTTP; `1` with HTTPS |
| `TZ` | Example uses `America/Los_Angeles` |
| `PRINTER_ENV` | Optional private environment path override for manual runs |

Change the UI password:

```bash
cd ~/.local/share/printer-app/current
.venv/bin/python -m printer_app configure
sudo systemctl restart printer-app-web.service
```

## Print ledger, retries and physical-output limits

The database records mailbox scope, UIDVALIDITY, UID, Message-ID, attachment hash, each status group, generated paths, page counts, state/errors, processing steps, timestamps, submission tokens and `lp` request IDs. UID and Message-ID deduplication persist across restarts. Hashes are audited, not globally deduplicated: a genuinely new email containing the same report may legitimately require another print.

`SUBMITTED` means accepted by CUPS, not physically printed. Only CUPS state `completed` produces `PRINTED` or `ERROR PRINTED`; this is not independent proof that someone received paper. `failure_kind` retains parser/conversion/printer errors alongside the delivery status. Device-offline jobs accepted by CUPS stay in its spool; the app does not create another copy on every poll. Known report rejection/cancellation/abortion results in an error sheet. Known error-sheet submission failures are retried every 60 seconds, including after restart.

SQLite and a physical printer cannot share an atomic transaction. Each attempt has a unique CUPS title for reconciliation after a crash between submission and database acknowledgement. An interrupted submission without a recoverable receipt is **uncertain**, never blindly resubmitted. After 60 seconds without a known result, an uncertain original report generates one automatic diagnostic sheet; the original remains available for reconciliation and is not sent again. The same applies when a recorded CUPS job's history becomes unavailable. This is automatic error reporting, not manual approval.

If the diagnostic sheet's own submission is also uncertain, its receipt must be reconciled rather than recursively printing more error sheets. The UI records the uncertainty. A broken/offline printer cannot guarantee immediate physical output; an unknowable device outcome cannot simultaneously guarantee exactly-once paper delivery and unlimited automatic retries. Never clear the database simply to force a retry. Preserve CUPS job history for recovery.

## Automated tests

The independent CI workflow installs only printer dependencies and runs real LibreOffice conversion alongside fake IMAP/CUPS adapters, pipeline recovery, oversized downloads, authentication, Python compilation, shell syntax and architecture checks. CI never accesses your mailbox or physically prints. The package is also copied away from the Stats repository and started independently in a subprocess test.

With LibreOffice and CUPS development dependencies installed:

```bash
python3 -m venv /tmp/printer-tests
/tmp/printer-tests/bin/pip install -r printer_app/requirements.txt pytest xlwt
/tmp/printer-tests/bin/python -m pytest printer_app/tests -v
```

## On-Pi acceptance procedure

1. Keep Stats running; install the printer app and verify authenticated UI/health. Record Stats' PID and existing routes. A printer-only deployment must not change them. Stop Stats using its existing service command, verify printer polling and a physical Test Print, then start Stats again. Stop printer units and verify Stats remains operational. Separately stop web and worker to verify their independent lifecycles.
2. Send one-page and two-page **received PDFs**: both print directly. Send XLSX, XLS and XLSM workbooks with arbitrary status names and verify separate Tabloid landscape reports with preserved headers/columns. No macros should execute.
3. Make one Excel group long enough to render to multiple pages. Only its one-page physical error sheet should print; other groups continue. Confirm the rejected PDF remains downloadable. Send corrupt, unsupported, missing-status and empty-table inputs and inspect their physical error sheets.
4. Restart the worker and re-poll the same email: no duplicate report. Send a genuinely new message with identical attachment bytes: it should print. Send an attachment larger than the warning threshold: it still downloads. Check job timestamps, hashes, steps and request IDs.
5. Interrupt Gmail connectivity: the web and worker stay alive and recover. Turn off the printer: jobs remain queued or record errors, never false completion. Restore it and check completion/retry. Pause polling and confirm already downloaded work continues. Verify Run Now, Resume and Test Print.
6. Check independent login, wrong-password throttling, CSRF rejection, authenticated previews and no secret/arbitrary-file disclosure. Confirm only the private example, not real secrets, is committed. Reboot and verify both printer units start without depending on Stats.

Physical Raspberry Pi operation, live Gmail, Account Track and actual printed sheets require this on-device acceptance test; automated tests do not substitute for it.
