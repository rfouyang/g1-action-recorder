"""System status endpoints for the G1 3D API."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from app.api_g1_3d.dependencies import get_application
from app.api_g1_3d.system.schemas import HealthResponse
from app.application import RobotApplication

router = APIRouter(prefix="/system", tags=["system"])


@router.get("/health", response_model=HealthResponse)
def health(
    application: Annotated[RobotApplication, Depends(get_application)],
) -> HealthResponse:
    """Report that the shared application and G1 model are ready."""
    return HealthResponse(model_id=application.joint_schema.model_id)
