"""Render time-sampled G1 joint trajectories through MuJoCo."""

from __future__ import annotations

import logging
import math
import threading
from collections.abc import Sequence
from pathlib import Path

import mujoco
import numpy as np
from numpy.typing import NDArray
from PIL import Image, ImageDraw

from config.settings import AppSettings
from util.mujoco_pose_helper import CameraView, MujocoPoseHelper

LOGGER = logging.getLogger(__name__)


class MujocoActionHelper:
    """Render forward-kinematics trajectory samples as multi-camera GIFs."""

    CAMERA_LABELS = {
        CameraView.FRONT: "Front",
        CameraView.ROBOT_RIGHT: "Robot right",
        CameraView.FRONT_RIGHT: "Front-right 45°",
        CameraView.ROBOT_LEFT: "Robot left",
        CameraView.FRONT_LEFT: "Front-left 45°",
    }

    def __init__(self, *, pose_helper: MujocoPoseHelper) -> None:
        self.pose_helper = pose_helper
        self._render_lock = threading.Lock()

    def render_trajectory_gif(
        self,
        *,
        joint_names: Sequence[str],
        timestamps: Sequence[float] | NDArray[np.float64],
        joint_positions: Sequence[Sequence[float]] | NDArray[np.float64],
        output_path: Path,
        camera_views: tuple[CameraView, ...] = MujocoPoseHelper.DEFAULT_CAMERA_VIEWS,
        view_width: int = 240,
        view_height: int = 180,
        end_hold_seconds: float = 0.4,
    ) -> Path:
        """Render all samples without stepping dynamics and save an animated GIF."""
        names, times, positions = self._validate_trajectory(
            joint_names=joint_names,
            timestamps=timestamps,
            joint_positions=joint_positions,
        )
        if output_path.suffix.lower() != ".gif":
            raise ValueError(f"Action preview path must end in .gif: {output_path}")
        if not camera_views:
            raise ValueError("At least one action preview camera is required")
        if len(set(camera_views)) != len(camera_views):
            raise ValueError("Action preview cameras must be unique")
        self.pose_helper.validate_image_size(width=view_width, height=view_height)
        if not math.isfinite(end_hold_seconds) or end_hold_seconds <= 0.0:
            raise ValueError("Action preview end hold must be finite and positive")

        with self._render_lock:
            frames = self._render_frames(
                joint_names=names,
                joint_positions=positions,
                camera_views=camera_views,
                view_width=view_width,
                view_height=view_height,
            )
        frame_durations_ms = self._frame_durations_ms(
            timestamps=times,
            end_hold_seconds=end_hold_seconds,
        )
        output_path.parent.mkdir(parents=True, exist_ok=True)
        frames[0].save(
            output_path,
            save_all=True,
            append_images=frames[1:],
            duration=frame_durations_ms,
            loop=0,
            disposal=2,
            optimize=False,
        )
        return output_path

    def _render_frames(
        self,
        *,
        joint_names: tuple[str, ...],
        joint_positions: NDArray[np.float64],
        camera_views: tuple[CameraView, ...],
        view_width: int,
        view_height: int,
    ) -> list[Image.Image]:
        model = self.pose_helper.model
        data = mujoco.MjData(model)
        renderer = mujoco.Renderer(model, height=view_height, width=view_width)
        frames: list[Image.Image] = []
        try:
            for sample in joint_positions:
                mujoco.mj_resetData(model, data)
                self.pose_helper.apply_joint_values(
                    data=data,
                    joint_values={
                        joint_name: float(value)
                        for joint_name, value in zip(joint_names, sample, strict=True)
                    },
                )
                mujoco.mj_forward(model, data)
                view_images = []
                for camera_view in camera_views:
                    renderer.update_scene(
                        data,
                        camera=self.pose_helper.create_camera(camera_view),
                    )
                    view_image = Image.fromarray(renderer.render().copy())
                    self._draw_camera_label(view_image, camera_view)
                    view_images.append(view_image)
                frames.append(
                    self._compose_camera_grid(
                        view_images=view_images,
                        view_width=view_width,
                        view_height=view_height,
                    )
                )
        finally:
            renderer.close()
        return frames

    def _compose_camera_grid(
        self,
        *,
        view_images: list[Image.Image],
        view_width: int,
        view_height: int,
    ) -> Image.Image:
        column_count = min(3, len(view_images))
        row_count = math.ceil(len(view_images) / column_count)
        canvas = Image.new(
            "RGB",
            (column_count * view_width, row_count * view_height),
            color=(0, 0, 0),
        )
        for index, view_image in enumerate(view_images):
            column = index % column_count
            row = index // column_count
            canvas.paste(view_image, (column * view_width, row * view_height))
        return canvas

    def _draw_camera_label(self, image: Image.Image, camera_view: CameraView) -> None:
        ImageDraw.Draw(image).text(
            (8, 8),
            self.CAMERA_LABELS[camera_view],
            fill=(255, 255, 255),
            stroke_width=2,
            stroke_fill=(0, 0, 0),
        )

    def _validate_trajectory(
        self,
        *,
        joint_names: Sequence[str],
        timestamps: Sequence[float] | NDArray[np.float64],
        joint_positions: Sequence[Sequence[float]] | NDArray[np.float64],
    ) -> tuple[tuple[str, ...], NDArray[np.float64], NDArray[np.float64]]:
        names = tuple(joint_names)
        if not names or len(set(names)) != len(names):
            raise ValueError("Action preview joint names must be non-empty and unique")
        if set(names) - set(self.pose_helper.joint_names):
            raise ValueError("Action preview contains unknown MuJoCo joints")
        times = np.asarray(timestamps, dtype=np.float64)
        positions = np.asarray(joint_positions, dtype=np.float64)
        if times.ndim != 1 or len(times) < 2 or not np.all(np.isfinite(times)):
            raise ValueError("Action preview timestamps must be a finite one-dimensional array")
        if not math.isclose(float(times[0]), 0.0, abs_tol=1e-12) or not np.all(
            np.diff(times) > 0.0
        ):
            raise ValueError("Action preview timestamps must start at zero and increase")
        if positions.shape != (len(times), len(names)) or not np.all(
            np.isfinite(positions)
        ):
            raise ValueError("Action preview joint-position shape or values are invalid")
        return names, times, positions

    def _frame_durations_ms(
        self,
        *,
        timestamps: NDArray[np.float64],
        end_hold_seconds: float,
    ) -> list[int]:
        sample_durations = np.diff(timestamps)
        durations_ms = [max(10, round(float(duration) * 1_000)) for duration in sample_durations]
        durations_ms.append(max(10, round(end_hold_seconds * 1_000)))
        return durations_ms


def demo_mujoco_action_helper() -> None:
    logging.basicConfig(level=logging.INFO)
    settings = AppSettings()
    pose_helper = MujocoPoseHelper(
        mjcf_path=settings.g1_asset_dir / "g1_29dof_fake_hand.xml"
    )
    helper = MujocoActionHelper(pose_helper=pose_helper)
    joint_names = ("left_shoulder_roll_joint", "left_elbow_joint")
    output_path = settings.action_preview_dir / "mujoco_action_demo.gif"
    helper.render_trajectory_gif(
        joint_names=joint_names,
        timestamps=(0.0, 0.5, 1.0),
        joint_positions=((0.18, 1.4), (1.0, 0.6), (0.18, 1.4)),
        output_path=output_path,
    )
    LOGGER.info("Rendered MuJoCo action preview: %s", output_path)


def main() -> None:
    demo_mujoco_action_helper()


if __name__ == "__main__":
    main()
