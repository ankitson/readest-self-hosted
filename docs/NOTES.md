## 2026-10-08

### Calibre Marvin highlight import

#### Outcome

- The 2026-09-10 audit missed Calibre's `mm_annotations` custom column: Marvin
  had stored 119 quotes across 15 books there. 110 were imported into 15
  existing Readest books and verified at their stored CFIs; 7 matched existing
  Apple Books highlights and were skipped; 2 on a different *12 Rules for Life*
  edition could not be located and were left out.
- Readest held *Atomic Habits* and *The Body* only as PDFs converted from ebooks
  (calibre 4.15 and Zamzar), while Marvin had annotated EPUBs. The original
  EPUBs were imported through the web app; each PDF row's status, status clock,
  `created_at`, `last_read_at` (the import had set it to the import time),
  group and tags were copied onto the EPUB row, and the PDF rows were
  soft-deleted. The PDF objects stay in MinIO; the four rows' prior state is in
  `tmp/calibre-marvin-highlights/recovery/books-before-pdf-to-epub-*.csv`.
- Marvin can put `**Page N**` directly after a quote with no blank line; the
  exporter ends the quote there (only *Atomic Habits* carries page markers).
- Book-level reviews (before Marvin's first `---`) and *Chasing the Thrill*'s
  review are not imported; Readest has no book-level review field.

#### Design

- Marvin keeps no CFI, ID, colour or timestamp. The planner hands the Apple Books
  locator a placeholder CFI, forcing its whole-book selected-text search, which
  fails closed. Retries strip Marvin's `1.` list markers (the EPUB numbers its
  `<ol>` with CSS), then fall back to the `>` paragraph alone with the reader's
  run-on text as the note.
- Note IDs are `calibre-marvin-<uuid5(calibre id, quote)>`. The apply is
  insert-only (`ON CONFLICT DO NOTHING`), so a re-run never resurrects or
  overwrites a highlight deleted or edited on a device. Notes are stamped with
  the apply time because sync pulls `book_notes` by `updated_at > cursor`.
- Each target edition is the exact Readest file downloaded from MinIO and checked
  against its partial MD5, not the Calibre copy.

#### Read status

- Calibre read status disagrees with Readest for 15 books, 12 of them Apple Books
  imports reading `reading` at the 2025-09-05 migration clock. Calibre carries no
  status timestamp, so under the newer-Readest-wins rule nothing was changed.
- Calibre ratings (28 books) have no Readest field and were not imported.

#### Second Calibre library (`organize-resources/reading/calibre_library`)

