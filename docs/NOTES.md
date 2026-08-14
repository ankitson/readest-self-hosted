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
- Added high-confidence series metadata for the GPU and Hitchhiker's books plus other known series.

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
- Migrated three newly readable books, including the affected book's one highlight and source reading state.
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
