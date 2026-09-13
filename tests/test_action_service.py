"""Tests for action persistence and ordered pose resolution."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import numpy as np
from PIL import Image

from component.action_service import ActionService
from component.common.action_models import (
    ActionDefinition,
    ActionPoseReference,
    ActionTransition,
)
from component.common.g1_joint_schema import G1JointSchema, PoseType
from component.common.models import PoseDefinition, PoseSource
from component.pose_service import PoseService
from config.settings import AppSettings
from util.g1_asset_helper import G1AssetHelper
from util.mujoco_action_helper import MujocoActionHelper
from util.mujoco_pose_helper import MujocoPoseHelper
from util.numpy_archive_helper import NumpyArchiveHelper
from util.pink_ik_helper import PinkIKHelper
from util.pose_file_helper import PoseFileHelper


class ActionServiceTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.settings = AppSettings()
        cls.asset_helper = G1AssetHelper(asset_dir=cls.settings.g1_asset_dir)
        cls.schema = G1JointSchema(asset_helper=cls.asset_helper)

    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        temporary_root = Path(self.temporary_directory.name)
        file_helper = PoseFileHelper()
        simulation_helper = MujocoPoseHelper(mjcf_path=self.asset_helper.mjcf_path)
        self.pose_service = PoseService(
            schema=self.schema,
            pose_dir=temporary_root / "poses",
            file_helper=file_helper,
            simulation_helper=simulation_helper,
        )
        self.service = ActionService(
            schema=self.schema,
            action_definition_dir=temporary_root / "actions",
            file_helper=file_helper,
            pose_service=self.pose_service,
            ik_helper=PinkIKHelper(urdf_path=self.asset_helper.urdf_path),
            action_trajectory_dir=temporary_root / "trajectories",
            archive_helper=NumpyArchiveHelper(),
            action_preview_helper=MujocoActionHelper(
                pose_helper=simulation_helper
            ),
            action_preview_dir=temporary_root / "previews",
        )
        self.initial_pose = self._save_pose(PoseType.BASE, "concierge_init", elbow=1.4)
        self.left_pose = self._save_pose(
            PoseType.COMPOSED,
            "concierge_present_left",
            elbow=0.8,
        )
        self.right_pose = self._save_pose(
            PoseType.COMPOSED,
            "concierge_present_right",
            elbow=1.0,
        )

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def test_create_and_resolve_preserves_pose_and_duration_order(self) -> None:
        action = self._create_action()

        resolved = self.service.resolve_action(action=action)

        self.assertEqual(
            tuple(pose.name for pose in resolved.pose_sequence),
            (
                "concierge_init",
                "concierge_present_left",
                "concierge_present_right",
                "concierge_init",
            ),
        )
        self.assertEqual(
            tuple(transition.duration_seconds for transition in resolved.transitions),
            (1.5, 2.0, 1.0),
        )
        self.assertEqual(
            tuple(transition.hold_seconds for transition in resolved.transitions),
            (0.5, 0.25, 0.0),
        )
        self.assertEqual(resolved.initial_pose, self.initial_pose)
        self.assertEqual(resolved.transitions[0].target_pose, self.left_pose)
        self.assertEqual(resolved.transitions[1].target_pose, self.right_pose)
        self.assertEqual(resolved.transitions[2].target_pose, self.initial_pose)

    def test_save_load_list_and_explicit_overwrite(self) -> None:
        action = self._create_action()

        saved_path = self.service.save_action(action=action)

        self.assertEqual(saved_path.name, "welcome_sequence.json")
        self.assertEqual(self.service.load_action(name=action.name), action)
        self.assertEqual(self.service.list_actions(), (action,))
        with self.assertRaises(FileExistsError):
            self.service.save_action(action=action)
        self.service.save_action(action=action, overwrite=True)

    def test_generates_time_sampled_trajectory_with_exact_keyframes(self) -> None:
        action = self._create_action()

        trajectory = self.service.generate_trajectory(
            action=action,
            sample_frequency_hz=20.0,
        )

        self.assertEqual(trajectory.joint_names, self.schema.BASE_JOINT_NAMES)
        self.assertEqual(trajectory.source_pose_names, tuple(
            pose.name for pose in self.service.resolve_action(action=action).pose_sequence
        ))
        self.assertEqual(trajectory.keyframe_sample_indices, (0, 30, 80, 105))
        self.assertEqual(trajectory.sample_count, 106)
        self.assertAlmostEqual(trajectory.duration_seconds, 5.25)
        resolved = self.service.resolve_action(action=action)
        for pose, sample_index in zip(
            resolved.pose_sequence,
            trajectory.keyframe_sample_indices,
            strict=True,
        ):
            actual_values = trajectory.joint_values_at(sample_index)
            np.testing.assert_allclose(
                [actual_values[name] for name in trajectory.joint_names],
                [pose.joint_values[name] for name in trajectory.joint_names],
                rtol=0.0,
                atol=1e-12,
            )
        self.assertLess(trajectory.max_tracking_error, 1e-8)

    def test_save_load_list_and_explicit_overwrite_for_npz_trajectory(self) -> None:
        trajectory = self.service.generate_trajectory(action=self._create_action())

        saved_path = self.service.save_trajectory(trajectory=trajectory)

        self.assertEqual(saved_path.name, "welcome_sequence.npz")
        self.assertEqual(self.service.list_trajectories(), ("welcome_sequence",))
        restored = self.service.load_trajectory(name="welcome_sequence")
        self.assertEqual(restored.action_name, trajectory.action_name)
        self.assertEqual(restored.robot_model_id, trajectory.robot_model_id)
        self.assertEqual(restored.joint_names, trajectory.joint_names)
        self.assertEqual(restored.keyframe_sample_indices, trajectory.keyframe_sample_indices)
        self.assertEqual(restored.source_pose_names, trajectory.source_pose_names)
        self.assertEqual(
            restored.keyframe_hold_seconds,
            trajectory.keyframe_hold_seconds,
        )
        self.assertEqual(restored.requested_sample_frequency_hz, 25.0)
        np.testing.assert_array_equal(restored.timestamps, trajectory.timestamps)
        np.testing.assert_array_equal(restored.joint_positions, trajectory.joint_positions)
        with self.assertRaises(FileExistsError):
            self.service.save_trajectory(trajectory=trajectory)
        self.service.save_trajectory(trajectory=trajectory, overwrite=True)

    def test_load_trajectory_rejects_missing_archive_fields(self) -> None:
        self.service.archive_helper.write_npz(
            path=self.service.action_trajectory_dir / "broken.npz",
            arrays={"schema_version": np.asarray(1)},
        )

        with self.assertRaisesRegex(ValueError, "Invalid trajectory archive fields"):
            self.service.load_trajectory(name="broken")

    def test_loads_schema_one_npz_with_zero_hold_metadata(self) -> None:
        trajectory = self.service.generate_trajectory(action=self._create_action())
        path = self.service.save_trajectory(trajectory=trajectory)
        legacy_arrays = self.service.archive_helper.read_npz(path=path)
        legacy_arrays["schema_version"] = np.asarray(1, dtype=np.int64)
        legacy_arrays.pop("keyframe_hold_seconds")
        self.service.archive_helper.write_npz(
            path=path,
            arrays=legacy_arrays,
            overwrite=True,
        )

        restored = self.service.load_trajectory(name=trajectory.action_name)

        self.assertEqual(
            restored.keyframe_hold_seconds,
            tuple(0.0 for _ in restored.source_pose_names),
        )

    def test_loads_saved_npz_and_renders_five_camera_mujoco_preview(self) -> None:
        trajectory = self.service.generate_trajectory(
            action=self._create_action(),
            sample_frequency_hz=5.0,
        )
        self.service.save_trajectory(trajectory=trajectory)

        preview_path = self.service.render_saved_trajectory_preview(
            name=trajectory.action_name,
            view_width=80,
            view_height=60,
        )

        self.assertEqual(
            preview_path,
            self.service.action_preview_dir / "welcome_sequence.gif",
        )
        self.assertGreater(preview_path.stat().st_size, 1_000)
        with Image.open(preview_path) as preview:
            self.assertEqual(preview.size, (240, 120))
            self.assertGreater(preview.n_frames, 2)

    def test_missing_pose_is_rejected_with_reference_context(self) -> None:
        missing_reference = ActionPoseReference(PoseType.COMPOSED, "missing_pose")
        with self.assertRaisesRegex(
            ValueError,
            "composed/missing_pose",
        ):
            self.service.create_action(
                name="invalid_action",
                initial_pose=ActionPoseReference(PoseType.BASE, "concierge_init"),
                transitions=(
                    ActionTransition(missing_reference, 1.0),
                    ActionTransition(
                        ActionPoseReference(PoseType.BASE, "concierge_init"),
                        1.0,
                    ),
                ),
            )

    def test_load_does_not_hide_definition_when_pose_is_missing(self) -> None:
        action = self._create_action()
        self.service.save_action(action=action)
        (self.pose_service.pose_dir / "composed" / "concierge_present_left.json").unlink()

        loaded_action = self.service.load_action(name=action.name)

        self.assertEqual(loaded_action, action)
        with self.assertRaisesRegex(ValueError, "concierge_present_left"):
            self.service.resolve_action(action=loaded_action)

    def test_action_filename_must_match_embedded_name(self) -> None:
        action = self._create_action()
        payload = action.to_dict()
        payload["name"] = "different_name"
        self.service.file_helper.write_json(
            path=self.service.action_definition_dir / "expected_name.json",
            payload=payload,
        )

        with self.assertRaisesRegex(ValueError, "different action name"):
            self.service.load_action(name="expected_name")

    def test_wrong_robot_model_is_rejected_before_resolution(self) -> None:
        action = self._create_action()
        invalid_action = ActionDefinition(
            schema_version=action.schema_version,
            name=action.name,
            robot_model_id="another_robot",
            initial_pose=action.initial_pose,
            transitions=action.transitions,
            created_at=action.created_at,
        )

        with self.assertRaisesRegex(ValueError, "does not match"):
            self.service.resolve_action(action=invalid_action)

    def _create_action(self) -> ActionDefinition:
        return self.service.create_action(
            name="welcome_sequence",
            initial_pose=ActionPoseReference(PoseType.BASE, "concierge_init"),
            transitions=(
                ActionTransition(
                    ActionPoseReference(PoseType.COMPOSED, "concierge_present_left"),
                    1.5,
                    0.5,
                ),
                ActionTransition(
                    ActionPoseReference(PoseType.COMPOSED, "concierge_present_right"),
                    2.0,
                    0.25,
                ),
                ActionTransition(
                    ActionPoseReference(PoseType.BASE, "concierge_init"),
                    1.0,
                ),
            ),
        )

    def _save_pose(
        self,
        pose_type: PoseType,
        name: str,
        *,
        elbow: float,
    ) -> PoseDefinition:
        joint_values = self.schema.neutral_values(pose_type)
        joint_values["left_elbow_joint"] = elbow
        pose = PoseDefinition.create(
            schema=self.schema,
            name=name,
            pose_type=pose_type,
            joint_values=joint_values,
            source=PoseSource.SIMULATION,
        )
        self.pose_service.save_pose(pose=pose)
        return pose


def demo_test_action_service() -> None:
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(ActionServiceTest)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    if not result.wasSuccessful():
        raise SystemExit(1)


def main() -> None:
    demo_test_action_service()


if __name__ == "__main__":
    main()
