"""Load the G1 URDF and solve bounded frame targets with Pink."""

from __future__ import annotations

import logging
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from numbers import Real
from pathlib import Path
from types import MappingProxyType

import numpy as np
import pink
import pinocchio as pin
from numpy.typing import NDArray
from pink.tasks import FrameTask, PostureTask
from qpsolvers import available_solvers

from config.settings import AppSettings
from util.mujoco_pose_helper import MujocoPoseHelper

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class FramePose:
    """One frame transform expressed in the fixed world frame."""

    translation: tuple[float, float, float]
    rotation: tuple[tuple[float, float, float], ...]


@dataclass(frozen=True, slots=True)
class PinkIKResult:
    """Result and convergence evidence from one differential IK solve."""

    joint_values: Mapping[str, float]
    iterations: int
    converged: bool
    initial_position_error: float
    final_position_error: float
    initial_orientation_error: float
    final_orientation_error: float

    def __post_init__(self) -> None:
        object.__setattr__(self, "joint_values", MappingProxyType(dict(self.joint_values)))


@dataclass(frozen=True, slots=True)
class PinkPostureTrajectoryResult:
    """Time samples produced by Pink while tracking smooth posture references."""

    joint_names: tuple[str, ...]
    timestamps: NDArray[np.float64]
    joint_positions: NDArray[np.float64]
    keyframe_sample_indices: tuple[int, ...]
    requested_sample_frequency_hz: float
    max_tracking_error: float

    def __post_init__(self) -> None:
        timestamps = np.asarray(self.timestamps, dtype=np.float64).copy()
        joint_positions = np.asarray(self.joint_positions, dtype=np.float64).copy()
        timestamps.setflags(write=False)
        joint_positions.setflags(write=False)
        object.__setattr__(self, "timestamps", timestamps)
        object.__setattr__(self, "joint_positions", joint_positions)


