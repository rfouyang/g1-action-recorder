"""Tests for the G1 DDS and pose joint schema."""

from __future__ import annotations

import math
import unittest

from component.common.g1_joint_schema import G1JointSchema, JointGroup, PoseType
from config.settings import AppSettings
from util.g1_asset_helper import G1AssetHelper


class G1JointSchemaTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        settings = AppSettings()
        cls.schema = G1JointSchema(asset_helper=G1AssetHelper(asset_dir=settings.g1_asset_dir))

    def test_dds_indices_and_groups(self) -> None:
        self.assertEqual(len(self.schema.definitions), 29)
        expected_indices = {
            "left_hip_pitch_joint": 0,
            "waist_yaw_joint": 12,
            "waist_pitch_joint": 14,
            "left_shoulder_pitch_joint": 15,
            "left_wrist_yaw_joint": 21,
            "right_shoulder_pitch_joint": 22,
            "right_wrist_yaw_joint": 28,
        }
        for joint_name, dds_index in expected_indices.items():
            self.assertEqual(self.schema.definition(joint_name).dds_index, dds_index)
        self.assertEqual(
            self.schema.definition("left_wrist_yaw_joint").group,
            JointGroup.LEFT_ARM,
        )
        self.assertEqual(
            self.schema.definition("right_wrist_yaw_joint").group,
            JointGroup.RIGHT_ARM,
        )

    def test_pose_joint_sets(self) -> None:
        self.assertEqual(len(self.schema.joint_names(PoseType.BASE)), 17)
        self.assertEqual(len(self.schema.joint_names(PoseType.LEFT_ARM)), 7)
        self.assertEqual(len(self.schema.joint_names(PoseType.RIGHT_ARM)), 7)
        self.assertEqual(
            self.schema.joint_names(PoseType.COMPOSED),
            self.schema.joint_names(PoseType.BASE),
        )
        self.assertFalse(any("hand" in name for name in self.schema.joint_names(PoseType.BASE)))

    def test_extract_from_dds_uses_official_indices(self) -> None:
        motor_positions = [0.0] * 29
        motor_positions[15] = 0.25
        motor_positions[21] = -0.3
        values = self.schema.extract_from_dds(
            motor_positions=motor_positions,
            pose_type=PoseType.LEFT_ARM,
        )
        self.assertEqual(values["left_shoulder_pitch_joint"], 0.25)
        self.assertEqual(values["left_wrist_yaw_joint"], -0.3)

    def test_extract_rejects_short_low_state(self) -> None:
        with self.assertRaisesRegex(ValueError, "expected at least 29"):
            self.schema.extract_from_dds(
                motor_positions=[0.0] * 28,
                pose_type=PoseType.BASE,
            )

    def test_validation_rejects_invalid_values(self) -> None:
        missing_joint = self.schema.neutral_values(PoseType.LEFT_ARM)
        missing_joint.pop("left_elbow_joint")
        with self.assertRaisesRegex(ValueError, "missing"):
            self.schema.validate_joint_values(
                pose_type=PoseType.LEFT_ARM,
                joint_values=missing_joint,
            )

        unknown_joint = self.schema.neutral_values(PoseType.LEFT_ARM)
        unknown_joint["unknown_joint"] = 0.0
        with self.assertRaisesRegex(ValueError, "unknown"):
            self.schema.validate_joint_values(
                pose_type=PoseType.LEFT_ARM,
                joint_values=unknown_joint,
            )

        non_finite = self.schema.neutral_values(PoseType.LEFT_ARM)
        non_finite["left_elbow_joint"] = math.nan
        with self.assertRaisesRegex(ValueError, "finite"):
            self.schema.validate_joint_values(
                pose_type=PoseType.LEFT_ARM,
                joint_values=non_finite,
            )

        out_of_range = self.schema.neutral_values(PoseType.LEFT_ARM)
        out_of_range["left_elbow_joint"] = 100.0
        with self.assertRaisesRegex(ValueError, "outside"):
            self.schema.validate_joint_values(
                pose_type=PoseType.LEFT_ARM,
                joint_values=out_of_range,
            )


def demo_test_g1_joint_schema() -> None:
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(G1JointSchemaTest)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    if not result.wasSuccessful():
        raise SystemExit(1)


def main() -> None:
    demo_test_g1_joint_schema()


if __name__ == "__main__":
    main()
