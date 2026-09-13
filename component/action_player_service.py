"""Normalize uploaded motion files into safe two-arm simulation trajectories."""

from __future__ import annotations

import math
import threading
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

import numpy as np
from numpy.typing import NDArray

from component.action_playback_service import (
    ActionPlayback,
    ActionPlaybackSnapshot,
    ActionPlaybackSource,
    ActionPlaybackState,
)
from component.action_service import ActionService
from component.common.action_models import ActionTrajectory
from component.common.g1_joint_schema import G1JointSchema, PoseType
from component.common.models import PoseDefinition
from component.pose_service import PoseService
from util.ardy_action_helper import ArdyActionHelper
from util.g1_motion_conversion_helper import ConvertedArmMotion
from util.kimodo_action_helper import KimodoActionHelper


class ActionFileFormat(str, Enum):
    """Supported uploaded motion containers."""

    NATIVE_NPZ = "native_npz"
    KIMODO_NPZ = "kimodo_npz"
    ARDY_PKL = "ardy_pkl"


@dataclass(frozen=True, slots=True)
class LoadedAction:
    """One normalized action and the source details shown by the player UI."""

    trajectory: ActionTrajectory
    source_format: ActionFileFormat | None
    source_filename: str
    source_joint_count: int
    warnings: tuple[str, ...]

    @property
    def arm_joint_count(self) -> int:
        return len(self.trajectory.joint_names)


@dataclass(frozen=True, slots=True)
class CapturedActionPose:
    """One arm pose captured from an exact paused trajectory sample."""

    pose: PoseDefinition
    action_name: str
    sample_index: int
    sample_count: int
    timestamp_seconds: float


