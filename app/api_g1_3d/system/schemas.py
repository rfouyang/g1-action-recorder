"""Transport schemas for the G1 system API."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel


class HealthResponse(BaseModel):
    """Small readiness response for clients and deployment checks."""

    status: Literal["ok"] = "ok"
    model_id: str
    runtime: Literal["simulation"] = "simulation"
