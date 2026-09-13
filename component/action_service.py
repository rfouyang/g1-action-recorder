"""Persist action definitions and resolve their ordered pose references."""

from __future__ import annotations

import logging
import tempfile
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from component.common.action_models import (
    ActionDefinition,
    ActionPoseReference,
    ActionTrajectory,
    ActionTransition,
)
from component.common.g1_joint_schema import G1JointSchema, PoseType
from component.common.models import PoseDefinition
from component.pose_service import PoseService
from config.settings import AppSettings
from util.g1_asset_helper import G1AssetHelper
from util.mujoco_action_helper import MujocoActionHelper
from util.mujoco_pose_helper import CameraView, MujocoPoseHelper
from util.numpy_archive_helper import NumpyArchiveHelper
from util.pink_ik_helper import PinkIKHelper
from util.pose_file_helper import PoseFileHelper

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ResolvedActionTransition:
    """One validated target pose with its travel and hold durations."""

    target_pose: PoseDefinition
    duration_seconds: float
    hold_seconds: float


@dataclass(frozen=True, slots=True)
class ResolvedAction:
    """An action definition with every pose reference loaded and validated."""

    definition: ActionDefinition
    initial_pose: PoseDefinition
    transitions: tuple[ResolvedActionTransition, ...]

    @property
    def pose_sequence(self) -> tuple[PoseDefinition, ...]:
        return (self.initial_pose,) + tuple(
            transition.target_pose for transition in self.transitions
        )


