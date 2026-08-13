## 2026-08-13

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

- Twenty-one Apple Store items are cloud-only and must be downloaded in Apple Books before their file packages can be validated and imported.
- Seven exported highlights belong to those cloud-only books.

### Apple Books exporter and real-library migration validation

#### Outcome

- Extended the existing Mac exporter with per-book, versioned Readest JSON while retaining its Markdown output.
- Exported 1,538 annotations from 70 books, including 26 attached notes; all exported annotations have valid EPUB CFIs.
- Located 404/404 annotations across six varied real EPUBs with Readest's production loader.
- Imported and field-by-field verified all 15 annotations in the live sample book without changing its existing bookmark.

#### Sync decision

The source annotation modification time remains in the interchange file for provenance. Imported Readest notes use the file's stable `exportedAt` as `updatedAt`, because Readest's server pull is cursor-based and historical Apple timestamps can fall behind a device's existing cursor.

#### Safety

Before live mutation, captured and verified a PostgreSQL custom-format dump and the complete MinIO book bucket at `/mnt/passport2tb/root/shared_storage/backups/readest/apple-books-migration-2026-08-13`.

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
