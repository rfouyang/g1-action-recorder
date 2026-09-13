"""Serializable action definitions built from ordered upper-body pose references."""

from __future__ import annotations

import json
import logging
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from numbers import Real
from typing import ClassVar

import numpy as np
from numpy.typing import NDArray

from component.common.g1_joint_schema import G1JointSchema, PoseType
from component.common.models import PoseDefinition
from config.settings import CONCIERGE_INITIAL_POSE_NAME, AppSettings
from util.g1_asset_helper import G1AssetHelper

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ActionPoseReference:
    """Reference one complete upper-body pose used by an action."""

    pose_type: PoseType
    name: str

    ALLOWED_POSE_TYPES = frozenset({PoseType.BASE, PoseType.COMPOSED})

    def __post_init__(self) -> None:
        if not isinstance(self.pose_type, PoseType):
            raise ValueError("Action pose reference pose_type must be a PoseType")
        if self.pose_type not in self.ALLOWED_POSE_TYPES:
            raise ValueError(
                "Action poses must be base or composed; "
                f"received {self.pose_type.value}"
            )
        object.__setattr__(self, "name", PoseDefinition.validate_name(self.name))

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> ActionPoseReference:
        required_keys = {"pose_type", "name"}
        missing_keys = sorted(required_keys - set(payload))
        if missing_keys:
            raise ValueError(f"Action pose reference is missing fields: {missing_keys}")
        name = payload["name"]
        if not isinstance(name, str):
            raise ValueError("Action pose reference name must be a string")
        return cls(
            pose_type=PoseType(str(payload["pose_type"])),
            name=name,
        )

    def to_dict(self) -> dict[str, str]:
        return {"pose_type": self.pose_type.value, "name": self.name}


@dataclass(frozen=True, slots=True)
class ActionTransition:
    """Move into a target pose, then optionally hold that exact pose."""

    target_pose: ActionPoseReference
    duration_seconds: float
    hold_seconds: float = 0.0

    def __post_init__(self) -> None:
        if not isinstance(self.target_pose, ActionPoseReference):
            raise ValueError("Action transition target_pose must be a pose reference")
        if isinstance(self.duration_seconds, bool) or not isinstance(self.duration_seconds, Real):
            raise ValueError("Action transition duration must be a real number")
        duration_seconds = float(self.duration_seconds)
        if not math.isfinite(duration_seconds) or duration_seconds <= 0.0:
            raise ValueError("Action transition duration must be finite and greater than zero")
        object.__setattr__(self, "duration_seconds", duration_seconds)
        if isinstance(self.hold_seconds, bool) or not isinstance(self.hold_seconds, Real):
            raise ValueError("Action transition hold must be a real number")
        hold_seconds = float(self.hold_seconds)
        if not math.isfinite(hold_seconds) or hold_seconds < 0.0:
            raise ValueError("Action transition hold must be finite and nonnegative")
        object.__setattr__(self, "hold_seconds", hold_seconds)

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> ActionTransition:
        required_keys = {"target_pose", "duration_seconds"}
        missing_keys = sorted(required_keys - set(payload))
        if missing_keys:
            raise ValueError(f"Action transition is missing fields: {missing_keys}")
        target_pose = payload["target_pose"]
        if not isinstance(target_pose, Mapping):
            raise ValueError("Action transition target_pose must be an object")
        return cls(
            target_pose=ActionPoseReference.from_dict(target_pose),
            duration_seconds=payload["duration_seconds"],
            hold_seconds=payload.get("hold_seconds", 0.0),
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "target_pose": self.target_pose.to_dict(),
            "duration_seconds": self.duration_seconds,
            "hold_seconds": self.hold_seconds,
        }


