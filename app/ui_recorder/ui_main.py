"""The page. It renders the static layout only; everything it shows or changes goes through /api."""

from __future__ import annotations

import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[2]
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

import math

from fastapi import APIRouter, Request, Response
from fastapi.templating import Jinja2Templates
from loguru import logger

from app.context import recorder_context
from config.settings import RobotConfig, SpeechConfig, ViewerConfig, use_utf8_output

UI_DIR = Path(__file__).resolve().parent
STATIC_DIR = UI_DIR / "static"
templates = Jinja2Templates(directory=UI_DIR / "templates")
router = APIRouter(include_in_schema=False)


@router.api_route("/", methods=["GET", "HEAD"])
def index(request: Request):
    rows = []
    for row in recorder_context.joint_rows():
        # Sliders work in degrees; rounding inward keeps both ends inside the joint limit.
        rows.append({**row, "lower_deg": math.ceil(math.degrees(row["lower"]) * 10) / 10,
                     "upper_deg": math.floor(math.degrees(row["upper"]) * 10) / 10})
    context = {"joint_rows": rows, "home": RobotConfig.HOME_POSE_NAME, "viser_port": recorder_context.display.port,
               "viser_public_url": ViewerConfig.PUBLIC_URL or "",
               "data_dir": _shown_path(recorder_context.data_dir), "pause_choices": SpeechConfig.PAUSE_CHOICES,
               "max_pause": SpeechConfig.MAX_PAUSE_SECONDS}
    page = templates.TemplateResponse(request, "index.html", context)
    return page


def _shown_path(path: Path) -> str:
    """Inside the project, relative to it (data, output/demo/review/data); elsewhere, in full."""
    path = Path(path).resolve()
    shown = path.relative_to(BASE_DIR).as_posix() if path.is_relative_to(BASE_DIR) else str(path)
    return shown


@router.get("/favicon.ico")
def favicon() -> Response:
    """Browsers ask on every load; an empty answer keeps a 404 out of the log."""
    response = Response(status_code=204)
    return response


def demo_ui_main() -> None:
    from fastapi import FastAPI
    from fastapi.staticfiles import StaticFiles
    from fastapi.testclient import TestClient

    app = FastAPI()
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    app.include_router(router)
    client = TestClient(app)
    page = client.get("/")
    logger.info("Page {} ({} bytes, {} sliders)", page.status_code, len(page.text), page.text.count("data-slider"))
    for name in ("common", "stage", "record", "compose", "action", "play", "library", "speech", "map_canvas",
                 "map_tools", "map_page"):
        logger.info("js/{}.js -> {}", name, client.get(f"/static/js/{name}.js").status_code)


def main() -> None:
    use_utf8_output()
    demo_ui_main()


if __name__ == "__main__":
    main()
