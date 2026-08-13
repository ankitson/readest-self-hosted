# Readest library metadata and cover cleanup

## Outcome

The cleanup corrected metadata on 94 of 191 live Readest books, supplied or repaired covers for 33 books, and fixed the application so metadata edits no longer change the “Date Read” ordering. The live library now has a cover for every book, no `UnknownAuthor` values, no filename-like titles, and only two self-published PDFs without a stable identifier.

| Metadata change | Books |
| --- | ---: |
| Titles normalized | 61 |
| Subtitles moved to `metadata.subtitle` | 52 |
| Author metadata normalized | 42 |
| Top-level author display normalized | 35 |
| Identifiers added | 21 |
| ISBN fields added | 18 |
| Series names changed | 15 |
| Series positions added | 14 |

The checked-in correction manifest remains idempotent: the final delayed dry run reports `changedBooks: 0`, including after allowing time for an existing client to sync.

## Date Read and metadata sync fix

Readest previously exposed the general `books.updated_at` row timestamp as “Date Read.” Editing a title, author, or cover therefore moved a book to the front of that sort. The database already had a `metadata_updated_at` column, but it was not carried through the API, client models, transforms, or merge rules; an older client could consequently overwrite a server-side metadata cleanup.

The deployed application now uses two independent field clocks:

- `last_read_at` / `lastReadAt` is the actual reading date and the “Date Read” sort key. Reading progress updates it.
- `metadata_updated_at` / `metadataUpdatedAt` resolves metadata conflicts without advancing the general row timestamp or the reading date.

Migration `019_add_last_read_at.sql` backfilled the new field from the existing historical timestamp. The five books called out by the user now have these effective reading dates:

| Book | Date Read (UTC) |
| --- | --- |
| Agent Zero | 2023-01-07 17:48:56.946 |
| The Kama Sutra | 2011-01-04 19:13:56.000 |
| The Republic | 2026-06-27 23:05:53.776 |
| The Adventures of Sherlock Holmes | 2024-04-27 09:09:13.620 |
| How Life Works | 2025-09-05 07:23:51.085 |

*The Republic* can still appear fairly near the front because June 27, 2026 is its real source reading date. The other recent-looking general `updated_at` values were deliberately left intact; they are no longer used for this sort.

This required a new Readest image. The earlier one-off SQL correction was safe, but without the app-side field wiring a stale client subsequently pushed its metadata copy back to the server. The fix makes the correction durable across native and file sync instead of relying on another timestamp rewrite.

## Cover backfill

The cover backfill found 33 books requiring a cover or cover-index repair and completed all 33 with no failures. The live verification is 191 books and 191 resolvable cover objects.

The source policy was:

1. Preserve a valid existing user cover.
2. Extract the declared EPUB cover or render a PDF's first page from the exact stored book file.
3. Use an edition-specific ISBN, publisher, Gutenberg, or Open Library image only when the stored file supplied no usable cover.

The five previously selected covers for Agent Zero, The Republic, The Kama Sutra, The Adventures of Sherlock Holmes, and How Life Works were preserved when already present; How Life Works received a missing cover. One existing but incompletely indexed Notes from Underground cover was normalized and reindexed. The generated plan and review sheet are:

```text
/mnt/passport2tb/root/shared_storage/backups/readest/readest-metadata-cleanup-2026-08-13/covers/cover-plan.json
/mnt/passport2tb/root/shared_storage/backups/readest/readest-metadata-cleanup-2026-08-13/covers/cover-contact-sheet.jpg
```

## Metadata decisions

- Titles with a clear colon-delimited subtitle use separate `title` and `subtitle` fields.
- Personal authors use natural `Firstname Lastname` display order. Multiple authors use natural English lists with a final “and”. The corporate author “Immigration, Refugees and Citizenship Canada” remains unchanged.
- The three GPU books use the series *The History of the GPU*, positions 1–3.
- The two present Hitchhiker's books use the series *The Hitchhiker's Guide to the Galaxy*, positions 1 and 5.
- Other high-confidence series were added for Southern Reach, Monk and Robot, A Song of Ice and Fire, Millennium, Hercule Poirot, Moomins, Thursday Murder Club, and Culture.
- “Apple Books Classics” was removed from Sherlock Holmes because it is a retailer collection rather than the book's literary series.
- Exact-edition identifiers came from embedded book data where available and were supplemented by publisher/catalog records for the local editions.
- David Cain's *How to Do Things* and *How to Save the World* remain without identifiers because no stable ISBN or ASIN was present or confidently identifiable.

## Recovery points and deployment

The original pre-cleanup recovery point is:

```text
/mnt/passport2tb/root/shared_storage/backups/readest/readest-metadata-cleanup-2026-08-13/pre-cleanup
```

A fresh checkpoint immediately before the cover and Date Read follow-up is:

```text
/mnt/passport2tb/root/shared_storage/backups/readest/readest-metadata-cleanup-2026-08-13/followup-pre-cover-date-fix
```

The latter contains a verified PostgreSQL custom-format dump, a 191-book JSON snapshot, the restore listing, the one pre-existing cover object that the backfill normalized, and SHA-256 checksums. The preceding Docker image is recoverable as `ghcr.io/ankitson/readest:pre-metadata-sync-20260813`.

The live image was built from commit `dfba5a6a` and is tagged `ghcr.io/ankitson/readest:metadata-sync-20260813` and `ghcr.io/ankitson/readest:latest`. After migration and container replacement, Readest returns HTTP 200, has zero restarts, and its logs show a normal Next.js startup.

## Verification

- Metadata cleanup: 94 changes applied initially; final delayed dry run has zero changes.
- Covers: 33/33 uploads and indexes verified by hash and object size; zero live books lack a cover.
- Library invariants: progress, reading status, creation/upload dates, groups, tags, files, notes, configs, page statistics, and the five general `updated_at` values were unchanged by the follow-up.
- Targeted TypeScript and Python tests: 83 app tests and 7 script tests passed.
- Type checking and targeted Biome checks passed.
- Full Vitest run: 7,761 tests passed and 8 were skipped in the default environment; its only 18 failures were in two proofread suites missing their public Supabase test variables. Both suites then passed 63/63 tests with the expected public test configuration.
- Final live counts: 191 books, 1,532 notes/highlights, 186 reader configs, and 456 reading-stat pages.

An already-open browser or installed PWA should be refreshed once so it activates the new service worker and Date Read behavior.

## Commands

```bash
just readest-metadata-cleanup-test
just readest-metadata-cleanup-dry-run
just readest-cover-backfill-test
just readest-cover-backfill-prepare
```

Both mutating scripts require an explicit `--apply`; their default path is a dry run or plan generation.