class PinkIKHelper:
    """Adapt a fixed-base scalar-joint URDF to Pink differential IK.

    A reduced Pinocchio model is built for each solve. Joints not listed in
    ``active_joint_names`` are fixed at the supplied reference values, which
    prevents the legs, waist, or opposite arm from drifting unexpectedly.
    """

    def __init__(self, *, urdf_path: Path, solver: str = "quadprog") -> None:
        if not urdf_path.is_file():
            raise FileNotFoundError(f"G1 URDF does not exist: {urdf_path}")
        if solver not in available_solvers:
            raise ValueError(
                f"Pink QP solver {solver!r} is unavailable; available={available_solvers}"
            )

        self.urdf_path = urdf_path
        self.solver = solver
        self._model = pin.buildModelFromUrdf(str(urdf_path))
        self._joint_names = tuple(str(name) for name in self._model.names[1:])
        self._joint_name_set = set(self._joint_names)
        self._validate_scalar_joint_model()

    @property
    def joint_names(self) -> tuple[str, ...]:
        return self._joint_names

    @property
    def frame_names(self) -> tuple[str, ...]:
        return tuple(str(frame.name) for frame in self._model.frames)

    def frame_pose(
        self,
        *,
        joint_values: Mapping[str, object],
        frame_name: str,
    ) -> FramePose:
        """Run forward kinematics and return a named frame's world pose."""
        self._validate_frame_name(frame_name)
        configuration_values = self._configuration_values(joint_values)
        data = self._model.createData()
        pin.forwardKinematics(self._model, data, configuration_values)
        pin.updateFramePlacements(self._model, data)
        transform = data.oMf[self._model.getFrameId(frame_name)]
        return self._to_frame_pose(transform)

    def solve_frame_target(
        self,
        *,
        joint_values: Mapping[str, object],
        active_joint_names: Sequence[str],
        frame_name: str,
        target_translation: Sequence[float],
        target_rotation: Sequence[Sequence[float]] | None = None,
        dt: float = 0.01,
        max_iterations: int = 300,
        position_tolerance: float = 1e-4,
        orientation_tolerance: float = 1e-4,
        posture_cost: float = 1e-3,
    ) -> PinkIKResult:
        """Solve a frame target while fixing every joint outside the active set."""
        self._validate_solve_options(
            dt=dt,
            max_iterations=max_iterations,
            position_tolerance=position_tolerance,
            orientation_tolerance=orientation_tolerance,
            posture_cost=posture_cost,
        )
        self._validate_frame_name(frame_name)
        active_names = self._validate_active_joint_names(active_joint_names, joint_values)
        full_reference = self._configuration_values(joint_values)
        reduced_model, reduced_values = self._build_reduced_model(
            active_joint_names=active_names,
            full_reference=full_reference,
        )
        configuration = pink.Configuration(
            reduced_model,
            reduced_model.createData(),
            reduced_values,
        )

        initial_transform = configuration.get_transform_frame_to_world(frame_name)
        translation = self._translation_vector(target_translation)
        rotation = self._rotation_matrix(target_rotation, initial_transform.rotation)
        target_transform = pin.SE3(rotation, translation)

        frame_task = FrameTask(
            frame_name,
            position_cost=1.0,
            orientation_cost=1.0,
            gain=0.5,
        )
        frame_task.set_target(target_transform)
        posture_task = PostureTask(cost=float(posture_cost))
        posture_task.set_target(configuration.q)

        initial_position_error, initial_orientation_error = self._frame_errors(
            initial_transform,
            target_transform,
        )
        final_position_error = initial_position_error
        final_orientation_error = initial_orientation_error
        iterations = 0
        converged = self._within_tolerance(
            position_error=final_position_error,
            orientation_error=final_orientation_error,
            position_tolerance=position_tolerance,
            orientation_tolerance=orientation_tolerance,
        )

        while not converged and iterations < max_iterations:
            velocity = pink.solve_ik(
                configuration,
                [frame_task, posture_task],
                dt,
                solver=self.solver,
            )
            configuration.integrate_inplace(velocity, dt)
            iterations += 1
            final_transform = configuration.get_transform_frame_to_world(frame_name)
            final_position_error, final_orientation_error = self._frame_errors(
                final_transform,
                target_transform,
            )
            converged = self._within_tolerance(
                position_error=final_position_error,
                orientation_error=final_orientation_error,
                position_tolerance=position_tolerance,
                orientation_tolerance=orientation_tolerance,
            )

        solved_values = {
            joint_name: float(value) for joint_name, value in joint_values.items()
        }
        for joint_name in active_names:
            reduced_joint = reduced_model.joints[reduced_model.getJointId(joint_name)]
            solved_values[joint_name] = float(configuration.q[reduced_joint.idx_q])

        return PinkIKResult(
            joint_values=solved_values,
            iterations=iterations,
            converged=converged,
            initial_position_error=initial_position_error,
            final_position_error=final_position_error,
            initial_orientation_error=initial_orientation_error,
            final_orientation_error=final_orientation_error,
        )

    def solve_posture_trajectory(
        self,
        *,
        keyframes: Sequence[Mapping[str, object]],
        joint_names: Sequence[str],
        transition_durations: Sequence[float],
        target_hold_durations: Sequence[float] | None = None,
        sample_frequency_hz: float = 25.0,
        endpoint_tolerance: float = 1e-8,
    ) -> PinkPostureTrajectoryResult:
        """Track minimum-jerk posture references with Pink at each time sample."""
        active_names, durations, holds, frequency, tolerance = (
            self._validate_trajectory_inputs(
                keyframes=keyframes,
                joint_names=joint_names,
                transition_durations=transition_durations,
                target_hold_durations=target_hold_durations,
                sample_frequency_hz=sample_frequency_hz,
                endpoint_tolerance=endpoint_tolerance,
            )
        )
        full_keyframes = [self._configuration_values(keyframe) for keyframe in keyframes]
        reduced_model, initial_values = self._build_reduced_model(
            active_joint_names=active_names,
            full_reference=full_keyframes[0],
        )
        reduced_indices = tuple(
            reduced_model.joints[reduced_model.getJointId(joint_name)].idx_q
            for joint_name in active_names
        )

        def reduced_keyframe(full_values: np.ndarray) -> np.ndarray:
            values = pin.neutral(reduced_model)
            for joint_name, reduced_index in zip(
                active_names,
                reduced_indices,
                strict=True,
            ):
                full_joint = self._model.joints[self._model.getJointId(joint_name)]
                values[reduced_index] = full_values[full_joint.idx_q]
            return values

        reduced_keyframes = [reduced_keyframe(values) for values in full_keyframes]
        configuration = pink.Configuration(
            reduced_model,
            reduced_model.createData(),
            initial_values,
        )
        posture_task = PostureTask(cost=1.0, gain=1.0)
        timestamps = [0.0]
        joint_positions = [
            np.asarray([configuration.q[index] for index in reduced_indices], dtype=float)
        ]
        keyframe_sample_indices = [0]
        elapsed_time = 0.0
        max_tracking_error = 0.0

        for transition_index, (duration, hold_duration) in enumerate(
            zip(durations, holds, strict=True)
        ):
            start_values = reduced_keyframes[transition_index]
            target_values = reduced_keyframes[transition_index + 1]
            interval_count = max(1, math.ceil(duration * frequency))
            local_times = np.linspace(0.0, duration, interval_count + 1)
            previous_local_time = 0.0
            for local_time in local_times[1:]:
                phase = float(local_time / duration)
                blend = self._minimum_jerk_blend(phase)
                desired_values = start_values + blend * (target_values - start_values)
                posture_task.set_target(desired_values)
                sample_dt = float(local_time - previous_local_time)
                velocity = pink.solve_ik(
                    configuration,
                    [posture_task],
                    sample_dt,
                    solver=self.solver,
                )
                configuration.integrate_inplace(velocity, sample_dt)
                tracking_error = float(
                    np.max(np.abs(configuration.q - desired_values), initial=0.0)
                )
                max_tracking_error = max(max_tracking_error, tracking_error)
                timestamps.append(elapsed_time + float(local_time))
                joint_positions.append(
                    np.asarray(
                        [configuration.q[index] for index in reduced_indices],
                        dtype=float,
                    )
                )
                previous_local_time = float(local_time)

            endpoint_error = float(
                np.max(np.abs(configuration.q - target_values), initial=0.0)
            )
            if endpoint_error > tolerance:
                raise ValueError(
                    f"Transition {transition_index} cannot reach its target within "
                    f"{duration} seconds; maximum joint error is {endpoint_error:.6f} rad"
                )
            elapsed_time += duration
            timestamps[-1] = elapsed_time
            arrival_sample_index = len(timestamps) - 1

            if hold_duration > 0.0:
                hold_interval_count = max(1, math.ceil(hold_duration * frequency))
                hold_local_times = np.linspace(
                    0.0,
                    hold_duration,
                    hold_interval_count + 1,
                )
                held_position = joint_positions[-1]
                for hold_local_time in hold_local_times[1:]:
                    timestamps.append(elapsed_time + float(hold_local_time))
                    joint_positions.append(held_position.copy())
                elapsed_time += hold_duration
                timestamps[-1] = elapsed_time

            is_final_transition = transition_index == len(durations) - 1
            keyframe_sample_indices.append(
                len(timestamps) - 1 if is_final_transition else arrival_sample_index
            )

        return PinkPostureTrajectoryResult(
            joint_names=active_names,
            timestamps=np.asarray(timestamps, dtype=np.float64),
            joint_positions=np.asarray(joint_positions, dtype=np.float64),
            keyframe_sample_indices=tuple(keyframe_sample_indices),
            requested_sample_frequency_hz=frequency,
            max_tracking_error=max_tracking_error,
        )

    def _configuration_values(self, joint_values: Mapping[str, object]) -> np.ndarray:
        unknown_joint_names = sorted(set(joint_values) - self._joint_name_set)
        if unknown_joint_names:
            raise ValueError(f"Unknown URDF joints: {unknown_joint_names}")

        configuration_values = pin.neutral(self._model)
        for joint_name, raw_value in joint_values.items():
            value = self._joint_value(joint_name, raw_value)
            joint = self._model.joints[self._model.getJointId(joint_name)]
            lower_limit = float(self._model.lowerPositionLimit[joint.idx_q])
            upper_limit = float(self._model.upperPositionLimit[joint.idx_q])
            if not lower_limit <= value <= upper_limit:
                raise ValueError(
                    f"Joint {joint_name} value {value} is outside "
                    f"[{lower_limit}, {upper_limit}]"
                )
            configuration_values[joint.idx_q] = value
        return configuration_values

    def _build_reduced_model(
        self,
        *,
        active_joint_names: tuple[str, ...],
        full_reference: np.ndarray,
    ) -> tuple[pin.Model, np.ndarray]:
        locked_joint_ids = [
            self._model.getJointId(joint_name)
            for joint_name in self._joint_names
            if joint_name not in active_joint_names
        ]
        reduced_model = pin.buildReducedModel(self._model, locked_joint_ids, full_reference)
        reduced_values = pin.neutral(reduced_model)
        for joint_name in active_joint_names:
            full_joint = self._model.joints[self._model.getJointId(joint_name)]
            reduced_joint = reduced_model.joints[reduced_model.getJointId(joint_name)]
            reduced_values[reduced_joint.idx_q] = full_reference[full_joint.idx_q]
        return reduced_model, reduced_values

    def _validate_active_joint_names(
        self,
        active_joint_names: Sequence[str],
        joint_values: Mapping[str, object],
    ) -> tuple[str, ...]:
        active_names = tuple(active_joint_names)
        if not active_names:
            raise ValueError("At least one active joint is required for IK")
        if len(set(active_names)) != len(active_names):
            raise ValueError("Active IK joint names must be unique")
        unknown_joint_names = sorted(set(active_names) - self._joint_name_set)
        if unknown_joint_names:
            raise ValueError(f"Unknown active URDF joints: {unknown_joint_names}")
        missing_values = sorted(set(active_names) - set(joint_values))
        if missing_values:
            raise ValueError(f"Active IK joints lack reference values: {missing_values}")
        return active_names

    def _validate_trajectory_inputs(
        self,
        *,
        keyframes: Sequence[Mapping[str, object]],
        joint_names: Sequence[str],
        transition_durations: Sequence[float],
        target_hold_durations: Sequence[float] | None,
        sample_frequency_hz: float,
        endpoint_tolerance: float,
    ) -> tuple[
        tuple[str, ...],
        tuple[float, ...],
        tuple[float, ...],
        float,
        float,
    ]:
        if len(keyframes) < 2:
            raise ValueError("A posture trajectory requires at least two keyframes")
        if len(transition_durations) != len(keyframes) - 1:
            raise ValueError("Transition duration count must be one less than keyframe count")
        active_names = self._validate_active_joint_names(joint_names, keyframes[0])
        expected_joint_set = set(active_names)
        for index, keyframe in enumerate(keyframes):
            if set(keyframe) != expected_joint_set:
                raise ValueError(
                    f"Trajectory keyframe {index} must contain exactly the active joints"
                )

        durations = tuple(
            self._positive_real(
                name=f"Transition {index} duration",
                raw_value=duration,
            )
            for index, duration in enumerate(transition_durations)
        )
        raw_holds = (
            tuple(0.0 for _ in transition_durations)
            if target_hold_durations is None
            else tuple(target_hold_durations)
        )
        if len(raw_holds) != len(transition_durations):
            raise ValueError("Target hold duration count must match transition count")
        holds = tuple(
            self._nonnegative_real(
                name=f"Target {index} hold duration",
                raw_value=hold_duration,
            )
            for index, hold_duration in enumerate(raw_holds)
        )
        frequency = self._positive_real(
            name="Sample frequency",
            raw_value=sample_frequency_hz,
        )
        tolerance = self._positive_real(
            name="Endpoint tolerance",
            raw_value=endpoint_tolerance,
        )
        return active_names, durations, holds, frequency, tolerance

    def _validate_frame_name(self, frame_name: str) -> None:
        if not self._model.existFrame(frame_name):
            raise ValueError(f"Unknown URDF frame: {frame_name}")

    def _validate_scalar_joint_model(self) -> None:
        non_scalar_joint_names = [
            joint_name
            for joint_name in self._joint_names
            if self._model.joints[self._model.getJointId(joint_name)].nq != 1
            or self._model.joints[self._model.getJointId(joint_name)].nv != 1
        ]
        if non_scalar_joint_names:
            raise ValueError(f"Pink IK helper requires scalar joints: {non_scalar_joint_names}")

    def _validate_solve_options(
        self,
        *,
        dt: float,
        max_iterations: int,
        position_tolerance: float,
        orientation_tolerance: float,
        posture_cost: float,
    ) -> None:
        numeric_options = {
            "dt": dt,
            "position_tolerance": position_tolerance,
            "orientation_tolerance": orientation_tolerance,
            "posture_cost": posture_cost,
        }
        for name, value in numeric_options.items():
            if not math.isfinite(value) or value <= 0.0:
                raise ValueError(f"{name} must be finite and greater than zero")
        if isinstance(max_iterations, bool) or not isinstance(max_iterations, int):
            raise ValueError("max_iterations must be an integer")
        if max_iterations <= 0:
            raise ValueError("max_iterations must be greater than zero")

    def _joint_value(self, joint_name: str, raw_value: object) -> float:
        if isinstance(raw_value, bool) or not isinstance(raw_value, Real):
            raise ValueError(f"Joint {joint_name} must be a real number")
        value = float(raw_value)
        if not math.isfinite(value):
            raise ValueError(f"Joint {joint_name} must be finite")
        return value

    def _positive_real(self, *, name: str, raw_value: object) -> float:
        if isinstance(raw_value, bool) or not isinstance(raw_value, Real):
            raise ValueError(f"{name} must be a real number")
        value = float(raw_value)
        if not math.isfinite(value) or value <= 0.0:
            raise ValueError(f"{name} must be finite and greater than zero")
        return value

    def _nonnegative_real(self, *, name: str, raw_value: object) -> float:
        if isinstance(raw_value, bool) or not isinstance(raw_value, Real):
            raise ValueError(f"{name} must be a real number")
        value = float(raw_value)
        if not math.isfinite(value) or value < 0.0:
            raise ValueError(f"{name} must be finite and nonnegative")
        return value

    def _minimum_jerk_blend(self, phase: float) -> float:
        return 10.0 * phase**3 - 15.0 * phase**4 + 6.0 * phase**5

    def _translation_vector(self, translation: Sequence[float]) -> np.ndarray:
        values = np.asarray(translation, dtype=float)
        if values.shape != (3,) or not np.all(np.isfinite(values)):
            raise ValueError("Target translation must contain three finite values")
        return values

    def _rotation_matrix(
        self,
        rotation: Sequence[Sequence[float]] | None,
        default_rotation: np.ndarray,
    ) -> np.ndarray:
        if rotation is None:
            return default_rotation.copy()
        values = np.asarray(rotation, dtype=float)
        if values.shape != (3, 3) or not np.all(np.isfinite(values)):
            raise ValueError("Target rotation must be a finite 3x3 matrix")
        if not np.allclose(values.T @ values, np.eye(3), atol=1e-6) or not math.isclose(
            float(np.linalg.det(values)),
            1.0,
            abs_tol=1e-6,
        ):
            raise ValueError("Target rotation must be a proper rotation matrix")
        return values

    def _to_frame_pose(self, transform: pin.SE3) -> FramePose:
        return FramePose(
            translation=tuple(float(value) for value in transform.translation),
            rotation=tuple(
                tuple(float(value) for value in row) for row in transform.rotation
            ),
        )

    def _frame_errors(self, current: pin.SE3, target: pin.SE3) -> tuple[float, float]:
        position_error = float(np.linalg.norm(current.translation - target.translation))
        orientation_error = float(np.linalg.norm(pin.log3(current.rotation.T @ target.rotation)))
        return position_error, orientation_error

    def _within_tolerance(
        self,
        *,
        position_error: float,
        orientation_error: float,
        position_tolerance: float,
        orientation_tolerance: float,
    ) -> bool:
        return (
            position_error <= position_tolerance
            and orientation_error <= orientation_tolerance
        )


