# Independent Raspberry Pi printer automation

This directory is a **second application**, not a Stats feature. It has its own Flask instance, Waitress web process, worker process, authentication, environment, virtual environment, SQLite database, artifacts, logs and systemd units. It imports no Stats modules. Stats can be stopped, crashed, updated or removed without stopping an installed printer release, and vice versa. Both applications share only repository distribution. No existing Stats file, route, service, dependency or database is modified.

## Final behavior

* **Received PDFs print directly**, including multi-page PDFs. They are validated as readable, non-encrypted PDFs but are neither converted nor subjected to the Excel one-page limit. Existing queue defaults are retained for these PDFs.
* `.xlsx`, `.xls` and `.xlsm` are read as cached values. The largest unambiguous table with a `Sub Status` header is detected, outer blank area is removed, headers/column order are preserved, and actual Sub Status values determine the groups. No status names are hardcoded. Blank values form a `(blank)` group. A tie between main-table candidates is a parser error rather than a guess. Rows with data but blank status are not discarded.
* Each group becomes a new **values-only, macro-free** workbook, with Tabloid (11×17 inch) landscape layout and a bounded print area. Fit-to-width is enabled; height is not forced into one unreadable page. The actual resulting PDF is checked using pypdf. One page prints the report. Two or more pages print a **one-page physical error sheet instead**, with the rejected report retained for preview/download.
* Unsupported files, corrupt input, missing Sub Status, empty tables, uncached formulas and conversion failures produce one-page error sheets. A failing group does not cancel the others. There is **no approval queue**.
* **Oversized attachments are downloaded**, not rejected because of size. `ATTACHMENT_WARN_MB` is only a warning. IMAP downloads use one-megabyte chunks to disk. MIME decoding still uses memory; the worker has a separate systemd memory limit. Free-disk protection leaves messages unacknowledged for retry rather than discarding them. ZIP expansion and cell-count safeguards apply to parsing, not downloading, and produce a physical processing-error sheet.

## Ownership and boundaries

`bootstrap.py` is this application's composition root. `config.py` owns only its environment. `db.py` owns connection/schema/migration/backup; all business SQL is in `repository.py`. `contracts.py` defines normalized mail, report and printer contracts. `gmail_client.py`, `converter.py` and `printer.py` are replaceable adapters. `parser.py` reads tables without Office execution. `services.py` owns workflows and the monitoring/control contract. `worker.py` owns polling, a process lock, commands and heartbeat. `web.py`, `templates/` and `static/` own HTTP/UI. `error_pages.py` renders fixed one-page error sheets independently of LibreOffice. There is no dependency on Stats bootstrap or runtime.

## Install on the Pi

Run as **scoreboard**, inside the existing checkout on **main**:

```bash
git pull --ff-only origin main
bash printer_app/install.sh
```

The installer uses sudo only to install Python/LibreOffice/CUPS-client build dependencies and install/enable the two service units. **It does not use lpadmin, replace the Konica driver/filter, change queue options, change Account Track, or alter Stats.** It verifies that `konicaa` already exists. Python 3.10 or newer is required. Both running services are non-root `scoreboard` processes. A private UI password is requested during first setup; there is no default password.

Then configure the mailbox and filters in the private environment file:

```bash
nano ~/.config/printer-app/env
chmod 600 ~/.config/printer-app/env
sudo systemctl restart printer-app-web.service printer-app-worker.service
```

Enter Gmail app credentials only on the Pi, never into the repository. With no Gmail credentials, the web UI and worker still start, but the Email Monitor reports a connection error. Before adding credentials, set the sender/subject filters and lookback window deliberately: the first successful scan processes qualifying attachments in that window, even if mail is already marked read. No flags, labels, messages or attachments are deleted or changed in Gmail. A sliding lookback window is used on each poll; increase it after an outage longer than the window to catch older unprocessed messages. Inline MIME parts with filenames are treated as attachments; ordinary email body text is not printed.

Web: `http://<pi-ip>:5055/system/print-control` (also `/`). This is separate from Stats and absent from its menu. UI username defaults to `admin`; the password is the one chosen at installation. Use only on a trusted LAN; HTTP is not encrypted. Do not port-forward this service. For untrusted networks, use an HTTPS reverse proxy or a trusted VPN; set `COOKIE_SECURE=1` when serving via HTTPS. Authentication, CSRF protection, login throttling and cookies are independent of Stats. No filesystem browsing or secret-reading endpoint is provided.

