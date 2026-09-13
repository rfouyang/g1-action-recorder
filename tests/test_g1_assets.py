"""Tests for the canonical G1 fake-hand model assets."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from config.settings import AppSettings
from util.g1_asset_helper import G1AssetHelper


class G1AssetHelperTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        settings = AppSettings()
        cls.asset_dir = settings.g1_asset_dir
        cls.helper = G1AssetHelper(asset_dir=cls.asset_dir)

    def test_urdf_and_mjcf_contract(self) -> None:
        report = self.helper.validate()
        self.assertEqual(report.robot_joint_count, 29)
        self.assertEqual(report.upper_body_joint_count, 17)
        self.assertEqual(report.actuator_count, 29)
        self.assertEqual(report.mesh_count, 35)

    def test_metadata_matches_validated_contract(self) -> None:
        metadata = json.loads((self.asset_dir / "model_metadata.json").read_text())
        report = self.helper.validate()

        self.assertEqual(metadata["robot_joint_count"], report.robot_joint_count)
        self.assertEqual(metadata["pose_joint_count"], report.upper_body_joint_count)
        self.assertEqual(metadata["mesh_count"], report.mesh_count)
        self.assertEqual(metadata["hand_joint_count"], 0)
        self.assertEqual(metadata["hand_geometry"]["attachment"], "fixed")

    def test_neutral_pose_renders(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            output_path = Path(temporary_directory) / "neutral_pose.png"
            rendered_path = self.helper.render_neutral_pose(output_path=output_path)
            self.assertTrue(rendered_path.is_file())
            self.assertGreater(rendered_path.stat().st_size, 1_000)


def demo_test_g1_assets() -> None:
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(G1AssetHelperTest)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    if not result.wasSuccessful():
        raise SystemExit(1)


def main() -> None:
    demo_test_g1_assets()


if __name__ == "__main__":
    main()
