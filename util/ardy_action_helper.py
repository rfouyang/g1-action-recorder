"""Decode trusted-local ARDY session PKL files with a restricted unpickler."""

from __future__ import annotations

import builtins
import io
import pickle
from dataclasses import dataclass

import numpy as np

from util.g1_motion_conversion_helper import ConvertedArmMotion, G1MotionConversionHelper


@dataclass(frozen=True, slots=True)
class _AllowedGlobal:
    module: str
    name: str
    value: object


class _NumpySessionUnpickler(pickle.Unpickler):
    """Allow only the globals required by dictionaries containing NumPy arrays."""

    _ALLOWED = {
        (entry.module, entry.name): entry.value
        for entry in (
            _AllowedGlobal("builtins", "slice", builtins.slice),
            _AllowedGlobal("numpy", "dtype", np.dtype),
            _AllowedGlobal("numpy", "ndarray", np.ndarray),
            _AllowedGlobal(
                "numpy.core.multiarray",
                "_reconstruct",
                np.core.multiarray._reconstruct,
            ),
            _AllowedGlobal(
                "numpy._core.multiarray",
                "_reconstruct",
                np.core.multiarray._reconstruct,
            ),
            _AllowedGlobal(
                "numpy.core.numeric",
                "_frombuffer",
                np._core.numeric._frombuffer,
            ),
            _AllowedGlobal(
                "numpy._core.numeric",
                "_frombuffer",
                np._core.numeric._frombuffer,
            ),
        )
    }

    def find_class(self, module: str, name: str) -> object:
        try:
            return self._ALLOWED[(module, name)]
        except KeyError as error:
            raise pickle.UnpicklingError(
                f"ARDY session uses unsupported pickle global {module}.{name}"
            ) from error


class ArdyActionHelper:
    """Extract one G1-34 motion from an ARDY interactive session export."""

    def __init__(self, *, conversion_helper: G1MotionConversionHelper) -> None:
        self.conversion_helper = conversion_helper

    def load(self, *, content: bytes) -> ConvertedArmMotion:
        try:
            payload = _NumpySessionUnpickler(io.BytesIO(content)).load()
        except (EOFError, pickle.UnpicklingError, ValueError) as error:
            raise ValueError(f"Could not read restricted ARDY session: {error}") from error
        if not isinstance(payload, dict):
            raise ValueError("ARDY PKL root must be a dictionary")
        if payload.get("version") != "1.0":
            raise ValueError(f"Unsupported ARDY session version: {payload.get('version')!r}")
        skeleton = payload.get("skeleton")
        if not isinstance(skeleton, dict) or skeleton.get("nbjoints") != 34:
            raise ValueError("ARDY session must identify the 34-joint G1 skeleton")
        motion = payload.get("motion")
        if not isinstance(motion, dict):
            raise ValueError("ARDY session does not contain motion data")

        if motion.get("local_rot_mats") is not None:
            rotations = motion["local_rot_mats"]
            joint_positions = self.conversion_helper.arm_positions_from_local_rotations(
                rotations
            )
        elif motion.get("joints_rot") is not None:
            rotations = motion["joints_rot"]
            joint_positions = self.conversion_helper.arm_positions_from_global_rotations(
                rotations
            )
        else:
            raise ValueError(
                "ARDY session must contain motion.local_rot_mats or motion.joints_rot"
            )

        frames_per_second = self._frames_per_second(payload.get("model_fps"))
        return ConvertedArmMotion(
            joint_positions=joint_positions,
            frames_per_second=frames_per_second,
            source_joint_count=int(np.asarray(rotations).shape[-3]),
        )

    @staticmethod
    def _frames_per_second(raw_value: object) -> float:
        if isinstance(raw_value, bool) or not isinstance(raw_value, (int, float)):
            raise ValueError("ARDY model_fps must be a numeric scalar")
        value = float(raw_value)
        if not np.isfinite(value) or value <= 0.0 or value > 240.0:
            raise ValueError("ARDY model_fps must be within (0, 240] Hz")
        return value
