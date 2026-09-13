"""Tests for the shared MuJoCo simulation state capability."""

from __future__ import annotations

import unittest

from component.common.g1_joint_schema import G1JointSchema
from component.simulation import SimulationService
from config.settings import AppSettings
from util.g1_asset_helper import G1AssetHelper
from util.mujoco_pose_helper import MujocoPoseHelper


class SimulationServiceTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        settings = AppSettings()
        assets = G1AssetHelper(asset_dir=settings.g1_asset_dir)
        cls.schema = G1JointSchema(asset_helper=assets)
        cls.service = SimulationService(
            schema=cls.schema,
            pose_helper=MujocoPoseHelper(mjcf_path=assets.mjcf_path),
        )

    def test_partial_update_produces_complete_mujoco_snapshot(self) -> None:
        before = self.service.snapshot()
        after = self.service.update_joint_positions({"left_elbow_joint": 1.1})

        self.assertGreater(after.revision, before.revision)
        self.assertEqual(after.joint_position_map()["left_elbow_joint"], 1.1)
        self.assertEqual(len(after.joint_positions), 29)
        self.assertAlmostEqual(after.base_position[2], 0.793)

    def test_unknown_and_out_of_limit_joints_are_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "Unknown G1 joints"):
            self.service.update_joint_positions({"not_a_joint": 0.0})
        with self.assertRaisesRegex(ValueError, "outside"):
            self.service.update_joint_positions({"left_elbow_joint": 100.0})


def demo_test_simulation_service() -> None:
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(SimulationServiceTest)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    if not result.wasSuccessful():
        raise SystemExit(1)


def main() -> None:
    demo_test_simulation_service()


if __name__ == "__main__":
    main()
