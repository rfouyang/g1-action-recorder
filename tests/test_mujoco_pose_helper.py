"""Tests for arbitrary G1 pose application and front-view rendering."""

from __future__ import annotations

import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import mujoco
import numpy as np

from config.settings import AppSettings
from util.mujoco_pose_helper import CameraView, MujocoPoseHelper


class MujocoPoseHelperTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        settings = AppSettings()
        cls.helper = MujocoPoseHelper(mjcf_path=settings.g1_asset_dir / "g1_29dof_fake_hand.xml")

    def test_named_values_are_applied_to_the_correct_qpos_addresses(self) -> None:
        data = mujoco.MjData(self.helper.model)
        values = {
            "waist_yaw_joint": 0.2,
            "left_shoulder_roll_joint": 1.2,
            "right_elbow_joint": 0.7,
        }
        self.helper.apply_joint_values(data=data, joint_values=values)

        for joint_name, expected_value in values.items():
            joint_id = mujoco.mj_name2id(
                self.helper.model,
                mujoco.mjtObj.mjOBJ_JOINT,
                joint_name,
            )
            qpos_address = self.helper.model.jnt_qposadr[joint_id]
            self.assertAlmostEqual(data.qpos[qpos_address], expected_value)

    def test_arbitrary_pose_renders_and_differs_from_neutral(self) -> None:
        neutral_pixels = self.helper.render_joint_values(
            joint_values={},
            width=320,
            height=240,
        )
        raised_left_arm_pixels = self.helper.render_joint_values(
            joint_values={"left_shoulder_roll_joint": 1.2},
            width=320,
            height=240,
        )

        self.assertEqual(raised_left_arm_pixels.shape, (240, 320, 3))
        self.assertEqual(raised_left_arm_pixels.dtype, np.uint8)
        self.assertGreater(
            np.count_nonzero(neutral_pixels != raised_left_arm_pixels),
            1_000,
        )

    def test_front_camera_and_png_output(self) -> None:
        camera = self.helper.create_front_camera()
        self.assertEqual(camera.azimuth, 180.0)
        self.assertEqual(camera.elevation, -10.0)

        with tempfile.TemporaryDirectory() as temporary_directory:
            output_path = Path(temporary_directory) / "pose.png"
            result = self.helper.render_joint_values_to_file(
                joint_values={"left_elbow_joint": 0.8},
                output_path=output_path,
                width=320,
                height=240,
            )
            self.assertEqual(result, output_path)
            self.assertGreater(output_path.stat().st_size, 1_000)

    def test_five_robot_centric_camera_views_share_one_pose_state(self) -> None:
        expected_azimuths = {
            CameraView.FRONT: 180.0,
            CameraView.ROBOT_RIGHT: 90.0,
            CameraView.FRONT_RIGHT: 135.0,
            CameraView.ROBOT_LEFT: 270.0,
            CameraView.FRONT_LEFT: 225.0,
        }
        for camera_view, expected_azimuth in expected_azimuths.items():
            with self.subTest(camera_view=camera_view):
                self.assertEqual(
                    self.helper.create_camera(camera_view).azimuth,
                    expected_azimuth,
                )

        data = mujoco.MjData(self.helper.model)
        mujoco.mj_forward(self.helper.model, data)
        camera_positions = {}
        for camera_view in CameraView:
            scene = mujoco.MjvScene(self.helper.model, maxgeom=10_000)
            mujoco.mjv_updateScene(
                self.helper.model,
                data,
                mujoco.MjvOption(),
                mujoco.MjvPerturb(),
                self.helper.create_camera(camera_view),
                mujoco.mjtCatBit.mjCAT_ALL,
                scene,
            )
            camera_positions[camera_view] = np.mean(
                (scene.camera[0].pos, scene.camera[1].pos),
                axis=0,
            )

        self.assertGreater(camera_positions[CameraView.FRONT][0], 0.0)
        self.assertGreater(camera_positions[CameraView.ROBOT_LEFT][1], 0.0)
        self.assertLess(camera_positions[CameraView.ROBOT_RIGHT][1], 0.0)
        self.assertGreater(camera_positions[CameraView.FRONT_LEFT][1], 0.0)
        self.assertLess(camera_positions[CameraView.FRONT_RIGHT][1], 0.0)

        images = self.helper.render_joint_values_for_views(
            joint_values={"left_shoulder_roll_joint": 1.2},
            width=320,
            height=240,
        )
        self.assertEqual(set(images), set(CameraView))
        self.assertTrue(all(image.shape == (240, 320, 3) for image in images.values()))
        self.assertFalse(np.array_equal(images[CameraView.FRONT], images[CameraView.ROBOT_RIGHT]))
        self.assertFalse(np.array_equal(images[CameraView.FRONT], images[CameraView.FRONT_RIGHT]))
        self.assertFalse(np.array_equal(images[CameraView.FRONT], images[CameraView.ROBOT_LEFT]))
        self.assertFalse(np.array_equal(images[CameraView.FRONT], images[CameraView.FRONT_LEFT]))

    def test_concurrent_preview_requests_are_serialized_safely(self) -> None:
        def render(value: float) -> np.ndarray:
            return self.helper.render_joint_values(
                joint_values={"left_shoulder_roll_joint": value},
                width=160,
                height=120,
            )

        with ThreadPoolExecutor(max_workers=4) as executor:
            images = tuple(executor.map(render, (0.1, 0.2, 0.3, 0.4)))

        self.assertTrue(all(image.shape == (120, 160, 3) for image in images))

    def test_invalid_joint_value_and_image_size_are_rejected(self) -> None:
        data = mujoco.MjData(self.helper.model)
        with self.assertRaisesRegex(ValueError, "Unknown MuJoCo joints"):
            self.helper.apply_joint_values(data=data, joint_values={"not_a_joint": 0.0})
        with self.assertRaisesRegex(ValueError, "must be finite"):
            self.helper.apply_joint_values(
                data=data,
                joint_values={"left_elbow_joint": float("nan")},
            )
        with self.assertRaisesRegex(ValueError, "outside"):
            self.helper.apply_joint_values(
                data=data,
                joint_values={"left_elbow_joint": 99.0},
            )
        with self.assertRaisesRegex(ValueError, "width must be positive"):
            self.helper.render_joint_values(joint_values={}, width=0, height=240)
        with self.assertRaisesRegex(ValueError, "must end in .png"):
            self.helper.render_joint_values_to_file(
                joint_values={},
                output_path=Path("preview.jpg"),
            )


def demo_test_mujoco_pose_helper() -> None:
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(MujocoPoseHelperTest)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    if not result.wasSuccessful():
        raise SystemExit(1)


def main() -> None:
    demo_test_mujoco_pose_helper()


if __name__ == "__main__":
    main()
