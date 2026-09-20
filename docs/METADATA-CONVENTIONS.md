# Book metadata conventions

Moved. These conventions describe the **deployment's library data**, not this
repo's code, and would still hold if the fork were rewritten from scratch — so
they live in the engineering wiki rather than here:

`~/hroot/allplace/wiki/engineering/readest-self-hosted.md` → "Book metadata
conventions"

That page carries the full detail: what `book_hash` and `meta_hash` each key and
why editing the `metadata` column cannot re-key a book; the identifier, author,
language and date shapes; the changes deliberately *not* made to the identifier
reducer and to `getPreferredIdentifier`, with the measurements behind each; the
three separate clocks; and the dump → dry-run → rollback-rehearsal → apply
procedure for touching library data.

Kept as a pointer because `docs/NOTES.md` and `docs/CHANGELOG.md` reference this
path in dated entries.
