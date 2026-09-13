"""FastAPI dependency providers for the G1 3D API."""

from __future__ import annotations

from typing import cast

from fastapi import Request, WebSocket

from app.application import RobotApplication


def get_application(request: Request) -> RobotApplication:
    """Return the process-wide application assembled by the web host."""
    return cast(RobotApplication, request.app.state.robot_app)


def get_websocket_application(websocket: WebSocket) -> RobotApplication:
    """Return the shared application for a FastAPI WebSocket connection."""
    return cast(RobotApplication, websocket.app.state.robot_app)
