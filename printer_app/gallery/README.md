# Phone gallery: complete cards, dates and floating controls

The gallery is a single vertically scrolling feed, with full-width work-order
images grouped by their printed document date, newest first. Unknown dates have
their own group at the end. The entire stored image is displayed at its original
aspect ratio: no thumbnail grid, square crops, cover scaling, or new image files.
Opening a card shows the same full image. Retention and the border cutter are not
changed by this presentation update.

The Gallery feed floating controls are **Menu**, **Notes**, and **Search**. **Show
related** is intentionally available only after opening a work order; it is never a
feed action. The Menu opens a Gallery sheet containing Share, Offline (when available),
and Refresh. Those utilities are not part of the calendar.

Related compares the explicit Lead Name and Address extracted from the opened work
order. Name identity uses letters only: spacing, punctuation, hyphens, apostrophes,
symbols and digits are ignored, then the name may differ by at most one letter.
The address fallback remains exact after case/punctuation/spacing normalization, so
house numbers still matter. Results span all retained dates.

Notes opens a bottom sheet only to add a note for the selected card. Existing
notes are shown underneath the document when that work order is opened. The target
remains pinned while editing, and other open viewers refresh within five seconds.
Notes remain per document, not merged across related cards. Search opens a floating
sheet and searches recognized printed text, lead names, and shared notes. Load more
extends the same feed in bounded 24-card batches.

The gallery repository performs an additive, transactional lead-name/index upgrade
using already-saved search text. Existing images, notes, dates and import receipts
are preserved; no OCR rerun, source reimport or new print jobs. New imports populate
the same index. This feature stays within gallery policy/service/repository/web and
its own frontend assets. Stats, Gmail polling, print scheduling, CUPS, credentials,
cleanup rules, and other printer pages are untouched. Deploy through the existing
leaderboard Update button; reopen the gallery afterward.


## Tap a date or swipe between days

Tap a printed date heading, the date at the top, or the date in an open image to
choose a day in the calendar sheet. Only days with matching retained work orders
are selectable; the month selector jumps between months that contain records.
Choosing a date filters the feed to that day. The date sheet contains only date
browsing controls. Share, Offline and Refresh live in the Gallery hamburger menu,
not in the calendar. This is browsing state, not a change to a document's saved date
or retention.

Swipe **left for the next newer date**, **right for the previous older date** on
the card feed, or use the arrow buttons next to the date. Empty days are skipped.
From All dates, a swipe starts at the touched card's group; the buttons use the
visible group. There is no wrapping at the first/last date. Undated cards do not
participate in chronological swipes; use the calendar to return to dated cards.
Vertical scrolling, pinch-to-zoom, edge navigation and gestures inside image or
notes/search dialogs do not switch dates. Nothing is resized into a thumbnail.

Starting Search or Show related resets the day filter, so matches still span all
retained dates. The calendar and swipes then use the dates in those results, not
unrelated cards. Date counts come from the entire result set, including records
beyond the first 24-card batch. Load more still appends full cards. An expired or
newly emptied day displays an empty state with access to All dates/the calendar.

The repository owns date-scoped SQL and a read snapshot of counts/rows. Policy
validates the optional `date` query parameter (YYYY-MM-DD, empty, or `undated`).
The service and gallery HTTP layer pass the normalized filter; `gallery_dates.js`
owns calendar/gesture behavior, and `gallery.js` continues to own retrieval and
card rendering. No schema migration, OCR/crop changes, files or dates rewritten,
printer mutations, new dependencies, or new service lifecycle.


## Gallery-only email routing

In printer Settings, matching PDFs now default to **Gallery only — do not print
matching PDFs**. Other attachments keep normal printing behavior. Subject and PDF
filename keywords are separate optional selectors (at least one is required); all
filled selectors and the optional sender restriction must match. Set filename to
`redlines` and clear subject to distinguish that PDF from another report in the same
email. These are literal case-insensitive substrings, not regular expressions.

**Import and also use normal print rules** deliberately allows both routes. Disabling
imports stops matching NEW messages; it is not a blanket no-print filter. Incomplete
handoffs keep their original exclusion even after a restart/settings change and wait
while imports are disabled. No fallback printing on gallery errors and no automatic
cancellation of existing print jobs. Intake failures are visible on Print Control and
in gallery settings; processing failures remain in the gallery information panel.

Classification lives at the ingestion boundary, not in the gallery worker or print
engine. The optional PDF consumer receives bytes only after the decision is durable.
No PDF reimport, recropping, notes/date migration or frontend gallery changes required.

## Queue controls and gallery actions

