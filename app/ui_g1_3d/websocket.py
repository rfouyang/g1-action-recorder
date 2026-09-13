"""Browser-only realtime transport for the G1 3D UI."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from typing import cast

from fastapi import WebSocket, WebSocketDisconnect

from app.application import RobotApplication
from component.action_playback_service import ActionPlaybackSnapshot
from component.simulation import SimulationSnapshot


async def ui_simulation_websocket(websocket: WebSocket) -> None:
    """Stream simulation state and accept UI target changes."""
    await websocket.accept()
    application = cast(RobotApplication, websocket.app.state.robot_app)
    sent_revision = -1
    try:
        while True:
            snapshot = application.simulation.snapshot()
            if snapshot.revision != sent_revision:
                await websocket.send_json(_snapshot_message(snapshot))
                sent_revision = snapshot.revision

            try:
                payload = await asyncio.wait_for(
                    websocket.receive_json(),
                    timeout=0.1,
                )
            except asyncio.TimeoutError:
                continue

            try:
                joint_positions = _joint_positions(payload)
                snapshot = application.simulation.update_joint_positions(
                    joint_positions
                )
                await websocket.send_json(_snapshot_message(snapshot))
                sent_revision = snapshot.revision
            except ValueError as error:
                await websocket.send_json(
                    {
                        "type": "error",
                        "detail": str(error),
                    }
                )
    except WebSocketDisconnect:
        return


async def ui_action_playback_websocket(websocket: WebSocket) -> None:
    """Stream low-frequency action playback status to the browser."""
    await websocket.accept()
    application = cast(RobotApplication, websocket.app.state.robot_app)
    sent_revision = -1
    try:
        while True:
            snapshot = application.action_player.snapshot()
            if snapshot.revision != sent_revision:
                await websocket.send_json(_playback_message(snapshot))
                sent_revision = snapshot.revision
            try:
                message = await asyncio.wait_for(
                    websocket.receive(),
                    timeout=0.05,
                )
            except asyncio.TimeoutError:
                continue
            if message["type"] == "websocket.disconnect":
                return
    except WebSocketDisconnect:
        return


def _joint_positions(payload: object) -> Mapping[str, object]:
    if not isinstance(payload, dict) or set(payload) != {"joint_positions"}:
        raise ValueError("Expected a joint_positions object")
    joint_positions = payload["joint_positions"]
    if not isinstance(joint_positions, dict) or not joint_positions:
        raise ValueError("At least one joint position is required")
    return joint_positions


def _snapshot_message(snapshot: SimulationSnapshot) -> dict[str, object]:
    return {
        "type": "simulation_state",
        "revision": snapshot.revision,
        "updated_at": snapshot.updated_at,
        "joint_positions": snapshot.joint_position_map(),
        "base_position": snapshot.base_position,
        "base_wxyz": snapshot.base_wxyz,
    }


def _playback_message(
    snapshot: ActionPlaybackSnapshot,
) -> dict[str, object]:
    return {
        "type": "action_playback",
        "revision": snapshot.revision,
        "state": snapshot.state.value,
        "source": snapshot.source.value if snapshot.source is not None else None,
        "action_name": snapshot.action_name,
        "sample_index": snapshot.sample_index,
        "sample_count": snapshot.sample_count,
        "elapsed_seconds": snapshot.elapsed_seconds,
        "duration_seconds": snapshot.duration_seconds,
        "progress": snapshot.progress,
        "loop": snapshot.loop,
        "phase": snapshot.phase.value,
        "from_pose_name": snapshot.from_pose_name,
        "target_pose_name": snapshot.target_pose_name,
        "keyframe_index": snapshot.keyframe_index,
        "keyframe_count": snapshot.keyframe_count,
        "error": snapshot.error,
    }
