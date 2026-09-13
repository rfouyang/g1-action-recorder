"""Tests for robot-relative Viser camera control."""

from __future__ import annotations

import math
import unittest
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import numpy as np

from app.ui_g1_3d.viser_manager import RobotCameraView, ViserManager


class ViserManagerTest(unittest.TestCase):
    def test_presets_use_the_robot_anatomical_coordinate_frame(self) -> None:
        presets = ViserManager.CAMERA_PRESETS

        self.assertGreater(presets[RobotCameraView.FRONT].position[0], 0.0)
        self.assertLess(presets[RobotCameraView.BACK].position[0], 0.0)
        self.assertGreater(presets[RobotCameraView.LEFT].position[1], 0.0)
        self.assertLess(presets[RobotCameraView.RIGHT].position[1], 0.0)
        self.assertGreater(
            presets[RobotCameraView.FRONT_LEFT_45].position[1],
            0.0,
        )
        self.assertLess(
            presets[RobotCameraView.FRONT_RIGHT_45].position[1],
            0.0,
        )

    def test_camera_preset_updates_connected_client_atomically(self) -> None:
        manager = ViserManager(
            simulation=Mock(),
            schema=Mock(),
            urdf_path=Path("robot.urdf"),
            host="127.0.0.1",
            port=0,
            camera_transition_seconds=0.0,
        )
        camera = SimpleNamespace(
            position=None,
            look_at=None,
            up_direction=None,
            fov=None,
        )
        client = Mock()
        client.camera = camera
        client.atomic.return_value = nullcontext()
        server = Mock()
        server.get_clients.return_value = {1: client}
        manager._server = server

        count = manager.set_camera_view(RobotCameraView.FRONT_LEFT_45)

        preset = manager.CAMERA_PRESETS[RobotCameraView.FRONT_LEFT_45]
        self.assertEqual(count, 1)
        self.assertEqual(camera.position, preset.position)
        self.assertEqual(camera.look_at, preset.look_at)
        self.assertEqual(camera.up_direction, preset.up)
        self.assertEqual(camera.fov, preset.vertical_fov)
        client.atomic.assert_called_once_with()

    def test_presets_use_a_tight_full_robot_composition(self) -> None:
        for preset in ViserManager.CAMERA_PRESETS.values():
            offset = np.asarray(preset.position) - np.asarray(preset.look_at)
            distance = float(np.linalg.norm(offset))
            visible_half_height = distance * math.tan(preset.vertical_fov / 2.0)

            self.assertAlmostEqual(preset.look_at[2], 0.68)
            self.assertAlmostEqual(math.degrees(preset.vertical_fov), 45.0)
            self.assertGreater(visible_half_height, 0.95)
            self.assertLess(visible_half_height, 0.97)

    def test_camera_transition_follows_an_orbit_instead_of_a_chord(self) -> None:
        front = ViserManager.CAMERA_PRESETS[RobotCameraView.FRONT]
        left = ViserManager.CAMERA_PRESETS[RobotCameraView.LEFT]

        position, look_at, up = ViserManager._interpolate_camera(
            start_position=np.asarray(front.position),
            start_look_at=np.asarray(front.look_at),
            start_up=np.asarray(front.up),
            preset=left,
            progress=0.5,
        )

        radius = np.linalg.norm((position - look_at)[:2])
        expected_radius = np.linalg.norm(
            (np.asarray(front.position) - np.asarray(front.look_at))[:2]
        )
        self.assertAlmostEqual(radius, expected_radius, places=6)
        self.assertGreater(position[0], 0.0)
        self.assertGreater(position[1], 0.0)
        np.testing.assert_allclose(up, (0.0, 0.0, 1.0))

    def test_camera_transition_reaches_exact_preset(self) -> None:
        front = ViserManager.CAMERA_PRESETS[RobotCameraView.FRONT]
        right = ViserManager.CAMERA_PRESETS[RobotCameraView.RIGHT]

        position, look_at, up = ViserManager._interpolate_camera(
            start_position=np.asarray(front.position),
            start_look_at=np.asarray(front.look_at),
            start_up=np.asarray(front.up),
            preset=right,
            progress=1.0,
        )

        np.testing.assert_allclose(position, right.position, atol=1e-12)
        np.testing.assert_allclose(look_at, right.look_at, atol=1e-12)
        np.testing.assert_allclose(up, right.up, atol=1e-12)


def demo_test_viser_manager() -> None:
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(ViserManagerTest)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    if not result.wasSuccessful():
        raise SystemExit(1)


def main() -> None:
    demo_test_viser_manager()


if __name__ == "__main__":
    main()
