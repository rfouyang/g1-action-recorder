"""UI-only dependencies for the G1 3D presentation surface."""

from __future__ import annotations

from dataclasses import dataclass
from typing import cast

from fastapi import Request

from app.application import RobotApplication
from app.ui_g1_3d.viser_manager import ViserManager


@dataclass(frozen=True, slots=True)
class UIContext:
    """Expose shared business capabilities without duplicating them in the UI."""

    app: RobotApplication
    viser: ViserManager

    @classmethod
    def from_request(cls, request: Request) -> UIContext:
        """Build a request-scoped UI context around the shared application."""
        return cls(
            app=cast(RobotApplication, request.app.state.robot_app),
            viser=cast(ViserManager, request.app.state.viser),
        )
