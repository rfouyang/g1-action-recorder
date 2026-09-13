"""Tests for atomic UTF-8 pose JSON file operations."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from util.pose_file_helper import PoseFileHelper


class PoseFileHelperTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.directory = Path(self.temporary_directory.name)
        self.helper = PoseFileHelper()

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def test_utf8_round_trip_and_listing(self) -> None:
        second_path = self.directory / "第二个.json"
        first_path = self.directory / "第一个.json"
        self.helper.write_json(path=second_path, payload={"name": "第二个"})
        self.helper.write_json(path=first_path, payload={"name": "第一个"})

        self.assertEqual(self.helper.read_json(path=first_path), {"name": "第一个"})
        self.assertEqual(
            self.helper.list_json_files(directory=self.directory),
            (first_path, second_path),
        )

    def test_existing_file_requires_explicit_overwrite(self) -> None:
        path = self.directory / "pose.json"
        self.helper.write_json(path=path, payload={"value": 1})
        with self.assertRaises(FileExistsError):
            self.helper.write_json(path=path, payload={"value": 2})
        self.assertEqual(self.helper.read_json(path=path), {"value": 1})

        self.helper.write_json(path=path, payload={"value": 2}, overwrite=True)
        self.assertEqual(self.helper.read_json(path=path), {"value": 2})

    def test_invalid_json_and_non_object_are_rejected(self) -> None:
        invalid_path = self.directory / "invalid.json"
        invalid_path.write_text("{", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "Invalid JSON"):
            self.helper.read_json(path=invalid_path)

        list_path = self.directory / "list.json"
        list_path.write_text("[]", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "root must be an object"):
            self.helper.read_json(path=list_path)


def demo_test_pose_file_helper() -> None:
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(PoseFileHelperTest)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    if not result.wasSuccessful():
        raise SystemExit(1)


def main() -> None:
    demo_test_pose_file_helper()


if __name__ == "__main__":
    main()
