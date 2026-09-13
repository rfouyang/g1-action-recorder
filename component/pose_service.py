"""Pose storage, composition, and robot-centric arm mirroring."""

from __future__ import annotations

import logging
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from numpy.typing import NDArray

from component.common.g1_joint_schema import G1JointSchema, PoseType
from component.common.models import PoseDefinition, PoseSource
from config.settings import AppSettings
from util.g1_asset_helper import G1AssetHelper
from util.mujoco_pose_helper import CameraView, MujocoPoseHelper
from util.pose_file_helper import PoseFileHelper

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ArmMirrorRule:
    """Map one anatomical left joint to its right-side counterpart."""

    left_joint: str
    right_joint: str
    sign: float


@dataclass(frozen=True, slots=True)
class PosePreviewSet:
    """Five synchronized robot-centric MuJoCo pose images."""

    front: NDArray[np.uint8]
    robot_right: NDArray[np.uint8]
    front_right: NDArray[np.uint8]
    robot_left: NDArray[np.uint8]
    front_left: NDArray[np.uint8]

    def as_tuple(self) -> tuple[NDArray[np.uint8], ...]:
        return (
            self.front,
            self.robot_right,
            self.front_right,
            self.robot_left,
            self.front_left,
        )


class PoseService:
    """Apply pose business rules and persist validated pose definitions."""

    ARM_MIRROR_RULES = (
        ArmMirrorRule("left_shoulder_pitch_joint", "right_shoulder_pitch_joint", 1.0),
        ArmMirrorRule("left_shoulder_roll_joint", "right_shoulder_roll_joint", -1.0),
        ArmMirrorRule("left_shoulder_yaw_joint", "right_shoulder_yaw_joint", -1.0),
        ArmMirrorRule("left_elbow_joint", "right_elbow_joint", 1.0),
        ArmMirrorRule("left_wrist_roll_joint", "right_wrist_roll_joint", -1.0),
        ArmMirrorRule("left_wrist_pitch_joint", "right_wrist_pitch_joint", 1.0),
        ArmMirrorRule("left_wrist_yaw_joint", "right_wrist_yaw_joint", -1.0),
    )

    def __init__(
        self,
        *,
        schema: G1JointSchema,
        pose_dir: Path,
        file_helper: PoseFileHelper,
        simulation_helper: MujocoPoseHelper,
    ) -> None:
        self.schema = schema
        self.pose_dir = pose_dir
        self.file_helper = file_helper
        self.simulation_helper = simulation_helper

    def create_simulated_pose(
        self,
        *,
        name: str,
        pose_type: PoseType,
        joint_values: Mapping[str, object],
        notes: str = "",
    ) -> PoseDefinition:
        """Create a validated pose from simulation editor values."""
        return PoseDefinition.create(
            schema=self.schema,
            name=name,
            pose_type=pose_type,
            joint_values=joint_values,
            source=PoseSource.SIMULATION,
            notes=notes,
        )

    def render_pose_preview(
        self,
        *,
        pose: PoseDefinition,
        base_pose: PoseDefinition | None = None,
        width: int = MujocoPoseHelper.DEFAULT_WIDTH,
        height: int = MujocoPoseHelper.DEFAULT_HEIGHT,
    ) -> NDArray[np.uint8]:
        """Render a pose over an optional base; otherwise omitted joints are neutral."""
        return self.simulation_helper.render_joint_values(
            joint_values=self._preview_joint_values(pose=pose, base_pose=base_pose),
            width=width,
            height=height,
        )

    def render_pose_previews(
        self,
        *,
        pose: PoseDefinition,
        base_pose: PoseDefinition | None = None,
        width: int = MujocoPoseHelper.DEFAULT_WIDTH,
        height: int = MujocoPoseHelper.DEFAULT_HEIGHT,
    ) -> PosePreviewSet:
        """Render front, side, and front-diagonal views of one pose state."""
        images = self.simulation_helper.render_joint_values_for_views(
            joint_values=self._preview_joint_values(pose=pose, base_pose=base_pose),
            width=width,
            height=height,
        )
        return PosePreviewSet(
            front=images[CameraView.FRONT],
            robot_right=images[CameraView.ROBOT_RIGHT],
            front_right=images[CameraView.FRONT_RIGHT],
            robot_left=images[CameraView.ROBOT_LEFT],
            front_left=images[CameraView.FRONT_LEFT],
        )

    def save_pose_preview(
        self,
        *,
        pose: PoseDefinition,
        output_path: Path,
        width: int = MujocoPoseHelper.DEFAULT_WIDTH,
        height: int = MujocoPoseHelper.DEFAULT_HEIGHT,
    ) -> Path:
        """Validate a pose and save its MuJoCo front preview."""
        self._validate_pose(pose)
        return self.simulation_helper.render_joint_values_to_file(
            joint_values=pose.joint_values,
            output_path=output_path,
            width=width,
            height=height,
        )

    def save_pose(self, *, pose: PoseDefinition, overwrite: bool = False) -> Path:
        self._validate_pose(pose)
        return self.file_helper.write_json(
            path=self._pose_path(pose_type=pose.pose_type, name=pose.name),
            payload=pose.to_dict(),
            overwrite=overwrite,
        )

    def load_pose(self, *, pose_type: PoseType, name: str) -> PoseDefinition:
        normalized_name = PoseDefinition.validate_name(name)
        path = self._pose_path(pose_type=pose_type, name=normalized_name)
        pose = PoseDefinition.from_dict(
            schema=self.schema,
            payload=self.file_helper.read_json(path=path),
        )
        if pose.pose_type is not pose_type:
            raise ValueError(
                f"Pose file {path} contains {pose.pose_type.value}, expected {pose_type.value}"
            )
        if pose.name != normalized_name:
            raise ValueError(f"Pose file {path} contains a different pose name: {pose.name}")
        return pose

    def list_poses(self, *, pose_type: PoseType) -> tuple[PoseDefinition, ...]:
        directory = self.pose_dir / pose_type.value
        return tuple(
            self.load_pose(pose_type=pose_type, name=path.stem)
            for path in self.file_helper.list_json_files(directory=directory)
        )

    def load_initial_base_pose(self, *, name: str) -> PoseDefinition:
        """Load the configured startup base, with neutral fallback when absent."""
        try:
            return self.load_pose(pose_type=PoseType.BASE, name=name)
        except FileNotFoundError:
            LOGGER.warning("Initial base pose %s was not found; using neutral values", name)
            return self.create_simulated_pose(
                name=name,
                pose_type=PoseType.BASE,
                joint_values=self.schema.neutral_values(PoseType.BASE),
                notes="Unsaved neutral fallback for a missing initial base pose",
            )

    def compose_pose(
        self,
        *,
        name: str,
        base: PoseDefinition,
        left_arm: PoseDefinition | None = None,
        right_arm: PoseDefinition | None = None,
        notes: str = "",
    ) -> PoseDefinition:
        """Copy the base, then overwrite the selected robot-left and robot-right arms."""
        self._require_pose_type(base, PoseType.BASE)
        if left_arm is not None:
            self._require_pose_type(left_arm, PoseType.LEFT_ARM)
        if right_arm is not None:
            self._require_pose_type(right_arm, PoseType.RIGHT_ARM)

        composed_values = dict(base.joint_values)
        source_parts = {"base": base.name}
        if left_arm is not None:
            composed_values.update(left_arm.joint_values)
            source_parts["left_arm"] = left_arm.name
        if right_arm is not None:
            composed_values.update(right_arm.joint_values)
            source_parts["right_arm"] = right_arm.name

        return PoseDefinition.create(
            schema=self.schema,
            name=name,
            pose_type=PoseType.COMPOSED,
            joint_values=composed_values,
            source=PoseSource.COMPOSITION,
            source_parts=source_parts,
            notes=notes,
        )

    def mirror_arm_pose(
        self,
        *,
        source_pose: PoseDefinition,
        name: str,
        notes: str = "",
    ) -> PoseDefinition:
        """Mirror one anatomical robot arm to the opposite arm."""
        self._validate_pose(source_pose)
        if source_pose.pose_type is PoseType.LEFT_ARM:
            target_pose_type = PoseType.RIGHT_ARM
            mirrored_values = {
                rule.right_joint: rule.sign * source_pose.joint_values[rule.left_joint]
                for rule in self.ARM_MIRROR_RULES
            }
        elif source_pose.pose_type is PoseType.RIGHT_ARM:
            target_pose_type = PoseType.LEFT_ARM
            mirrored_values = {
                rule.left_joint: rule.sign * source_pose.joint_values[rule.right_joint]
                for rule in self.ARM_MIRROR_RULES
            }
        else:
            raise ValueError("Only left_arm and right_arm poses can be mirrored")

        return PoseDefinition.create(
            schema=self.schema,
            name=name,
            pose_type=target_pose_type,
            joint_values=mirrored_values,
            source=PoseSource.MIRROR,
            source_parts={
                "mirror_source": source_pose.name,
                "mirror_source_type": source_pose.pose_type.value,
            },
            notes=notes,
        )

    def _pose_path(self, *, pose_type: PoseType, name: str) -> Path:
        return self.pose_dir / pose_type.value / f"{name}.json"

    def _require_pose_type(self, pose: PoseDefinition, expected_type: PoseType) -> None:
        self._validate_pose(pose)
        if pose.pose_type is not expected_type:
            raise ValueError(
                f"Pose {pose.name} is {pose.pose_type.value}; expected {expected_type.value}"
            )

    def _preview_joint_values(
        self,
        *,
        pose: PoseDefinition,
        base_pose: PoseDefinition | None,
    ) -> dict[str, float]:
        self._validate_pose(pose)
        preview_values: dict[str, float] = {}
        if base_pose is not None:
            self._require_pose_type(base_pose, PoseType.BASE)
            preview_values.update(base_pose.joint_values)
        preview_values.update(pose.joint_values)
        return preview_values

    def _validate_pose(self, pose: PoseDefinition) -> None:
        if pose.robot_model_id != self.schema.model_id:
            raise ValueError(
                f"Pose model {pose.robot_model_id} does not match {self.schema.model_id}"
            )
        self.schema.validate_joint_values(
            pose_type=pose.pose_type,
            joint_values=pose.joint_values,
        )


