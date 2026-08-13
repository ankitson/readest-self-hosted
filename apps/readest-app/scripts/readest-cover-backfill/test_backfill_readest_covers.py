"""Unit tests for Readest cover normalization helpers."""

import importlib.util
import io
import tempfile
import unittest
from pathlib import Path

from PIL import Image

MODULE_PATH = Path(__file__).with_name("backfill_readest_covers.py")
SPEC = importlib.util.spec_from_file_location("readest_cover_backfill", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)


class CoverBackfillTests(unittest.TestCase):
    def test_normalize_image_writes_bounded_rgb_png(self) -> None:
        source = Image.new("RGBA", (2400, 3000), (100, 120, 140, 128))
        raw = io.BytesIO()
        source.save(raw, "WEBP")
        with tempfile.TemporaryDirectory() as temp_name:
            destination = Path(temp_name) / "cover.png"
            MODULE.normalize_image(raw.getvalue(), destination)
            with Image.open(destination) as result:
                self.assertEqual(result.format, "PNG")
                self.assertEqual(result.mode, "RGB")
                self.assertLessEqual(result.width, 1600)
                self.assertLessEqual(result.height, 2000)

    def test_normalize_image_rejects_thumbnail(self) -> None:
        source = Image.new("RGB", (50, 50))
        raw = io.BytesIO()
        source.save(raw, "PNG")
        with (
            tempfile.TemporaryDirectory() as temp_name,
            self.assertRaisesRegex(ValueError, "too small"),
        ):
            MODULE.normalize_image(raw.getvalue(), Path(temp_name) / "cover.png")


if __name__ == "__main__":
    unittest.main()
