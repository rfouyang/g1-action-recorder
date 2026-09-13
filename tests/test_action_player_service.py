"""Tests for uploaded native, Kimodo, and ARDY arm-action normalization."""

from __future__ import annotations

import io
import pickle
import tempfile
import unittest
from pathlib import Path

import numpy as np

from app.application import RobotApplication
from component.action_player_service import ActionFileFormat
from component.common.g1_joint_schema import PoseType


class _UnsafePicklePayload:
    def __reduce__(self):
        return eval, ("1 + 1",)


class ActionPlayerServiceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        root = Path(self.temporary_directory.name)
        self.application = RobotApplication.create(
            pose_dir=root / "poses",
            action_definition_dir=root / "definitions",
            action_trajectory_dir=root / "trajectories",
            action_preview_dir=root / "previews",
        )
        self.service = self.application.action_player

    def tearDown(self) -> None:
        self.application.action_player.close()
        self.temporary_directory.cleanup()

    def test_loads_native_npz_and_discards_waist_columns(self) -> None:
        path = Path(__file__).resolve().parents[1] / "data/actions/trajectories/present_left.npz"

        loaded = self.service.load(
            source_format=ActionFileFormat.NATIVE_NPZ,
            filename=path.name,
            content=path.read_bytes(),
        )

        self.assertEqual(
            loaded.trajectory.joint_names,
            self.application.joint_schema.ARM_JOINT_NAMES,
        )
        self.assertEqual(loaded.source_joint_count, 17)
        self.assertEqual(loaded.trajectory.sample_count, 101)
        self.assertIn("waist", loaded.warnings[0])

    def test_loads_kimodo_global_rotations_with_explicit_fps(self) -> None:
        content = self._npz_bytes(
            global_rot_mats=np.tile(np.eye(3), (3, 34, 1, 1)),
            foot_contacts=np.zeros((3, 4), dtype=np.bool_),
        )

        loaded = self.service.load(
            source_format=ActionFileFormat.KIMODO_NPZ,
            filename="kimodo_wave.npz",
            content=content,
            source_fps=30.0,
        )

        self.assertEqual(loaded.source_joint_count, 34)
        self.assertEqual(loaded.trajectory.requested_sample_frequency_hz, 30.0)
        self.assertEqual(loaded.trajectory.source_pose_names[0], "concierge_init")
        self.assertEqual(loaded.trajectory.source_pose_names[-1], "concierge_init")
        self.assertGreater(loaded.trajectory.sample_count, 3)

    def test_loads_restricted_ardy_session(self) -> None:
        payload = {
            "version": "1.0",
            "model_fps": 25.0,
            "skeleton": {"name": "g1skel34", "nbjoints": 34},
            "motion": {
                "joints_rot": np.tile(np.eye(3), (1, 3, 34, 1, 1)),
            },
        }

        loaded = self.service.load(
            source_format=ActionFileFormat.ARDY_PKL,
            filename="ardy_wave.pkl",
            content=pickle.dumps(payload, protocol=pickle.HIGHEST_PROTOCOL),
        )

        self.assertEqual(loaded.source_joint_count, 34)
        self.assertEqual(loaded.trajectory.requested_sample_frequency_hz, 25.0)
        self.assertEqual(loaded.source_format, ActionFileFormat.ARDY_PKL)

    def test_restricted_ardy_loader_rejects_arbitrary_pickle_globals(self) -> None:
        with self.assertRaisesRegex(ValueError, "unsupported pickle global"):
            self.service.load(
                source_format=ActionFileFormat.ARDY_PKL,
                filename="unsafe.pkl",
                content=pickle.dumps(_UnsafePicklePayload()),
            )

    def test_rejects_wrong_extension_and_missing_kimodo_fps(self) -> None:
        content = self._npz_bytes(
            global_rot_mats=np.tile(np.eye(3), (2, 34, 1, 1)),
        )
        with self.assertRaisesRegex(ValueError, "must end with .npz"):
            self.service.load(
                source_format=ActionFileFormat.KIMODO_NPZ,
                filename="motion.pkl",
                content=content,
                source_fps=30.0,
            )
        with self.assertRaisesRegex(ValueError, "has no fps"):
            self.service.load(
                source_format=ActionFileFormat.KIMODO_NPZ,
                filename="motion.npz",
                content=content,
            )

    def test_saves_left_and_right_arm_poses_from_exact_paused_sample(self) -> None:
        path = Path(__file__).resolve().parents[1] / "data/actions/trajectories/present_left.npz"
        loaded = self.service.load(
            source_format=ActionFileFormat.NATIVE_NPZ,
            filename=path.name,
            content=path.read_bytes(),
        )
        self.service.play()
        self.service.pause()
        selected = self.service.seek(sample_index=50)

        left = self.service.save_paused_arm_pose(
            pose_type=PoseType.LEFT_ARM,
            name="captured_left",
        )
        right = self.service.save_paused_arm_pose(
            pose_type=PoseType.RIGHT_ARM,
            name="captured_right",
            notes="Selected greeting frame.",
        )
        with self.assertRaisesRegex(ValueError, "Stop the current action"):
            self.service.load(
                source_format=ActionFileFormat.NATIVE_NPZ,
                filename=path.name,
                content=path.read_bytes(),
            )

        self.assertEqual(selected.sample_index, 50)
        self.assertEqual(left.sample_index, 50)
        self.assertEqual(right.sample_index, 50)
        self.assertEqual(left.pose.pose_type, PoseType.LEFT_ARM)
        self.assertEqual(right.pose.pose_type, PoseType.RIGHT_ARM)
        self.assertIn("sample 51/101", left.pose.notes)
        self.assertIn("Selected greeting frame", right.pose.notes)
        sample = loaded.trajectory.joint_values_at(50)
        for joint_name in self.application.joint_schema.LEFT_ARM_JOINT_NAMES:
            self.assertAlmostEqual(left.pose.joint_values[joint_name], sample[joint_name])
        for joint_name in self.application.joint_schema.RIGHT_ARM_JOINT_NAMES:
            self.assertAlmostEqual(right.pose.joint_values[joint_name], sample[joint_name])
        self.assertEqual(
            self.application.pose_service.load_pose(
                pose_type=PoseType.LEFT_ARM,
                name="captured_left",
            ),
            left.pose,
        )

    def test_compiled_action_replaces_uploaded_action_only_after_stop(self) -> None:
        path = Path(__file__).resolve().parents[1] / "data/actions/trajectories/present_left.npz"
        loaded = self.service.load(
            source_format=ActionFileFormat.NATIVE_NPZ,
            filename=path.name,
            content=path.read_bytes(),
        )
        compiled_path = (
            self.application.action_service.action_trajectory_dir / path.name
        )
        compiled_path.parent.mkdir(parents=True, exist_ok=True)
        compiled_path.write_bytes(path.read_bytes())
        self.service.play()
        with self.assertRaisesRegex(ValueError, "Stop the current action"):
            self.service.load_saved(name=loaded.trajectory.action_name)
        self.service.stop()

        compiled = self.service.load_saved(name=loaded.trajectory.action_name)

        self.assertIsNone(compiled.source_format)
        self.assertEqual(self.service.snapshot().source.value, "compiled")

    @staticmethod
    def _npz_bytes(**arrays: object) -> bytes:
        output = io.BytesIO()
        np.savez(output, **arrays)
        return output.getvalue()


def demo_test_action_player_service() -> None:
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(ActionPlayerServiceTest)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    if not result.wasSuccessful():
        raise SystemExit(1)


def main() -> None:
    demo_test_action_player_service()


if __name__ == "__main__":
    main()
