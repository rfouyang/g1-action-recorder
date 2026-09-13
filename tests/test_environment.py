"""Smoke tests for the Step 1 project environment."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import mujoco
import numpy
import pink
import pinocchio
import viser
from qpsolvers import available_solvers

from config.settings import AppSettings


class EnvironmentTest(unittest.TestCase):
    def test_required_packages_import(self) -> None:
        self.assertTrue(mujoco.__version__)
        self.assertTrue(numpy.__version__)
        self.assertTrue(pink.__version__)
        self.assertTrue(pinocchio.__version__)
        self.assertTrue(viser.__version__)
        self.assertIn("quadprog", available_solvers)

    def test_runtime_directories_are_created(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            settings = AppSettings(project_root=Path(temporary_directory))
            settings.ensure_runtime_directories()

            expected_directories = (
                settings.pose_dir / "base",
                settings.pose_dir / "left_arm",
                settings.pose_dir / "right_arm",
                settings.pose_dir / "composed",
                settings.pose_preview_dir,
                settings.action_definition_dir,
                settings.action_trajectory_dir,
                settings.action_preview_dir,
            )
            for directory in expected_directories:
                self.assertTrue(directory.is_dir(), directory)


def demo_test_environment() -> None:
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(EnvironmentTest)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    if not result.wasSuccessful():
        raise SystemExit(1)


def main() -> None:
    demo_test_environment()


if __name__ == "__main__":
    main()
