# Apple Books annotation import

## Outcome

Readest can import a per-book Apple Books annotation JSON file from the open book's annotation menu. It preserves exact selected ranges when the same EPUB edition is used and can recover by matching selected text when markup has shifted.

Repeated imports are safe: `apple-books-<annotation UUID>` is the stable Readest note ID, and the existing merge path only applies new or newer annotations.

## Interchange format

```json
{
  "format": "readest-apple-books-annotations",
  "version": 1,
  "exportedAt": 1786605106320,
  "book": {
    "assetId": "Apple Books asset ID",
    "title": "Book title",
    "author": "Book author",
    "epubId": "Optional EPUB package identifier"
  },
  "annotations": [
    {
      "uuid": "Apple annotation UUID",
      "cfi": "epubcfi(...) range",
      "selectedText": "Highlighted text",
      "note": "Attached note or empty string",
      "style": 3,
      "createdAt": 1756000000000,
      "updatedAt": 1756000001000
    }
  ]
}
```

Timestamps are Unix epoch milliseconds. `createdAt` and the annotation-level `updatedAt` preserve Apple Books source history. `exportedAt` becomes the imported Readest note's sync-visible `updatedAt`, ensuring a newly migrated historical annotation is newer than existing device sync cursors. Annotations without selected text or a valid EPUB CFI should not be exported into this format.

## Apple Books source fields

The Mac exporter reads these fields from `ZAEANNOTATION`:

- `ZANNOTATIONASSETID`
- `ZANNOTATIONUUID`
- `ZANNOTATIONLOCATION`
- `ZANNOTATIONSELECTEDTEXT`
- `ZANNOTATIONNOTE`
- `ZANNOTATIONSTYLE`
- `ZANNOTATIONCREATIONDATE`
- `ZANNOTATIONMODIFICATIONDATE`
- `ZANNOTATIONDELETED`
- `ZANNOTATIONTYPE`

Book identity comes from `ZBKLIBRARYASSET` (`ZASSETID`, `ZTITLE`, `ZAUTHOR`, and `ZEPUBID`). Apple timestamps use the 2001-01-01 epoch and must be converted to Unix milliseconds.

## Location strategy

1. Parse the source CFI and load its expected spine section.
2. Resolve the source CFI against the target section document.
3. Accept it only when normalized resolved text equals normalized selected text.
4. If it fails, search normalized selected text across all section text nodes, including ranges that span inline elements.
5. Rebuild the CFI from the located target range and the target section's CFI.
6. Report annotations that cannot be located; never persist a guessed chapter-start highlight.

## Appearance mapping

| Apple style | Apple appearance | Readest style | Readest color |
| --- | --- | --- | --- |
| 0 | Underline | underline | red |
| 1 | Green | highlight | green |
| 2 | Blue | highlight | blue |
| 3 | Yellow | highlight | yellow |
| 4 | Pink | highlight | red |
| 5 | Purple | highlight | violet |

The Apple enum and CFI fields are corroborated by the open-source [calibre-annotations iBooks reader](https://github.com/davidfor/calibre-annotations/blob/master/readers/_iBooks.py) and [books-annotations format notes](https://github.com/dado3212/books-annotations#books-app-information).

## User workflow

1. On `m2book`, run the companion exporter:

   ```bash
   cd ~/Documents/docs-root/projects/code/export-apple-books-highlights
   python3 apple_books_highlights.py \
     --output-dir ./exports \
     --readest-output-dir ./readest-exports
   ```

2. Find the matching per-book file in `readest-exports/`.
3. Open the matching EPUB in Readest.
4. Open Annotations → Import Annotations → Apple Books.
5. Select that book's `.json` file.
6. Review the result toast for imported and unmatched counts.

Repeated imports of the same file are safe because source UUIDs become stable Readest IDs and the file's `exportedAt` remains stable.

## Migration validation

The 2026-08-13 export contained 70 books, 1,538 annotations, and 26 attached notes. Apple Books had locally accessible EPUB packages for 65 of those books.

Six materially different real EPUBs were opened with Readest's production document loader and passed through the complete locator:

| Book | Coverage | Relevant variation |
| --- | ---: | --- |
| It's Not Always Depression | 15/15 | Shared sample; attached note |
| The Gene | 180/180 | High annotation count; notes |
| The Emperor of All Maladies | 162/162 | High count; alternate colors |
| Project Hail Mary | 44/44 | Multiple attached notes |
| The Hitchhiker's Guide to the Galaxy | 1/1 | Alternate color and note |
| The Adventures of Sherlock Holmes | 2/2 | Apple Store EPUB package |

Total: 404/404 located, zero unmatched.

The live sample book was migrated after backing up Readest. A database comparison verified all 15 annotation IDs, CFIs, selected texts, notes, appearances, creation timestamps, and migration timestamps with zero mismatches. Its pre-existing Readest bookmark was preserved.

## Recovery point

The verified pre-migration backup is at:

```text
/mnt/passport2tb/root/shared_storage/backups/readest/apple-books-migration-2026-08-13
```

It contains a PostgreSQL custom-format dump, the complete Readest MinIO bucket archive, SHA-256 checksums, and content listings. `pg_restore --list`, archive listing, and checksum verification all passed before live data was changed.

For Readest-to-Markdown, use the existing Annotations → Export Annotations action. Its advanced custom template can reproduce the older Apple Books Markdown layout if desired.
