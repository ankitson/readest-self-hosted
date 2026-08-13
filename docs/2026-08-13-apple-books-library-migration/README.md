# Apple Books full-library migration

## Outcome

The migration moved every locally available Apple Books library item into the self-hosted Readest account while preserving newer Readest state and avoiding duplicate editions.

| Stage | Count |
| --- | ---: |
| Apple database rows | 365 |
| Synthetic Apple series containers excluded | 166 |
| Actual Apple library items | 199 |
| Locally available items | 178 |
| EPUB files | 156 |
| PDF files | 22 |
| Cloud-only Apple Store items | 21 |
| Existing Readest editions reused | 3 |
| New Readest books | 175 |

Apple stores EPUBs as directories. The Mac exporter packages them as standards-compatible EPUB ZIP files with an uncompressed first `mimetype` entry. All 178 staged files opened with Readest's production `DocumentLoader`; there were no file parse failures.

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

The locally available books referenced 1,531 Apple highlights/notes. Readest located and migrated 1,496. All 18 Apple bookmarks were migrated.

The 35 unresolved highlights were skipped rather than guessed:

- *Ageless*: 34/34 unmatched in the locally stored edition.
- *There Is No Antimemetics Division*: 1/10 unmatched.

Another seven highlights belong to cloud-only books and remain queued with those books.

## Reading-state result

Among the 178 migrated items:

| Readest status | Count |
| --- | ---: |
| Finished | 46 |
| Reading | 110 |
| Abandoned | 3 |
| Unread | 19 |

There are 159 migrated books with shelf progress, 153 with resume locations, and 157 Apple last-read markers in synced reading statistics. The three pre-existing Readest configs were newer and were preserved.

## Verification

The post-apply verifier checked the plan against PostgreSQL and S3/MinIO:

- 178/178 planned book rows.
- 178/178 book files.
- 1,514/1,514 planned annotations and bookmarks.
- 332/332 indexed objects present at the exact recorded byte size.
- Zero missing rows, files, notes, objects, or size mismatches.

The library now has 188 live books in Readest: the prior live library plus 175 new Apple items.

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

## Cloud-only queue

Twenty-one Apple Store items have metadata and reading state in the manifest but no local file. Apple documents that cloud items must be downloaded in Books by double-clicking the cloud-status item. They should be migrated by rerunning the exporter/planner after those downloads complete. Do not create unavailable Readest placeholders and do not assume a downloaded Store package is DRM-free; validate it with `DocumentLoader` first.
