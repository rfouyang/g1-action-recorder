"""Uploaded action playback workspace logic for the G1 3D UI."""

from __future__ import annotations

from app.ui_g1_3d.context import UIContext
from component.action_playback_service import ActionPlaybackSnapshot
from component.action_player_service import (
    ActionFileFormat,
    CapturedActionPose,
    LoadedAction,
)
from component.common.g1_joint_schema import PoseType


class ActionPlayerPanel:
    """Present file import and arm-only playback through shared capabilities."""

    name = "Action Player"
    template = "panels/action_player.html"
    order = 40

    @staticmethod
    def template_context(context: UIContext) -> dict[str, object]:
        return {
            "action_player_arm_joint_count": len(
                context.app.joint_schema.ARM_JOINT_NAMES
            ),
            "action_player_waist_pose": context.app.settings.initial_base_pose_name,
        }

    @staticmethod
    def load(
        *,
        context: UIContext,
        source_format: ActionFileFormat,
        filename: str,
        content: bytes,
        action_name: str | None,
        source_fps: float | None,
    ) -> LoadedAction:
        return context.app.action_player.load(
            source_format=source_format,
            filename=filename,
            content=content,
            action_name=action_name,
            source_fps=source_fps,
        )

    @staticmethod
    def response(loaded: LoadedAction) -> dict[str, object]:
        trajectory = loaded.trajectory
        return {
            "action_name": trajectory.action_name,
            "source_format": loaded.source_format.value,
            "source_filename": loaded.source_filename,
            "source_joint_count": loaded.source_joint_count,
            "arm_joint_count": loaded.arm_joint_count,
            "sample_count": trajectory.sample_count,
            "duration_seconds": trajectory.duration_seconds,
            "sample_frequency_hz": trajectory.requested_sample_frequency_hz,
            "warnings": loaded.warnings,
        }

    @staticmethod
    def seek(*, context: UIContext, sample_index: int) -> ActionPlaybackSnapshot:
        return context.app.action_player.seek(sample_index=sample_index)

    @staticmethod
    def save_pose(
        *,
        context: UIContext,
        pose_type: PoseType,
        name: str,
        notes: str,
        overwrite: bool,
    ) -> CapturedActionPose:
        return context.app.action_player.save_paused_arm_pose(
            pose_type=pose_type,
            name=name,
            notes=notes,
            overwrite=overwrite,
        )