@dataclass(frozen=True, slots=True)
class ActionDefinition:
    """An initial pose followed by an ordered list of timed transitions."""

    BOUNDARY_POSE_TYPE: ClassVar[PoseType] = PoseType.BASE
    BOUNDARY_POSE_NAME: ClassVar[str] = CONCIERGE_INITIAL_POSE_NAME

    schema_version: int
    name: str
    robot_model_id: str
    initial_pose: ActionPoseReference
    transitions: tuple[ActionTransition, ...]
    created_at: datetime
    notes: str = ""

    def __post_init__(self) -> None:
        if self.schema_version != 1:
            raise ValueError(f"Unsupported action schema version: {self.schema_version}")
        object.__setattr__(self, "name", PoseDefinition.validate_name(self.name))
        if not isinstance(self.robot_model_id, str) or not self.robot_model_id.strip():
            raise ValueError("Action robot_model_id must be a non-empty string")
        if not isinstance(self.initial_pose, ActionPoseReference):
            raise ValueError("Action initial_pose must be a pose reference")
        transitions = tuple(self.transitions)
        if not all(isinstance(transition, ActionTransition) for transition in transitions):
            raise ValueError("Action transitions must contain only ActionTransition values")
        if len(transitions) < 2:
            raise ValueError(
                "Action must contain at least three keyframes: "
                "concierge_init, one intermediate pose, and concierge_init"
            )
        required_boundary = ActionPoseReference(
            self.BOUNDARY_POSE_TYPE,
            self.BOUNDARY_POSE_NAME,
        )
        if self.initial_pose != required_boundary:
            raise ValueError("Action must start with base/concierge_init")
        if transitions[-1].target_pose != required_boundary:
            raise ValueError("Action must end with base/concierge_init")
        object.__setattr__(self, "transitions", transitions)
        if self.created_at.tzinfo is None or self.created_at.utcoffset() is None:
            raise ValueError("Action created_at must include a timezone")

    @property
    def total_duration_seconds(self) -> float:
        return sum(
            transition.duration_seconds + transition.hold_seconds
            for transition in self.transitions
        )

    @property
    def pose_sequence(self) -> tuple[ActionPoseReference, ...]:
        return (self.initial_pose,) + tuple(
            transition.target_pose for transition in self.transitions
        )

    @property
    def intermediate_poses(self) -> tuple[ActionPoseReference, ...]:
        return tuple(transition.target_pose for transition in self.transitions[:-1])

    @classmethod
    def create(
        cls,
        *,
        schema: G1JointSchema,
        name: str,
        initial_pose: ActionPoseReference,
        transitions: Sequence[ActionTransition],
        created_at: datetime | None = None,
        notes: str = "",
    ) -> ActionDefinition:
        return cls(
            schema_version=1,
            name=name,
            robot_model_id=schema.model_id,
            initial_pose=initial_pose,
            transitions=tuple(transitions),
            created_at=created_at or datetime.now(timezone.utc),
            notes=notes,
        )

    @classmethod
    def from_dict(
        cls,
        *,
        schema: G1JointSchema,
        payload: Mapping[str, object],
    ) -> ActionDefinition:
        required_keys = {
            "schema_version",
            "name",
            "robot_model_id",
            "initial_pose",
            "transitions",
            "created_at",
        }
        missing_keys = sorted(required_keys - set(payload))
        if missing_keys:
            raise ValueError(f"Action payload is missing fields: {missing_keys}")
        if payload["schema_version"] != 1:
            raise ValueError(
                f"Unsupported action schema version: {payload['schema_version']}"
            )
        if payload["robot_model_id"] != schema.model_id:
            raise ValueError(
                f"Action model {payload['robot_model_id']} does not match {schema.model_id}"
            )

        name = payload["name"]
        initial_pose = payload["initial_pose"]
        transitions = payload["transitions"]
        if not isinstance(name, str):
            raise ValueError("Action name must be a string")
        if not isinstance(initial_pose, Mapping):
            raise ValueError("Action initial_pose must be an object")
        if not isinstance(transitions, list):
            raise ValueError("Action transitions must be an array")
        transition_models = []
        for index, transition in enumerate(transitions):
            if not isinstance(transition, Mapping):
                raise ValueError(f"Action transition {index} must be an object")
            transition_models.append(ActionTransition.from_dict(transition))

        created_at = datetime.fromisoformat(str(payload["created_at"]).replace("Z", "+00:00"))
        return cls.create(
            schema=schema,
            name=name,
            initial_pose=ActionPoseReference.from_dict(initial_pose),
            transitions=transition_models,
            created_at=created_at,
            notes=str(payload.get("notes", "")),
        )

    @classmethod
    def from_json(
        cls,
        *,
        schema: G1JointSchema,
        content: str,
    ) -> ActionDefinition:
        payload = json.loads(content)
        if not isinstance(payload, dict):
            raise ValueError("Action JSON root must be an object")
        return cls.from_dict(schema=schema, payload=payload)

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "name": self.name,
            "robot_model_id": self.robot_model_id,
            "initial_pose": self.initial_pose.to_dict(),
            "transitions": [transition.to_dict() for transition in self.transitions],
            "created_at": self.created_at.astimezone(timezone.utc)
            .isoformat()
            .replace("+00:00", "Z"),
            "notes": self.notes,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2) + "\n"


