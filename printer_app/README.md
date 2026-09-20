# Independent Raspberry Pi printer automation

A second application in `matijepekovic/pi-sales-leaderboard`, delivered on `main`.
It does not import or require the Stats app, routes, database, scheduler or service.

## Install or update

**Leaderboard → Settings → Software → Check for Updates → Update**.
Wait for printer installation to finish, then use **Open Print Control**. No
terminal, separate clone or installer is needed. Stats v134 and later detect
printer-only updates separately; these do not reinstall or restart Stats.

Open `http://<pi-ip>:5055/` or `/system/print-control`. Both now require the
separate **printer admin** login; Settings, print previews/attachments, queues and
administrative APIs are protected by the same session. The first update that enables
this creates a random temporary password. In Stats Settings → Software, use
**Show printer login**, sign in as `admin`, then choose your own password before
Print Control opens. Only a password hash is retained by the printer app.

The work-order Gallery has its own full/temporary access tokens and does not inherit
printer administration. A Gallery link cannot unlock Print Control by changing its
URL. CSRF/same-origin checks remain in addition to authentication. After updating,
reopen Settings rather than resubmitting an old page.

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

## Daily MOD Sheets

**MOD Sheets** is the manual Manager On Duty page. **MOD Settings** is a
separate permanent configuration page for automatic printing. Save the market,
product/source filters and removal/color choices there once; the automatic job
uses those saved choices without persisting either date field.

The worker runs the automatic MOD job **Monday through Friday at 7:00 AM** in
`PRINTER_TIMEZONE`. Start Date and End Date are always that current local day.
If the worker starts later that weekday and the day has not been handled yet, it
catches up using the current day only; it never prints a prior date.

If the source has no matching appointments, no PDF enters the print queue and
the MOD status is recorded as **No appointments**. A source/render/generation
failure is tried once more after two minutes; a second failure is recorded and
stops for that day. Once a PDF is generated it enters the existing durable print
queue, whose normal CUPS receipt/recovery behavior owns printer failures.

Generated MOD PDFs are stored under
`~/.local/share/printer-app/mod-sheets/`. Daily queue identity is durable, so a
worker restart cannot enqueue a second automatic MOD PDF for the same date.
Source-specific Salesforce CLI/SOQL behavior remains inside the Salesforce
adapter; MOD scheduling, settings, rendering and workflow use normalized
contracts under `printer_app/mod_sheets/`.

## Embedded email images are not reports

The Gmail attachment selector ignores `image/*` parts marked `inline` and image
resources inside `multipart/related` bodies. A related body's root is retained
unless it is itself an inline image. The selector uses MIME structure, including
the related `start` parameter, not names such as `image001.png`, file sizes or
assumptions about picture contents. Skips are logged; these images are not
downloaded, queued or turned into physical error sheets.

Separately attached images and other unsupported files still produce the normal
error sheet. Named PDF and Excel parts are still processed even when marked
inline. The change applies to newly collected email; existing queued jobs and
print history are not deleted or reprocessed. It does not change the schedule.

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
settings and print receipts are preserved. With cleanup disabled, sources/previews
are retained: monitor disk space and do not restore an old deduplication database. CUPS submissions are held until
the request ID is saved, then automatically released. Restarts reconcile the original
request rather than blindly reprinting; lost CUPS history is reported as ambiguous.

The existing `konicaa` queue, Konica driver, `KMbeuEmpPS.pl`, Account Track and PIN
configuration are not modified. No root privileges are needed for normal runtime.

