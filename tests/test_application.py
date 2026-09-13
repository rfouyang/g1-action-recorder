"""Tests for the shared G1 application composition root."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from app.application import RobotApplication


class RobotApplicationTest(unittest.TestCase):
    def test_builds_shared_pose_and_action_services(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary_root = Path(temporary_directory)
            application = RobotApplication.create(
                pose_dir=temporary_root / "poses",
                action_definition_dir=temporary_root / "actions",
                action_trajectory_dir=temporary_root / "trajectories",
                action_preview_dir=temporary_root / "previews",
            )

            self.assertIs(application.action_service.pose_service, application.pose_service)
            self.assertIs(application.action_player._playback.simulation, application.simulation)
            self.assertIs(application.action_player.action_service, application.action_service)
            self.assertIs(application.pose_service.schema, application.joint_schema)
            self.assertIs(application.simulation.schema, application.joint_schema)
            self.assertEqual(
                application.simulation.snapshot().joint_names,
                application.joint_schema.DDS_JOINT_NAMES,
            )

def demo_test_robot_application() -> None:
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(RobotApplicationTest)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    if not result.wasSuccessful():
        raise SystemExit(1)


def main() -> None:
    demo_test_robot_application()


if __name__ == "__main__":
    main()
