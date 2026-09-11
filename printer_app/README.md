# Independent Raspberry Pi printer automation

A second application in `matijepekovic/pi-sales-leaderboard`, delivered on `main`.
It does not import or require the Stats app, routes, database, scheduler or service.

## Install or update

**Leaderboard → Settings → Software → Check for Updates → Update**.
Wait for printer installation to finish, then use **Open Print Control**. No
terminal, separate clone or installer is needed. Stats v134 and later detect
printer-only updates separately; these do not reinstall or restart Stats.

Open `http://<pi-ip>:5055/` or `/system/print-control`. Settings are at `/settings`.
There is no printer login. Keep port 5055 on a trusted LAN: anyone who can access
it can control printing, read previews and change settings. CSRF and same-origin
checks protect writes; they are not user authentication. Stats authentication is
not used. After updating, reopen Settings rather than resubmitting an old page.

## Keep collecting emails; print on selected days

Open **Print Control → Settings → When reports print**. Choose **Queue emails
until my weekly schedule**, select any combination of Monday–Sunday, set the time,
and **Save Settings**. That same time repeats on every selected day using the
printer timezone shown in the form. Change the timezone under Printing and time.
Keep **Enable automatic email printing** on to keep gathering emails.

The dashboard shows the saved schedule, next release time, waiting attachment
count and collected files, with links to prepared previews. Reports and error
sheets are held in the printer app's SQLite queue, not submitted to CUPS early.
There is no per-job approval workflow.

Each occurrence releases a fixed batch: attachments collected by its scheduled
timestamp. Later arrivals wait for the next selected day/time. Collected files
still being prepared remain part of the batch and print when their PDF is ready.
Email downloads and conversion run in separate bounded background tasks, so a
slow download/conversion does not block release of already prepared reports.
Only one email poll and one conversion run at a time. CUPS submission stays serial.

**Check Email Now** collects email only, without bypassing print timing.
**Pause Email / Resume Email** control collection only, not the print schedule.
**Print queued now** releases attachments collected when clicked once, without
changing the weekly schedule. **Test Print (now)** is explicitly immediate.
**Collect emails only — hold the print queue** disables automatic releases without
stopping collection. **Print as emails arrive** releases waiting work and restores
immediate printing. Immediate is the default until a schedule is saved.

A timing/timezone change governs not-yet-submitted work starting at the next future
occurrence after the worker applies it. Unrelated saves do not reset that cursor.
Already submitted jobs cannot be recalled by changing a schedule. A released
batch keeps retrying after printer outages, even outside the scheduled minute.
Queued files, releases, settings and schedule checkpoints survive updates/reboots.
After worker downtime, missed occurrences of an already-active schedule coalesce
into one overdue batch when the worker returns. Attachments collected after the
last due time still wait for the next slot. Restarting does not repeat a batch.

Local clock handling: a repeated autumn time runs at its first occurrence only;
a nonexistent spring time shifts forward by the clock gap (02:30 becomes 03:30).
The Pi's clock/timezone database must be correct. A scheduled time starts a batch;
it is not a guarantee that all paper has finished printing at that exact second.

| Setting | Values / default |
|---|---|
| `PRINT_SCHEDULE_MODE` | `immediate` (default), `weekly`, `hold` |
| `PRINT_SCHEDULE_DAYS` | Comma-separated `mon,tue,wed,thu,fri,sat,sun`; default weekdays |
| `PRINT_SCHEDULE_TIME` | Local `HH:MM`; default `09:00` |
| `PRINTER_TIMEZONE` | Existing timezone setting; default `America/Los_Angeles` |

## Gmail and print settings in the browser

In **Print Control → Settings**, enter the Gmail address and Google app password,
mailbox/label, subject/sender filters, lookback days and poll interval. **Test Gmail**
tests the entered values without saving, downloading attachments or printing.
**Save Settings** persists values on the Pi and applies them without a manual restart.
Passwords are write-only: a blank field keeps the saved password; removal is explicit.
Changing accounts requires a new app password. Secrets are never stored in Stats.

