"""View data for the interactive pose-recorder workspace."""

from __future__ import annotations

from dataclasses import dataclass

from app.ui_g1_3d.context import UIContext
from component.common.g1_joint_schema import PoseType
from component.common.models import PoseDefinition


@dataclass(frozen=True, slots=True)
class JointRow:
    """One editable upper-body joint shown by the pose recorder."""

    name: str
    label: str
    group: str
    lower_limit: float
    upper_limit: float
    target: float
    actual: float
    reset_value: float


class PoseRecorderPanel:
    """Build the initial pose-recorder view from shared simulation state."""

    name = "Pose Recorder"
    template = "panels/pose_recorder.html"
    EDITABLE_POSE_TYPES = (PoseType.BASE, PoseType.LEFT_ARM, PoseType.RIGHT_ARM)

    @classmethod
    def template_context(cls, context: UIContext) -> dict[str, object]:
        snapshot = context.app.simulation.snapshot()
        current_positions = snapshot.joint_position_map()
        schema = context.app.joint_schema
        initial_pose = context.app.pose_service.load_initial_base_pose(
            name=context.app.settings.initial_base_pose_name
        )
        editable_names = set(schema.BASE_JOINT_NAMES)
        rows = tuple(
            JointRow(
                name=definition.name,
                label=cls._joint_label(definition.name),
                group=definition.group.value,
                lower_limit=definition.lower_limit,
                upper_limit=definition.upper_limit,
                target=current_positions[definition.name],
                actual=current_positions[definition.name],
                reset_value=initial_pose.joint_values[definition.name],
            )
            for definition in schema.definitions
            if definition.name in editable_names
        )
        return {
            "joint_rows": rows,
            "editable_joint_count": len(rows),
            "default_pose_name": initial_pose.name,
            "default_pose_notes": initial_pose.notes,
            "initial_revision": snapshot.revision,
        }

    @classmethod
    def save_simulation_pose(
        cls,
        *,
        context: UIContext,
        pose_type: PoseType,
        name: str,
        notes: str,
        joint_positions: dict[str, float],
        overwrite: bool,
    ) -> tuple[PoseDefinition, int]:
        """Validate, apply, and save the selected simulated pose group."""
        if pose_type not in cls.EDITABLE_POSE_TYPES:
            raise ValueError(f"Pose type {pose_type.value} cannot be recorded")

        schema = context.app.joint_schema
        validated_positions = schema.validate_joint_values(
            pose_type=pose_type,
            joint_values=joint_positions,
        )
        snapshot = context.app.simulation.update_joint_positions(
            validated_positions
        )
        actual_positions = snapshot.joint_position_map()
        pose = context.app.pose_service.create_simulated_pose(
            name=name,
            pose_type=pose_type,
            joint_values={
                joint_name: actual_positions[joint_name]
                for joint_name in schema.joint_names(pose_type)
            },
            notes=notes,
        )
        context.app.pose_service.save_pose(pose=pose, overwrite=overwrite)
        return pose, snapshot.revision

    @staticmethod
    def mirror_arm(
        *,
        context: UIContext,
        source_pose_type: PoseType,
        source_positions: dict[str, float],
    ) -> tuple[PoseType, dict[str, float], dict[str, float], int]:
        """Validate the current editor arm and mirror it in MuJoCo."""
        target_pose_type, mirrored_positions = (
            context.app.pose_service.mirror_arm_values(
                source_pose_type=source_pose_type,
                joint_values=source_positions,
            )
        )
        updated = context.app.simulation.update_joint_positions(
            {**source_positions, **mirrored_positions}
        )
        return (
            target_pose_type,
            source_positions,
            mirrored_positions,
            updated.revision,
        )

    @staticmethod
    def _joint_label(joint_name: str) -> str:
        label = joint_name.removesuffix("_joint")
        for prefix in ("left_", "right_", "waist_"):
            if label.startswith(prefix):
                label = label.removeprefix(prefix)
                break
        return label.replace("_", " ").title()