def demo_pose_service() -> None:
    logging.basicConfig(level=logging.INFO)
    settings = AppSettings()
    schema = G1JointSchema(asset_helper=G1AssetHelper(asset_dir=settings.g1_asset_dir))
    simulation_helper = MujocoPoseHelper(mjcf_path=settings.g1_asset_dir / "g1_29dof_fake_hand.xml")
    with tempfile.TemporaryDirectory() as temporary_directory:
        service = PoseService(
            schema=schema,
            pose_dir=Path(temporary_directory),
            file_helper=PoseFileHelper(),
            simulation_helper=simulation_helper,
        )
        base = PoseDefinition.create(
            schema=schema,
            name="neutral_base",
            pose_type=PoseType.BASE,
            joint_values=schema.neutral_values(PoseType.BASE),
            source=PoseSource.SIMULATION,
        )
        left_values = schema.neutral_values(PoseType.LEFT_ARM)
        left_values["left_shoulder_roll_joint"] = 1.2
        left_values["left_elbow_joint"] = 0.6
        left_greeting = service.create_simulated_pose(
            name="left_greeting",
            pose_type=PoseType.LEFT_ARM,
            joint_values=left_values,
        )
        mirrored_right = service.mirror_arm_pose(
            source_pose=left_greeting,
            name="right_greeting",
        )
        composed = service.compose_pose(
            name="symmetric_greeting",
            base=base,
            left_arm=left_greeting,
            right_arm=mirrored_right,
        )
        path = service.save_pose(pose=composed)
        preview_path = service.save_pose_preview(
            pose=composed,
            output_path=settings.pose_preview_dir / "simulated_composed_pose.png",
        )
        LOGGER.info("Saved composed pose demo: %s", path)
        LOGGER.info("Saved composed pose preview: %s", preview_path)


def main() -> None:
    demo_pose_service()


if __name__ == "__main__":
    main()
