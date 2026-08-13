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
- Migrated three newly readable Apple Books and the recovered one migrated book highlight; intentionally excluded one unselected download and two FairPlay-protected packages.

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
