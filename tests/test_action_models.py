"""Tests for ordered pose references and action transition durations."""

from __future__ import annotations

import json
import unittest
from datetime import datetime, timezone

import numpy as np

from component.common.action_models import (
    ActionDefinition,
    ActionPoseReference,
    ActionTrajectory,
    ActionTransition,
)
from component.common.g1_joint_schema import G1JointSchema, PoseType
from config.settings import AppSettings
from util.g1_asset_helper import G1AssetHelper


class ActionDefinitionTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        settings = AppSettings()
        cls.schema = G1JointSchema(
            asset_helper=G1AssetHelper(asset_dir=settings.g1_asset_dir)
        )

    def create_action(self) -> ActionDefinition:
        return ActionDefinition.create(
            schema=self.schema,
            name="双侧迎宾",
            initial_pose=ActionPoseReference(PoseType.BASE, "concierge_init"),
            transitions=(
                ActionTransition(
                    target_pose=ActionPoseReference(
                        PoseType.COMPOSED,
                        "concierge_present_left",
                    ),
                    duration_seconds=1.5,
                    hold_seconds=0.5,
                ),
                ActionTransition(
                    target_pose=ActionPoseReference(
                        PoseType.COMPOSED,
                        "concierge_present_right",
                    ),
                    duration_seconds=2,
                    hold_seconds=0.25,
                ),
                ActionTransition(
                    target_pose=ActionPoseReference(PoseType.BASE, "concierge_init"),
                    duration_seconds=1.0,
                ),
            ),
            created_at=datetime(2026, 9, 12, 10, 0, tzinfo=timezone.utc),
            notes="先左后右",
        )

    def test_preserves_pose_order_and_transition_durations(self) -> None:
        action = self.create_action()

        self.assertEqual(
            tuple(reference.name for reference in action.pose_sequence),
            (
                "concierge_init",
                "concierge_present_left",
                "concierge_present_right",
                "concierge_init",
            ),
        )
        self.assertEqual(
            tuple(transition.duration_seconds for transition in action.transitions),
            (1.5, 2.0, 1.0),
        )
        self.assertEqual(
            tuple(transition.hold_seconds for transition in action.transitions),
            (0.5, 0.25, 0.0),
        )
        self.assertEqual(action.total_duration_seconds, 5.25)
        self.assertEqual(
            tuple(reference.name for reference in action.intermediate_poses),
            ("concierge_present_left", "concierge_present_right"),
        )
        self.assertIsInstance(action.transitions, tuple)

    def test_json_round_trip_preserves_unicode_and_structure(self) -> None:
        action = self.create_action()

        restored_action = ActionDefinition.from_json(
            schema=self.schema,
            content=action.to_json(),
        )

        self.assertEqual(restored_action, action)
        payload = json.loads(action.to_json())
        self.assertEqual(payload["name"], "双侧迎宾")
        self.assertEqual(payload["transitions"][0]["duration_seconds"], 1.5)
        self.assertEqual(payload["transitions"][0]["hold_seconds"], 0.5)

        for transition in payload["transitions"]:
            transition.pop("hold_seconds")
        backward_compatible = ActionDefinition.from_dict(
            schema=self.schema,
            payload=payload,
        )
        self.assertTrue(
            all(transition.hold_seconds == 0.0 for transition in backward_compatible.transitions)
        )

    def test_partial_arm_pose_cannot_be_an_action_keyframe(self) -> None:
        with self.assertRaisesRegex(ValueError, "must be base or composed"):
            ActionPoseReference(PoseType.LEFT_ARM, "left_only")
        with self.assertRaisesRegex(ValueError, "must be base or composed"):
            ActionPoseReference(PoseType.RIGHT_ARM, "right_only")

    def test_transition_duration_must_be_positive_and_finite(self) -> None:
        target_pose = ActionPoseReference(PoseType.BASE, "concierge_init")
        for invalid_duration in (True, 0.0, -1.0, float("nan"), float("inf")):
            with self.subTest(duration=invalid_duration):
                with self.assertRaisesRegex(ValueError, "duration"):
                    ActionTransition(
                        target_pose=target_pose,
                        duration_seconds=invalid_duration,
                    )

    def test_keyframe_hold_must_be_nonnegative_and_finite(self) -> None:
        target_pose = ActionPoseReference(PoseType.BASE, "concierge_init")
        self.assertEqual(ActionTransition(target_pose, 1.0, 0.0).hold_seconds, 0.0)
        self.assertEqual(ActionTransition(target_pose, 1.0, 1.5).hold_seconds, 1.5)
        for invalid_hold in (True, -0.1, float("nan"), float("inf")):
            with self.subTest(hold=invalid_hold):
                with self.assertRaisesRegex(ValueError, "hold"):
                    ActionTransition(target_pose, 1.0, invalid_hold)

    def test_action_requires_concierge_boundaries_and_an_intermediate_pose(self) -> None:
        initial_pose = ActionPoseReference(PoseType.BASE, "concierge_init")
        intermediate_pose = ActionPoseReference(PoseType.COMPOSED, "middle")
        with self.assertRaisesRegex(ValueError, "at least three keyframes"):
            ActionDefinition.create(
                schema=self.schema,
                name="empty",
                initial_pose=initial_pose,
                transitions=(),
            )
        with self.assertRaisesRegex(ValueError, "at least three keyframes"):
            ActionDefinition.create(
                schema=self.schema,
                name="no_middle",
                initial_pose=initial_pose,
                transitions=(ActionTransition(initial_pose, 1.0),),
            )
        with self.assertRaisesRegex(ValueError, "must start"):
            ActionDefinition.create(
                schema=self.schema,
                name="wrong_start",
                initial_pose=intermediate_pose,
                transitions=(
                    ActionTransition(intermediate_pose, 1.0),
                    ActionTransition(initial_pose, 1.0),
                ),
            )
        with self.assertRaisesRegex(ValueError, "must end"):
            ActionDefinition.create(
                schema=self.schema,
                name="wrong_end",
                initial_pose=initial_pose,
                transitions=(
                    ActionTransition(intermediate_pose, 1.0),
                    ActionTransition(intermediate_pose, 1.0),
                ),
            )

    def test_action_requires_an_aware_timestamp(self) -> None:
        initial_pose = ActionPoseReference(PoseType.BASE, "concierge_init")
        intermediate_pose = ActionPoseReference(PoseType.COMPOSED, "middle")
        with self.assertRaisesRegex(ValueError, "must include a timezone"):
            ActionDefinition.create(
                schema=self.schema,
                name="naive_time",
                initial_pose=initial_pose,
                transitions=(
                    ActionTransition(intermediate_pose, 1.0),
                    ActionTransition(initial_pose, 1.0),
                ),
                created_at=datetime(2026, 9, 12, 10, 0),
            )

    def test_deserialization_rejects_wrong_model_and_invalid_shapes(self) -> None:
        payload = self.create_action().to_dict()
        payload["robot_model_id"] = "another_robot"
        with self.assertRaisesRegex(ValueError, "does not match"):
            ActionDefinition.from_dict(schema=self.schema, payload=payload)

        payload = self.create_action().to_dict()
        payload["transitions"] = "not-an-array"
        with self.assertRaisesRegex(ValueError, "must be an array"):
            ActionDefinition.from_dict(schema=self.schema, payload=payload)

        with self.assertRaisesRegex(ValueError, "JSON root must be an object"):
            ActionDefinition.from_json(schema=self.schema, content="[]")

    def test_action_trajectory_validates_and_protects_sample_arrays(self) -> None:
        trajectory = ActionTrajectory(
            action_name="welcome",
            robot_model_id=self.schema.model_id,
            joint_names=("joint_a", "joint_b"),
            timestamps=np.array([0.0, 0.5, 1.0]),
            joint_positions=np.array([[0.0, 0.0], [0.5, -0.5], [0.0, 0.0]]),
            keyframe_sample_indices=(0, 1, 2),
            source_pose_names=(
                "concierge_init",
                "middle",
                "concierge_init",
            ),
            keyframe_hold_seconds=(0.0, 0.5, 0.0),
            requested_sample_frequency_hz=2.0,
            max_tracking_error=1e-12,
        )

        self.assertEqual(trajectory.sample_count, 3)
        self.assertEqual(trajectory.duration_seconds, 1.0)
        self.assertEqual(
            trajectory.joint_values_at(1),
            {"joint_a": 0.5, "joint_b": -0.5},
        )
        self.assertFalse(trajectory.timestamps.flags.writeable)
        self.assertFalse(trajectory.joint_positions.flags.writeable)

        with self.assertRaisesRegex(ValueError, "shape"):
            ActionTrajectory(
                action_name="invalid_shape",
                robot_model_id=self.schema.model_id,
                joint_names=("joint_a", "joint_b"),
                timestamps=np.array([0.0, 1.0]),
                joint_positions=np.zeros((2, 1)),
                keyframe_sample_indices=(0, 1, 1),
                source_pose_names=("concierge_init", "middle", "concierge_init"),
                keyframe_hold_seconds=(0.0, 0.0, 0.0),
                requested_sample_frequency_hz=1.0,
                max_tracking_error=0.0,
            )


def demo_test_action_models() -> None:
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(ActionDefinitionTest)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    if not result.wasSuccessful():
        raise SystemExit(1)


def main() -> None:
    demo_test_action_models()


if __name__ == "__main__":
    main()