def demo_pink_ik_helper() -> None:
    logging.basicConfig(level=logging.INFO)
    settings = AppSettings()
    helper = PinkIKHelper(
        urdf_path=settings.g1_asset_dir / "g1_29dof_fake_hand.urdf"
    )
    left_arm_joint_names = tuple(
        joint_name
        for joint_name in helper.joint_names
        if joint_name.startswith(("left_shoulder_", "left_elbow_", "left_wrist_"))
    )
    joint_values = {joint_name: 0.0 for joint_name in left_arm_joint_names}
    joint_values["left_shoulder_roll_joint"] = 0.18
    joint_values["left_elbow_joint"] = 1.4
    initial_pose = helper.frame_pose(
        joint_values=joint_values,
        frame_name="left_rubber_hand",
    )
    target_translation = np.asarray(initial_pose.translation) + np.array([0.0, 0.0, 0.03])
    result = helper.solve_frame_target(
        joint_values=joint_values,
        active_joint_names=left_arm_joint_names,
        frame_name="left_rubber_hand",
        target_translation=target_translation,
        target_rotation=initial_pose.rotation,
    )
    preview_path = settings.pose_preview_dir / "pink_ik_left_hand.png"
    MujocoPoseHelper(
        mjcf_path=settings.g1_asset_dir / "g1_29dof_fake_hand.xml"
    ).render_joint_values_to_file(
        joint_values=result.joint_values,
        output_path=preview_path,
    )
    LOGGER.info(
        "Pink left-hand IK converged=%s after %d iterations; position error=%.6f m",
        result.converged,
        result.iterations,
        result.final_position_error,
    )
    LOGGER.info("Rendered solved configuration in MuJoCo: %s", preview_path)


def main() -> None:
    demo_pink_ik_helper()


if __name__ == "__main__":
    main()
