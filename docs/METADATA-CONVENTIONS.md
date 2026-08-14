# Book metadata conventions

How book metadata is shaped in this deployment, and — just as important — which
tempting "fixes" are deliberately **not** applied. Written after a full library
audit; every claim here was verified against the code and the live database
rather than inferred.

## Background: the two hashes

| | derived from | keys |
|---|---|---|
| `book_hash` | `partialMD5(file)` — twelve 1 KB slices at exponentially spaced offsets (`utils/md5.ts`) | the **file**. Primary key `books(user_id, book_hash)`; names the storage directory |
| `meta_hash` | `md5("title\|authors\|identifiers")`, NFC-normalized (`getMetadataHashInfo`, `utils/book.ts`) | the **work**. Secondary matching key |

`meta_hash` exists so the same book arriving as a different file is recognized:
import dedup keys on `${metaHash}:${format}` (`bookService.ts`) and adopts the
existing config — progress, notes — instead of starting a fresh entry. The sync
API also matches on it (`book_hash.eq.X,meta_hash.eq.Y`, `pages/api/sync.ts`).

### The distinction that governs everything below

**`meta_hash` is computed from the metadata parsed out of the book FILE, never
from the `metadata` column.** All three write sites confirm it:

```
readerStore.ts    getMetadataHash(bookDoc.metadata)     // every book open, unconditional
bookService.ts    getMetadataHash(loadedBook.metadata)  // import
bookService.ts    getMetadataHash(bookDoc.metadata)
```

Consequences, both of which are load-bearing:

- Editing the `metadata` column **cannot re-key a book**. Server-side metadata
  cleanup is always hash-safe. There is no need for a "would this move the
  hash?" guard, and any such guard is solving a non-problem.
- Conversely, the **only** thing that re-keys books is changing the hashing code
  itself (`normalizeIdentifier`, `getIdentifiersList`, `getPreferredIdentifier`,
  or the `hashSource` template). See "Do not patch the reducer" below.

Because `readerStore` recomputes without a `??` guard, a re-key self-heals: each
client rewrites `meta_hash` from the file the next time the book is opened.

## Conventions we follow

**`identifier` — RFC URN form, payload verbatim.**
`urn:isbn:<compact, no hyphens>` and `urn:uuid:<lowercase>`. EPUB's
`dc:identifier` is specified as a URI; ISBN has `urn:isbn` (RFC 3187) and UUID
has `urn:uuid` (RFC 4122). Anything without a registered namespace keeps whatever
form it already has:

- **URLs stay whole.** A publisher or Gutenberg URL is already a URI.
- **ASINs stay `urn:asin:`.** Proprietary, but consistent, and for ebook-only
  titles no ISBN exists to prefer.
- **Opaque publisher ids stay as-is.** Do not guess a scheme.

**`author` — an array, one entry per author.** This is not cosmetic.
`formatAuthorName` splits on spaces and hoists the last *word* for sort order, so
a joined string sorts as `"Weinersmith, Kelly Weinersmith, Zach"` while an array
sorts correctly. `formatAuthors` also only reaches its list formatter for arrays.
Joined strings render verbatim and sort wrong.

**Author list rendering — `A, B, C`.** `formatAuthors` uses
`Intl.ListFormat` with type `unit`, not `conjunction`; a credit line is a list,
not a sentence. (This is a fork patch; see CHANGELOG 2026-08-14.)

**`language` — a BCP-47 string.** Plain `en` is the house default. Regional
variants (`en-US`, `en-GB`, and multi-region arrays) are **kept**: they are valid,
they encode real spelling/hyphenation intent, and `getPrimaryLanguage` splits on
`-` anyway so they cost nothing downstream.

**`published` — ISO 8601.** Four-digit year, zero-padded month and day.

**Writes stamp `metadata_updated_at`, never `updated_at`.** Metadata merges on
its own clock; `updated_at` drives the Date Read sort, so touching it makes a
metadata edit masquerade as a reading session.