```bash
journalctl -u printer-app-web.service -u printer-app-worker.service -f
journalctl -u printer-app-https.service -f
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

Rollback never restores an older print-receipt database. Releases predating required
printer-admin authentication are refused as rollback targets so a rollback cannot
silently reopen port 5055 without a password.

## Regression coverage

CI covers queue release/cutoffs, selected weekdays, DST, persistence, crash-atomic
release/cursor recovery, no repeat on restart, late arrivals, manual releases, hold
mode, printer retries, source-layout rendering, oversized downloads, Gmail deduplication,
admin authentication/CSRF, real browser form saves, and independent systemd deployment
through the leaderboard Update mechanism. Fixtures use disposable files/printer sinks;
no real Gmail account or physical Konica printer is used by CI.

## Seven-day automatic cleanup

In **Print Control → Settings → Automatic cleanup**, enable cleanup, keep **7 days**,
and check **Also permanently delete ALL old emails in this inbox**. Save Settings.
Both switches default to off, including on upgrade: installing code never silently
enables destructive cleanup. The selected Gmail account and `EMAIL_MAILBOX` are
shown alongside the permanent-deletion warning. Changing either requires fresh
opt-in; changing subject/sender filters does not restrict cleanup.

Cleanup runs hourly while the worker is running, with bounded catch-up batches.
It continues in scheduled/hold/immediate print modes, even while email collection
is paused/disabled. It waits for an in-progress email check before running so a
download cannot race deletion. It runs in the collection background slot; the
main loop can still release/print prepared reports at their scheduled time.
Switching cleanup off is checked between deletions, including before each remote
MOVE/STORE; an already-submitted remote command cannot be undone.

* Gmail: **all** messages in the configured inbox/label with a server receipt time
  older than the saved number of 24-hour days, irrespective of read/starred state,
  attachment type, print status or printing filters. Original email Date headers
  are not used. Incomplete local downloads are temporarily protected; already
  downloaded queued reports do not protect the remote email, only the local files.
* Pi: messages and their files/history are expired only after all associated jobs
  have a confirmed PRINTED / ERROR PRINTED result older than the retention period.
  Queued, retrying, interrupted and ambiguous work remains. Expired test prints
  are also removed. Job steps, print attempts, previews and saved per-job options
  are deleted together. Migration backups older than the period are pruned.
* Minimal hashed identity receipts remain, without email contents, subjects,
  filenames or print details. The Gmail collector checks them so clearing history
  does not replay the same Message-ID after a lookback increase or mailbox UID reset.
  SQLite reuses freed pages; the live database is never replaced or rolled back.

The Gmail adapter requires MOVE, UIDPLUS and X-GM-EXT-1 capabilities and locates
Trash through its special-use attribute (not an English folder-name assumption).
It records each selected message's stable identity in a printer-only outbox before
moving it. Only those selected messages are marked deleted and UID EXPUNGEd in
Trash; **no folder-wide EXPUNGE, CLOSE, thread deletion or Empty Trash is used**.
Interrupted moves/purges resume by the same identity. An email archived elsewhere
before the operation is not chased into other folders. Special All Mail, Trash,
Spam, Sent and Drafts folders cannot be configured as the cleanup source. Gmail
labels share a message: permanently deleting an inbox message removes that same
message from its other labels too, but does not target other mail in those labels.

The last cleanup time, counts, next check and errors appear on Print Control and
Settings. Gmail errors do not stop local cleanup or printing; failures retain
outbox entries for retry and do not log credentials. No live Gmail account is
contacted by tests. Update through the existing leaderboard Update button.

Owners: `retention_policy.py` defines settings/normalized mail identities;
`retention.py` owns the workflow, `retention_repository.py` owns retention SQL,
`retention_files.py` confines filesystem deletion, and `gmail_cleanup.py` owns the
IMAP operations. No Stats dependencies or changes to its data/services are made.
This policy does not delete the global system journal, CUPS' own logs/history, or
unrelated files; those belong to the operating system/printer administration.

After retention has run, releases predating this feature do not consult the new
minimal receipts. Stop the printer worker before rolling back to those releases;
recollecting old emails with them can replay history that was intentionally purged.
Cleanup relies on the Pi clock being correct. Shared operating-system/CUPS logs
and accumulated runtime release environments are not covered by file retention.

## Searchable work-order gallery

Update as usual, then open **Print Control → Settings → Searchable work-order gallery**.
Enable imports and set a subject keyword (default suggestion: `redlines`) and/or a PDF
filename keyword, with an optional sender filter. Every nonempty selector must match.
Use filename matching to distinguish multiple PDFs attached to one email. Existing
Gmail credentials/mailbox/check interval are used;
leave email collection enabled. Gallery import is off by default. It only sees newly
collected mail after enabling; resend an already processed PDF in a new email to import it.

**Matching gallery PDFs default to Gallery only — do not print matching PDFs**, including
on upgrades with gallery already enabled. They bypass the print queue even when the
same sender/email also matches print filters. Other attachments still use the saved
print rules and schedule. To intentionally permit both routes, choose **Import and
also use normal print rules** (`GALLERY_PRINT_MODE=also-print`). This allows normal
printing only when its own filters match; it does not force an extra print.

Routing decisions are durably recorded before MIME inspection/download. A failed,
paused or unavailable gallery handoff never switches a gallery-only PDF to printing,
including after a restart or a routing-setting change. Failed MIME inspection waits
without a paper error when the email might contain an excluded gallery PDF. Other
recognizable attachments/messages can still proceed. Download/encoding/handoff errors
appear on Print Control and in gallery settings; later processing errors appear in
the gallery information panel. No image-recognition or CUPS changes are involved.

The new selectors affect newly detected emails, not completed mail or jobs already
in the print queue. Cancel an accidentally queued old print separately; this update
does not cancel or delete any print jobs. Disabling gallery imports stops new gallery
matching, so new emails then follow normal print rules. Pending gallery-only handoffs
stay held while disabled. A failed handoff retains a FETCHING receipt, protecting that
inbox source from cleanup until the gallery copy is durable. Newly discovered mail is visited before
pending downloads so a blocked gallery does not starve new print mail.

Open the searchable image gallery from Print Control on port 5055. The Print Control
link and Full gallery access QR enroll that browser with full gallery capability. A full-access device can open the Gallery hamburger menu and use Share, Offline
(when available), or Refresh. Share names a session and creates a single-use QR grant
that expires 6 hours after creation. Active sessions are shown by
name under the QR and can be revoked by the full-access identity that created them;
revocation also terminates an already-open guest session. Guests can browse and add
notes but cannot use Offline, Share, Gallery Queue, reprocessing, or gallery
administration. Guest QR codes deliberately remain on the certificate-free HTTP
Gallery at port 5055.

The certificate/setup page remains installed but is no longer connected to the Gallery
UI. Normal HTTP Gallery pages hide Offline and do not redirect into setup. An
already-secure full-access phone continues to see/use Offline. Caddy remains an optional
isolated local adapter; no cloud server or hosted customer-data copy is introduced.
The secure Gallery registers its service worker and keeps downloaded work orders in
phone-local IndexedDB. Runtime availability is based on whether **Stats is reachable**, not whether
the phone has internet, so cellular/other Wi-Fi automatically uses downloaded cards and
office-network reachability switches back to live sync. Gallery POSTs retain
CSRF/origin checks through the trusted local proxy.

Print Control, Printer Settings, Gallery Queue and reprocessing require the separate
printer-admin password. Gallery full/guest credentials never grant those privileges.

Cropping is **border-only**, not OCR or equal thirds. Each PNG starts at a detected
wide outer box's top border and continues to just before the next outer top border;
the last reaches the page bottom. Existing side margins and between-box handwriting
remain. Skewed borders are followed without rotating/restyling the content. There are
no margin controls. Layouts without recognizable form rectangles (including summary
sheets) are reported as skipped, never blindly split. Damaged/connected borders may
need a clearer scan. This is not a guarantee of detecting every possible form layout.

Local Poppler renders temporary pages. OpenCV detects rules. Tesseract indexes all
recognized printed text and attempts the printed header dates **after cropping**.
Completed pages are checkpointed in the Gallery-owned work directory. If rendering is
interrupted by a restart, reboot or update, processing resumes from the next unfinished
page; only an in-progress page is repeated. No paid service/API is involved. Blurry printing and handwriting can be misread.
Search includes arbitrary recognized words, phrases, numbers, filenames and added notes.
**Show related** appears only inside an opened work order. It links work orders when
the lead-name **letters only** differ by at most one character or the normalized
address matches exactly. Name punctuation, spacing, symbols and digits are ignored;
address matching still has zero character tolerance so house numbers remain part of
the identity. On full Gallery access only, long-pressing the lead name in
the open viewer allows a global lead-name correction across that strict related set.
Temporary guests cannot perform identity edits.

Open an image in the gallery to enlarge it and add a note; other open devices fetch
saved notes within five seconds. Note authors are user-entered, not verified identities.
Separate notes are append-only with retry-safe IDs, so simultaneous additions do not
silently overwrite each other. Images are loaded in batches rather than all into RAM.

**Keep images for** is a separate gallery policy based on the printed document date,
not download/email age. The two repeated printed header dates must agree with sufficient
OCR confidence; otherwise the crop is marked **needs-date** and will not expire until
corrected in the gallery. Dates can always be corrected. Expiry deletes the image, its
search entry and its notes. Old documents can expire immediately after import. Settings
apply live; cleanup runs hourly. Exact-PDF hash receipts remain to prevent reimport after
expiry. The original PDF and full-page renders are temporary, not part of the archive.
After successful publication they are discarded; failed imports discard their temporary
source and require resending. Existing PDF files still needed by print jobs are untouched.

The gallery shows actual storage, free space and its disk budget, average PNG size,
and estimated retained image storage: **average PNG bytes × images/day × retention days**.
Enter expected images/day or use the observed rate. The estimate excludes database/notes
and temporary processing space, which are shown separately; scans vary in size. The
configured budget and a 512 MB free-disk reserve limit new imports; queued source PDFs
consume space until processed. Dates needing correction can persist longer than the estimate.

Ownership: gallery/policy.py is the normalized settings/search contract; gallery/service.py
owns gallery workflows; gallery/repository.py owns gallery search/notes/import SQL;
gallery/access_repository.py owns access SQL and gallery/access_service.py owns roles,
capabilities, invitations and expiry; gallery/files.py owns confined filesystem access;
gallery/processing.py and cropper.py own rendering/OCR and border detection; gallery/web.py
owns HTTP/cookies. gallery/bootstrap.py remains the feature composition boundary.
The email adapter hands off PDF bytes through the optional consumer contract.
`attachment_routing.py` owns pure per-attachment routing from normalized headers and
filenames; `attachment_routing_repository.py` persists frozen policies, attachment
routes and handoff errors in two additive printer-only tables. Their rows expire with
the parent ingestion record, while minimal replay receipts remain. Neither gallery
processing nor CUPS owns or bypasses this routing boundary. Releases predating these
receipts do not honor gallery-only routing; stop the worker before rolling back to one.
All gallery data is under `PRINTER_DATA_DIR/gallery/`, including its own `gallery.db`.
Printer retention never traverses those image records or directories.

`printer-app-gallery.service` runs independently of the print worker, with low CPU/IO
priority, CPU quota, memory limits, no network and no Gmail/CUPS access in its processing
subprocess. The printer health endpoint intentionally does not depend on gallery health.
System gallery tools use distro Python, not the printer venv. Installer failures for
optional gallery tools are reported without preventing the print runtime update.

Terminal update through the **existing installed distribution helper** (as scoreboard):

```bash
cd "$HOME/pi-tableau-leaderboard"
python3 -c "from app.update_delivery import request_install; print(request_install()['message'])"
journalctl -u printer-app-install.service -f
```

Ctrl+C exits log viewing, not the detached installer. This uses the same verified Git
bundle as the Update button and does not reinstall/restart Stats. Wait for completion
before opening Settings. The optional Git-checkout update script also installs the new
system dependencies. To restart only processing or view gallery logs:

```bash
sudo systemctl restart printer-app-gallery.service
journalctl -u printer-app-gallery.service -f
```

No customer PDF, crop or extracted customer text is shipped in the repository. Gallery
regressions use synthetic forms and fake mail, not live customer data or a physical printer.