class ActionPlayerService:
    """Import, select, and play one normalized two-arm action."""

    MAX_UPLOAD_BYTES = 128 * 1024 * 1024
    DEFAULT_BOUNDARY_SECONDS = 1.0

    def __init__(
        self,
        *,
        schema: G1JointSchema,
        initial_pose: PoseDefinition,
        action_service: ActionService,
        playback: ActionPlayback,
        pose_service: PoseService,
        kimodo_helper: KimodoActionHelper,
        ardy_helper: ArdyActionHelper,
    ) -> None:
        self.schema = schema
        self.initial_pose = initial_pose
        self.action_service = action_service
        self._playback = playback
        self.pose_service = pose_service
        self.kimodo_helper = kimodo_helper
        self.ardy_helper = ardy_helper
        self._lock = threading.Lock()
        self._loaded: LoadedAction | None = None

    def load(
        self,
        *,
        source_format: ActionFileFormat,
        filename: str,
        content: bytes,
        action_name: str | None = None,
        source_fps: float | None = None,
    ) -> LoadedAction:
        """Decode, normalize, validate, and retain one uploaded action."""
        if not isinstance(source_format, ActionFileFormat):
            raise ValueError("Select a supported action file format")
        self._require_inactive_playback()
        safe_filename = self._validate_upload(
            source_format=source_format,
            filename=filename,
            content=content,
        )
        if source_format is ActionFileFormat.NATIVE_NPZ:
            loaded = self._load_native(
                filename=safe_filename,
                content=content,
                action_name=action_name,
            )
        else:
            converted = (
                self.kimodo_helper.load(content=content, source_fps=source_fps)
                if source_format is ActionFileFormat.KIMODO_NPZ
                else self.ardy_helper.load(content=content)
            )
            normalized_name = PoseDefinition.validate_name(
                action_name if action_name and action_name.strip() else Path(safe_filename).stem
            )
            self._validate_arm_positions(converted.joint_positions)
            trajectory = self._add_concierge_boundaries(
                action_name=normalized_name,
                motion=converted,
            )
            loaded = LoadedAction(
                trajectory=trajectory,
                source_format=source_format,
                source_filename=safe_filename,
                source_joint_count=converted.source_joint_count,
                warnings=(
                    "Root, leg, and source waist motion were discarded.",
                    "The waist uses base/concierge_init during playback.",
                ),
            )
        with self._lock:
            self._loaded = loaded
        self._playback.load(
            trajectory=loaded.trajectory,
            source=ActionPlaybackSource.UPLOADED,
        )
        return loaded

    def load_saved(self, *, name: str) -> LoadedAction:
        """Load one compiled native trajectory for Action Composer playback."""
        self._require_inactive_playback()
        source = self.action_service.load_trajectory(name=name)
        loaded = self._normalize_native(
            source=source,
            filename=f"{source.action_name}.npz",
            action_name=source.action_name,
            source_format=None,
            warnings=(
                "Compiled waist samples are ignored; base/concierge_init owns the waist.",
            ),
        )
        with self._lock:
            self._loaded = loaded
        self._playback.load(
            trajectory=loaded.trajectory,
            source=ActionPlaybackSource.COMPILED,
        )
        return loaded

    def current(self) -> LoadedAction | None:
        with self._lock:
            return self._loaded

    def require_current(self) -> LoadedAction:
        loaded = self.current()
        if loaded is None:
            raise ValueError("Load an action file before playback")
        return loaded

    def seek(self, *, sample_index: int) -> ActionPlaybackSnapshot:
        """Preview one exact sample of the currently loaded paused action."""
        self.require_current()
        return self._playback.seek(sample_index=sample_index)

    def play(self, *, loop: bool = False) -> ActionPlaybackSnapshot:
        """Start the currently loaded action in the shared playback engine."""
        self.require_current()
        return self._playback.play(loop=loop)

    def pause(self) -> ActionPlaybackSnapshot:
        """Pause the selected action at its current sample."""
        self.require_current()
        return self._playback.pause()

    def resume(self) -> ActionPlaybackSnapshot:
        """Resume the selected action from its current sample."""
        self.require_current()
        return self._playback.resume()

    def stop(self) -> ActionPlaybackSnapshot:
        """Stop the selected action and restore its first sample."""
        self.require_current()
        return self._playback.stop()

    def set_loop(self, *, enabled: bool) -> ActionPlaybackSnapshot:
        """Set loop mode for the selected action."""
        self.require_current()
        return self._playback.set_loop(enabled=enabled)

    def snapshot(self) -> ActionPlaybackSnapshot:
        return self._playback.snapshot()

    def wait_for_revision(
        self,
        *,
        after_revision: int,
        timeout: float,
    ) -> ActionPlaybackSnapshot:
        return self._playback.wait_for_revision(
            after_revision=after_revision,
            timeout=timeout,
        )

    def close(self) -> None:
        self._playback.close()

    def save_paused_arm_pose(
        self,
        *,
        pose_type: PoseType,
        name: str,
        notes: str = "",
        overwrite: bool = False,
    ) -> CapturedActionPose:
        """Persist one arm from the exact sample selected during paused playback."""
        if pose_type not in (PoseType.LEFT_ARM, PoseType.RIGHT_ARM):
            raise ValueError("Action Player can record only left-arm or right-arm poses")
        loaded = self.require_current()
        trajectory = loaded.trajectory
        sample_index = self._playback.paused_sample_index()
        sample = trajectory.joint_values_at(sample_index)
        timestamp_seconds = float(trajectory.timestamps[sample_index])
        capture_note = (
            f"Captured from Action Player action {trajectory.action_name!r}, "
            f"sample {sample_index + 1}/{trajectory.sample_count} at "
            f"{timestamp_seconds:.6f} seconds."
        )
        normalized_notes = notes.strip()
        pose = self.pose_service.create_simulated_pose(
            name=name,
            pose_type=pose_type,
            joint_values={
                joint_name: sample[joint_name]
                for joint_name in self.schema.joint_names(pose_type)
            },
            notes=(
                f"{normalized_notes} {capture_note}"
                if normalized_notes
                else capture_note
            ),
        )
        self.pose_service.save_pose(pose=pose, overwrite=overwrite)
        return CapturedActionPose(
            pose=pose,
            action_name=trajectory.action_name,
            sample_index=sample_index,
            sample_count=trajectory.sample_count,
            timestamp_seconds=timestamp_seconds,
        )

    def _require_inactive_playback(self) -> None:
        if self._playback.snapshot().state in (
            ActionPlaybackState.PLAYING,
            ActionPlaybackState.PAUSED,
        ):
            raise ValueError("Stop the current action before loading another file")

    def _load_native(
        self,
        *,
        filename: str,
        content: bytes,
        action_name: str | None,
    ) -> LoadedAction:
        source = self.action_service.load_trajectory_bytes(
            content=content,
            source_label=filename,
        )
        return self._normalize_native(
            source=source,
            filename=filename,
            action_name=action_name,
            source_format=ActionFileFormat.NATIVE_NPZ,
            warnings=(
                "Native waist samples were discarded; base/concierge_init owns the waist.",
            ),
        )

    def _normalize_native(
        self,
        *,
        source: ActionTrajectory,
        filename: str,
        action_name: str | None,
        source_format: ActionFileFormat | None,
        warnings: tuple[str, ...],
    ) -> LoadedAction:
        indices = [source.joint_names.index(name) for name in self.schema.ARM_JOINT_NAMES]
        joint_positions = source.joint_positions[:, indices]
        self._validate_arm_positions(joint_positions)
        normalized_name = PoseDefinition.validate_name(
            action_name if action_name and action_name.strip() else source.action_name
        )
        trajectory = ActionTrajectory(
            action_name=normalized_name,
            robot_model_id=source.robot_model_id,
            joint_names=self.schema.ARM_JOINT_NAMES,
            timestamps=source.timestamps,
            joint_positions=joint_positions,
            keyframe_sample_indices=source.keyframe_sample_indices,
            source_pose_names=source.source_pose_names,
            keyframe_hold_seconds=source.keyframe_hold_seconds,
            requested_sample_frequency_hz=source.requested_sample_frequency_hz,
            max_tracking_error=source.max_tracking_error,
        )
        return LoadedAction(
            trajectory=trajectory,
            source_format=source_format,
            source_filename=filename,
            source_joint_count=len(source.joint_names),
            warnings=warnings,
        )

    def _add_concierge_boundaries(
        self,
        *,
        action_name: str,
        motion: ConvertedArmMotion,
    ) -> ActionTrajectory:
        source_positions = np.asarray(motion.joint_positions, dtype=np.float64)
        fps = motion.frames_per_second
        interval_count = max(1, int(math.ceil(self.DEFAULT_BOUNDARY_SECONDS * fps)))
        concierge = np.asarray(
            [self.initial_pose.joint_values[name] for name in self.schema.ARM_JOINT_NAMES],
            dtype=np.float64,
        )
        phase = np.linspace(0.0, 1.0, interval_count + 1, dtype=np.float64)
        blend = phase**3 * (phase * (phase * 6.0 - 15.0) + 10.0)
        entry = concierge + blend[:, None] * (source_positions[0] - concierge)
        exit_positions = source_positions[-1] + blend[1:, None] * (
            concierge - source_positions[-1]
        )
        positions = np.concatenate(
            (entry, source_positions[1:], exit_positions),
            axis=0,
        )
        timestamps = np.arange(len(positions), dtype=np.float64) / fps
        source_start_index = interval_count
        source_end_index = source_start_index + len(source_positions) - 1
        return ActionTrajectory(
            action_name=action_name,
            robot_model_id=self.schema.model_id,
            joint_names=self.schema.ARM_JOINT_NAMES,
            timestamps=timestamps,
            joint_positions=positions,
            keyframe_sample_indices=(
                0,
                source_start_index,
                source_end_index,
                len(positions) - 1,
            ),
            source_pose_names=(
                "concierge_init",
                "imported_start",
                "imported_end",
                "concierge_init",
            ),
            keyframe_hold_seconds=(0.0, 0.0, 0.0, 0.0),
            requested_sample_frequency_hz=fps,
            max_tracking_error=0.0,
        )

    def _validate_arm_positions(self, positions: NDArray[np.float64]) -> None:
        values = np.asarray(positions, dtype=np.float64)
        expected_shape = (len(self.schema.ARM_JOINT_NAMES),)
        if values.ndim != 2 or values.shape[1:] != expected_shape or len(values) < 2:
            raise ValueError(
                "Imported arm positions must have shape [at least 2 frames, 14 joints]"
            )
        if not np.all(np.isfinite(values)):
            raise ValueError("Imported arm positions must contain only finite values")
        for column, joint_name in enumerate(self.schema.ARM_JOINT_NAMES):
            definition = self.schema.definition(joint_name)
            below = values[:, column] < definition.lower_limit
            above = values[:, column] > definition.upper_limit
            if np.any(below | above):
                frame = int(np.flatnonzero(below | above)[0])
                raise ValueError(
                    f"Imported {joint_name} at frame {frame} is outside "
                    f"[{definition.lower_limit}, {definition.upper_limit}]"
                )

    def _validate_upload(
        self,
        *,
        source_format: ActionFileFormat,
        filename: str,
        content: bytes,
    ) -> str:
        if not isinstance(filename, str) or not filename.strip():
            raise ValueError("Uploaded file must have a name")
        normalized = Path(filename.strip()).name
        if normalized != filename.strip():
            raise ValueError("Uploaded file name cannot contain a directory")
        expected_suffix = (
            ".pkl" if source_format is ActionFileFormat.ARDY_PKL else ".npz"
        )
        if Path(normalized).suffix.lower() != expected_suffix:
            raise ValueError(
                f"{source_format.value} files must end with {expected_suffix}"
            )
        if not content:
            raise ValueError("Uploaded action file is empty")
        if len(content) > self.MAX_UPLOAD_BYTES:
            raise ValueError(
                f"Uploaded action file exceeds {self.MAX_UPLOAD_BYTES // (1024 * 1024)} MiB"
            )
        return normalized
