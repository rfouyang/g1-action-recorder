"""Tests for fixed-base G1 inverse kinematics through Pink."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import numpy as np

from component.common.g1_joint_schema import G1JointSchema, PoseType
from component.common.models import PoseDefinition
from config.settings import AppSettings
from util.g1_asset_helper import G1AssetHelper
from util.mujoco_pose_helper import MujocoPoseHelper
from util.pink_ik_helper import PinkIKHelper


class PinkIKHelperTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        settings = AppSettings()
        asset_helper = G1AssetHelper(asset_dir=settings.g1_asset_dir)
        cls.schema = G1JointSchema(asset_helper=asset_helper)
        cls.helper = PinkIKHelper(urdf_path=asset_helper.urdf_path)
        cls.mujoco_helper = MujocoPoseHelper(mjcf_path=asset_helper.mjcf_path)
        initial_pose_path = settings.pose_dir / "base" / settings.initial_base_pose_name
        initial_pose = PoseDefinition.from_json(
            schema=cls.schema,
            content=initial_pose_path.with_suffix(".json").read_text(encoding="utf-8"),
        )
        cls.reference_values = dict(initial_pose.joint_values)

    def test_loads_exact_fixed_base_g1_contract(self) -> None:
        self.assertEqual(self.helper.joint_names, self.schema.DDS_JOINT_NAMES)
        self.assertIn("left_rubber_hand", self.helper.frame_names)
        self.assertIn("right_rubber_hand", self.helper.frame_names)

    def test_frame_pose_uses_named_joint_values(self) -> None:
        frame_pose = self.helper.frame_pose(
            joint_values=self.reference_values,
            frame_name="left_rubber_hand",
        )

        self.assertEqual(len(frame_pose.translation), 3)
        self.assertEqual(np.asarray(frame_pose.rotation).shape, (3, 3))
        self.assertTrue(np.all(np.isfinite(frame_pose.translation)))

    def test_solves_small_left_hand_target_with_other_joints_fixed(self) -> None:
        initial_pose = self.helper.frame_pose(
            joint_values=self.reference_values,
            frame_name="left_rubber_hand",
        )
        target_translation = np.asarray(initial_pose.translation) + np.array([0.0, 0.0, 0.03])

        result = self.helper.solve_frame_target(
            joint_values=self.reference_values,
            active_joint_names=self.schema.LEFT_ARM_JOINT_NAMES,
            frame_name="left_rubber_hand",
            target_translation=target_translation,
            target_rotation=initial_pose.rotation,
        )

        self.assertTrue(result.converged)
        self.assertLessEqual(result.final_position_error, 1e-4)
        self.assertLessEqual(result.final_orientation_error, 1e-4)
        self.assertLess(result.final_position_error, result.initial_position_error)
        for joint_name in self.schema.WAIST_JOINT_NAMES + self.schema.RIGHT_ARM_JOINT_NAMES:
            self.assertEqual(result.joint_values[joint_name], self.reference_values[joint_name])
        self.schema.validate_joint_values(
            pose_type=PoseType.BASE,
            joint_values=result.joint_values,
        )

        with tempfile.TemporaryDirectory() as temporary_directory:
            output_path = Path(temporary_directory) / "pink_result.png"
            self.mujoco_helper.render_joint_values_to_file(
                joint_values=result.joint_values,
                output_path=output_path,
                width=320,
                height=240,
            )
            self.assertGreater(output_path.stat().st_size, 1_000)

    def test_rejects_unknown_frame(self) -> None:
        with self.assertRaisesRegex(ValueError, "Unknown URDF frame"):
            self.helper.frame_pose(
                joint_values=self.reference_values,
                frame_name="missing_hand",
            )

    def test_requires_reference_value_for_each_active_joint(self) -> None:
        with self.assertRaisesRegex(ValueError, "lack reference values"):
            self.helper.solve_frame_target(
                joint_values={},
                active_joint_names=self.schema.LEFT_ARM_JOINT_NAMES,
                frame_name="left_rubber_hand",
                target_translation=(0.0, 0.0, 0.0),
            )

    def test_posture_trajectory_has_exact_keyframes_and_duration(self) -> None:
        intermediate_values = dict(self.reference_values)
        intermediate_values["left_shoulder_roll_joint"] = 1.0
        intermediate_values["left_elbow_joint"] = 0.6

        result = self.helper.solve_posture_trajectory(
            keyframes=(
                self.reference_values,
                intermediate_values,
                self.reference_values,
            ),
            joint_names=self.schema.BASE_JOINT_NAMES,
            transition_durations=(1.5, 1.0),
            target_hold_durations=(0.5, 0.0),
            sample_frequency_hz=20.0,
        )

        self.assertEqual(result.keyframe_sample_indices, (0, 30, 60))
        self.assertEqual(result.timestamps.shape, (61,))
        self.assertEqual(result.joint_positions.shape, (61, 17))
        self.assertAlmostEqual(result.timestamps[-1], 3.0)
        expected_initial = np.asarray(
            [self.reference_values[name] for name in self.schema.BASE_JOINT_NAMES]
        )
        expected_intermediate = np.asarray(
            [intermediate_values[name] for name in self.schema.BASE_JOINT_NAMES]
        )
        np.testing.assert_allclose(result.joint_positions[0], expected_initial, atol=1e-12)
        np.testing.assert_allclose(
            result.joint_positions[30],
            expected_intermediate,
            atol=1e-12,
        )
        np.testing.assert_allclose(
            result.joint_positions[30:41],
            np.repeat(expected_intermediate[np.newaxis, :], 11, axis=0),
            atol=1e-12,
        )
        np.testing.assert_allclose(result.joint_positions[-1], expected_initial, atol=1e-12)
        self.assertLess(result.max_tracking_error, 1e-8)
        self.assertFalse(result.timestamps.flags.writeable)
        self.assertFalse(result.joint_positions.flags.writeable)

    def test_posture_trajectory_rejects_unreachable_short_duration(self) -> None:
        intermediate_values = dict(self.reference_values)
        intermediate_values["left_shoulder_roll_joint"] = 1.0
        intermediate_values["left_elbow_joint"] = 0.6

        with self.assertRaisesRegex(ValueError, "cannot reach its target"):
            self.helper.solve_posture_trajectory(
                keyframes=(self.reference_values, intermediate_values),
                joint_names=self.schema.BASE_JOINT_NAMES,
                transition_durations=(0.001,),
                sample_frequency_hz=50.0,
            )

    def test_posture_trajectory_rejects_invalid_hold_durations(self) -> None:
        with self.assertRaisesRegex(ValueError, "hold duration count"):
            self.helper.solve_posture_trajectory(
                keyframes=(self.reference_values, self.reference_values),
                joint_names=self.schema.BASE_JOINT_NAMES,
                transition_durations=(1.0,),
                target_hold_durations=(0.5, 0.5),
            )
        with self.assertRaisesRegex(ValueError, "nonnegative"):
            self.helper.solve_posture_trajectory(
                keyframes=(self.reference_values, self.reference_values),
                joint_names=self.schema.BASE_JOINT_NAMES,
                transition_durations=(1.0,),
                target_hold_durations=(-0.5,),
            )


def demo_test_pink_ik_helper() -> None:
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(PinkIKHelperTest)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    if not result.wasSuccessful():
        raise SystemExit(1)


def main() -> None:
    demo_test_pink_ik_helper()


if __name__ == "__main__":
    main()
