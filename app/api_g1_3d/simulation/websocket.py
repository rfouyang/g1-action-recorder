"""Realtime G1 simulation telemetry and joint update transport."""

from __future__ import annotations

import asyncio

from fastapi import WebSocket, WebSocketDisconnect
from pydantic import ValidationError

from app.api_g1_3d.dependencies import get_websocket_application
from app.api_g1_3d.simulation.schemas import (
    JointPositionCommand,
    SimulationStateResponse,
)


async def simulation_websocket(websocket: WebSocket) -> None:
    """Stream state changes and accept validated simulation-only joint updates."""
    await websocket.accept()
    application = get_websocket_application(websocket)
    sent_revision = -1
    try:
        while True:
            snapshot = application.simulation.snapshot()
            if snapshot.revision != sent_revision:
                response = SimulationStateResponse.from_snapshot(snapshot)
                await websocket.send_json(
                    {"type": "simulation_state", **response.model_dump()}
                )
                sent_revision = snapshot.revision

            try:
                payload = await asyncio.wait_for(
                    websocket.receive_json(),
                    timeout=0.1,
                )
            except asyncio.TimeoutError:
                continue

            try:
                command = JointPositionCommand.model_validate(payload)
                snapshot = application.simulation.update_joint_positions(
                    command.joint_positions
                )
                response = SimulationStateResponse.from_snapshot(snapshot)
                await websocket.send_json(
                    {"type": "simulation_state", **response.model_dump()}
                )
                sent_revision = snapshot.revision
            except (ValidationError, ValueError) as error:
                await websocket.send_json(
                    {
                        "type": "error",
                        "detail": str(error),
                    }
                )
    except WebSocketDisconnect:
        return
