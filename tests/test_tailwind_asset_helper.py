"""Tests for automatic G1 3D frontend asset rebuilding."""

from __future__ import annotations

import os
import tempfile
import time
import unittest
from pathlib import Path

from util.tailwind_asset_helper import TailwindAssetHelper


class TailwindAssetHelperTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.project_root = Path(self.temporary_directory.name)
        self.source_directory = self.project_root / "templates"
        self.source_directory.mkdir()
        self.input_path = self.project_root / "input.css"
        self.output_path = self.project_root / "app.css"
        self.template_path = self.source_directory / "base.html"
        self.input_path.write_text('@import "tailwindcss";', encoding="utf-8")
        self.template_path.write_text("<main></main>", encoding="utf-8")
        self.helper = TailwindAssetHelper(
            project_root=self.project_root,
            input_path=self.input_path,
            output_path=self.output_path,
            source_directories=(self.source_directory,),
        )

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def test_missing_output_requires_build(self) -> None:
        self.assertTrue(self.helper.needs_build())

    def test_newer_source_requires_build(self) -> None:
        self.output_path.write_text("compiled", encoding="utf-8")
        now = time.time_ns()
        os.utime(self.input_path, ns=(now, now))
        os.utime(self.template_path, ns=(now, now))
        os.utime(self.output_path, ns=(now + 1_000_000, now + 1_000_000))

        self.assertFalse(self.helper.needs_build())

        os.utime(self.template_path, ns=(now + 2_000_000, now + 2_000_000))
        self.assertTrue(self.helper.needs_build())


def demo_test_tailwind_asset_helper() -> None:
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(TailwindAssetHelperTest)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    if not result.wasSuccessful():
        raise SystemExit(1)


def main() -> None:
    demo_test_tailwind_asset_helper()


if __name__ == "__main__":
    main()
