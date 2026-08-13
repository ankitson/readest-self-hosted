# Readest library metadata cleanup

## Outcome

The one-off cleanup corrected metadata on 94 of 191 live Readest books without changing reading state or cover art. A second dry run reports zero changes, so the checked-in correction manifest is idempotent against the cleaned library.

| Change | Books |
| --- | ---: |
| Titles normalized | 61 |
| Subtitles moved to `metadata.subtitle` | 52 |
| Author metadata normalized | 42 |
| Top-level author display normalized | 35 |
| Identifiers added | 21 |
| ISBN fields added | 18 |
| Series names changed | 15 |
| Series positions added | 14 |

The resulting library has no `UnknownAuthor` values, no filename-like titles, and no inverted personal-author display names. The only books without an identifier are David Cain's two self-published PDFs, *How to Do Things* and *How to Save the World*, for which no stable ISBN or ASIN was present or confidently identifiable.

## Date Read preservation

Readest labels `books.updated_at` as “Date Read” in the library sort menu, even though the field is a general book-update timestamp. Metadata updates therefore write `metadata_updated_at` and leave `updated_at` unchanged.

Five books had already been moved by manual metadata editing. Their `updated_at` values were restored from their historical Apple Books last-opened/engagement state:

| Book | Restored Date Read (UTC) |
| --- | --- |
| Agent Zero | 2023-01-07 17:48:56.946 |
| The Kama Sutra | 2011-01-04 19:13:56.000 |
| The Republic | 2026-06-27 23:05:53.776 |
| The Adventures of Sherlock Holmes | 2024-04-27 09:09:13.620 |
| How Life Works | 2025-09-05 07:23:51.085 |

These were the only five Date Read changes. The Republic's restored date is later than the others because that is its real source reading date, not the metadata-edit time.

## Metadata decisions

- Titles with a clear colon-delimited subtitle now use separate `title` and `subtitle` fields.
- Personal authors use natural `Firstname Lastname` display order. Multiple authors use natural English lists with a final “and”. The corporate author “Immigration, Refugees and Citizenship Canada” remains unchanged.
- The three GPU books use the series *The History of the GPU*, positions 1–3.
- The two present Hitchhiker's books use the series *The Hitchhiker's Guide to the Galaxy*, positions 1 and 5.
- Other high-confidence series were added for Southern Reach, Monk and Robot, A Song of Ice and Fire, Millennium, Hercule Poirot, Moomins, Thursday Murder Club, and Culture.
- “Apple Books Classics” was removed from Sherlock Holmes because it is a retailer collection rather than the book's literary series.
- Existing user-selected covers were preserved. No files, covers, notes, or highlights were rewritten.
- Exact-edition identifiers came from embedded book data where available and were supplemented by publisher/catalog records for the local editions.

## Safety and verification

The verified recovery point is:

```text
/mnt/passport2tb/root/shared_storage/backups/readest/readest-metadata-cleanup-2026-08-13/pre-cleanup
```

It contains a PostgreSQL custom-format dump, a 191-book JSON snapshot, a `pg_restore` listing, and SHA-256 checksums. Both the dump and snapshot checksums passed immediately before apply.

The apply command ran as one guarded PostgreSQL transaction. Post-apply fingerprints proved these remained byte-for-byte logically unchanged:

- Book progress, reading status, status timestamp, creation/upload dates, groups, tags, and metadata hashes.
- Cover hashes and cover timestamps.
- Reader configuration and resume positions.
- Notes and highlights.
- Book files and their indexes.
- Book/page reading statistics.

The post-apply dry run reports `changedBooks: 0`. No Readest image was built, replaced, or deployed for this cleanup.

## Commands

```bash
just readest-metadata-cleanup-test
just readest-metadata-cleanup-dry-run
```

The mutating operation is intentionally explicit:

```bash
cd apps/readest-app/scripts/readest-metadata-cleanup
uv run --script apply_readest_metadata_cleanup.py --apply --report /path/to/report.json
```
