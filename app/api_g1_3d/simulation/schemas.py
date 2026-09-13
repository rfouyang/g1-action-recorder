"""Transport schemas for G1 MuJoCo state and joint commands."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from component.simulation import SimulationSnapshot


class JointPositionCommand(BaseModel):
    """Validated transport envelope for a partial simulated configuration."""

    model_config = ConfigDict(extra="forbid")

    joint_positions: dict[str, float] = Field(min_length=1)


class SimulationStateResponse(BaseModel):
    """Complete simulation state suitable for REST or WebSocket telemetry."""

    revision: int
    updated_at: float
    joint_positions: dict[str, float]
    base_position: tuple[float, float, float]
    base_wxyz: tuple[float, float, float, float]

    @classmethod
    def from_snapshot(
        cls,
        snapshot: SimulationSnapshot,
    ) -> SimulationStateResponse:
        return cls(
            revision=snapshot.revision,
            updated_at=snapshot.updated_at,
            joint_positions=snapshot.joint_position_map(),
            base_position=snapshot.base_position,
            base_wxyz=snapshot.base_wxyz,
        )
