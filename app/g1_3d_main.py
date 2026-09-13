"""Run the combined host for independent G1 3D UI and API surfaces."""

from __future__ import annotations

import logging
import os
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

# Make direct IDE/file execution behave the same as ``python -m app.g1_3d_main``.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# MuJoCo rendering works headlessly by default; an explicit caller value still wins.
os.environ.setdefault("MUJOCO_GL", "egl")

from app.api_g1_3d.api_main import router as api_router  # noqa: E402
from app.application import RobotApplication  # noqa: E402
from app.ui_g1_3d.ui_main import router as ui_router  # noqa: E402
from app.ui_g1_3d.viser_manager import ViserManager  # noqa: E402
from config.settings import AppSettings  # noqa: E402
from util.tailwind_asset_helper import TailwindAssetHelper  # noqa: E402

LOGGER = logging.getLogger(__name__)
STATIC_DIR = Path(__file__).resolve().parent / "ui_g1_3d" / "static"
FRONTEND_ASSETS = TailwindAssetHelper.for_g1_3d(project_root=PROJECT_ROOT)


def create_web_app(
    *,
    robot_application: RobotApplication | None = None,
    viser_manager: ViserManager | None = None,
) -> FastAPI:
    """Create the HTTP host while keeping UI and API routers independent."""

    @asynccontextmanager
    async def lifespan(web_app: FastAPI) -> AsyncIterator[None]:
        FRONTEND_ASSETS.ensure_built()
        application = robot_application or RobotApplication.create()
        manager = viser_manager or ViserManager(
            simulation=application.simulation,
            schema=application.joint_schema,
            urdf_path=application.settings.g1_asset_dir / "g1_29dof_fake_hand.urdf",
            host=application.settings.viser_host,
            port=application.settings.viser_port,
        )
        manager.start()
        web_app.state.robot_app = application
        web_app.state.viser = manager
        try:
            yield
        finally:
            application.action_playback.close()
            manager.stop()

    web_app = FastAPI(
        title="G1 Action Recorder",
        version="0.1.0",
        lifespan=lifespan,
    )
    web_app.mount(
        "/static/g1-3d",
        StaticFiles(directory=STATIC_DIR),
        name="g1_3d_static",
    )
    web_app.include_router(api_router)
    web_app.include_router(ui_router)
    return web_app


web_app = create_web_app()


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    settings = AppSettings()
    LOGGER.info(
        "Starting G1 3D console at http://%s:%d",
        settings.g1_3d_host,
        settings.g1_3d_port,
    )
    uvicorn.run(web_app, host=settings.g1_3d_host, port=settings.g1_3d_port)


if __name__ == "__main__":
    main()
