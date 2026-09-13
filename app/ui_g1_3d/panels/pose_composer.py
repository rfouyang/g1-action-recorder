"""Pose-composer workspace logic for the G1 3D UI."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from app.ui_g1_3d.context import UIContext
from component.common.g1_joint_schema import PoseType
from component.common.models import PoseDefinition


class ComposePoseCommand(BaseModel):
    """Browser command for previewing or saving a composed pose."""

    model_config = ConfigDict(extra="forbid")

    base_pose: str
    left_arm_pose: str | None = None
    right_arm_pose: str | None = None
    name: str = ""
    notes: str = ""
    overwrite: bool = False


class PoseComposerPanel:
    """Compose persisted pose parts and apply them to shared simulation."""

    name = "Pose Composer"
    template = "panels/pose_composer.html"

    @classmethod
    def template_context(cls, context: UIContext) -> dict[str, object]:
        pose_names = cls.pose_names(context)
        default_base = context.app.settings.initial_base_pose_name
        return {
            "base_pose_names": pose_names[PoseType.BASE.value],
            "left_arm_pose_names": pose_names[PoseType.LEFT_ARM.value],
            "right_arm_pose_names": pose_names[PoseType.RIGHT_ARM.value],
            "composed_pose_names": pose_names[PoseType.COMPOSED.value],
            "default_composer_base": (
                default_base
                if default_base in pose_names[PoseType.BASE.value]
                else None
            ),
        }

    @staticmethod
    def pose_names(context: UIContext) -> dict[str, tuple[str, ...]]:
        service = context.app.pose_service
        return {
            pose_type.value: tuple(
                pose.name for pose in service.list_poses(pose_type=pose_type)
            )
            for pose_type in PoseType
        }

    @classmethod
    def preview(
        cls,
        *,
        context: UIContext,
        command: ComposePoseCommand,
    ) -> tuple[PoseDefinition, int]:
        pose = cls._compose(
            context=context,
            command=command,
            fallback_name="unsaved_composed_preview",
        )
        snapshot = context.app.simulation.update_joint_positions(pose.joint_values)
        return pose, snapshot.revision

    @classmethod
    def save(
        cls,
        *,
        context: UIContext,
        command: ComposePoseCommand,
    ) -> tuple[PoseDefinition, int]:
        pose = cls._compose(context=context, command=command)
        context.app.pose_service.save_pose(
            pose=pose,
            overwrite=command.overwrite,
        )
        snapshot = context.app.simulation.update_joint_positions(pose.joint_values)
        return pose, snapshot.revision

    @staticmethod
    def _compose(
        *,
        context: UIContext,
        command: ComposePoseCommand,
        fallback_name: str | None = None,
    ) -> PoseDefinition:
        if not command.base_pose:
            raise ValueError("Select a base pose")
        name = command.name.strip() or fallback_name
        if name is None:
            raise ValueError("Enter a composed pose name")

        service = context.app.pose_service
        base = service.load_pose(
            pose_type=PoseType.BASE,
            name=command.base_pose,
        )
        left_arm = (
            service.load_pose(
                pose_type=PoseType.LEFT_ARM,
                name=command.left_arm_pose,
            )
            if command.left_arm_pose
            else None
        )
        right_arm = (
            service.load_pose(
                pose_type=PoseType.RIGHT_ARM,
                name=command.right_arm_pose,
            )
            if command.right_arm_pose
            else None
        )
        return service.compose_pose(
            name=name,
            base=base,
            left_arm=left_arm,
            right_arm=right_arm,
            notes=command.notes,
        )