@dataclass(frozen=True, slots=True, eq=False)
class ActionTrajectory:
    """Validated in-memory samples for one resolved action definition."""

    action_name: str
    robot_model_id: str
    joint_names: tuple[str, ...]
    timestamps: NDArray[np.float64]
    joint_positions: NDArray[np.float64]
    keyframe_sample_indices: tuple[int, ...]
    source_pose_names: tuple[str, ...]
    keyframe_hold_seconds: tuple[float, ...]
    requested_sample_frequency_hz: float
    max_tracking_error: float

    def __post_init__(self) -> None:
        object.__setattr__(self, "action_name", PoseDefinition.validate_name(self.action_name))
        if not isinstance(self.robot_model_id, str) or not self.robot_model_id.strip():
            raise ValueError("Trajectory robot_model_id must be a non-empty string")
        joint_names = tuple(self.joint_names)
        if not joint_names or len(set(joint_names)) != len(joint_names):
            raise ValueError("Trajectory joint_names must be non-empty and unique")
        object.__setattr__(self, "joint_names", joint_names)

        timestamps = np.asarray(self.timestamps, dtype=np.float64).copy()
        joint_positions = np.asarray(self.joint_positions, dtype=np.float64).copy()
        if timestamps.ndim != 1 or len(timestamps) < 2:
            raise ValueError("Trajectory timestamps must be a one-dimensional sample array")
        if not np.all(np.isfinite(timestamps)):
            raise ValueError("Trajectory timestamps must be finite")
        if not math.isclose(float(timestamps[0]), 0.0, abs_tol=1e-12):
            raise ValueError("Trajectory timestamps must start at zero")
        if not np.all(np.diff(timestamps) > 0.0):
            raise ValueError("Trajectory timestamps must be strictly increasing")
        if joint_positions.shape != (len(timestamps), len(joint_names)):
            raise ValueError(
                "Trajectory joint_positions shape must match timestamps and joint_names"
            )
        if not np.all(np.isfinite(joint_positions)):
            raise ValueError("Trajectory joint positions must be finite")

        keyframe_indices = tuple(self.keyframe_sample_indices)
        source_pose_names = tuple(self.source_pose_names)
        if len(keyframe_indices) < 3 or len(keyframe_indices) != len(source_pose_names):
            raise ValueError(
                "Trajectory keyframes must contain matching indices and source pose names"
            )
        if keyframe_indices[0] != 0 or keyframe_indices[-1] != len(timestamps) - 1:
            raise ValueError("Trajectory keyframe indices must include both endpoints")
        if any(
            isinstance(index, bool) or not isinstance(index, int)
            for index in keyframe_indices
        ) or any(
            current >= following
            for current, following in zip(
                keyframe_indices,
                keyframe_indices[1:],
                strict=False,
            )
        ):
            raise ValueError("Trajectory keyframe indices must be strictly increasing integers")
        source_pose_names = tuple(
            PoseDefinition.validate_name(pose_name) for pose_name in source_pose_names
        )
        keyframe_hold_seconds = tuple(
            self._nonnegative_value(
                name=f"Trajectory keyframe {index} hold",
                value=hold_seconds,
            )
            for index, hold_seconds in enumerate(self.keyframe_hold_seconds)
        )
        if len(keyframe_hold_seconds) != len(keyframe_indices):
            raise ValueError(
                "Trajectory keyframe holds must match keyframe indices"
            )
        if keyframe_hold_seconds[0] != 0.0:
            raise ValueError("Trajectory initial keyframe hold must be zero")

        frequency = self._positive_value(
            name="Trajectory sample frequency",
            value=self.requested_sample_frequency_hz,
        )
        tracking_error = self._nonnegative_value(
            name="Trajectory tracking error",
            value=self.max_tracking_error,
        )
        timestamps.setflags(write=False)
        joint_positions.setflags(write=False)
        object.__setattr__(self, "timestamps", timestamps)
        object.__setattr__(self, "joint_positions", joint_positions)
        object.__setattr__(self, "keyframe_sample_indices", keyframe_indices)
        object.__setattr__(self, "source_pose_names", source_pose_names)
        object.__setattr__(self, "keyframe_hold_seconds", keyframe_hold_seconds)
        object.__setattr__(self, "requested_sample_frequency_hz", frequency)
        object.__setattr__(self, "max_tracking_error", tracking_error)

    @property
    def sample_count(self) -> int:
        return len(self.timestamps)

    @property
    def duration_seconds(self) -> float:
        return float(self.timestamps[-1])

    def joint_values_at(self, sample_index: int) -> dict[str, float]:
        return {
            joint_name: float(value)
            for joint_name, value in zip(
                self.joint_names,
                self.joint_positions[sample_index],
                strict=True,
            )
        }

    def _positive_value(self, *, name: str, value: object) -> float:
        if isinstance(value, bool) or not isinstance(value, Real):
            raise ValueError(f"{name} must be a real number")
        numeric_value = float(value)
        if not math.isfinite(numeric_value) or numeric_value <= 0.0:
            raise ValueError(f"{name} must be finite and greater than zero")
        return numeric_value

    def _nonnegative_value(self, *, name: str, value: object) -> float:
        if isinstance(value, bool) or not isinstance(value, Real):
            raise ValueError(f"{name} must be a real number")
        numeric_value = float(value)
        if not math.isfinite(numeric_value) or numeric_value < 0.0:
            raise ValueError(f"{name} must be finite and nonnegative")
        return numeric_value


