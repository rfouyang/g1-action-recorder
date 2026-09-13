"""Serializable pose definitions shared by the pose workflow."""

from __future__ import annotations

import json
import logging
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from types import MappingProxyType

from component.common.g1_joint_schema import G1JointSchema, PoseType
from config.settings import AppSettings
from util.g1_asset_helper import G1AssetHelper

LOGGER = logging.getLogger(__name__)


class PoseSource(str, Enum):
    """Origin of a saved pose definition."""

    SIMULATION = "simulation"
    ROBOT = "robot"
    MIRROR = "mirror"
    COMPOSITION = "composition"


@dataclass(frozen=True, slots=True)
class PoseDefinition:
    """A validated, immutable set of named G1 joint positions."""

    schema_version: int
    name: str
    pose_type: PoseType
    robot_model_id: str
    joint_values: Mapping[str, float]
    source: PoseSource
    created_at: datetime
    source_parts: Mapping[str, str] = field(default_factory=dict)
    notes: str = ""

    def __post_init__(self) -> None:
        normalized_name = self.validate_name(self.name)
        if self.schema_version != 1:
            raise ValueError(f"Unsupported pose schema version: {self.schema_version}")
        if self.created_at.tzinfo is None or self.created_at.utcoffset() is None:
            raise ValueError("Pose created_at must include a timezone")

        object.__setattr__(self, "name", normalized_name)
        object.__setattr__(self, "joint_values", MappingProxyType(dict(self.joint_values)))
        object.__setattr__(self, "source_parts", MappingProxyType(dict(self.source_parts)))

    @classmethod
    def validate_name(cls, name: str) -> str:
        """Return a normalized Unicode pose name that is safe as a filename."""
        if not isinstance(name, str):
            raise ValueError("Pose name must be a string")
        normalized_name = name.strip()
        if not normalized_name:
            raise ValueError("Pose name cannot be empty")
        if len(normalized_name) > 100:
            raise ValueError("Pose name cannot exceed 100 characters")
        if normalized_name in {".", ".."} or any(
            character in normalized_name for character in '<>:"/\\|?*'
        ):
            raise ValueError("Pose name contains a path-unsafe character")
        if any(ord(character) < 32 for character in normalized_name):
            raise ValueError("Pose name contains a control character")
        return normalized_name

    @classmethod
    def create(
        cls,
        *,
        schema: G1JointSchema,
        name: str,
        pose_type: PoseType,
        joint_values: Mapping[str, object],
        source: PoseSource,
        created_at: datetime | None = None,
        source_parts: Mapping[str, str] | None = None,
        notes: str = "",
    ) -> PoseDefinition:
        validated_values = schema.validate_joint_values(
            pose_type=pose_type,
            joint_values=joint_values,
        )
        return cls(
            schema_version=1,
            name=name,
            pose_type=pose_type,
            robot_model_id=schema.model_id,
            joint_values=validated_values,
            source=source,
            created_at=created_at or datetime.now(timezone.utc),
            source_parts=source_parts or {},
            notes=notes,
        )

    @classmethod
    def from_dict(
        cls,
        *,
        schema: G1JointSchema,
        payload: Mapping[str, object],
    ) -> PoseDefinition:
        required_keys = {
            "schema_version",
            "name",
            "pose_type",
            "robot_model_id",
            "joint_values",
            "source",
            "created_at",
        }
        missing_keys = sorted(required_keys - set(payload))
        if missing_keys:
            raise ValueError(f"Pose payload is missing fields: {missing_keys}")
        if payload["schema_version"] != 1:
            raise ValueError(f"Unsupported pose schema version: {payload['schema_version']}")
        if payload["robot_model_id"] != schema.model_id:
            raise ValueError(
                f"Pose model {payload['robot_model_id']} does not match {schema.model_id}"
            )
        joint_values = payload["joint_values"]
        source_parts = payload.get("source_parts", {})
        name = payload["name"]
        if not isinstance(name, str):
            raise ValueError("Pose name must be a string")
        if not isinstance(joint_values, Mapping):
            raise ValueError("Pose joint_values must be an object")
        if not isinstance(source_parts, Mapping):
            raise ValueError("Pose source_parts must be an object")

        created_at_text = str(payload["created_at"])
        created_at = datetime.fromisoformat(created_at_text.replace("Z", "+00:00"))
        return cls.create(
            schema=schema,
            name=name,
            pose_type=PoseType(str(payload["pose_type"])),
            joint_values=joint_values,
            source=PoseSource(str(payload["source"])),
            created_at=created_at,
            source_parts={str(key): str(value) for key, value in source_parts.items()},
            notes=str(payload.get("notes", "")),
        )

    @classmethod
    def from_json(cls, *, schema: G1JointSchema, content: str) -> PoseDefinition:
        payload = json.loads(content)
        if not isinstance(payload, dict):
            raise ValueError("Pose JSON root must be an object")
        return cls.from_dict(schema=schema, payload=payload)

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "name": self.name,
            "pose_type": self.pose_type.value,
            "robot_model_id": self.robot_model_id,
            "joint_values": dict(self.joint_values),
            "source": self.source.value,
            "created_at": self.created_at.astimezone(timezone.utc)
            .isoformat()
            .replace("+00:00", "Z"),
            "source_parts": dict(self.source_parts),
            "notes": self.notes,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2) + "\n"


def demo_pose_definition() -> None:
    logging.basicConfig(level=logging.INFO)
    settings = AppSettings()
    schema = G1JointSchema(asset_helper=G1AssetHelper(asset_dir=settings.g1_asset_dir))
    pose = PoseDefinition.create(
        schema=schema,
        name="simulated_neutral_base",
        pose_type=PoseType.BASE,
        joint_values=schema.neutral_values(PoseType.BASE),
        source=PoseSource.SIMULATION,
        notes="Step 3 in-memory serialization demo",
    )
    restored_pose = PoseDefinition.from_json(schema=schema, content=pose.to_json())
    LOGGER.info(
        "Serialized and restored %s with %d joints",
        restored_pose.name,
        len(restored_pose.joint_values),
    )


def main() -> None:
    demo_pose_definition()


if __name__ == "__main__":
    main()
