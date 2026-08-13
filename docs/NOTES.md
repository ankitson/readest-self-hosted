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

- Extend the existing Mac Apple Books exporter to emit the documented JSON interchange files.
- Run a compatibility audit across additional Apple Books EPUBs when `m2book` or its shared code tree is available.

