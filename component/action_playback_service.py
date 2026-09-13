"""Play validated action trajectories into the shared MuJoCo simulation."""

from __future__ import annotations

import math
import threading
import time
from dataclasses import dataclass
from enum import Enum

from component.common.action_models import ActionTrajectory
from component.simulation import SimulationService


class ActionPlaybackState(str, Enum):
    """Lifecycle states exposed to playback clients."""

    IDLE = "idle"
    PLAYING = "playing"
    PAUSED = "paused"
    STOPPED = "stopped"
    COMPLETED = "completed"
    FAILED = "failed"


class ActionPlaybackPhase(str, Enum):
    """Semantic position inside the trajectory keyframe sequence."""

    NONE = "none"
    KEYFRAME = "keyframe"
    TRANSITION = "transition"
    HOLD = "hold"


@dataclass(frozen=True, slots=True)
class ActionPlaybackSnapshot:
    """Immutable playback status for UI and API transports."""

    revision: int
    state: ActionPlaybackState
    action_name: str | None
    sample_index: int
    sample_count: int
    elapsed_seconds: float
    duration_seconds: float
    loop: bool
    phase: ActionPlaybackPhase
    from_pose_name: str | None
    target_pose_name: str | None
    keyframe_index: int
    keyframe_count: int
    error: str | None = None

    @property
    def progress(self) -> float:
        if self.duration_seconds <= 0.0:
            return 0.0
        return min(1.0, max(0.0, self.elapsed_seconds / self.duration_seconds))