**Every group / tag mutation must stamp `metadataUpdatedAt`.** `groupId`,
`groupName` and `tags` are resolved on the metadata clock. A mutation that bumps
only `updatedAt` leaves the clocks tied, ties resolve to local, and two devices
revert each other indefinitely. There is a source-level guard test for this.

## Conventions we deliberately do NOT follow

**Do not patch `normalizeIdentifier`.** It has three genuine defects: `urn:`
detection is case-sensitive (`URN:ISBN:x` keeps `ISBN:` in the payload), a
non-`urn` URI loses its scheme (`http://host/600` → `//host/600`), and the
payload is not canonicalized so `978-0-…` and `9780…` hash differently. All three
were measured against the real library and cost **nothing**: a hash needs to be
*deterministic*, not correct-looking, every device runs identical code, and no
pair of files in the library differs only in identifier packaging. Against that,
patching it means:

- a one-time re-key of every book;
- permanent divergence in a file upstream edits roughly every two months, merged
  by an unattended nightly cron — where the likely outcome is not a loud conflict
  but upstream updates quietly ceasing to land;
- a nonzero chance of a clean-but-semantically-wrong merge that re-keys again
  silently.

Revisit only if a real missed match appears. Upstream showed the sanctioned way
to ship such a change: bump a version key (`meta_hash` → `meta_hash_v1`) so
caches recompute rather than migrate.

**Do not flip `getPreferredIdentifier`'s `uuid > calibre > isbn` order.** It
looks backwards — a UUID differs between independently sourced files while an
ISBN identifies the edition — but it is correct for its stated purpose
(`compat(koplugin): … robust for calibre conversions and metadata edits`).
`uuid`/`calibre` identify the library *record* and survive a user correcting a
title, author, or ISBN; `isbn` is user-editable data. ISBN is also not
single-valued: one book in this library carries two ISBNs for two editions, so
isbn-first would make its hash depend on array order.

**Do not canonicalize harder to force more matches.** Upstream's most recent
change in this area was *"do not dedupe distinct PDFs with identical metadata"* —
they were fixing over-merging. A missed match yields a duplicate you can delete;
a false match silently fuses two books' progress and highlights. Prefer the
recoverable failure.

**Do not rewrite `altIdentifier`.** It is a verbatim record of what the EPUB
declared — provenance. It is not displayed, and the ISBN extractor already
tolerates every shape it takes (string, array, `{scheme, value}` object).
Rewriting destroys information for no gain. Note it also *wins over* `identifier`
in `getIdentifiersList`, so for books that have one, the scalar `identifier`
never reaches the hash at all.

**Do not flatten regional language variants** to bare `en`. See above.

**Do not mint identifiers that do not exist.** A self-published title with no
ISBN or ASIN gets the author's canonical page URL, or nothing. Inventing an
identifier fabricates data and adds an entry to `hashSource` where there was
none.

**Do not hard-delete a book to remove it.** Deletion propagates via a
`deleted_at` tombstone; a hard delete vanishes server-side but leaves the row on
every device, which pushes it straight back. Mirror the app: tombstone the
`books` row (`deleted_at`, `uploaded_at=NULL`), drop the `files` rows, and remove
the storage objects. Purge the tombstone only once every device has synced.

## Applying metadata changes safely

The pattern used for every pass, and worth keeping:

1. `pg_dumpall` first.
2. **Dry run** — print every proposed change; eyeball anything heuristic
   (author splitting in particular: organisation names containing "and" must not
   be split, and a role prefix like `Edited by` belongs to the whole credit, not
   to the first name).
3. **Rollback rehearsal** — execute the full statement set in a transaction that
   ends in `ROLLBACK`, with probes for row counts, note counts, the double-encoded
   `metadata` shape, and `updated_at` immobility. Compare against the real apply.
4. **Apply**, and confirm the probes match the rehearsal.

Encode literals as base64 decoded server-side (`convert_from(decode(…),'UTF8')`)
— book titles are full of apostrophes. Re-encode `metadata` with
`to_json(<text>)` to reproduce the double-encoded shape the client writes.

Ad-hoc scripts and anything quoting real library contents live in the gitignored
`tmp/`, never in the repo — this repo is public.
