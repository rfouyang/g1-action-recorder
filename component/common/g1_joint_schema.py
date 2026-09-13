"""Canonical Unitree G1 joint groups, DDS indices, and limits."""

from __future__ import annotations

import logging
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import Enum
from numbers import Real

from config.settings import AppSettings
from util.g1_asset_helper import G1AssetHelper

LOGGER = logging.getLogger(__name__)


class PoseType(str, Enum):
    """Supported saved pose shapes."""

    BASE = "base"
    LEFT_ARM = "left_arm"
    RIGHT_ARM = "right_arm"
    COMPOSED = "composed"


class JointGroup(str, Enum):
    """Physical joint groups in the 29-DOF G1 model."""

    LEFT_LEG = "left_leg"
    RIGHT_LEG = "right_leg"
    WAIST = "waist"
    LEFT_ARM = "left_arm"
    RIGHT_ARM = "right_arm"


@dataclass(frozen=True, slots=True)
class JointDefinition:
    """One named G1 joint and its Unitree DDS position."""

    name: str
    dds_index: int
    group: JointGroup
    axis: tuple[float, float, float]
    lower_limit: float
    upper_limit: float


class G1JointSchema:
    """Single application-level view of the G1 29-DOF joint contract."""

    DDS_JOINT_NAMES = (
        "left_hip_pitch_joint",
        "left_hip_roll_joint",
        "left_hip_yaw_joint",
        "left_knee_joint",
        "left_ankle_pitch_joint",
        "left_ankle_roll_joint",
        "right_hip_pitch_joint",
        "right_hip_roll_joint",
        "right_hip_yaw_joint",
        "right_knee_joint",
        "right_ankle_pitch_joint",
        "right_ankle_roll_joint",
        "waist_yaw_joint",
        "waist_roll_joint",
        "waist_pitch_joint",
        "left_shoulder_pitch_joint",
        "left_shoulder_roll_joint",
        "left_shoulder_yaw_joint",
        "left_elbow_joint",
        "left_wrist_roll_joint",
        "left_wrist_pitch_joint",
        "left_wrist_yaw_joint",
        "right_shoulder_pitch_joint",
        "right_shoulder_roll_joint",
        "right_shoulder_yaw_joint",
        "right_elbow_joint",
        "right_wrist_roll_joint",
        "right_wrist_pitch_joint",
        "right_wrist_yaw_joint",
    )
    LEG_JOINT_NAMES = DDS_JOINT_NAMES[:12]
    WAIST_JOINT_NAMES = DDS_JOINT_NAMES[12:15]
    LEFT_ARM_JOINT_NAMES = DDS_JOINT_NAMES[15:22]
    RIGHT_ARM_JOINT_NAMES = DDS_JOINT_NAMES[22:29]
    ARM_JOINT_NAMES = LEFT_ARM_JOINT_NAMES + RIGHT_ARM_JOINT_NAMES
    BASE_JOINT_NAMES = WAIST_JOINT_NAMES + LEFT_ARM_JOINT_NAMES + RIGHT_ARM_JOINT_NAMES

    def __init__(self, *, asset_helper: G1AssetHelper) -> None:
        asset_helper.validate()
        metadata = asset_helper.load_metadata()
        model_joint_specs = asset_helper.load_joint_specs()
        if set(model_joint_specs) != set(self.DDS_JOINT_NAMES):
            raise ValueError("DDS joint names do not match the canonical G1 model")

        self.model_id = str(metadata["model_id"])
        self.mode_machine = int(metadata["mode_machine"])
        self._definitions = tuple(
            JointDefinition(
                name=joint_name,
                dds_index=dds_index,
                group=self._joint_group(dds_index),
                axis=model_joint_specs[joint_name].axis,
                lower_limit=model_joint_specs[joint_name].lower_limit,
                upper_limit=model_joint_specs[joint_name].upper_limit,
            )
            for dds_index, joint_name in enumerate(self.DDS_JOINT_NAMES)
        )
        self._definitions_by_name = {
            definition.name: definition for definition in self._definitions
        }

    @property
    def definitions(self) -> tuple[JointDefinition, ...]:
        return self._definitions

    def definition(self, joint_name: str) -> JointDefinition:
        try:
            return self._definitions_by_name[joint_name]
        except KeyError as error:
            raise ValueError(f"Unknown G1 joint: {joint_name}") from error

    def joint_names(self, pose_type: PoseType) -> tuple[str, ...]:
        if pose_type is PoseType.LEFT_ARM:
            return self.LEFT_ARM_JOINT_NAMES
        if pose_type is PoseType.RIGHT_ARM:
            return self.RIGHT_ARM_JOINT_NAMES
        return self.BASE_JOINT_NAMES

    def extract_from_dds(
        self,
        *,
        motor_positions: Sequence[float],
        pose_type: PoseType,
    ) -> dict[str, float]:
        """Extract an ordered pose subset from a 29-motor LowState sequence."""
        if len(motor_positions) < len(self.DDS_JOINT_NAMES):
            raise ValueError(f"LowState has {len(motor_positions)} motors; expected at least 29")
        extracted_values = {
            joint_name: motor_positions[self.definition(joint_name).dds_index]
            for joint_name in self.joint_names(pose_type)
        }
        return self.validate_joint_values(pose_type=pose_type, joint_values=extracted_values)

    def validate_joint_values(
        self,
        *,
        pose_type: PoseType,
        joint_values: Mapping[str, object],
    ) -> dict[str, float]:
        """Validate a pose's exact joint set, finite values, and model limits."""
        expected_joint_names = self.joint_names(pose_type)
        expected_joint_set = set(expected_joint_names)
        actual_joint_set = set(joint_values)
        if actual_joint_set != expected_joint_set:
            missing = sorted(expected_joint_set - actual_joint_set)
            unknown = sorted(actual_joint_set - expected_joint_set)
            details = []
            if missing:
                details.append(f"missing={missing}")
            if unknown:
                details.append(f"unknown={unknown}")
            raise ValueError(f"Invalid {pose_type.value} joint set: {', '.join(details)}")

        validated_values: dict[str, float] = {}
        for joint_name in expected_joint_names:
            raw_value = joint_values[joint_name]
            if isinstance(raw_value, bool) or not isinstance(raw_value, Real):
                raise ValueError(f"Joint {joint_name} must be a real number")
            value = float(raw_value)
            if not math.isfinite(value):
                raise ValueError(f"Joint {joint_name} must be finite")
            definition = self.definition(joint_name)
            if not definition.lower_limit <= value <= definition.upper_limit:
                raise ValueError(
                    f"Joint {joint_name} value {value} is outside "
                    f"[{definition.lower_limit}, {definition.upper_limit}]"
                )
            validated_values[joint_name] = value
        return validated_values

    def neutral_values(self, pose_type: PoseType) -> dict[str, float]:
        return {joint_name: 0.0 for joint_name in self.joint_names(pose_type)}

    def _joint_group(self, dds_index: int) -> JointGroup:
        if dds_index < 6:
            return JointGroup.LEFT_LEG
        if dds_index < 12:
            return JointGroup.RIGHT_LEG
        if dds_index < 15:
            return JointGroup.WAIST
        if dds_index < 22:
            return JointGroup.LEFT_ARM
        return JointGroup.RIGHT_ARM


def demo_g1_joint_schema() -> None:
    logging.basicConfig(level=logging.INFO)
    settings = AppSettings()
    schema = G1JointSchema(asset_helper=G1AssetHelper(asset_dir=settings.g1_asset_dir))
    simulated_low_state = [0.0] * len(schema.DDS_JOINT_NAMES)
    base_values = schema.extract_from_dds(
        motor_positions=simulated_low_state,
        pose_type=PoseType.BASE,
    )
    LOGGER.info(
        "Loaded %d G1 joints and extracted %d base-pose joints for model %s",
        len(schema.definitions),
        len(base_values),
        schema.model_id,
    )


def main() -> None:
    demo_g1_joint_schema()


if __name__ == "__main__":
    main()
