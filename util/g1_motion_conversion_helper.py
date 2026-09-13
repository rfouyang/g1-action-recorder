"""Convert G1 skeleton rotation matrices into canonical MuJoCo joint angles."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from numpy.typing import NDArray

from component.common.g1_joint_schema import G1JointSchema


@dataclass(frozen=True, slots=True)
class _HingeProjection:
    joint_name: str
    skeleton_index: int
    frame_to_joint: NDArray[np.float64]
    axis_in_joint_frame: NDArray[np.float64]


@dataclass(frozen=True, slots=True)
class ConvertedArmMotion:
    """Canonical arm samples decoded from one external motion container."""

    joint_positions: NDArray[np.float64]
    frames_per_second: float
    source_joint_count: int


class G1MotionConversionHelper:
    """Project Kimodo/ARDY G1-34 rotations onto the 29 robot hinge axes."""

    SKELETON_NAMES = (
        "pelvis_skel",
        "left_hip_pitch_skel",
        "left_hip_roll_skel",
        "left_hip_yaw_skel",
        "left_knee_skel",
        "left_ankle_pitch_skel",
        "left_ankle_roll_skel",
        "left_toe_base",
        "right_hip_pitch_skel",
        "right_hip_roll_skel",
        "right_hip_yaw_skel",
        "right_knee_skel",
        "right_ankle_pitch_skel",
        "right_ankle_roll_skel",
        "right_toe_base",
        "waist_yaw_skel",
        "waist_roll_skel",
        "waist_pitch_skel",
        "left_shoulder_pitch_skel",
        "left_shoulder_roll_skel",
        "left_shoulder_yaw_skel",
        "left_elbow_skel",
        "left_wrist_roll_skel",
        "left_wrist_pitch_skel",
        "left_wrist_yaw_skel",
        "left_hand_roll_skel",
        "right_shoulder_pitch_skel",
        "right_shoulder_roll_skel",
        "right_shoulder_yaw_skel",
        "right_elbow_skel",
        "right_wrist_roll_skel",
        "right_wrist_pitch_skel",
        "right_wrist_yaw_skel",
        "right_hand_roll_skel",
    )
    PARENT_INDICES = (
        -1,
        0,
        1,
        2,
        3,
        4,
        5,
        6,
        0,
        8,
        9,
        10,
        11,
        12,
        13,
        0,
        15,
        16,
        17,
        18,
        19,
        20,
        21,
        22,
        23,
        24,
        17,
        26,
        27,
        28,
        29,
        30,
        31,
        32,
    )
    MUJOCO_TO_MOTION = np.asarray(
        ((0.0, 1.0, 0.0), (0.0, 0.0, 1.0), (1.0, 0.0, 0.0)),
        dtype=np.float64,
    )

    def __init__(self, *, schema: G1JointSchema, mjcf_path: Path) -> None:
        self.schema = schema
        self.mjcf_path = mjcf_path
        self._skeleton_indices = {
            name: index for index, name in enumerate(self.SKELETON_NAMES)
        }
        self._projections = self._load_projections()

    def arm_positions_from_global_rotations(
        self,
        rotations: object,
    ) -> NDArray[np.float64]:
        """Convert global G1-34 rotations into frame-major arm joint angles."""
        global_rotations = self._validated_rotations(rotations, name="global rotations")
        local_rotations = global_rotations.copy()
        for joint_index, parent_index in enumerate(self.PARENT_INDICES):
            if parent_index >= 0:
                local_rotations[:, joint_index] = np.matmul(
                    np.swapaxes(global_rotations[:, parent_index], -1, -2),
                    global_rotations[:, joint_index],
                )
        return self.arm_positions_from_local_rotations(local_rotations)

    def arm_positions_from_local_rotations(
        self,
        rotations: object,
    ) -> NDArray[np.float64]:
        """Convert parent-relative G1-34 rotations into arm joint angles."""
        local_rotations = self._validated_rotations(rotations, name="local rotations")
        angles_by_name: dict[str, NDArray[np.float64]] = {}
        for projection in self._projections:
            joint_rotations = np.matmul(
                projection.frame_to_joint,
                local_rotations[:, projection.skeleton_index],
            )
            joint_euler_components = np.stack(
                (
                    np.arctan2(joint_rotations[:, 2, 1], joint_rotations[:, 2, 2]),
                    np.arctan2(joint_rotations[:, 0, 2], joint_rotations[:, 0, 0]),
                    np.arctan2(joint_rotations[:, 1, 0], joint_rotations[:, 1, 1]),
                ),
                axis=-1,
            )
            angles_by_name[projection.joint_name] = np.matmul(
                joint_euler_components,
                projection.axis_in_joint_frame,
            )
        return np.column_stack(
            [angles_by_name[name] for name in self.schema.ARM_JOINT_NAMES]
        )

    def _validated_rotations(
        self,
        rotations: object,
        *,
        name: str,
    ) -> NDArray[np.float64]:
        values = np.asarray(rotations, dtype=np.float64)
        if values.ndim == 5:
            if values.shape[0] != 1:
                raise ValueError(f"{name} must contain exactly one motion sample")
            values = values[0]
        expected_tail = (len(self.SKELETON_NAMES), 3, 3)
        if values.ndim != 4 or values.shape[1:] != expected_tail:
            raise ValueError(
                f"{name} must have shape [frame, 34, 3, 3]; got {values.shape}"
            )
        if values.shape[0] < 2:
            raise ValueError(f"{name} must contain at least two frames")
        if not np.all(np.isfinite(values)):
            raise ValueError(f"{name} must contain only finite values")
        identities = np.matmul(np.swapaxes(values, -1, -2), values)
        if not np.allclose(identities, np.eye(3), atol=5e-3, rtol=0.0):
            raise ValueError(f"{name} contain matrices that are not valid rotations")
        determinants = np.linalg.det(values)
        if not np.allclose(determinants, 1.0, atol=5e-3, rtol=0.0):
            raise ValueError(f"{name} contain reflected or scaled matrices")
        return values

    def _load_projections(self) -> tuple[_HingeProjection, ...]:
        tree = ET.parse(self.mjcf_path)
        root = tree.getroot()
        default_axes: dict[str, NDArray[np.float64]] = {}
        for default in root.findall(".//default"):
            class_name = default.get("class")
            joint = default.find("joint")
            if class_name and joint is not None and joint.get("axis"):
                default_axes[class_name] = self._vector(joint.get("axis"))

        parent_map = {child: parent for parent in root.iter() for child in parent}
        projections: list[_HingeProjection] = []
        seen: set[str] = set()
        for joint in root.findall(".//worldbody//joint"):
            joint_name = joint.get("name")
            if joint_name not in self.schema.DDS_JOINT_NAMES:
                continue
            skeleton_name = joint_name.removesuffix("_joint") + "_skel"
            if skeleton_name not in self._skeleton_indices:
                raise ValueError(f"Motion skeleton is missing G1 joint {skeleton_name}")
            axis_text = joint.get("axis")
            if axis_text:
                axis_mujoco = self._vector(axis_text)
            else:
                class_name = joint.get("class")
                if not class_name or class_name not in default_axes:
                    raise ValueError(f"MuJoCo joint {joint_name} has no resolved axis")
                axis_mujoco = default_axes[class_name]
            axis_mujoco = axis_mujoco / np.linalg.norm(axis_mujoco)
            axis_motion = self.MUJOCO_TO_MOTION @ axis_mujoco

            body = parent_map[joint]
            body_rotation = self._quaternion_matrix(body.get("quat", "1 0 0 0"))
            body_rotation_motion = (
                self.MUJOCO_TO_MOTION
                @ body_rotation
                @ self.MUJOCO_TO_MOTION.T
            )
            frame_to_joint = body_rotation_motion.T
            axis_in_joint_frame = frame_to_joint @ axis_motion
            axis_in_joint_frame /= np.linalg.norm(axis_in_joint_frame)
            projections.append(
                _HingeProjection(
                    joint_name=joint_name,
                    skeleton_index=self._skeleton_indices[skeleton_name],
                    frame_to_joint=frame_to_joint,
                    axis_in_joint_frame=axis_in_joint_frame,
                )
            )
            seen.add(joint_name)

        missing = sorted(set(self.schema.DDS_JOINT_NAMES) - seen)
        if missing:
            raise ValueError(f"MuJoCo model is missing projected G1 joints: {missing}")
        return tuple(projections)

    @staticmethod
    def _vector(content: str | None) -> NDArray[np.float64]:
        if content is None:
            raise ValueError("Expected a three-value vector")
        vector = np.fromstring(content, sep=" ", dtype=np.float64)
        if vector.shape != (3,) or not np.all(np.isfinite(vector)):
            raise ValueError(f"Invalid three-value vector: {content!r}")
        if np.linalg.norm(vector) <= 0.0:
            raise ValueError("Joint axis cannot be zero")
        return vector

    @staticmethod
    def _quaternion_matrix(content: str) -> NDArray[np.float64]:
        quaternion = np.fromstring(content, sep=" ", dtype=np.float64)
        if quaternion.shape != (4,) or not np.all(np.isfinite(quaternion)):
            raise ValueError(f"Invalid MuJoCo quaternion: {content!r}")
        quaternion /= np.linalg.norm(quaternion)
        w, x, y, z = quaternion
        return np.asarray(
            (
                (1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)),
                (2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)),
                (2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)),
            ),
            dtype=np.float64,
        )
