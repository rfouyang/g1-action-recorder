"""Tests for multi-camera MuJoCo action GIF rendering."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import numpy as np
from PIL import Image

from config.settings import AppSettings
from util.mujoco_action_helper import MujocoActionHelper
from util.mujoco_pose_helper import CameraView, MujocoPoseHelper


class MujocoActionHelperTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        settings = AppSettings()
        cls.helper = MujocoActionHelper(
            pose_helper=MujocoPoseHelper(
                mjcf_path=settings.g1_asset_dir / "g1_29dof_fake_hand.xml"
            )
        )

    def test_renders_synchronized_five_camera_gif(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            output_path = Path(temporary_directory) / "action.gif"
            result = self.helper.render_trajectory_gif(
                joint_names=("left_shoulder_roll_joint", "left_elbow_joint"),
                timestamps=(0.0, 0.5, 1.0),
                joint_positions=((0.18, 1.4), (1.0, 0.6), (0.18, 1.4)),
                output_path=output_path,
                view_width=80,
                view_height=60,
            )

            self.assertEqual(result, output_path)
            self.assertGreater(output_path.stat().st_size, 1_000)
            with Image.open(output_path) as preview:
                self.assertEqual(preview.n_frames, 3)
                self.assertEqual(preview.size, (240, 120))

    def test_can_render_one_selected_camera(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            output_path = Path(temporary_directory) / "front.gif"
            self.helper.render_trajectory_gif(
                joint_names=("left_elbow_joint",),
                timestamps=np.array([0.0, 0.1]),
                joint_positions=np.array([[1.4], [0.8]]),
                output_path=output_path,
                camera_views=(CameraView.FRONT,),
                view_width=80,
                view_height=60,
            )
            with Image.open(output_path) as preview:
                self.assertEqual(preview.size, (80, 60))

    def test_rejects_invalid_trajectory_and_output_options(self) -> None:
        valid_arguments = {
            "joint_names": ("left_elbow_joint",),
            "timestamps": (0.0, 0.1),
            "joint_positions": ((1.4,), (0.8,)),
        }
        with self.assertRaisesRegex(ValueError, "must end in .gif"):
            self.helper.render_trajectory_gif(
                **valid_arguments,
                output_path=Path("action.mp4"),
            )
        with self.assertRaisesRegex(ValueError, "unknown MuJoCo joints"):
            self.helper.render_trajectory_gif(
                joint_names=("missing_joint",),
                timestamps=(0.0, 0.1),
                joint_positions=((0.0,), (0.1,)),
                output_path=Path("action.gif"),
            )
        with self.assertRaisesRegex(ValueError, "shape or values"):
            self.helper.render_trajectory_gif(
                joint_names=("left_elbow_joint",),
                timestamps=(0.0, 0.1),
                joint_positions=((1.4,),),
                output_path=Path("action.gif"),
            )


def demo_test_mujoco_action_helper() -> None:
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(MujocoActionHelperTest)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    if not result.wasSuccessful():
        raise SystemExit(1)


def main() -> None:
    demo_test_mujoco_action_helper()


if __name__ == "__main__":
    main()
