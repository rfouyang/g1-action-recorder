"""REST and WebSocket routes for the shared G1 MuJoCo state."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from app.api_g1_3d.dependencies import get_application
from app.api_g1_3d.simulation.schemas import (
    JointPositionCommand,
    SimulationStateResponse,
)
from app.api_g1_3d.simulation.websocket import simulation_websocket
from app.application import RobotApplication

router = APIRouter(prefix="/simulation", tags=["simulation"])
router.add_api_websocket_route("/ws", simulation_websocket)


@router.get("/state", response_model=SimulationStateResponse)
def get_state(
    application: Annotated[RobotApplication, Depends(get_application)],
) -> SimulationStateResponse:
    """Return the latest complete MuJoCo state."""
    return SimulationStateResponse.from_snapshot(application.simulation.snapshot())


@router.put("/joints", response_model=SimulationStateResponse)
def update_joints(
    command: JointPositionCommand,
    application: Annotated[RobotApplication, Depends(get_application)],
) -> SimulationStateResponse:
    """Apply safe, model-limited joint positions to simulation only."""
    try:
        snapshot = application.simulation.update_joint_positions(
            command.joint_positions
        )
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    return SimulationStateResponse.from_snapshot(snapshot)
