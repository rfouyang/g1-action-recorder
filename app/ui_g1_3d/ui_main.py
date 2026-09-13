"""HTML routes for the G1 3D engineering console."""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, ConfigDict, Field

from app.ui_g1_3d.context import UIContext
from app.ui_g1_3d.panels.action import (
    ActionPanel,
    CompileActionCommand,
    PreviewActionPoseCommand,
    SaveActionCommand,
)
from app.ui_g1_3d.panels.pose_composer import (
    ComposePoseCommand,
    PoseComposerPanel,
)
from app.ui_g1_3d.panels.pose_recorder import PoseRecorderPanel
from app.ui_g1_3d.viser_manager import RobotCameraView
from app.ui_g1_3d.websocket import (
    ui_action_playback_websocket,
    ui_simulation_websocket,
)
from component.action_playback_service import ActionPlaybackSnapshot
from component.common.g1_joint_schema import PoseType
from component.common.models import PoseDefinition

LOGGER = logging.getLogger(__name__)
TEMPLATE_DIR = Path(__file__).resolve().parent / "templates"
templates = Jinja2Templates(directory=TEMPLATE_DIR)
router = APIRouter(include_in_schema=False)
router.add_api_websocket_route(
    "/ui/g1-3d/simulation/ws",
    ui_simulation_websocket,
)
router.add_api_websocket_route(
    "/ui/g1-3d/action/playback/ws",
    ui_action_playback_websocket,
)


class SavePoseCommand(BaseModel):
    """Browser command for persisting one simulated pose group."""

    model_config = ConfigDict(extra="forbid")

    pose_type: PoseType
    name: str
    notes: str = ""
    joint_positions: dict[str, float] = Field(min_length=1)
    overwrite: bool = False


class PlayActionCommand(BaseModel):
    """Browser command for starting one saved trajectory."""

    model_config = ConfigDict(extra="forbid")

    action_name: str
    loop: bool = False


class LoopPlaybackCommand(BaseModel):
    """Browser command for changing the current loop mode."""

    model_config = ConfigDict(extra="forbid")

    enabled: bool


@router.get("/", response_class=HTMLResponse, name="g1_3d_home")
def home(request: Request) -> HTMLResponse:
    """Render the initial three-workspace console shell."""
    context = UIContext.from_request(request)
    template_context = {
        "model_id": context.app.joint_schema.model_id,
        "initial_pose_name": context.app.settings.initial_base_pose_name,
        "viser_port": context.viser.port,
        **PoseRecorderPanel.template_context(context),
        **PoseComposerPanel.template_context(context),
        **ActionPanel.template_context(context),
    }
    return templates.TemplateResponse(
        request=request,
        name="base.html",
        context=template_context,
    )


@router.post("/ui/g1-3d/viewer/camera/{camera_view}")
def set_camera_view(
    request: Request,
    camera_view: RobotCameraView,
) -> dict[str, object]:
    """Move the connected embedded Viser client to a robot-relative view."""
    context = UIContext.from_request(request)
    client_count = context.viser.set_camera_view(camera_view)
    return {
        "camera_view": camera_view.value,
        "connected_clients": client_count,
        "transition_seconds": context.viser.camera_transition_seconds,
    }


@router.post("/ui/g1-3d/poses")
def save_pose(
    request: Request,
    command: SavePoseCommand,
) -> dict[str, object]:
    """Save a validated pose from the browser's current simulated targets."""
    context = UIContext.from_request(request)
    try:
        pose, revision = PoseRecorderPanel.save_simulation_pose(
            context=context,
            pose_type=command.pose_type,
            name=command.name,
            notes=command.notes,
            joint_positions=command.joint_positions,
            overwrite=command.overwrite,
        )
    except FileExistsError as error:
        raise HTTPException(
            status_code=409,
            detail=(
                f"Pose {command.name!r} already exists. Enable replacement to save over it."
            ),
        ) from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    return {
        "pose_name": pose.name,
        "pose_type": pose.pose_type.value,
        "revision": revision,
    }


@router.get("/ui/g1-3d/poses")
def list_poses(request: Request) -> dict[str, tuple[str, ...]]:
    """Return current saved pose names for browser workspace refreshes."""
    context = UIContext.from_request(request)
    return PoseComposerPanel.pose_names(context)


@router.post("/ui/g1-3d/pose-composer/preview")
def preview_composed_pose(
    request: Request,
    command: ComposePoseCommand,
) -> dict[str, object]:
    """Compose selected sources and apply the unsaved result to MuJoCo."""
    context = UIContext.from_request(request)
    try:
        pose, revision = PoseComposerPanel.preview(
            context=context,
            command=command,
        )
    except (FileNotFoundError, ValueError) as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    return _composed_pose_response(pose=pose, revision=revision)


@router.post("/ui/g1-3d/pose-composer/save")
def save_composed_pose(
    request: Request,
    command: ComposePoseCommand,
) -> dict[str, object]:
    """Compose, persist, and apply a final upper-body pose."""
    context = UIContext.from_request(request)
    try:
        pose, revision = PoseComposerPanel.save(
            context=context,
            command=command,
        )
    except FileExistsError as error:
        raise HTTPException(
            status_code=409,
            detail=(
                f"Pose {command.name!r} already exists. Enable replacement to save over it."
            ),
        ) from error
    except (FileNotFoundError, ValueError) as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    return _composed_pose_response(pose=pose, revision=revision)


def _composed_pose_response(
    *,
    pose: PoseDefinition,
    revision: int,
) -> dict[str, object]:
    return {
        "pose_name": pose.name,
        "pose_type": pose.pose_type.value,
        "source_parts": dict(pose.source_parts),
        "revision": revision,
    }