Print Control includes **Gallery Queue**, which lists pending email handoffs and
separate gallery imports. **View gallery jobs** opens processing status; each PDF
links to its own log, timestamps, progress, and retained full-card images.

**Remove from print queue** opens a confirmation for one waiting attachment. The
POST uses existing same-origin/CSRF protection and the dispatch service's durable
cancellation boundary. Once submission is reserved, removal is rejected; this is
not a CUPS cancellation button. Other reports and gallery data are unchanged.

In the sales gallery, **Notes** can still target the fully visible, unobscured card
from the feed. **Show related** requires opening that card first, which removes any
ambiguity about the anchor work order. Related uses the strict identity rule:
letters-only lead name within one character **or** exact normalized address. It
starts across all dates, not just the current date or loaded page. Existing images
and notes are unchanged; address metadata is backfilled from already-saved OCR text.

The gallery's links back to Print Control and Settings are removed. Gallery access
is capability-based: full-access devices can browse, add notes, keep an offline copy
and share temporary access; temporary guests can browse and add notes only. Neither
Gallery role grants printer administration. Gallery Queue, reprocessing, approval,
deletion, Print Control and Settings require the separate printer-admin password.

PR #117 shipped backend helpers but omitted their web/template/action connections.
This completes those connections. The updater uses the existing installation
mechanism; already-stored incorrect crops are not silently deleted or rebuilt.


## Full access, temporary sharing and Offline

Password-protected Print Control is the enrollment boundary for a full-access gallery
device. Opening the gallery from Print Control, or scanning its Full gallery access QR
code, exchanges
a short-lived enrollment token for a long-lived gallery credential. Reopening from
Print Control does not replace an existing full identity, so the phone keeps the same
account-scoped offline store.

The hamburger Gallery menu shows **Share**, **Offline** (when available), and
**Refresh**. Share opens a Gallery sheet where the full-access user first names the
session, then creates a QR code. The bearer URL is never printed in the UI. Each session lasts **6 hours from
creation**. Active sessions created by that full-access Gallery identity are listed
under the QR with their name, whether the QR has been opened, expiry time, and a
**Revoke** button. Revocation immediately invalidates both an unused QR and an
already-redeemed guest credential. A different full-access identity cannot revoke or
list sessions it did not create.

Guest access is checked server-side on every Gallery request and cannot use Offline,
Share, Gallery Queue, reprocessing, or gallery administration. The access repository
keeps each guest credential tied to its issuing share grant so expiry/revocation
cannot be bypassed by keeping an old cookie. Legacy temporary grants from the older
24-hour, non-revocable flow are invalidated when this schema is installed.

Offline is phone-local and is available only to full-access Gallery identities.
The installer still retains the private HTTPS/certificate setup page for an already
configured installation, but the Gallery UI does not link or redirect to it. On normal
HTTP Gallery pages the Offline control is hidden. An already-secure full-access phone
continues to see and use Offline normally. Temporary six-hour guests stay on the normal
`http://<pi-address>:5055` Gallery and never receive Offline capability.

On the secure full-device origin, enabling Offline registers the Gallery service
worker and asks for persistent browser storage when available. IndexedDB owns normalized
card metadata, details, notes and queued-note state. Work-order image bodies use a
separate Cache Storage namespace owned by the Offline runtime. Each cached image gets a
subject-scoped synthetic `/gallery/offline-image/...` URL that the service worker serves
directly while Stats is unreachable. This avoids depending on iPhone/WebKit restoring
persisted Blob/object URLs correctly after Safari/PWA relaunch. Existing readable
IndexedDB image records can self-migrate without deleting browser data, and any missing
image is downloaded again automatically during the next live sync. When the phone is
on cellular or another Wi-Fi, internet can still
be available while the private Pi is unreachable. `gallery_network.js` therefore owns
**Stats reachability** with bounded probes/timeouts; neither `gallery.js` nor
`gallery_offline.js` uses `navigator.onLine` as the availability decision. A secure
Gallery navigation falls back to its cached shell after a short failed Pi connection,
then the UI reads downloaded work orders immediately. It probes Stats periodically and
returns to live mode/sync automatically when the Pi becomes reachable again.

Server retention never deletes the browser store, so a previously downloaded image can
remain on the phone after its server copy expires. Turning Offline off stops automatic
downloads but does not erase downloaded cards. Queued offline notes sync when Stats is
reachable again. Browser/OS storage can still be evicted; the app requests persistence
but cannot override iOS storage policy.

