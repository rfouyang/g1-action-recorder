"""Tests for pose persistence, composition, and robot-centric mirroring."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import mujoco
import numpy as np

from component.common.g1_joint_schema import G1JointSchema, PoseType
from component.common.models import PoseDefinition, PoseSource
from component.pose_service import PoseService
from config.settings import AppSettings
from util.g1_asset_helper import G1AssetHelper
from util.mujoco_pose_helper import MujocoPoseHelper
from util.pose_file_helper import PoseFileHelper


class PoseServiceTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.settings = AppSettings()
        cls.schema = G1JointSchema(asset_helper=G1AssetHelper(asset_dir=cls.settings.g1_asset_dir))

    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.service = PoseService(
            schema=self.schema,
            pose_dir=Path(self.temporary_directory.name),
            file_helper=PoseFileHelper(),
            simulation_helper=MujocoPoseHelper(
                mjcf_path=self.settings.g1_asset_dir / "g1_29dof_fake_hand.xml"
            ),
        )

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def test_save_load_list_and_explicit_overwrite(self) -> None:
        pose = self._pose(PoseType.LEFT_ARM, "左手问候")
        saved_path = self.service.save_pose(pose=pose)
        self.assertEqual(saved_path.name, "左手问候.json")
        self.assertEqual(self.service.load_pose(pose_type=PoseType.LEFT_ARM, name=pose.name), pose)
        self.assertEqual(self.service.list_poses(pose_type=PoseType.LEFT_ARM), (pose,))

        with self.assertRaises(FileExistsError):
            self.service.save_pose(pose=pose)
        self.service.save_pose(pose=pose, overwrite=True)

    def test_initial_base_pose_loads_saved_pose_or_falls_back_to_neutral(self) -> None:
        fallback = self.service.load_initial_base_pose(name="missing_initial")
        self.assertEqual(
            dict(fallback.joint_values),
            self.schema.neutral_values(PoseType.BASE),
        )

        initial_values = self.schema.neutral_values(PoseType.BASE)
        initial_values["left_elbow_joint"] = 1.4
        saved_initial = self._pose(PoseType.BASE, "concierge_init", values=initial_values)
        self.service.save_pose(pose=saved_initial)
        self.assertEqual(
            self.service.load_initial_base_pose(name="concierge_init"),
            saved_initial,
        )

    def test_create_and_render_simulated_partial_pose(self) -> None:
        left_values = self.schema.neutral_values(PoseType.LEFT_ARM)
        left_values["left_shoulder_roll_joint"] = 1.2
        pose = self.service.create_simulated_pose(
            name="simulated_left_greeting",
            pose_type=PoseType.LEFT_ARM,
            joint_values=left_values,
            notes="Edited without a physical robot",
        )

        pixels = self.service.render_pose_preview(pose=pose, width=320, height=240)
        output_path = Path(self.temporary_directory.name) / "preview.png"
        saved_path = self.service.save_pose_preview(
            pose=pose,
            output_path=output_path,
            width=320,
            height=240,
        )

        self.assertEqual(pose.source, PoseSource.SIMULATION)
        self.assertEqual(pixels.shape, (240, 320, 3))
        self.assertEqual(pixels.dtype, np.uint8)
        self.assertEqual(saved_path, output_path)
        self.assertGreater(saved_path.stat().st_size, 1_000)

    def test_render_pose_previews_returns_five_distinct_views(self) -> None:
        left_values = self.schema.neutral_values(PoseType.LEFT_ARM)
        left_values["left_shoulder_roll_joint"] = 1.2
        pose = self.service.create_simulated_pose(
            name="three_views",
            pose_type=PoseType.LEFT_ARM,
            joint_values=left_values,
        )

        previews = self.service.render_pose_previews(pose=pose, width=320, height=240)

        self.assertTrue(all(image.shape == (240, 320, 3) for image in previews.as_tuple()))
        self.assertFalse(np.array_equal(previews.front, previews.robot_right))
        self.assertFalse(np.array_equal(previews.front, previews.front_right))
        self.assertFalse(np.array_equal(previews.front, previews.robot_left))
        self.assertFalse(np.array_equal(previews.front, previews.front_left))

    def test_partial_pose_preview_can_be_overlaid_on_an_initial_base(self) -> None:
        base_values = self.schema.neutral_values(PoseType.BASE)
        base_values["right_elbow_joint"] = 1.4
        base = self._pose(PoseType.BASE, "concierge_init", values=base_values)
        left_values = self.schema.neutral_values(PoseType.LEFT_ARM)
        left_values["left_shoulder_roll_joint"] = 1.2
        left = self._pose(PoseType.LEFT_ARM, "left_override", values=left_values)
        composed = self.service.compose_pose(
            name="expected_preview",
            base=base,
            left_arm=left,
        )

        overlaid_previews = self.service.render_pose_previews(
            pose=left,
            base_pose=base,
            width=160,
            height=120,
        )
        composed_previews = self.service.render_pose_previews(
            pose=composed,
            width=160,
            height=120,
        )

        for overlaid, expected in zip(
            overlaid_previews.as_tuple(),
            composed_previews.as_tuple(),
            strict=True,
        ):
            np.testing.assert_allclose(overlaid, expected, rtol=0.0, atol=1.0)

    def test_composition_overwrites_only_selected_arms(self) -> None:
        base_values = self.schema.neutral_values(PoseType.BASE)
        base_values["waist_yaw_joint"] = 0.2
        base_values["left_elbow_joint"] = 0.1
        base_values["right_elbow_joint"] = 0.15
        base = self._pose(PoseType.BASE, "base", values=base_values)

        left_values = self.schema.neutral_values(PoseType.LEFT_ARM)
        left_values["left_elbow_joint"] = 0.8
        left_arm = self._pose(PoseType.LEFT_ARM, "left", values=left_values)

        right_values = self.schema.neutral_values(PoseType.RIGHT_ARM)
        right_values["right_elbow_joint"] = 0.9
        right_arm = self._pose(PoseType.RIGHT_ARM, "right", values=right_values)

        expectations = (
            (None, None, 0.1, 0.15, {"base": "base"}),
            (left_arm, None, 0.8, 0.15, {"base": "base", "left_arm": "left"}),
            (None, right_arm, 0.1, 0.9, {"base": "base", "right_arm": "right"}),
            (
                left_arm,
                right_arm,
                0.8,
                0.9,
                {"base": "base", "left_arm": "left", "right_arm": "right"},
            ),
        )
        for index, (selected_left, selected_right, left_elbow, right_elbow, sources) in enumerate(
            expectations
        ):
            with self.subTest(index=index):
                composed = self.service.compose_pose(
                    name=f"composed_{index}",
                    base=base,
                    left_arm=selected_left,
                    right_arm=selected_right,
                )
                self.assertEqual(composed.joint_values["waist_yaw_joint"], 0.2)
                self.assertEqual(composed.joint_values["left_elbow_joint"], left_elbow)
                self.assertEqual(composed.joint_values["right_elbow_joint"], right_elbow)
                self.assertEqual(dict(composed.source_parts), sources)

    def test_left_right_mirror_and_double_mirror(self) -> None:
        left_values = dict(
            zip(
                self.schema.LEFT_ARM_JOINT_NAMES,
                (0.4, 0.35, -0.3, 0.8, 0.25, -0.2, 0.3),
                strict=True,
            )
        )
        left_pose = self._pose(PoseType.LEFT_ARM, "left_source", values=left_values)
        right_pose = self.service.mirror_arm_pose(
            source_pose=left_pose,
            name="right_mirror",
        )
        expected_right_values = dict(
            zip(
                self.schema.RIGHT_ARM_JOINT_NAMES,
                (0.4, -0.35, 0.3, 0.8, -0.25, -0.2, -0.3),
                strict=True,
            )
        )
        self.assertEqual(dict(right_pose.joint_values), expected_right_values)
        self.assertEqual(right_pose.pose_type, PoseType.RIGHT_ARM)
        self.assertEqual(right_pose.source, PoseSource.MIRROR)

        restored_left = self.service.mirror_arm_pose(
            source_pose=right_pose,
            name="left_restored",
        )
        self.assertEqual(dict(restored_left.joint_values), left_values)

    def test_mirror_matches_mujoco_sagittal_reflection(self) -> None:
        left_values = dict(
            zip(
                self.schema.LEFT_ARM_JOINT_NAMES,
                (0.4, 0.35, -0.3, 0.8, 0.25, -0.2, 0.3),
                strict=True,
            )
        )
        left_pose = self._pose(PoseType.LEFT_ARM, "left_geometry", values=left_values)
        right_pose = self.service.mirror_arm_pose(
            source_pose=left_pose,
            name="right_geometry",
        )
        model = mujoco.MjModel.from_xml_path(
            str(self.settings.g1_asset_dir / "g1_29dof_fake_hand.xml")
        )
        data = mujoco.MjData(model)
        for joint_name, value in left_pose.joint_values.items():
            joint_id = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_JOINT, joint_name)
            data.qpos[model.jnt_qposadr[joint_id]] = value
        for joint_name, value in right_pose.joint_values.items():
            joint_id = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_JOINT, joint_name)
            data.qpos[model.jnt_qposadr[joint_id]] = value
        mujoco.mj_forward(model, data)

        reflection = np.diag((1.0, -1.0, 1.0))
        for body_suffix in (
            "shoulder_pitch_link",
            "shoulder_roll_link",
            "shoulder_yaw_link",
            "elbow_link",
            "wrist_roll_link",
            "wrist_pitch_link",
            "wrist_yaw_link",
        ):
            with self.subTest(body_suffix=body_suffix):
                left_body_id = mujoco.mj_name2id(
                    model,
                    mujoco.mjtObj.mjOBJ_BODY,
                    f"left_{body_suffix}",
                )
                right_body_id = mujoco.mj_name2id(
                    model,
                    mujoco.mjtObj.mjOBJ_BODY,
                    f"right_{body_suffix}",
                )
                expected_right_position = reflection @ data.xpos[left_body_id]
                expected_right_rotation = (
                    reflection @ data.xmat[left_body_id].reshape(3, 3) @ reflection
                )
                np.testing.assert_allclose(
                    data.xpos[right_body_id],
                    expected_right_position,
                    atol=2e-5,
                )
                np.testing.assert_allclose(
                    data.xmat[right_body_id].reshape(3, 3),
                    expected_right_rotation,
                    atol=1e-7,
                )

    def test_invalid_composition_and_mirror_types_are_rejected(self) -> None:
        left_arm = self._pose(PoseType.LEFT_ARM, "left")
        right_arm = self._pose(PoseType.RIGHT_ARM, "right")
        with self.assertRaisesRegex(ValueError, "expected base"):
            self.service.compose_pose(name="invalid", base=left_arm)
        with self.assertRaisesRegex(ValueError, "expected left_arm"):
            self.service.compose_pose(
                name="invalid",
                base=self._pose(PoseType.BASE, "base"),
                left_arm=right_arm,
            )
        with self.assertRaisesRegex(ValueError, "Only left_arm and right_arm"):
            self.service.mirror_arm_pose(
                source_pose=self._pose(PoseType.BASE, "base_for_mirror"),
                name="invalid_mirror",
            )

    def _pose(
        self,
        pose_type: PoseType,
        name: str,
        *,
        values: dict[str, float] | None = None,
    ) -> PoseDefinition:
        return PoseDefinition.create(
            schema=self.schema,
            name=name,
            pose_type=pose_type,
            joint_values=values or self.schema.neutral_values(pose_type),
            source=PoseSource.SIMULATION,
        )


def demo_test_pose_service() -> None:
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(PoseServiceTest)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    if not result.wasSuccessful():
        raise SystemExit(1)


def main() -> None:
    demo_test_pose_service()


if __name__ == "__main__":
    main()