The first successful scan collects matching emails from the lookback window.
Empty subject/sender filters match everything. Sender matching is not sender
verification. Disabling email monitoring stops new checks, including Check Email
Now; collected work still follows its print schedule. An operation already in
progress finishes with its existing configuration. The UI shows when the worker
has applied the saved revision. The working printer queue is read-only in the UI.

**How reports print** controls paper, orientation, color, sides, copies, PDF
scaling, Excel scaling/margins/sheets and Excel's multi-page policy. Print-layout
options are captured per prepared job, so retries do not silently change layout.
Print timing is separate and governs not-yet-submitted jobs, including prepared ones.

## File policy

The custom parser and Sub Status splitting are removed. XLS/XLSX/XLSM reports render
from the original workbook layout with explicitly selected page settings; they are
not rebuilt into a new table. Office macros and link updates are disabled in the
isolated LibreOffice renderer. LibreOffice/fonts can differ from Microsoft Excel;
the job's PDF preview shows the actual rendered layout.

Incoming PDFs retain their original bytes and all pages. Excel's one-page rule is
the default; Settings can instead allow the entire multi-page workbook. Conversion
or unsupported-file errors produce one error sheet. These outputs all follow the
same email print schedule. Oversized attachments download in full; `MAX_ATTACHMENT_MB`
is only a warning. CUPS completion is not an independent paper-exit sensor.

## Independence, storage and operations

`printer-app-web.service` and `printer-app-worker.service` run as `scoreboard`,
start at boot and restart on failure. Each installed release has its own virtual
environment under `~/.local/lib/printer-app/releases/`, selected by `current`.
Printer crashes/restarts do not affect Stats. Stats may be stopped or unavailable.
Only repository/update distribution is shared through `app/update_delivery.py`.
The detached `printer-app-install.service` owns setup, not either application's runtime.

`print_schedule.py` owns the pure timing contract/calendar arithmetic;
`print_dispatch.py` owns release workflows; `print_queue_repository.py` owns SQL.
The additive `print_queue_releases` table and `print_schedule_state` metadata are in
the printer database only. Batch release and advancing its cursor commit atomically.
The worker alone releases batches and owns CUPS submission; HTTP only queues commands.

| Item | Location |
|---|---|
| Private settings/secrets | `~/.config/printer-app/env` (mode 0600) |
| Printer database | `~/.local/share/printer-app/printer_app.db` |
| Collected attachments | `~/.local/share/printer-app/attachments/` |
| PDFs and processing files | `~/.local/share/printer-app/jobs/` |
| Migration backups | `~/.local/share/printer-app/backups/` |
| Active runtime | `~/.local/lib/printer-app/current/` |
| Distribution status | `~/.local/share/leaderboard-distribution/` |

All environment keys/defaults are in `.env.example`. Existing credentials, noneditable
settings and print receipts are preserved. Sources/previews are retained: monitor disk
space and do not restore an old deduplication database. CUPS submissions are held until
the request ID is saved, then automatically released. Restarts reconcile the original
request rather than blindly reprinting; lost CUPS history is reported as ambiguous.

The existing `konicaa` queue, Konica driver, `KMbeuEmpPS.pl`, Account Track and PIN
configuration are not modified. No root privileges are needed for normal runtime.

```bash
journalctl -u printer-app-web.service -u printer-app-worker.service -f
journalctl -u printer-app-install.service -f
curl --fail http://127.0.0.1:5055/health
```

Health exposes only web/database/worker/known-CUPS-queue booleans, not secrets.
Optional administrator commands from a `main` checkout remain independent of Stats:

```bash
bash printer_app/install.sh
bash scripts/update-printer-app.sh
python3 printer_app/deploy.py rollback
```

Rollback to a version predating scheduling restores that version's immediate-print
behavior. Stop the printer worker before such a rollback if waiting work must stay held.
Rollback never restores an older print-receipt database.

## Regression coverage

CI covers queue release/cutoffs, selected weekdays, DST, persistence, crash-atomic
release/cursor recovery, no repeat on restart, late arrivals, manual releases, hold
mode, printer retries, source-layout rendering, oversized downloads, Gmail deduplication,
no-login forms/CSRF, real browser form saves, and independent systemd deployment
through the leaderboard Update mechanism. Fixtures use disposable files/printer sinks;
no real Gmail account or physical Konica printer is used by CI.
