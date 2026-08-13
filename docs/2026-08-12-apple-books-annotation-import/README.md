# Apple Books annotation import

## Outcome

Readest can import a per-book Apple Books annotation JSON file from the open book's annotation menu. It preserves exact selected ranges when the same EPUB edition is used and can recover by matching selected text when markup has shifted.

Repeated imports are safe: `apple-books-<annotation UUID>` is the stable Readest note ID, and the existing merge path only applies new or newer annotations.

## Interchange format

```json
{
  "format": "readest-apple-books-annotations",
  "version": 1,
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

Timestamps are Unix epoch milliseconds. Annotations without selected text or a valid EPUB CFI should not be exported into this format.

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

1. Export Apple Books annotations into per-book `.json` files using the companion exporter.
2. Open the matching EPUB in Readest.
3. Open Annotations → Import Annotations → Apple Books.
4. Select that book's `.json` file.
5. Review the result toast for imported and unmatched counts.

For Readest-to-Markdown, use the existing Annotations → Export Annotations action. Its advanced custom template can reproduce the older Apple Books Markdown layout if desired.

