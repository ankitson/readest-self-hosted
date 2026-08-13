import hashlib
import tempfile
import unittest
from pathlib import Path

from apply_apple_books_library import (
    ExistingReadestBook,
    partial_md5,
    remap_matching_readest_editions,
    sql_progress,
    sql_text,
)


class ApplyAppleBooksLibraryTests(unittest.TestCase):
    def test_partial_md5_matches_full_md5_for_small_file(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "small.epub"
            path.write_bytes(b"readest migration")
            self.assertEqual(
                partial_md5(path),
                hashlib.md5(path.read_bytes(), usedforsecurity=False).hexdigest(),
            )

    def test_sql_text_does_not_embed_original_text(self):
        expression = sql_text("apostrophe's and unicode π")
        self.assertNotIn("apostrophe", expression)
        self.assertIn("decode(", expression)

    def test_progress_renders_readest_database_shapes(self):
        self.assertEqual(sql_progress([25, 100], "array"), "ARRAY[25,100]::integer[]")
        self.assertIn("to_jsonb", sql_progress([25, 100], "json"))

    def test_remaps_same_metadata_to_existing_readest_edition(self):
        book = {
            "assetId": "apple-1",
            "bookHash": "apple-hash",
            "metaHash": "same-meta",
            "notes": [{"bookHash": "apple-hash"}],
        }
        existing = {
            "readest-hash": ExistingReadestBook(
                book_hash="readest-hash",
                meta_hash="same-meta",
                updated_at=10,
                config_updated_at=10,
                has_book_file=True,
                has_cover_file=True,
            )
        }

        remapped, resolutions = remap_matching_readest_editions([book], existing)

        self.assertEqual(remapped[0]["bookHash"], "readest-hash")
        self.assertEqual(remapped[0]["notes"][0]["bookHash"], "readest-hash")
        self.assertEqual(book["bookHash"], "apple-hash")
        self.assertEqual(len(resolutions), 1)


if __name__ == "__main__":
    unittest.main()