The health route is unauthenticated and contains only four booleans:

```bash
curl -fsS http://127.0.0.1:5055/health
```

It checks web liveness, database access, fresh worker heartbeat and the worker's knowledge of the CUPS queue. Gmail authentication is reported only in the authenticated UI. Printer online/offline status is **CUPS-reported**, not a separate physical network probe.

## Services, storage and logging

| Item | Location / command |
| --- | --- |
| Web unit | `printer-app-web.service` |
| Worker unit | `printer-app-worker.service` |
| Private environment | `/home/scoreboard/.config/printer-app/env` |
| Database | `/home/scoreboard/.local/share/printer-app/data/printer_app.db` |
| Attachments and previews | `.../data/attachments/` and `.../data/outputs/` |
| Immutable deployed code and venvs | `.../printer-app/releases/<content-hash>/` |
| Active / previous release | `.../printer-app/current` and `.../printer-app/previous` |
| Database deployment backups | `.../printer-app/backups/` |

```bash
systemctl status printer-app-web.service printer-app-worker.service
journalctl -u printer-app-web.service -u printer-app-worker.service -f
sudo systemctl restart printer-app-worker.service
```

There are no Requires/PartOf/BindsTo relationships with Stats or with each other. The web stays up when the worker is unavailable; health becomes degraded. The worker continues when the web is stopped. Each has its own cgroup, restart policy and journal identifier. A persistent advisory lock prevents two printer workers from owning the same data directory. Never point `PRINTER_DATA_DIR` at Stats storage. The supplied unit sandbox permits writes only below the printer state root; custom data paths require adjusting **only these printer units**.

## Update and rollback

From the repository checkout, as scoreboard:

```bash
bash printer_app/update.sh
```

This checks that the checkout is `main`, refuses modified tracked files, performs `git pull --ff-only origin main`, and compares the printer source content to the active printer release. If printer code is unchanged, neither printer service is restarted. If changed, it installs dependencies into a **new printer-only virtual environment**, installs printer units, backs up the printer database, migrates, switches the active release, restarts **only the printer units**, and checks health. A failed activation switches back to the prior printer code. Stats is never stopped or restarted by this command. Updated Stats files in the checkout follow Stats' own deployment/restart policy.

Already pulled? Deploy without another pull:

```bash
python3 printer_app/deploy.py deploy
```

Rollback printer code independently, without resetting `main`, reverting unrelated commits or deleting job history:

```bash
python3 printer_app/deploy.py rollback
```

Do **not** restore an old print database as a routine rollback: forgetting completed jobs can cause duplicate physical output. Rollback retains the live print ledger. Schema version 1 is used; future migrations must preserve rollback compatibility or explicitly document a recovery plan. Deployed release directories are deployment snapshots, not competing implementations or version-numbered source files. They are intentionally outside the source checkout so Git pulls/Stats updates cannot replace code in a running printer process. Old releases and previews are retained; monitor disk use and remove only unreferenced releases/archived artifacts after preserving required records.

**Existing updater distinction:** the current Stats in-app updater is a VERSION-gated ZIP installer that copies only Stats paths. It is deliberately unchanged; its button does not deploy this application. A raw `git pull` delivers the files but does not restart a service by itself. Use the command above as the Git-pull-and-printer-deploy entrypoint. This is not a runtime call from Stats into the printer application.

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
| `ATTACHMENT_WARN_MB` | `25`; warning only, **not a rejection threshold** |
| `DISK_RESERVE_MB` | `128`; retry mail later below this free-space threshold |
| `CONVERSION_TIMEOUT_SECONDS` | `90` |
| `PRINTER_QUEUE` | `konicaa` |
| `PRINTER_HOST` / `PRINTER_PORT` | `0.0.0.0` / `5055` |
| `PRINTER_DATA_DIR` | Printer-owned directory listed above |
| `UI_USER` | `admin` |
| `UI_PASSWORD_HASH` | Generated by configure; required, never a plaintext UI password |
| `SESSION_SECRET` | Generated random secret; required |
| `COOKIE_SECURE` | `0` for direct LAN HTTP; use `1` with HTTPS |
| `TZ` | Example uses `America/Los_Angeles`; local time shown on sheets/UI |
| `PRINTER_ENV` | Optional override of the private environment-file path for manual runs |

