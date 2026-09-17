# Phone gallery: complete cards, dates and floating controls

The gallery is a single vertically scrolling feed, with full-width work-order
images grouped by their printed document date, newest first. Unknown dates have
their own group at the end. The entire stored image is displayed at its original
aspect ratio: no thumbnail grid, square crops, cover scaling, or new image files.
Opening a card shows the same full image. Retention and the border cutter are not
changed by this presentation update.

The floating controls are **Show related**, **Notes**, and **Search**. Tap a card
first to select it. Show related lists that lead's retained work orders across all
dates, vertically, newest first (including the selected card). It matches only the
explicit Lead Name header, not mentions in reps/notes, partial names or filenames.
Case and extra whitespace are ignored; different spellings are not silently merged.
No name is guessed when the header is unreadable. Confirm/correct it under Notes →
Card details; a Show related request without a name opens that field. Matching a
name alone is not proof that two records represent the same person.

Notes opens a bottom sheet for the selected card to read or add centrally saved
notes. Other open viewers refresh within five seconds. Notes remain per document,
not merged across related cards. Search opens a floating sheet and searches all
recognized printed text, corrected lead names, and shared notes. All cards restores
the date-grouped feed. Load more extends the same feed in bounded 24-card batches.
The information button contains storage, QR access, refresh and gallery settings.

The gallery repository performs an additive, transactional lead-name/index upgrade
using already-saved search text. Existing images, notes, dates and import receipts
are preserved; no OCR rerun, source reimport or new print jobs. New imports populate
the same index. This feature stays within gallery policy/service/repository/web and
its own frontend assets. Stats, Gmail polling, print scheduling, CUPS, credentials,
cleanup rules, and other printer pages are untouched. Deploy through the existing
leaderboard Update button; reopen the gallery afterward.
