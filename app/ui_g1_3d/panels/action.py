"""Action-authoring workspace logic for the G1 3D UI."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from app.ui_g1_3d.context import UIContext
from component.common.action_models import (
    ActionDefinition,
    ActionPoseReference,
    ActionTrajectory,
    ActionTransition,
)
from component.common.g1_joint_schema import PoseType


class ActionFrameCommand(BaseModel):
    """One complete intermediate pose and its timing."""

    model_config = ConfigDict(extra="forbid")

    pose_type: PoseType
    name: str
    duration_seconds: float = Field(gt=0.0)
    hold_seconds: float = Field(default=0.0, ge=0.0)


class SaveActionCommand(BaseModel):
    """Browser command for validating and saving an action definition."""

    model_config = ConfigDict(extra="forbid")

    name: str
    notes: str = ""
    frames: tuple[ActionFrameCommand, ...] = Field(min_length=1)
    return_duration_seconds: float = Field(gt=0.0)
    overwrite: bool = False


class CompileActionCommand(SaveActionCommand):
    """Browser command for compiling an action to a sampled trajectory."""

    sample_frequency_hz: float = Field(default=25.0, gt=0.0)


class PreviewActionPoseCommand(BaseModel):
    """Browser command for showing one complete action pose in MuJoCo."""

    model_config = ConfigDict(extra="forbid")

    pose_type: PoseType
    name: str


class ActionComposerPanel:
    """Author ordered actions while delegating validation to ActionService."""

    name = "Action Composer"
    template = "panels/action.html"
    default_transition_seconds = 1.0
    default_sample_frequency_hz = 25.0
    boundary_reference = ActionPoseReference(
        ActionDefinition.BOUNDARY_POSE_TYPE,
        ActionDefinition.BOUNDARY_POSE_NAME,
    )

    @classmethod
    def template_context(cls, context: UIContext) -> dict[str, object]:
        sources = cls.sources(context)
        return {
            "action_pose_choices": sources["pose_choices"],
            "saved_action_names": sources["saved_actions"],
            "compiled_action_names": sources["compiled_actions"],
            "action_boundary_pose": cls.boundary_reference.name,
            "default_action_transition_seconds": cls.default_transition_seconds,
            "default_action_sample_frequency_hz": cls.default_sample_frequency_hz,
        }

    @classmethod
    def sources(cls, context: UIContext) -> dict[str, object]:
        choices: list[dict[str, str]] = []
        for pose_type, type_label in (
            (PoseType.BASE, "Base"),
            (PoseType.COMPOSED, "Composed"),
        ):
            for pose in context.app.pose_service.list_poses(pose_type=pose_type):
                if pose_type is PoseType.BASE and pose.name == cls.boundary_reference.name:
                    continue
                choices.append(
                    {
                        "pose_type": pose_type.value,
                        "name": pose.name,
                        "value": f"{pose_type.value}/{pose.name}",
                        "label": f"{type_label} · {pose.name}",
                    }
                )
        return {
            "pose_choices": tuple(choices),
            "saved_actions": tuple(
                action.name for action in context.app.action_service.list_actions()
            ),
            "compiled_actions": context.app.action_service.list_trajectories(),
        }

    @classmethod
    def create_action(
        cls,
        *,
        context: UIContext,
        command: SaveActionCommand,
    ) -> ActionDefinition:
        if not command.name.strip():
            raise ValueError("Enter an action name")
        transitions = [
            ActionTransition(
                target_pose=ActionPoseReference(frame.pose_type, frame.name),
                duration_seconds=frame.duration_seconds,
                hold_seconds=frame.hold_seconds,
            )
            for frame in command.frames
        ]
        transitions.append(
            ActionTransition(
                target_pose=cls.boundary_reference,
                duration_seconds=command.return_duration_seconds,
            )
        )
        return context.app.action_service.create_action(
            name=command.name,
            initial_pose=cls.boundary_reference,
            transitions=transitions,
            notes=command.notes,
        )

    @classmethod
    def save(
        cls,
        *,
        context: UIContext,
        command: SaveActionCommand,
    ) -> ActionDefinition:
        action = cls.create_action(context=context, command=command)
        context.app.action_service.save_action(
            action=action,
            overwrite=command.overwrite,
        )
        return action

    @classmethod
    def compile(
        cls,
        *,
        context: UIContext,
        command: CompileActionCommand,
    ) -> ActionTrajectory:
        action = cls.create_action(context=context, command=command)
        trajectory = context.app.action_service.generate_trajectory(
            action=action,
            sample_frequency_hz=command.sample_frequency_hz,
        )
        context.app.action_service.save_trajectory(
            trajectory=trajectory,
            overwrite=command.overwrite,
        )
        return trajectory

    @classmethod
    def load(cls, *, context: UIContext, name: str) -> dict[str, object]:
        action = context.app.action_service.load_action(name=name)
        return {
            "name": action.name,
            "notes": action.notes,
            "frames": tuple(
                {
                    "pose_type": transition.target_pose.pose_type.value,
                    "name": transition.target_pose.name,
                    "duration_seconds": transition.duration_seconds,
                    "hold_seconds": transition.hold_seconds,
                }
                for transition in action.transitions[:-1]
            ),
            "return_duration_seconds": action.transitions[-1].duration_seconds,
            "total_duration_seconds": action.total_duration_seconds,
        }

    @staticmethod
    def preview_pose(
        *,
        context: UIContext,
        command: PreviewActionPoseCommand,
    ) -> int:
        reference = ActionPoseReference(command.pose_type, command.name)
        pose = context.app.pose_service.load_pose(
            pose_type=reference.pose_type,
            name=reference.name,
        )
        return context.app.simulation.update_joint_positions(pose.joint_values).revision
