## 2026-10-08

### Calibre Marvin highlight import

- Added `export_calibre_marvin_highlights.py`, `calibre-marvin-highlights-plan.test.ts`
  and `apply_calibre_marvin_highlights.py` (`just calibre-marvin-export/plan/apply`)
  to import highlights the Marvin iOS reader stored in Calibre's `mm_annotations`
  column into books already in Readest.
- Imported 110 highlights across 15 books; skipped 7 already present from Apple
  Books and left 2 that could not be located.
- Replaced the PDF editions of *Atomic Habits* and *The Body* (calibre/Zamzar
  conversions) with the original EPUBs Marvin had annotated, carrying over
  status, read date, group and tags, and soft-deleting the PDF rows.
- Imported 21 books and textbooks from a second, newer Calibre library and
  cleared import-time `last_read_at` stamps on all web-imported rows.

## 2026-09-10

### Calibre Book staging migration

- Added a read-only Calibre stage exporter, Readest-native EPUB/PDF planner,
  guarded PostgreSQL/MinIO apply tool, and full verifier for the approved
  Book-only import.
- Imported 290 missing books into `Calibre Staging`: 211 EPUBs, 79 PDFs, and
  290 converted covers; verified all 290 rows and all 580 indexed objects.
- Normalized title/subtitle and author shapes, assigned a catalog-backed
  identifier to every record, and rejected a copied UUID shared by two
  unrelated source EPUBs.
- Preserved Date Read using historical source clocks and the eight explicit
  Calibre read dates; created no configs, notes, or reading statistics.
- Restored one exact-hash soft-deleted book without changing its absent user
  state, and proved all pre-existing config/note/stat fingerprints unchanged.

## 2026-08-14

### Metadata sync correctness

- Fixed the Apple Books importer discarding the spine step before resolving a
  source CFI, so exact-CFI placement works instead of always falling back to
  first-occurrence text search. Strengthened the test that was passing either way.
- Gated `lastReadAt` on a changed page position in both `saveConfig` and
  `updateBookProgress`, so font/layout changes, the annotation import and
  status-only edits no longer move Date Read.
- Stamped `metadataUpdatedAt` on every group/tag mutation in `GroupingModal` and
  `ingestService`, ending a revert loop between devices; added a merge test and a
  source-level guard test.
- Changed `formatAuthors` to `Intl.ListFormat` type `unit`, rendering author
  lists as `A, B, C`.

### Library data canonicalization

- Canonicalized 131 identifiers to `urn:isbn:` / `urn:uuid:` form, repaired one
  malformed `urn|nid|payload`, and left URLs, ASINs and opaque publisher ids
  untouched.
- Normalized all 191 author values to arrays, splitting 16 joined multi-author
  strings; guarded organisation names containing "and" and stripped role prefixes
  before splitting.
- Filled 20 missing languages and repaired 18 malformed ones (`eng`, `En`,
  `EN-US`, `eee`, `und`, duplicated arrays, one wrong language code); kept valid
  regional variants.
- Filled 2 titles, 1 author and 2 publication dates; identified 2 self-published
  books by their canonical author-domain URL.
- Removed the 6 bundled demo-shelf rows and one metadata-only stub via tombstones,
  and purged 2 long-standing tombstones; every remaining book now has a file, a
  cover, a language and an identifier.

### Documentation

- Added `docs/METADATA-CONVENTIONS.md` recording the metadata scheme, the two
  hashes and what each keys, and the changes deliberately not made — with the
  measurements behind each decision.

## 2026-08-13

### Durable metadata sync, Date Read, and cover backfill

- Added independent `lastReadAt` and `metadataUpdatedAt` clocks so metadata edits and stale-client merges cannot change the Date Read sort.
- Backfilled and preserved the source reading dates for the five manually edited books without rewriting their general row timestamps.
- Added a guarded cover-backfill utility and supplied or repaired 33 covers, leaving all 191 live books with verified cover objects.
- Built and deployed the fixed image with database migration 019; verified HTTP health, zero restarts, an empty delayed metadata dry run, and unchanged reading state, notes, files, configs, and statistics.

### Readest library metadata cleanup

- Added an idempotent, guarded metadata-cleanup manifest and apply/verify command.
- Normalized 61 titles, 52 subtitles, 42 author records, 21 identifiers, and 15 series records across 94 live books.
- Recorded the historical Date Read values for five manually edited books while preserving all other reading state.
- Verified that reading state, covers, notes, files, configs, and statistics remained unchanged; no application image deployment was required.

### Apple Books downloaded-title follow-up

- Added Apple FairPlay payload detection to prevent encrypted Store EPUBs from entering migration plans as apparently parseable books.
- Added invalid-XHTML HTML fallback for selected-text annotation recovery.
- Migrated three newly readable Apple Books and the one recovered highlight; intentionally excluded one unselected download and two FairPlay-protected packages.

### Apple Books full-library migration tooling

- Added a versioned full-library manifest and standards-compatible Apple EPUB packager.
- Added a Readest-native planner for EPUB/PDF metadata, progress, status, resume positions, bookmarks, annotations, covers, and hashes.
- Added an idempotent PostgreSQL/S3 migration command with dry-run mode and newer-Readest-state conflict preservation.
- Added a post-apply verifier for planned rows, note identities, object presence, and byte sizes.
- Migrated 178 locally available Apple items into Readest, adding 175 new books.

### Apple Books migration hardening

- Added a required stable export timestamp so imported historical annotations cross Readest sync cursors.
- Completed a 404-annotation compatibility audit across six real EPUBs with zero unmatched ranges.
- Completed and verified the 15-annotation live migration for the shared sample book.
- Documented the companion exporter workflow and verified recovery point.

## 2026-08-12

### Apple Books annotation import

- Added a versioned Apple Books JSON parser with strict runtime validation.
- Added lossless Apple Books-to-Readest annotation conversion, style mapping, stable IDs, and timestamp preservation.
- Added target-EPUB CFI verification and selected-text recovery for markup changes.
- Added Apple Books to the reader's annotation import dialog with mismatch, invalid-file, and unmatched-range feedback.
- Added unit and UI coverage for parsing, conversion, style mapping, title matching, CFI location, fallback recovery, and dialog behavior.