def demo_action_definition() -> None:
    logging.basicConfig(level=logging.INFO)
    settings = AppSettings()
    schema = G1JointSchema(asset_helper=G1AssetHelper(asset_dir=settings.g1_asset_dir))
    action = ActionDefinition.create(
        schema=schema,
        name="双侧迎宾演示",
        initial_pose=ActionPoseReference(PoseType.BASE, "concierge_init"),
        transitions=(
            ActionTransition(
                target_pose=ActionPoseReference(
                    PoseType.COMPOSED,
                    "concierge_present_left",
                ),
                duration_seconds=1.5,
            ),
            ActionTransition(
                target_pose=ActionPoseReference(
                    PoseType.COMPOSED,
                    "concierge_present_right",
                ),
                duration_seconds=2.0,
            ),
            ActionTransition(
                target_pose=ActionPoseReference(PoseType.BASE, "concierge_init"),
                duration_seconds=1.5,
            ),
        ),
        notes="Ordered-pose action definition demo",
    )
    restored_action = ActionDefinition.from_json(schema=schema, content=action.to_json())
    LOGGER.info(
        "Restored action %s with %d transitions over %.1f seconds",
        restored_action.name,
        len(restored_action.transitions),
        restored_action.total_duration_seconds,
    )


def main() -> None:
    demo_action_definition()


if __name__ == "__main__":
    main()