class ActionService:
    """Apply action persistence rules and resolve pose dependencies."""

    TRAJECTORY_SCHEMA_VERSION = 2
    TRAJECTORY_V1_ARRAY_NAMES = frozenset(
        {
            "schema_version",
            "action_name",
            "robot_model_id",
            "fps",
            "joint_names",
            "timestamps",
            "joint_positions",
            "keyframe_sample_indices",
            "source_pose_names",
            "max_tracking_error",
        }
    )
    TRAJECTORY_ARRAY_NAMES = TRAJECTORY_V1_ARRAY_NAMES | {"keyframe_hold_seconds"}

    def __init__(
        self,
        *,
        schema: G1JointSchema,
        action_definition_dir: Path,
        file_helper: PoseFileHelper,
        pose_service: PoseService,
        ik_helper: PinkIKHelper,
        action_trajectory_dir: Path,
        archive_helper: NumpyArchiveHelper,
        action_preview_helper: MujocoActionHelper,
        action_preview_dir: Path,
    ) -> None:
        self.schema = schema
        self.action_definition_dir = action_definition_dir
        self.file_helper = file_helper
        self.pose_service = pose_service
        self.ik_helper = ik_helper
        self.action_trajectory_dir = action_trajectory_dir
        self.archive_helper = archive_helper
        self.action_preview_helper = action_preview_helper
        self.action_preview_dir = action_preview_dir

    def create_action(
        self,
        *,
        name: str,
        initial_pose: ActionPoseReference,
        transitions: Sequence[ActionTransition],
        notes: str = "",
    ) -> ActionDefinition:
        """Create an action only when all referenced poses currently resolve."""
        action = ActionDefinition.create(
            schema=self.schema,
            name=name,
            initial_pose=initial_pose,
            transitions=transitions,
            notes=notes,
        )
        self.resolve_action(action=action)
        return action

    def save_action(
        self,
        *,
        action: ActionDefinition,
        overwrite: bool = False,
    ) -> Path:
        """Validate pose dependencies, then atomically save an action definition."""
        self.resolve_action(action=action)
        return self.file_helper.write_json(
            path=self._action_path(name=action.name),
            payload=action.to_dict(),
            overwrite=overwrite,
        )

    def load_action(self, *, name: str) -> ActionDefinition:
        """Load an action definition without requiring its pose files to exist."""
        normalized_name = PoseDefinition.validate_name(name)
        path = self._action_path(name=normalized_name)
        action = ActionDefinition.from_dict(
            schema=self.schema,
            payload=self.file_helper.read_json(path=path),
        )
        if action.name != normalized_name:
            raise ValueError(
                f"Action file {path} contains a different action name: {action.name}"
            )
        return action

    def list_actions(self) -> tuple[ActionDefinition, ...]:
        """List saved definitions even if a referenced pose was later removed."""
        return tuple(
            self.load_action(name=path.stem)
            for path in self.file_helper.list_json_files(
                directory=self.action_definition_dir
            )
        )

    def resolve_action(self, *, action: ActionDefinition) -> ResolvedAction:
        """Resolve ordered references into complete, model-compatible poses."""
        self._validate_action_model(action)
        pose_cache: dict[ActionPoseReference, PoseDefinition] = {}

        def resolve(reference: ActionPoseReference) -> PoseDefinition:
            if reference not in pose_cache:
                try:
                    pose_cache[reference] = self.pose_service.load_pose(
                        pose_type=reference.pose_type,
                        name=reference.name,
                    )
                except (FileNotFoundError, ValueError) as error:
                    raise ValueError(
                        "Could not resolve action pose "
                        f"{reference.pose_type.value}/{reference.name}: {error}"
                    ) from error
            return pose_cache[reference]

        initial_pose = resolve(action.initial_pose)
        transitions = tuple(
            ResolvedActionTransition(
                target_pose=resolve(transition.target_pose),
                duration_seconds=transition.duration_seconds,
                hold_seconds=transition.hold_seconds,
            )
            for transition in action.transitions
        )
        return ResolvedAction(
            definition=action,
            initial_pose=initial_pose,
            transitions=transitions,
        )

    def generate_trajectory(
        self,
        *,
        action: ActionDefinition,
        sample_frequency_hz: float = 25.0,
    ) -> ActionTrajectory:
        """Resolve an action and generate Pink-constrained posture samples."""
        resolved = self.resolve_action(action=action)
        trajectory_result = self.ik_helper.solve_posture_trajectory(
            keyframes=tuple(pose.joint_values for pose in resolved.pose_sequence),
            joint_names=self.schema.BASE_JOINT_NAMES,
            transition_durations=tuple(
                transition.duration_seconds for transition in resolved.transitions
            ),
            target_hold_durations=tuple(
                transition.hold_seconds for transition in resolved.transitions
            ),
            sample_frequency_hz=sample_frequency_hz,
        )
        return ActionTrajectory(
            action_name=action.name,
            robot_model_id=action.robot_model_id,
            joint_names=trajectory_result.joint_names,
            timestamps=trajectory_result.timestamps,
            joint_positions=trajectory_result.joint_positions,
            keyframe_sample_indices=trajectory_result.keyframe_sample_indices,
            source_pose_names=tuple(pose.name for pose in resolved.pose_sequence),
            keyframe_hold_seconds=(0.0,) + tuple(
                transition.hold_seconds for transition in resolved.transitions
            ),
            requested_sample_frequency_hz=(
                trajectory_result.requested_sample_frequency_hz
            ),
            max_tracking_error=trajectory_result.max_tracking_error,
        )

    def save_trajectory(
        self,
        *,
        trajectory: ActionTrajectory,
        overwrite: bool = False,
    ) -> Path:
        """Save a validated trajectory as one self-describing NPZ archive."""
        self._validate_trajectory(trajectory)
        return self.archive_helper.write_npz(
            path=self._trajectory_path(name=trajectory.action_name),
            arrays={
                "schema_version": np.asarray(self.TRAJECTORY_SCHEMA_VERSION, dtype=np.int64),
                "action_name": np.asarray(trajectory.action_name),
                "robot_model_id": np.asarray(trajectory.robot_model_id),
                "fps": np.asarray(
                    trajectory.requested_sample_frequency_hz,
                    dtype=np.float64,
                ),
                "joint_names": np.asarray(trajectory.joint_names),
                "timestamps": trajectory.timestamps,
                "joint_positions": trajectory.joint_positions,
                "keyframe_sample_indices": np.asarray(
                    trajectory.keyframe_sample_indices,
                    dtype=np.int64,
                ),
                "source_pose_names": np.asarray(trajectory.source_pose_names),
                "keyframe_hold_seconds": np.asarray(
                    trajectory.keyframe_hold_seconds,
                    dtype=np.float64,
                ),
                "max_tracking_error": np.asarray(
                    trajectory.max_tracking_error,
                    dtype=np.float64,
                ),
            },
            overwrite=overwrite,
        )

    def load_trajectory(self, *, name: str) -> ActionTrajectory:
        """Load and validate a pickle-free action trajectory NPZ archive."""
        normalized_name = PoseDefinition.validate_name(name)
        path = self._trajectory_path(name=normalized_name)
        arrays = self.archive_helper.read_npz(path=path)
        return self.trajectory_from_arrays(
            arrays=arrays,
            expected_name=normalized_name,
            source_label=str(path),
        )

    def load_trajectory_bytes(
        self,
        *,
        content: bytes,
        source_label: str = "uploaded trajectory archive",
    ) -> ActionTrajectory:
        """Load and validate native trajectory NPZ content held in memory."""
        return self.trajectory_from_arrays(
            arrays=self.archive_helper.read_npz_bytes(content=content),
            source_label=source_label,
        )

    def trajectory_from_arrays(
        self,
        *,
        arrays: dict[str, np.ndarray],
        expected_name: str | None = None,
        source_label: str = "trajectory archive",
    ) -> ActionTrajectory:
        """Build a validated native trajectory from already decoded NPZ arrays."""
        actual_names = set(arrays)
        if "schema_version" not in arrays:
            self._raise_invalid_trajectory_fields(actual_names, self.TRAJECTORY_ARRAY_NAMES)
        schema_version = self._scalar_int(arrays["schema_version"], "schema_version")
        if schema_version == 1:
            expected_names = self.TRAJECTORY_V1_ARRAY_NAMES
        elif schema_version == self.TRAJECTORY_SCHEMA_VERSION:
            expected_names = self.TRAJECTORY_ARRAY_NAMES
        else:
            raise ValueError(f"Unsupported trajectory schema version: {schema_version}")
        if actual_names != expected_names:
            self._raise_invalid_trajectory_fields(actual_names, expected_names)

        keyframe_sample_indices = self._integer_tuple(
            arrays["keyframe_sample_indices"],
            "keyframe_sample_indices",
        )
        keyframe_hold_seconds = (
            tuple(0.0 for _ in keyframe_sample_indices)
            if schema_version == 1
            else self._float_tuple(
                arrays["keyframe_hold_seconds"],
                "keyframe_hold_seconds",
            )
        )

        trajectory = ActionTrajectory(
            action_name=self._scalar_string(arrays["action_name"], "action_name"),
            robot_model_id=self._scalar_string(
                arrays["robot_model_id"],
                "robot_model_id",
            ),
            joint_names=self._string_tuple(arrays["joint_names"], "joint_names"),
            timestamps=self._numeric_array(arrays["timestamps"], "timestamps"),
            joint_positions=self._numeric_array(
                arrays["joint_positions"],
                "joint_positions",
            ),
            keyframe_sample_indices=keyframe_sample_indices,
            source_pose_names=self._string_tuple(
                arrays["source_pose_names"],
                "source_pose_names",
            ),
            keyframe_hold_seconds=keyframe_hold_seconds,
            requested_sample_frequency_hz=self._scalar_float(arrays["fps"], "fps"),
            max_tracking_error=self._scalar_float(
                arrays["max_tracking_error"],
                "max_tracking_error",
            ),
        )
        if expected_name is not None and trajectory.action_name != expected_name:
            raise ValueError(
                f"Trajectory file {source_label} contains a different action name: "
                f"{trajectory.action_name}"
            )
        self._validate_trajectory(trajectory)
        return trajectory

    def list_trajectories(self) -> tuple[str, ...]:
        return tuple(
            path.stem
            for path in self.archive_helper.list_npz_files(
                directory=self.action_trajectory_dir
            )
        )

    def render_trajectory_preview(
        self,
        *,
        trajectory: ActionTrajectory,
        output_path: Path | None = None,
        camera_views: tuple[CameraView, ...] = MujocoPoseHelper.DEFAULT_CAMERA_VIEWS,
        view_width: int = 240,
        view_height: int = 180,
    ) -> Path:
        """Render a validated trajectory as a synchronized multi-camera GIF."""
        self._validate_trajectory(trajectory)
        resolved_output_path = output_path or (
            self.action_preview_dir / f"{trajectory.action_name}.gif"
        )
        return self.action_preview_helper.render_trajectory_gif(
            joint_names=trajectory.joint_names,
            timestamps=trajectory.timestamps,
            joint_positions=trajectory.joint_positions,
            output_path=resolved_output_path,
            camera_views=camera_views,
            view_width=view_width,
            view_height=view_height,
        )

    def render_saved_trajectory_preview(
        self,
        *,
        name: str,
        output_path: Path | None = None,
        camera_views: tuple[CameraView, ...] = MujocoPoseHelper.DEFAULT_CAMERA_VIEWS,
        view_width: int = 240,
        view_height: int = 180,
    ) -> Path:
        """Load a trajectory NPZ, validate it, and render its MuJoCo preview."""
        return self.render_trajectory_preview(
            trajectory=self.load_trajectory(name=name),
            output_path=output_path,
            camera_views=camera_views,
            view_width=view_width,
            view_height=view_height,
        )

    def _validate_action_model(self, action: ActionDefinition) -> None:
        if action.robot_model_id != self.schema.model_id:
            raise ValueError(
                f"Action model {action.robot_model_id} does not match {self.schema.model_id}"
            )

    def _action_path(self, *, name: str) -> Path:
        return self.action_definition_dir / f"{name}.json"

    def _trajectory_path(self, *, name: str) -> Path:
        return self.action_trajectory_dir / f"{name}.npz"

    def _validate_trajectory(self, trajectory: ActionTrajectory) -> None:
        if trajectory.robot_model_id != self.schema.model_id:
            raise ValueError(
                f"Trajectory model {trajectory.robot_model_id} does not match "
                f"{self.schema.model_id}"
            )
        if trajectory.joint_names != self.schema.BASE_JOINT_NAMES:
            raise ValueError("Trajectory joints do not match the canonical G1 upper body")
        if (
            trajectory.source_pose_names[0] != ActionDefinition.BOUNDARY_POSE_NAME
            or trajectory.source_pose_names[-1] != ActionDefinition.BOUNDARY_POSE_NAME
        ):
            raise ValueError("Trajectory must start and end with concierge_init")
        for column, joint_name in enumerate(trajectory.joint_names):
            definition = self.schema.definition(joint_name)
            values = trajectory.joint_positions[:, column]
            if np.any(values < definition.lower_limit) or np.any(
                values > definition.upper_limit
            ):
                raise ValueError(f"Trajectory joint {joint_name} exceeds its limits")

    def _scalar_string(self, array: np.ndarray, name: str) -> str:
        if array.shape != () or array.dtype.kind != "U":
            raise ValueError(f"Trajectory field {name} must be a Unicode string scalar")
        return str(array.item())

    def _raise_invalid_trajectory_fields(
        self,
        actual_names: set[str],
        expected_names: frozenset[str],
    ) -> None:
        missing = sorted(expected_names - actual_names)
        unknown = sorted(actual_names - expected_names)
        raise ValueError(
            f"Invalid trajectory archive fields: missing={missing}, unknown={unknown}"
        )

    def _scalar_int(self, array: np.ndarray, name: str) -> int:
        if array.shape != () or array.dtype.kind not in "iu":
            raise ValueError(f"Trajectory field {name} must be an integer scalar")
        return int(array.item())

    def _scalar_float(self, array: np.ndarray, name: str) -> float:
        if array.shape != () or array.dtype.kind not in "fiu":
            raise ValueError(f"Trajectory field {name} must be a numeric scalar")
        return float(array.item())

    def _string_tuple(self, array: np.ndarray, name: str) -> tuple[str, ...]:
        if array.ndim != 1 or array.dtype.kind != "U":
            raise ValueError(f"Trajectory field {name} must be a Unicode string array")
        return tuple(str(value) for value in array)

    def _integer_tuple(self, array: np.ndarray, name: str) -> tuple[int, ...]:
        if array.ndim != 1 or array.dtype.kind not in "iu":
            raise ValueError(f"Trajectory field {name} must be an integer array")
        return tuple(int(value) for value in array)

    def _float_tuple(self, array: np.ndarray, name: str) -> tuple[float, ...]:
        numeric_array = self._numeric_array(array, name)
        if numeric_array.ndim != 1:
            raise ValueError(f"Trajectory field {name} must be a numeric array")
        return tuple(float(value) for value in numeric_array)

    def _numeric_array(self, array: np.ndarray, name: str) -> np.ndarray:
        if array.dtype.kind not in "fiu":
            raise ValueError(f"Trajectory field {name} must be a numeric array")
        return np.asarray(array, dtype=np.float64)