@router.get("/ui/g1-3d/action/sources")
def action_sources(request: Request) -> dict[str, object]:
    """Return complete pose choices and saved definitions for the Action panel."""
    context = UIContext.from_request(request)
    return ActionPanel.sources(context)


@router.get("/ui/g1-3d/action/definitions/{action_name}")
def load_action_definition(request: Request, action_name: str) -> dict[str, object]:
    """Load one saved action into the browser-side sequence editor."""
    context = UIContext.from_request(request)
    try:
        return ActionPanel.load(context=context, name=action_name)
    except (FileNotFoundError, ValueError) as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@router.post("/ui/g1-3d/action/preview-pose")
def preview_action_pose(
    request: Request,
    command: PreviewActionPoseCommand,
) -> dict[str, object]:
    """Apply one action keyframe to the shared MuJoCo and Viser scene."""
    context = UIContext.from_request(request)
    try:
        revision = ActionPanel.preview_pose(context=context, command=command)
    except (FileNotFoundError, ValueError) as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    return {
        "pose_type": command.pose_type.value,
        "pose_name": command.name,
        "revision": revision,
    }


@router.post("/ui/g1-3d/action/save")
def save_action_definition(
    request: Request,
    command: SaveActionCommand,
) -> dict[str, object]:
    """Validate and persist an action definition as JSON."""
    context = UIContext.from_request(request)
    try:
        action = ActionPanel.save(context=context, command=command)
    except FileExistsError as error:
        raise HTTPException(
            status_code=409,
            detail=(
                f"Action {command.name!r} already exists. "
                "Enable replacement to save over it."
            ),
        ) from error
    except (FileNotFoundError, ValueError) as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    return {
        "action_name": action.name,
        "keyframe_count": len(action.pose_sequence),
        "total_duration_seconds": action.total_duration_seconds,
    }


@router.post("/ui/g1-3d/action/compile")
def compile_action_trajectory(
    request: Request,
    command: CompileActionCommand,
) -> dict[str, object]:
    """Compile the browser sequence into a validated NPZ trajectory."""
    context = UIContext.from_request(request)
    try:
        trajectory = ActionPanel.compile(context=context, command=command)
    except FileExistsError as error:
        raise HTTPException(
            status_code=409,
            detail=(
                f"Trajectory {command.name!r} already exists. "
                "Enable replacement to compile over it."
            ),
        ) from error
    except (FileNotFoundError, ValueError) as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    return {
        "action_name": trajectory.action_name,
        "sample_count": trajectory.sample_count,
        "duration_seconds": trajectory.duration_seconds,
        "sample_frequency_hz": trajectory.requested_sample_frequency_hz,
        "max_tracking_error": trajectory.max_tracking_error,
        "download_url": str(
            request.url_for(
                "download_action_trajectory",
                action_name=trajectory.action_name,
            )
        ),
    }


@router.get(
    "/ui/g1-3d/action/trajectories/{action_name}",
    name="download_action_trajectory",
)
def download_action_trajectory(request: Request, action_name: str) -> FileResponse:
    """Return a previously validated compiled trajectory as a download."""
    context = UIContext.from_request(request)
    try:
        trajectory = context.app.action_service.load_trajectory(name=action_name)
    except (FileNotFoundError, ValueError) as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    path = context.app.action_service.action_trajectory_dir / (
        f"{trajectory.action_name}.npz"
    )
    return FileResponse(
        path=path,
        filename=path.name,
        media_type="application/octet-stream",
    )


@router.post("/ui/g1-3d/action/playback/play")
def play_action_trajectory(
    request: Request,
    command: PlayActionCommand,
) -> dict[str, object]:
    """Load and play one compiled trajectory in the shared simulation."""
    context = UIContext.from_request(request)
    try:
        trajectory = context.app.action_service.load_trajectory(
            name=command.action_name
        )
        snapshot = context.app.action_playback.play(
            trajectory=trajectory,
            loop=command.loop,
        )
    except (FileNotFoundError, ValueError) as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    return _playback_response(snapshot)


@router.post("/ui/g1-3d/action/playback/pause")
def pause_action_playback(request: Request) -> dict[str, object]:
    """Pause the shared action player at its current trajectory sample."""
    context = UIContext.from_request(request)
    try:
        snapshot = context.app.action_playback.pause()
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    return _playback_response(snapshot)


@router.post("/ui/g1-3d/action/playback/resume")
def resume_action_playback(request: Request) -> dict[str, object]:
    """Resume a paused action trajectory."""
    context = UIContext.from_request(request)
    try:
        snapshot = context.app.action_playback.resume()
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    return _playback_response(snapshot)


@router.post("/ui/g1-3d/action/playback/stop")
def stop_action_playback(request: Request) -> dict[str, object]:
    """Stop action playback and return to the trajectory's initial pose."""
    context = UIContext.from_request(request)
    return _playback_response(context.app.action_playback.stop())


@router.post("/ui/g1-3d/action/playback/loop")
def set_action_playback_loop(
    request: Request,
    command: LoopPlaybackCommand,
) -> dict[str, object]:
    """Update loop mode for the current or next active trajectory."""
    context = UIContext.from_request(request)
    return _playback_response(
        context.app.action_playback.set_loop(enabled=command.enabled)
    )


def _playback_response(snapshot: ActionPlaybackSnapshot) -> dict[str, object]:
    return {
        "state": snapshot.state.value,
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


def demo_ui_routes() -> None:
    logging.basicConfig(level=logging.INFO)
    LOGGER.info("G1 3D UI router exposes %d route(s)", len(router.routes))


def main() -> None:
    demo_ui_routes()


if __name__ == "__main__":
    main()
