## 2026-08-13

### Apple Books migration hardening

- Added a required stable export timestamp so imported historical annotations cross Readest sync cursors.
- Completed a 404-annotation compatibility audit across six real EPUBs with zero unmatched ranges.
- Completed and verified the 15-annotation live migration for the shared sample book.
- Documented the companion exporter workflow and verified recovery point.

## 2026-08-12

### Apple Books annotation import

- Added a versioned Apple Books JSON parser with strict runtime validation.
- Added lossless Apple Books-to-Readest annotation conversion, style mapping, stable IDs, and timestamp preservation.
- Added target-EPUB CFI verification and selected-text recovery for markup changes.
- Added Apple Books to the reader's annotation import dialog with mismatch, invalid-file, and unmatched-range feedback.
- Added unit and UI coverage for parsing, conversion, style mapping, title matching, CFI location, fallback recovery, and dialog behavior.