- A newer 439-book library (last edited 2024-07-08) had 26 records absent from
  Readest. 21 went to Readest (12 books, Havel's essay, 8 textbooks), 4 papers
  to Zotero, and an empty `update 1.1.0` record was discarded. Ten PDF records
  and three book records had no file in the library; their files had been
  moved to loose copies in `organize-resources/reading/`, which were used.
- Imported through the web app, then hash-, size- and cover-verified against
  MinIO. The MOBI got Calibre's `cover.jpg` via the cover-backfill apply path.
- The web import stamps `last_read_at` with the import time. For these 21 and
  the two earlier web imports (*Shoe Dog*, *Ask Polly*) it was cleared, and
  `created_at` set to the Calibre date added; prior rows are in
  `tmp/calibre-marvin-highlights/recovery/books-before-clock-fix-*.csv`.

#### Recovery

- `tmp/calibre-marvin-highlights/recovery/book_notes-before-*.csv` holds each
  apply's target books' notes beforehand; every imported row is removable by its
  `calibre-marvin-` ID prefix.

## 2026-09-10

### Calibre Book staging import

#### Outcome

- Exported and checksum-verified the frozen 290-Book allowlist from the partial
  Calibre library on `desktop-win`.
- Parsed every selected file through Readest and imported 211 EPUBs plus 79
  PDFs into the manual `Calibre Staging` Group.
- Converted and uploaded all 290 Calibre covers; the full verifier passed for
  290 book rows, 580 file rows, and 580 MinIO objects.

#### Metadata and clock decisions

- Calibre catalog identifiers replace embedded identifiers because two
  unrelated EPUBs reused one copied UUID.
- Obvious inverted and overloaded pipe author values are normalized to one
  natural-order author per metadata element; subtitles are separated from main
  titles at the first catalog colon for this staging pass.
- General `updated_at` stays at the historical Calibre timestamp. Import time
  advances only upload/metadata clocks, and `last_read_at` is set only for the
  eight books with explicit Calibre reading dates.
- No config, note, progress, `stat_books`, or `stat_pages` row is synthesized.

#### Recovery and verification

- The requested simple pre-import PostgreSQL custom-format dump was checksumed
  and listed successfully with `pg_restore`; it is not a paired MinIO backup.
- *The Snowball* matched an exact-hash soft-deleted row with no attached state,
  so apply restored that row instead of duplicating it.
- A post-import verifier confirmed the target Group, metadata and timestamp
  values, every file index/object size, and unchanged pre-existing
  config/note/stat table fingerprints.

## 2026-08-14

### Library metadata canonicalization and sync-clock fixes

#### Goal

Establish one consistent scheme for book metadata — identifiers, authors,
languages — and make sure the scheme survives contact with upstream and with
every client.

#### Discovery

- `meta_hash` is computed from the metadata parsed out of the book **file**, at
  all three write sites, never from the `metadata` column. Server-side metadata
  edits therefore cannot re-key a book, and the hash-safety guard written for the
  first audit pass was solving a non-problem — it had refused 12 edits for no
  reason.
- `normalizeIdentifier` has three real defects (case-sensitive `urn:`, non-`urn`
  URI schemes stripped, payload not canonicalized). Measured against the library,
  all three cost nothing: a hash needs to be deterministic, not correct-looking,
  and none of the three duplicate-title groups would merge if they were fixed.
- `utils/book.ts` sees roughly one upstream edit to the identifier/hash region
  every two months, merged by an unattended nightly cron. Upstream's most recent
  change there was fixing *over*-merging.
- Group and tag mutations bumped only `updatedAt` while those fields merge on the
  metadata clock, so the clocks tied, ties resolved to local, and two devices
  would revert each other indefinitely.
- The Apple Books importer passed a whole book-relative CFI to `CFI.toRange`
  without stripping the spine step, so the exact-CFI path never resolved and every
  annotation was placed by first-occurrence text search.
- `lastReadAt` was stamped on every `saveConfig`, including font changes and the
  annotation import — reintroducing on the new clock the contamination it was
  added to escape.

#### Decision

Fix the **data**, not the identifier logic. See `docs/METADATA-CONVENTIONS.md`
for the full follow / do-not-follow list and the reasoning. The reducer and the
`uuid > calibre > isbn` precedence are left exactly as upstream ships them.

#### Verification

Each pass ran as a dry run, then the full statement set inside a transaction
ending in `ROLLBACK` with probes (row counts, note counts, `metadata` encoding
shape, `updated_at` immobility), then the real apply with the same probes
compared. `pg_dumpall` taken before each. Notes held at 1,556 throughout.

#### Next steps

- Three books show a decorative divider as their cover: they are text-only
  Gutenberg EPUBs with no cover image and no `<meta name="cover">`, so extraction
  fell back to the only image present. Needs real artwork and an edition choice.
- Tombstones from this cleanup can be purged once every device has synced.

## 2026-08-13

### Durable Readest metadata and cover follow-up

#### Root cause

- The library labeled the general `books.updated_at` timestamp as “Date Read”, so manual metadata edits changed the sort order.
- Although the server schema had `metadata_updated_at`, the field was absent from app types, API transforms, and merge rules. A connected client therefore reverted five server-side corrections after the original apply.

#### Resolution

- Added `last_read_at` as a dedicated reading clock and changed Date Read sorting, recent shelves, grouping, and progress writes to use it.
- Wired `metadata_updated_at` end to end and made metadata edits advance only that field.
- Kept the five books' general row timestamps unchanged while assigning their historical Apple Books activity to `last_read_at`.
- Extracted exact-file EPUB/PDF covers first, then used edition-specific web fallbacks. Applied and verified 33/33 cover repairs; all 191 live books now have a cover.

#### Safety and verification

- Captured and checksum-verified a fresh PostgreSQL/book snapshot before the follow-up and tagged the preceding image for rollback.
- Verified the live image at commit `dfba5a6a` after migration 019: HTTP 200, zero restarts, clean startup logs.
- Confirmed no changes to progress, reading status, notes, files, configs, statistics, or the five general row timestamps.
- Confirmed an empty delayed metadata dry run after a client-sync window, eliminating the earlier stale-client reversion.
- Passed 83 targeted app tests, 7 script tests, type checking, and targeted formatting checks. The full run passed 7,761 tests with 18 proofread-suite failures caused only by absent public Supabase test variables; those suites passed 63/63 when rerun with their expected public test configuration.

### Readest metadata normalization

#### Outcome

- Cleaned 94/191 live book records and left 97 already-clean records untouched.
- Removed every `UnknownAuthor` and filename-like title; only two self-published PDFs remain without a stable identifier.
- Added high-confidence series metadata for the book groups that had a clear published series.

#### Timestamp decision

- At the time of the initial cleanup, Readest's “Date Read” sort used the general `books.updated_at` field.
- The follow-up application fix now gives Date Read and metadata synchronization independent clocks.
- Five books previously moved by manual edits use their historical Apple Books activity in the dedicated `last_read_at` field.

#### Safety

- Verified the pre-apply custom PostgreSQL dump and 191-book JSON snapshot by SHA-256.
- Post-apply fingerprints prove progress, status, covers, reader configs, notes, files, and statistics are unchanged.
- The initial post-apply dry run was empty; a later client sync exposed the missing application-side metadata clock and prompted the durable follow-up deployment documented above.

### Apple Books selected cloud-download follow-up

#### Outcome

- Re-exported Apple Books after five requested downloads and retained the complete fresh manifest for audit.
- Migrated three newly readable books, including one recovered highlight and its source reading state.
- Excluded the incidentally downloaded ArtMash per the user's selected scope.
- Rejected Middlemarch and the Tolstoy collection because their reading resources use Apple FairPlay encryption.

#### Hardening

- Added explicit FairPlay payload detection so a parseable EPUB container is not mistaken for a readable book.
- Added an HTML reparse fallback for invalid XHTML, recovering the affected book's selected text and canonical CFI.

#### Verification

- Verified 3/3 book rows, 3/3 book files, 1/1 annotation, and 6/6 storage objects with zero failures.
- Verified the pre-apply PostgreSQL custom-format checkpoint by listing it with `pg_restore` and checking its SHA-256 digest.
- Built and deployed the production web image at commit `2b27dfeb`; the live container returns HTTP 200 with zero restarts, and the preceding image has a rollback tag.

### Apple Books full-library migration

#### Outcome

- Identified 199 actual Apple library items after excluding 166 synthetic series rows.
- Staged and parsed all 178 local files: 156 EPUBs and 22 PDFs.
- Reused three existing Readest editions and added 175 new books.
- Migrated 1,496 highlights/notes and all 18 bookmarks; 35 unresolved ranges were safely skipped.
- Preserved Apple metadata, progress, reading status, resume position, source dates, and last-read markers.

#### Conflict and sync decisions

- Existing Readest config/progress wins when newer than Apple's source state.
- New configs use the migration timestamp for sync visibility while source dates remain under `metadata.appleBooks` and statistics markers.
- A unique metadata-hash match attaches state to the existing Readest edition instead of duplicating the book.
- Reading-history markers use zero duration so the migration does not invent time spent reading.

#### Verification

- 178/178 planned book rows and files verified.
- 1,514/1,514 planned annotations/bookmarks verified.
- 332/332 S3 objects verified at their indexed sizes.
- The exact pre-bulk PostgreSQL and MinIO snapshot passed archive and SHA-256 validation.

#### Remaining

- Fifteen deliberately skipped Apple Store items remain cloud-only; ArtMash downloaded incidentally and was also deliberately skipped.
- Middlemarch and the Tolstoy collection are downloaded but FairPlay-protected, so their files cannot be read by Readest.

### Apple Books exporter and real-library migration validation

#### Outcome

- Extended the existing Mac exporter with per-book, versioned Readest JSON while retaining its Markdown output.
- Exported 1,538 annotations from 70 books, including 26 attached notes; all exported annotations have valid EPUB CFIs.
- Located 404/404 annotations across six varied real EPUBs with Readest's production loader.
- Imported and field-by-field verified all 15 annotations in the live sample book without changing its existing bookmark.

#### Sync decision

The source annotation modification time remains in the interchange file for provenance. Imported Readest notes use the file's stable `exportedAt` as `updatedAt`, because Readest's server pull is cursor-based and historical Apple timestamps can fall behind a device's existing cursor.

#### Safety

Before live mutation, captured and verified a PostgreSQL custom-format dump and the complete MinIO book bucket at `$READEST_BACKUP_ROOT/apple-books-migration-2026-08-13`.

## 2026-08-12

### Apple Books annotation migration

#### Goal

Import Apple Books highlights and attached notes into the matching EPUB in Readest without losing the selected range, appearance, timestamps, or source identity.

#### Discovery

- Apple Books stores a standard EPUB CFI in `ZAEANNOTATION.ZANNOTATIONLOCATION`.
- The sample book's Apple CFI package/body assertions are present verbatim in the EPUB opened by Readest.
- Apple highlight style values are `0=underline`, `1=green`, `2=blue`, `3=yellow`, `4=pink`, and `5=purple`.
- Readest already exports annotations to Markdown through `ExportMarkdownDialog`, including notes, chapters, appearance, timestamps, links, and custom templates.

#### Decision

- Use a versioned JSON interchange file rather than embedding machine data in the human-readable Apple Books Markdown export.
- Verify every source CFI against the target EPUB and rebuild a canonical Readest CFI before persistence.
- Fall back to normalized selected-text matching across DOM text nodes when an EPUB's markup changed.
- Derive stable Readest note IDs from Apple annotation UUIDs so repeated imports are idempotent.

#### Verification

- The real sample EPUB resolved an Apple Books highlight to the exact selected range.
- Targeted importer/dialog tests pass.
- Full app suite: 588 test files passed, 3 skipped; 7,772 tests passed, 7 skipped.
- `pnpm lint` passes (TypeScript and Biome).

#### Next steps

- Make a self-host client release containing the importer when ready for normal UI use.
- Optionally add an Apple-like default custom template to Readest's existing Markdown exporter.