def demo_action_service() -> None:
    logging.basicConfig(level=logging.INFO)
    settings = AppSettings()
    asset_helper = G1AssetHelper(asset_dir=settings.g1_asset_dir)
    schema = G1JointSchema(asset_helper=asset_helper)
    file_helper = PoseFileHelper()
    pose_service = PoseService(
        schema=schema,
        pose_dir=settings.pose_dir,
        file_helper=file_helper,
        simulation_helper=MujocoPoseHelper(mjcf_path=asset_helper.mjcf_path),
    )
    action_preview_helper = MujocoActionHelper(
        pose_helper=pose_service.simulation_helper
    )
    with tempfile.TemporaryDirectory() as temporary_directory:
        service = ActionService(
            schema=schema,
            action_definition_dir=Path(temporary_directory),
            file_helper=file_helper,
            pose_service=pose_service,
            ik_helper=PinkIKHelper(urdf_path=asset_helper.urdf_path),
            action_trajectory_dir=Path(temporary_directory) / "trajectories",
            archive_helper=NumpyArchiveHelper(),
            action_preview_helper=action_preview_helper,
            action_preview_dir=settings.action_preview_dir,
        )
        action = service.create_action(
            name="concierge_presentation_demo",
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
                    target_pose=ActionPoseReference(PoseType.BASE, "concierge_init"),
                    duration_seconds=1.5,
                ),
            ),
        )
        saved_path = service.save_action(action=action)
        resolved = service.resolve_action(action=service.load_action(name=action.name))
        trajectory = service.generate_trajectory(action=action)
        trajectory_path = service.save_trajectory(trajectory=trajectory)
        LOGGER.info(
            "Saved and resolved %s with pose sequence %s",
            saved_path,
            [pose.name for pose in resolved.pose_sequence],
        )
        LOGGER.info(
            "Generated %d Pink trajectory samples over %.1f seconds",
            trajectory.sample_count,
            trajectory.duration_seconds,
        )
        LOGGER.info("Saved and reloaded trajectory: %s", trajectory_path)
        preview_path = service.render_saved_trajectory_preview(name=action.name)
        LOGGER.info("Rendered saved trajectory preview: %s", preview_path)


def main() -> None:
    demo_action_service()


if __name__ == "__main__":
    main()