Change the UI password with the deployed interpreter, then restart only the web unit:

```bash
cd ~/.local/share/printer-app/current
.venv/bin/python -m printer_app configure
sudo systemctl restart printer-app-web.service
```

## Delivery, retries and the physical-print boundary

The database records mailbox scope, UIDVALIDITY, UID, Message-ID, attachment hash, each Sub Status job, artifacts, page counts, processing steps, timestamps, every submission token and the `lp` request ID. UID identity and Message-ID prevent replay of a processed message across restarts. Hashes are recorded, not globally deduplicated: two deliberately separate messages with identical attachments may legitimately need two prints.

`SUBMITTED` means accepted by CUPS, **not printed**. Only CUPS state `completed` produces `PRINTED` or `ERROR PRINTED`. CUPS does not provide independent confirmation that a person received a complete physical sheet. If the device is offline but CUPS accepts the job, the existing CUPS spool waits; the app does not submit copies on every poll. A known rejected/canceled/aborted report is replaced by an error sheet. Known failures to submit an error sheet are retried after 60 seconds, including after worker restart. Missing CUPS history is not treated as success.

There is no distributed transaction between SQLite and a physical printer. A unique CUPS job title lets the worker reconcile a process crash after `lp` accepted the job but before its request ID was committed. If an interrupted submission cannot be found in CUPS history, its state is **uncertain** and automatic duplicate submission is blocked. Do not clear that state/database merely to force retry. This exceptional state requires inspecting CUPS/job history; it is not a manual-approval workflow. No program can guarantee both exactly-once physical output and automatic retry when the printer's outcome has become unknowable. The UI records this explicitly rather than claiming a successful print.

## Tests

CI runs the independent test suite, real LibreOffice rendering tests, Python compilation, shell syntax checks and architectural boundary checks. Tests use fake mail and printer adapters: **CI never accesses your mailbox or physically prints**.

```bash
python3 -m venv /tmp/printer-tests
/tmp/printer-tests/bin/pip install -r printer_app/requirements.txt pytest xlwt
/tmp/printer-tests/bin/python -m pytest printer_app/tests -v
```

On the actual Pi, with the real mailbox/queue configured:

1. Keep Stats running; install this app and verify its authenticated UI and `/health`. Record Stats' PID. A printer-only update must not change that PID or its routes.
2. Stop Stats with its existing service command; verify the printer UI, Gmail poll and a physical Test Print. Start Stats again. Stop both printer units; verify Stats still works. Restart the printer units. Separately stop the web unit and verify the worker continues processing, then reverse the test.
3. Send a one-page **and a two-page received PDF**: both print directly (the final PDF instruction overrides the original one-page restriction for received PDFs).
4. Send XLSX/XLS/XLSM fixtures with multiple **arbitrary** Sub Status names. Check separate Tabloid landscape PDFs, header/column preservation and actual output.
5. Make one group long enough to render to multiple pages: only its one-page error sheet prints, other groups print normally. Check the rejected PDF is downloadable. Send a corrupt workbook, a missing-status workbook and an unsupported attachment; each produces a physical error sheet.
6. Restart worker after ingestion and poll the same message again: no duplicate report. A distinct new email carrying the same attachment should still print. Send an attachment over the warning threshold: it is downloaded, not rejected for size.
7. Disconnect Gmail: polling records an error while web/worker remain alive; restore credentials/network and verify recovery. Turn the printer off: check that jobs stay queued or show recorded errors, never false completion. Turn it on and verify completion/retry. Retain CUPS job history for crash reconciliation.
8. Verify login, incorrect credentials, CSRF rejection, authenticated previews, no secret disclosure, and no ability to request arbitrary files. Reboot and confirm both printer units start independently of Stats.

The Konica Minolta bizhub C360i, its `KMbeuEmpPS.pl` filter and working Account Track setup are intentionally outside this application's responsibilities.
