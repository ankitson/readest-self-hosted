# Apple Books full-library migration

## Outcome

The migration moved every readable Apple Books library item in the selected scope into the self-hosted Readest account while preserving newer Readest state and avoiding duplicate editions. After the initial migration, five cloud books were downloaded and re-evaluated. Three were readable and migrated; two contained Apple FairPlay-encrypted content and were rejected rather than added as broken Readest books.

| Stage | Count |
| --- | ---: |
| Apple database rows | 365 |
| Synthetic Apple series containers excluded | 166 |
| Actual Apple library items | 199 |
| Initially locally available items | 178 |
| Follow-up downloads selected | 5 |
| Follow-up downloads readable/migrated | 3 |
| Follow-up downloads FairPlay-protected/skipped | 2 |
| Total migrated Apple items | 181 |
| Migrated EPUB files | 159 |
| PDF files | 22 |
| Remaining cloud-only items intentionally skipped | 15 |
| Downloaded `ArtMash` intentionally skipped | 1 |
| Existing Readest editions reused | 3 |
| New Readest books | 178 |

Apple stores EPUBs as directories. The Mac exporter packages them as standards-compatible EPUB ZIP files with an uncompressed first `mimetype` entry. All 181 migrated files opened with Readest's production `DocumentLoader`. The planner now separately detects Apple's `http://itunes.apple.com/dataenc` FairPlay payloads because their containers can parse even though Readest cannot decrypt or render their reading content.

## Preserved data

- File bytes and parsed EPUB/PDF metadata.
- Apple title, author, identifiers, language, description, genre, year, series, and store provenance where present.
- Reading progress and high-watermark progress.
- Explicit `finished`, `reading`, `unread`, and `abandoned` shelf status.
- Finished, purchased, last-opened, last-engaged, and last-location timestamps under `metadata.appleBooks`.
- Exact Apple type-3 EPUB CFI resume locations when resolvable, with physical-section/progress fallback otherwise.
- Apple type-1 bookmarks.
- Highlights, attached notes, appearance, source creation time, and stable UUID identity.
- A zero-duration statistics marker at the Apple last-read time. This preserves history without fabricating reading duration.

Readest does not have a dedicated book-level `lastReadAt` column. The lossless source timestamp therefore remains in `metadata.appleBooks.lastReadAt`, while `stat_pages` carries the last-read marker and ordinary Readest fields carry progress/status.

## Conflict policy

- Exact content hashes are idempotent.
- A single existing Readest edition with the same metadata hash receives Apple annotations instead of creating a duplicate.
- Existing Readest config/progress wins when its update timestamp is newer than Apple's source state.
- Source UUID-based note IDs make reruns safe.
- Files and covers are content/size checked and not uploaded again when already indexed.

This preserved the existing Readest editions of *It's Not Always Depression* and *Focusing*. All five *Focusing* annotations were separately verified against the existing Readest EPUB before the bulk migration.

## Annotation coverage

The initially available books referenced 1,531 Apple highlights/notes. Readest located and migrated 1,496. All 18 Apple bookmarks were migrated. The follow-up added the one Agent Zero highlight after recovering it from invalid XHTML as HTML, bringing the total migrated Apple annotations to 1,497 with zero unmatched annotations in the readable follow-up books.

The 35 unresolved highlights were skipped rather than guessed:

- *Ageless*: 34/34 unmatched in the locally stored edition.
- *There Is No Antimemetics Division*: 1/10 unmatched.

Of the original seven highlights on cloud-only books, one Agent Zero highlight is now migrated. Three belong to the protected Tolstoy collection and three belong to titles the user chose to skip.

## Reading-state result

Among the 181 migrated items:

| Readest status | Count |
| --- | ---: |
| Finished | 48 |
| Reading | 111 |
| Abandoned | 3 |
| Unread | 19 |

There are 162 migrated books with shelf progress, 156 with resume locations, and 160 Apple last-read markers in synced reading statistics. The three pre-existing Readest configs were newer and were preserved.

## Verification

The initial post-apply verifier checked its plan against PostgreSQL and S3/MinIO:

- 178/178 planned book rows.
- 178/178 book files.
- 1,514/1,514 planned annotations and bookmarks.
- 332/332 indexed objects present at the exact recorded byte size.
- Zero missing rows, files, notes, objects, or size mismatches.

The incremental verifier then checked 3/3 book rows, 3/3 book files, 1/1 annotation, and 6/6 indexed objects with zero failures. The library now has 191 live books in Readest: the prior live library plus 178 new Apple items.

## Recovery and artifacts

All artifacts live under:

```text
/mnt/passport2tb/root/shared_storage/backups/readest/apple-books-library-migration-2026-08-13
```

Important paths:

- `source-files/`: 178 standardized EPUB/PDF files.
- `annotation-exports/`: per-book lossless annotation JSON.
- `library-manifest.json`: all 199 Apple library records, including cloud-only items.
- `plan/migration-plan.json`: Readest-parsed hashes, metadata, state, and notes.
- `plan/covers/`: 153 extracted covers.
- `pre-bulk-readest/`: verified PostgreSQL and MinIO snapshot immediately before the bulk write.
- `final-five/`: complete fresh Apple manifest, the five selected packages, the three-book migration plan, and a verified pre-apply PostgreSQL checkpoint.

The pre-bulk database dump passed `pg_restore --list`; the MinIO archive listed successfully; both SHA-256 checks passed.

## Rerun commands

From the Readest repository:

```bash
just apple-books-migration-test
just apple-books-migration-plan
just apple-books-migration-dry-run
just apple-books-migration-verify
```

The apply operation remains intentionally explicit:

```bash
cd apps/readest-app/scripts/apple-books-library-migration
uv run --script apply_apple_books_library.py \
  --plan /path/to/plan/migration-plan.json \
  --stage-dir /path/to/source-files \
  --covers-dir /path/to/plan/covers \
  --env-file /path/to/readest.secrets.env \
  --apply
```

## Final exclusions

The user intentionally skipped 16 of the original cloud-only titles: 15 remain cloud-only and `ArtMash` downloaded incidentally but was excluded from the selected manifest. `Middlemarch` and `Leo Tolstoy: The Complete Novels and Novellas` were selected and downloaded, but their EPUB reading resources use Apple FairPlay encryption. Their raw packages, metadata, reading state, and annotation exports remain under `final-five/`, but the books were not inserted into Readest. A DRM-free replacement edition could be evaluated later, but progress and annotation locations must not be assumed compatible across editions.
