"""Decode Kimodo G1 NPZ motion files into canonical arm positions."""

from __future__ import annotations

import numpy as np

from util.g1_motion_conversion_helper import ConvertedArmMotion, G1MotionConversionHelper
from util.numpy_archive_helper import NumpyArchiveHelper


class KimodoActionHelper:
    """Read the supported G1-34 Kimodo rotation archive variants."""

    def __init__(
        self,
        *,
        archive_helper: NumpyArchiveHelper,
        conversion_helper: G1MotionConversionHelper,
    ) -> None:
        self.archive_helper = archive_helper
        self.conversion_helper = conversion_helper

    def load(self, *, content: bytes, source_fps: float | None) -> ConvertedArmMotion:
        arrays = self.archive_helper.read_npz_bytes(content=content)
        if "local_rot_mats" in arrays:
            rotations = arrays["local_rot_mats"]
            joint_positions = self.conversion_helper.arm_positions_from_local_rotations(
                rotations
            )
        elif "global_rot_mats" in arrays:
            rotations = arrays["global_rot_mats"]
            joint_positions = self.conversion_helper.arm_positions_from_global_rotations(
                rotations
            )
        else:
            raise ValueError(
                "Kimodo NPZ must contain local_rot_mats or global_rot_mats"
            )
        embedded_fps = arrays.get("fps")
        frames_per_second = self._frames_per_second(
            embedded_fps=embedded_fps,
            requested_fps=source_fps,
        )
        return ConvertedArmMotion(
            joint_positions=joint_positions,
            frames_per_second=frames_per_second,
            source_joint_count=int(np.asarray(rotations).shape[-3]),
        )

    @staticmethod
    def _frames_per_second(
        *,
        embedded_fps: np.ndarray | None,
        requested_fps: float | None,
    ) -> float:
        if embedded_fps is not None:
            if embedded_fps.shape != () or embedded_fps.dtype.kind not in "fiu":
                raise ValueError("Kimodo fps must be a numeric scalar")
            value = float(embedded_fps.item())
        elif requested_fps is not None:
            value = float(requested_fps)
        else:
            raise ValueError("Kimodo NPZ has no fps; enter its source frequency")
        if not np.isfinite(value) or value <= 0.0 or value > 240.0:
            raise ValueError("Kimodo source frequency must be within (0, 240] Hz")
        return value
