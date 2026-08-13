"""Unit tests for deterministic Readest metadata cleanup planning."""

import importlib.util
import unittest
from pathlib import Path

MODULE_PATH = Path(__file__).with_name("apply_readest_metadata_cleanup.py")
SPEC = importlib.util.spec_from_file_location("readest_metadata_cleanup", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)


class MetadataCleanupTests(unittest.TestCase):
    def test_valid_isbn_checks_checksums(self) -> None:
        self.assertEqual(MODULE.valid_isbn("978-0-19-068601-7"), "9780190686017")
        self.assertEqual(MODULE.valid_isbn("0393046346"), "0393046346")
        self.assertIsNone(MODULE.valid_isbn("9780190686018"))

    def test_natural_author_list(self) -> None:
        self.assertEqual(
            MODULE.natural_author_list("Connie Zweig; Steven Wolf"),
            "Connie Zweig and Steven Wolf",
        )
        self.assertEqual(MODULE.natural_author_list("A; B; C"), "A, B, and C")
        self.assertEqual(MODULE.natural_author_list("James Nestor;"), "James Nestor")

    def test_global_title_and_author_normalization_preserves_date(self) -> None:
        books = [
            {
                "userId": "user",
                "hash": "hash",
                "title": "Book: Subtitle",
                "author": "First Author; Second Author",
                "updatedAt": 1234,
                "metadata": {
                    "title": "Book: Subtitle",
                    "author": "First Author; Second Author",
                },
            }
        ]
        corrections = {
            "normalizations": {
                "splitTitleSubtitleAtFirstColon": True,
                "normalizeSemicolonSeparatedAuthors": True,
            },
            "restoreUpdatedAt": {},
            "books": {},
        }
        plan = MODULE.build_cleanup_plan(books, corrections)[0]
        self.assertEqual(plan["metadata"]["title"], "Book")
        self.assertEqual(plan["metadata"]["subtitle"], "Subtitle")
        self.assertEqual(plan["author"], "First Author and Second Author")
        self.assertEqual(plan["updatedAt"], 1234)

    def test_reviewed_override_and_date_restore(self) -> None:
        books = [
            {
                "userId": "user",
                "hash": "hash",
                "title": "BAD TITLE",
                "author": "UnknownAuthor",
                "updatedAt": 9999,
                "metadata": {"title": "BAD TITLE", "author": "UnknownAuthor"},
            }
        ]
        corrections = {
            "normalizations": {},
            "restoreUpdatedAt": {"hash": 1111},
            "books": {
                "hash": {
                    "expectedTitle": "BAD TITLE",
                    "set": {"title": "Good Title", "author": "Good Author"},
                }
            },
        }
        plan = MODULE.build_cleanup_plan(books, corrections)[0]
        self.assertEqual(plan["title"], "Good Title")
        self.assertEqual(plan["updatedAt"], 1111)

    def test_reviewed_override_is_idempotent_after_cleanup(self) -> None:
        books = [
            {
                "userId": "user",
                "hash": "hash",
                "title": "Good Title",
                "author": "Good Author",
                "updatedAt": 1111,
                "metadata": {"title": "Good Title", "author": "Good Author"},
            }
        ]
        corrections = {
            "normalizations": {},
            "restoreUpdatedAt": {"hash": 1111},
            "books": {
                "hash": {
                    "expectedTitle": "BAD TITLE",
                    "set": {"title": "Good Title", "author": "Good Author"},
                }
            },
        }
        self.assertEqual(MODULE.build_cleanup_plan(books, corrections), [])


if __name__ == "__main__":
    unittest.main()
