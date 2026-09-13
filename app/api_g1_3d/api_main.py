"""Assemble domain routers for the G1 3D API."""

from __future__ import annotations

from fastapi import APIRouter

from app.api_g1_3d.simulation.router import router as simulation_router
from app.api_g1_3d.system.router import router as system_router

router = APIRouter(prefix="/api/g1")
router.include_router(system_router)
router.include_router(simulation_router)