class ActionPlaybackService:
    """Own one interruptible trajectory player for the shared simulation."""

    def __init__(self, *, simulation: SimulationService) -> None:
        self.simulation = simulation
        self._command_lock = threading.Lock()
        self._condition = threading.Condition()
        self._generation = 0
        self._revision = 0
        self._state = ActionPlaybackState.IDLE
        self._trajectory: ActionTrajectory | None = None
        self._sample_index = 0
        self._elapsed_seconds = 0.0
        self._loop = False
        self._error: str | None = None
        self._thread: threading.Thread | None = None

    def play(
        self,
        *,
        trajectory: ActionTrajectory,
        loop: bool = False,
    ) -> ActionPlaybackSnapshot:
        """Start a trajectory from its first sample, replacing any current run."""
        if not isinstance(trajectory, ActionTrajectory):
            raise ValueError("Playback requires a validated ActionTrajectory")
        with self._command_lock:
            self._cancel_worker()
            self.simulation.update_joint_positions(trajectory.joint_values_at(0))
            with self._condition:
                self._generation += 1
                generation = self._generation
                self._trajectory = trajectory
                self._sample_index = 0
                self._elapsed_seconds = 0.0
                self._loop = bool(loop)
                self._error = None
                self._state = ActionPlaybackState.PLAYING
                self._revision += 1
                thread = threading.Thread(
                    target=self._run,
                    args=(trajectory, generation),
                    name=f"action-playback-{trajectory.action_name}",
                    daemon=True,
                )
                self._thread = thread
                snapshot = self._snapshot_unlocked()
                self._condition.notify_all()
            thread.start()
            return snapshot

    def pause(self) -> ActionPlaybackSnapshot:
        """Pause the current playback without changing its simulated pose."""
        with self._condition:
            if self._state is not ActionPlaybackState.PLAYING:
                raise ValueError("Only a playing action can be paused")
            self._state = ActionPlaybackState.PAUSED
            self._revision += 1
            self._condition.notify_all()
            return self._snapshot_unlocked()

    def resume(self) -> ActionPlaybackSnapshot:
        """Continue a paused playback from its current sample."""
        with self._condition:
            if self._state is not ActionPlaybackState.PAUSED:
                raise ValueError("Only a paused action can be resumed")
            self._state = ActionPlaybackState.PLAYING
            self._revision += 1
            self._condition.notify_all()
            return self._snapshot_unlocked()

    def stop(self) -> ActionPlaybackSnapshot:
        """Stop playback and return the simulation to the first trajectory sample."""
        with self._command_lock:
            self._cancel_worker()
            with self._condition:
                trajectory = self._trajectory
            if trajectory is not None:
                self.simulation.update_joint_positions(trajectory.joint_values_at(0))
            with self._condition:
                self._sample_index = 0
                self._elapsed_seconds = 0.0
                self._state = ActionPlaybackState.STOPPED
                self._error = None
                self._revision += 1
                self._condition.notify_all()
                return self._snapshot_unlocked()

    def set_loop(self, *, enabled: bool) -> ActionPlaybackSnapshot:
        """Update whether the current trajectory restarts after its last sample."""
        with self._condition:
            self._loop = bool(enabled)
            self._revision += 1
            self._condition.notify_all()
            return self._snapshot_unlocked()

    def snapshot(self) -> ActionPlaybackSnapshot:
        with self._condition:
            return self._snapshot_unlocked()

    def wait_for_revision(
        self,
        *,
        after_revision: int,
        timeout: float,
    ) -> ActionPlaybackSnapshot:
        with self._condition:
            self._condition.wait_for(
                lambda: self._revision > after_revision,
                timeout=timeout,
            )
            return self._snapshot_unlocked()

    def close(self) -> None:
        """Stop the worker without changing the simulation during app shutdown."""
        with self._command_lock:
            self._cancel_worker()
            with self._condition:
                self._state = ActionPlaybackState.IDLE
                self._trajectory = None
                self._sample_index = 0
                self._elapsed_seconds = 0.0
                self._loop = False
                self._error = None
                self._revision += 1
                self._condition.notify_all()

    def _cancel_worker(self) -> None:
        with self._condition:
            self._generation += 1
            thread = self._thread
            self._thread = None
            self._condition.notify_all()
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=2.0)

    def _run(self, trajectory: ActionTrajectory, generation: int) -> None:
        cycle_started_at = time.monotonic()
        sample_index = 1
        while True:
            with self._condition:
                if generation != self._generation:
                    return
                if self._state is ActionPlaybackState.PAUSED:
                    paused_at = time.monotonic()
                    self._condition.wait_for(
                        lambda: generation != self._generation
                        or self._state is not ActionPlaybackState.PAUSED
                    )
                    cycle_started_at += time.monotonic() - paused_at
                    continue
                if self._state is not ActionPlaybackState.PLAYING:
                    return

                target_time = cycle_started_at + float(
                    trajectory.timestamps[sample_index]
                )
                remaining = target_time - time.monotonic()
                if remaining > 0.0:
                    self._condition.wait(timeout=remaining)
                    continue

                try:
                    self.simulation.update_joint_positions(
                        trajectory.joint_values_at(sample_index)
                    )
                except Exception as error:
                    self._state = ActionPlaybackState.FAILED
                    self._error = str(error)
                    self._thread = None
                    self._revision += 1
                    self._condition.notify_all()
                    return

                self._sample_index = sample_index
                self._elapsed_seconds = float(trajectory.timestamps[sample_index])
                self._revision += 1
                self._condition.notify_all()

                if sample_index < trajectory.sample_count - 1:
                    sample_index += 1
                    continue
                if not self._loop:
                    self._state = ActionPlaybackState.COMPLETED
                    self._thread = None
                    self._revision += 1
                    self._condition.notify_all()
                    return

                self.simulation.update_joint_positions(trajectory.joint_values_at(0))
                self._sample_index = 0
                self._elapsed_seconds = 0.0
                self._revision += 1
                self._condition.notify_all()
                cycle_started_at = time.monotonic()
                sample_index = 1

    def _snapshot_unlocked(self) -> ActionPlaybackSnapshot:
        trajectory = self._trajectory
        (
            phase,
            from_pose_name,
            target_pose_name,
            keyframe_index,
            keyframe_count,
        ) = self._keyframe_context(trajectory)
        return ActionPlaybackSnapshot(
            revision=self._revision,
            state=self._state,
            action_name=trajectory.action_name if trajectory is not None else None,
            sample_index=self._sample_index,
            sample_count=trajectory.sample_count if trajectory is not None else 0,
            elapsed_seconds=self._elapsed_seconds,
            duration_seconds=(
                trajectory.duration_seconds if trajectory is not None else 0.0
            ),
            loop=self._loop,
            phase=phase,
            from_pose_name=from_pose_name,
            target_pose_name=target_pose_name,
            keyframe_index=keyframe_index,
            keyframe_count=keyframe_count,
            error=self._error,
        )

    def _keyframe_context(
        self,
        trajectory: ActionTrajectory | None,
    ) -> tuple[ActionPlaybackPhase, str | None, str | None, int, int]:
        if trajectory is None:
            return ActionPlaybackPhase.NONE, None, None, 0, 0

        names = trajectory.source_pose_names
        indices = trajectory.keyframe_sample_indices
        holds = trajectory.keyframe_hold_seconds
        keyframe_count = len(names)
        arrivals = [float(trajectory.timestamps[index]) for index in indices]
        if holds[-1] > 0.0:
            arrivals[-1] -= holds[-1]
        elapsed = self._elapsed_seconds
        tolerance = 1e-9

        for keyframe_index, (name, arrival, hold) in enumerate(
            zip(names, arrivals, holds, strict=True)
        ):
            if keyframe_index == 0 and math.isclose(
                elapsed,
                arrival,
                abs_tol=tolerance,
            ):
                return (
                    ActionPlaybackPhase.KEYFRAME,
                    name,
                    name,
                    keyframe_index,
                    keyframe_count,
                )
            if elapsed < arrival - tolerance:
                previous_name = names[keyframe_index - 1]
                previous_hold_end = (
                    arrivals[keyframe_index - 1] + holds[keyframe_index - 1]
                )
                if elapsed <= previous_hold_end + tolerance:
                    return (
                        ActionPlaybackPhase.HOLD,
                        previous_name,
                        previous_name,
                        keyframe_index - 1,
                        keyframe_count,
                    )
                return (
                    ActionPlaybackPhase.TRANSITION,
                    previous_name,
                    name,
                    keyframe_index,
                    keyframe_count,
                )
            if elapsed <= arrival + hold + tolerance:
                phase = (
                    ActionPlaybackPhase.HOLD
                    if hold > 0.0 and elapsed > arrival + tolerance
                    else ActionPlaybackPhase.KEYFRAME
                )
                return phase, name, name, keyframe_index, keyframe_count

        final_index = keyframe_count - 1
        return (
            ActionPlaybackPhase.KEYFRAME,
            names[-1],
            names[-1],
            final_index,
            keyframe_count,
        )
