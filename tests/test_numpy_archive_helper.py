"""Tests for safe atomic NPZ archive operations."""

from __future__ import annotations

import io
import tempfile
import unittest
from pathlib import Path

import numpy as np

from util.numpy_archive_helper import NumpyArchiveHelper


class NumpyArchiveHelperTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.directory = Path(self.temporary_directory.name)
        self.helper = NumpyArchiveHelper()

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def test_round_trip_and_sorted_listing(self) -> None:
        first_path = self.directory / "b_action.npz"
        second_path = self.directory / "a_action.npz"
        arrays = {
            "fps": np.asarray(25.0),
            "joint_names": np.asarray(["waist_yaw_joint", "left_elbow_joint"]),
            "joint_positions": np.asarray([[0.0, 1.4], [0.1, 0.8]]),
        }

        self.helper.write_npz(path=first_path, arrays=arrays)
        self.helper.write_npz(path=second_path, arrays=arrays)

        restored = self.helper.read_npz(path=first_path)
        self.assertEqual(set(restored), set(arrays))
        for name, expected in arrays.items():
            np.testing.assert_array_equal(restored[name], expected)
        self.assertEqual(
            self.helper.list_npz_files(directory=self.directory),
            (second_path, first_path),
        )

    def test_existing_file_requires_explicit_overwrite(self) -> None:
        path = self.directory / "action.npz"
        self.helper.write_npz(path=path, arrays={"value": np.asarray(1)})

        with self.assertRaises(FileExistsError):
            self.helper.write_npz(path=path, arrays={"value": np.asarray(2)})

        self.helper.write_npz(
            path=path,
            arrays={"value": np.asarray(2)},
            overwrite=True,
        )
        self.assertEqual(int(self.helper.read_npz(path=path)["value"]), 2)

    def test_rejects_invalid_suffix_empty_archive_and_object_arrays(self) -> None:
        with self.assertRaisesRegex(ValueError, "must end in .npz"):
            self.helper.write_npz(path=self.directory / "action.npy", arrays={"value": [1]})
        with self.assertRaisesRegex(ValueError, "at least one array"):
            self.helper.write_npz(path=self.directory / "empty.npz", arrays={})
        with self.assertRaisesRegex(ValueError, "object dtype"):
            self.helper.write_npz(
                path=self.directory / "unsafe.npz",
                arrays={"payload": np.asarray([{"unsafe": True}], dtype=object)},
            )

    def test_uploaded_archive_rejects_npy_and_pickle_arrays(self) -> None:
        npy_output = io.BytesIO()
        np.save(npy_output, np.zeros(2))
        with self.assertRaisesRegex(ValueError, "NPZ archive"):
            self.helper.read_npz_bytes(content=npy_output.getvalue())

        object_output = io.BytesIO()
        np.savez(object_output, payload=np.asarray([{"unsafe": True}], dtype=object))
        with self.assertRaisesRegex(ValueError, "Object arrays cannot be loaded"):
            self.helper.read_npz_bytes(content=object_output.getvalue())


def demo_test_numpy_archive_helper() -> None:
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(NumpyArchiveHelperTest)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    if not result.wasSuccessful():
        raise SystemExit(1)


def main() -> None:
    demo_test_numpy_archive_helper()


if __name__ == "__main__":
    main()