`https_adapter.py` owns Caddy/local-CA deployment and exposes only normalized readiness
and the public CA certificate to runtime composition. `printer-app-https.service` is an
optional isolated proxy and cannot make printer health fail. The access repository owns
access SQL, the access service owns roles/capabilities/shares, the Gallery web layer owns
certificate/setup HTTP endpoints, `gallery_network.js` owns Pi reachability, and
`gallery_offline.js` owns phone storage/sync. Gallery business/repository modules do not
depend on Caddy.


## Template-assisted fast processing

The blank single-card work-order template is represented by normalized printed-rule
geometry in `form_template.py`. It is a conservative fast path, not a replacement for
the generic cutter: a card must strongly match the known rule spacing before template
registration is trusted; otherwise the existing border/report validation remains in
control.

Page-wide skew is still corrected once before cutting, but Canny/Hough and line-grid
analysis now run on bounded working copies and the resulting geometry is mapped back to
the original 3300-pixel render. Saved Gallery crops remain full resolution and still use
optimized PNG output, so storage/image quality behavior is unchanged.

For recognized work orders, template registration supplies a cheap positive form check.
Earlier stacked cards keep the existing hard boundary at the next card's top. The final
card uses the template to locate its printed bottom, then extends only through meaningful
ink below that border before trimming blank scanner tail.

Search indexing remains on the critical path and its OCR path is intentionally
unchanged: Tesseract still sees the complete full-resolution card, preserving the
existing searchable-text behavior. The first reliable document date is still reused
across the PDF; no time value is reused. Optimized PNG output and Gallery CPU/service
limits are unchanged.

## Resumable PDF processing

Gallery rendering checkpoints only after a complete PDF page has finished. The work
folder keeps the crops and normalized recognition metadata for every completed page.
If the Gallery worker is restarted, the Pi reboots, an update stops the service, or
the processing child is otherwise interrupted, the import returns to the queue and
continues at the next unfinished page. An interruption in the middle of a page repeats
that page only; completed pages are not rendered/cropped again.

The checkpoint lives only in the Gallery-owned `work/<pdf-hash>/` directory. It does
not publish partial cards to the normal Gallery, alter the source PDF, or create print
jobs. Renderer timeouts, temporary tool/runtime failures, memory pressure and storage
interruptions use an explicit retry exit contract: the source PDF and completed-page
checkpoint are preserved and the job returns to the queue. A slow page also gets up to
five minutes of Poppler render time before it is treated as interrupted. Invalid PDFs
or unsupported layouts still use the hard-failure path. `processing.py` owns the
checkpoint/retry classification, `processing_contract.py` is the subprocess boundary,
`gallery/files.py` owns workspace size/accounting, and `gallery/worker.py` owns the
retry/restart lifecycle.

## Manual review for unnamed generated cards

OCR no longer has authority to publish an unnamed generated crop directly to the
work-order Gallery. At import completion, a card with a recognized lead name is
ACTIVE; a card without one is stored as REVIEW. Review cards remain visible only
on the admin-only Gallery Job page and are excluded from normal Gallery search,
related results, date browsing and offline sync until a printer admin chooses
**Approve to Gallery**.

The Gallery Job page also owns per-card deletion. **Delete** removes that generated
server image and its server-side notes without reprocessing the PDF, touching other
cards, affecting printing, or removing phone-local offline copies. Existing unnamed
active cards are moved behind the review gate once during the repository migration;
a manual approval is durable and is not automatically undone on restart.

The repository owns review state and transitions, the service coordinates the
gallery-owned crop file deletion, and the web/template layer only exposes those
actions behind printer-admin authentication. Geometry/OCR remain advisory inputs rather than approval
authority for unnamed cards.


## Lead-name correction

On an opened work order, a full-access Gallery device can long-press the lead name
in the viewer header to open **Change lead name**. The same long-press also works
when the title is **Work order** because no name was recognized. Temporary guests
cannot open the editor and the server rejects the edit capability for them.

For an already named card, saving is intentionally global within the current related
identity: every active work order whose current lead name is within one character of
the selected card's name **or** whose normalized address exactly matches the selected
card receives the new confirmed lead name. For an unnamed active card, the first
manual name applies only to that work order; later changes use the normal related
identity rule.

Printer admins can also set/change the lead name directly on every retained card in
the Gallery Job page, including REVIEW cards whose name was not recognized. That
job-page correction changes only the selected generated card and does not publish a
REVIEW card automatically; **Approve to Gallery** remains a separate explicit action.

These corrections do not rewrite OCR text, images, addresses, notes, dates, source
files, or print history. `gallery/policy.py` owns the strict identity contract,
`gallery/repository.py` owns lead persistence/bulk updates, the Gallery service owns
the naming workflows, and the web layer separately enforces full-access Gallery edits
versus printer-admin Job-page edits.
