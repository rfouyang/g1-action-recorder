"""Render validated G1 joint configurations with MuJoCo."""

from __future__ import annotations

import logging
import math
import threading
from collections.abc import Mapping
from enum import Enum
from numbers import Integral, Real
from pathlib import Path

import mujoco
import numpy as np
from numpy.typing import NDArray
from PIL import Image

from config.settings import AppSettings

LOGGER = logging.getLogger(__name__)


class CameraView(str, Enum):
    """Named robot-centric camera viewpoints used by the pose UI."""

    FRONT = "front"
    ROBOT_RIGHT = "robot_right"
    FRONT_RIGHT = "front_right"
    ROBOT_LEFT = "robot_left"
    FRONT_LEFT = "front_left"


class MujocoPoseHelper:
    """Apply named joints and render robot-centric MuJoCo previews."""

    DEFAULT_WIDTH = 640
    DEFAULT_HEIGHT = 480
    FRONT_CAMERA_AZIMUTH = 180.0
    FRONT_CAMERA_ELEVATION = -10.0
    FRONT_CAMERA_DISTANCE = 2.6
    FRONT_CAMERA_LOOKAT = (0.0, 0.0, 0.8)
    CAMERA_AZIMUTHS = {
        CameraView.FRONT: 180.0,
        CameraView.ROBOT_RIGHT: 90.0,
        CameraView.FRONT_RIGHT: 135.0,
        CameraView.ROBOT_LEFT: 270.0,
        CameraView.FRONT_LEFT: 225.0,
    }
    DEFAULT_CAMERA_VIEWS = (
        CameraView.FRONT,
        CameraView.ROBOT_RIGHT,
        CameraView.FRONT_RIGHT,
        CameraView.ROBOT_LEFT,
        CameraView.FRONT_LEFT,
    )

    def __init__(self, *, mjcf_path: Path) -> None:
        self.mjcf_path = mjcf_path
        self.model = mujoco.MjModel.from_xml_path(str(mjcf_path))
        self._joint_ids = self._load_scalar_joint_ids()
        self._render_lock = threading.Lock()

    @property
    def joint_names(self) -> tuple[str, ...]:
        return tuple(self._joint_ids)

    def render_joint_values(
        self,
        *,
        joint_values: Mapping[str, object],
        camera_view: CameraView = CameraView.FRONT,
        width: int = DEFAULT_WIDTH,
        height: int = DEFAULT_HEIGHT,
    ) -> NDArray[np.uint8]:
        """Render named joint values without advancing the physics simulation."""
        return self.render_joint_values_for_views(
            joint_values=joint_values,
            camera_views=(camera_view,),
            width=width,
            height=height,
        )[camera_view]

    def render_joint_values_for_views(
        self,
        *,
        joint_values: Mapping[str, object],
        camera_views: tuple[CameraView, ...] = DEFAULT_CAMERA_VIEWS,
        width: int = DEFAULT_WIDTH,
        height: int = DEFAULT_HEIGHT,
    ) -> dict[CameraView, NDArray[np.uint8]]:
        """Render one joint state from multiple cameras in a single GL context."""
        self.validate_image_size(width=width, height=height)
        if not camera_views:
            raise ValueError("At least one camera view is required")
        if len(set(camera_views)) != len(camera_views):
            raise ValueError("Camera views must be unique")
        with self._render_lock:
            data = mujoco.MjData(self.model)
            self.apply_joint_values(data=data, joint_values=joint_values)
            mujoco.mj_forward(self.model, data)

            renderer = mujoco.Renderer(self.model, height=height, width=width)
            try:
                rendered_views = {}
                for camera_view in camera_views:
                    renderer.update_scene(data, camera=self.create_camera(camera_view))
                    rendered_views[camera_view] = renderer.render().copy()
                return rendered_views
            finally:
                renderer.close()

    def render_joint_values_to_file(
        self,
        *,
        joint_values: Mapping[str, object],
        output_path: Path,
        camera_view: CameraView = CameraView.FRONT,
        width: int = DEFAULT_WIDTH,
        height: int = DEFAULT_HEIGHT,
    ) -> Path:
        """Render a configuration and save it as a PNG image."""
        if output_path.suffix.lower() != ".png":
            raise ValueError(f"Pose preview path must end in .png: {output_path}")
        pixels = self.render_joint_values(
            joint_values=joint_values,
            camera_view=camera_view,
            width=width,
            height=height,
        )
        output_path.parent.mkdir(parents=True, exist_ok=True)
        Image.fromarray(pixels).save(output_path)
        return output_path

    def apply_joint_values(
        self,
        *,
        data: mujoco.MjData,
        joint_values: Mapping[str, object],
    ) -> None:
        """Set scalar robot joints on fresh or reset MuJoCo data."""
        unknown_joint_names = sorted(set(joint_values) - set(self._joint_ids))
        if unknown_joint_names:
            raise ValueError(f"Unknown MuJoCo joints: {unknown_joint_names}")

        for joint_name, raw_value in joint_values.items():
            if isinstance(raw_value, bool) or not isinstance(raw_value, Real):
                raise ValueError(f"Joint {joint_name} must be a real number")
            value = float(raw_value)
            if not math.isfinite(value):
                raise ValueError(f"Joint {joint_name} must be finite")
            joint_id = self._joint_ids[joint_name]
            if self.model.jnt_limited[joint_id]:
                lower_limit, upper_limit = self.model.jnt_range[joint_id]
                if not lower_limit <= value <= upper_limit:
                    raise ValueError(
                        f"Joint {joint_name} value {value} is outside "
                        f"[{lower_limit}, {upper_limit}]"
                    )
            data.qpos[self.model.jnt_qposadr[joint_id]] = value

    def create_front_camera(self) -> mujoco.MjvCamera:
        """Build the shared front camera; robot-left appears image-right."""
        return self.create_camera(CameraView.FRONT)

    def create_camera(self, camera_view: CameraView) -> mujoco.MjvCamera:
        """Build a camera located on the named anatomical side of the robot."""
        camera = mujoco.MjvCamera()
        mujoco.mjv_defaultCamera(camera)
        camera.lookat[:] = self.FRONT_CAMERA_LOOKAT
        camera.distance = self.FRONT_CAMERA_DISTANCE
        camera.azimuth = self.CAMERA_AZIMUTHS[camera_view]
        camera.elevation = self.FRONT_CAMERA_ELEVATION
        return camera

    def validate_image_size(self, *, width: int, height: int) -> None:
        """Validate dimensions shared by pose and action renderers."""
        for dimension_name, dimension in (("width", width), ("height", height)):
            if isinstance(dimension, bool) or not isinstance(dimension, Integral):
                raise ValueError(f"Preview {dimension_name} must be an integer")
            if dimension <= 0:
                raise ValueError(f"Preview {dimension_name} must be positive")

    def _load_scalar_joint_ids(self) -> dict[str, int]:
        joint_ids: dict[str, int] = {}
        for joint_id in range(self.model.njnt):
            joint_type = int(self.model.jnt_type[joint_id])
            if joint_type not in {
                int(mujoco.mjtJoint.mjJNT_HINGE),
                int(mujoco.mjtJoint.mjJNT_SLIDE),
            }:
                continue
            joint_name = mujoco.mj_id2name(
                self.model,
                mujoco.mjtObj.mjOBJ_JOINT,
                joint_id,
            )
            if joint_name is None:
                raise ValueError(f"MuJoCo scalar joint {joint_id} has no name")
            joint_ids[joint_name] = joint_id
        return joint_ids

def demo_mujoco_pose_helper() -> None:
    logging.basicConfig(level=logging.INFO)
    settings = AppSettings()
    helper = MujocoPoseHelper(mjcf_path=settings.g1_asset_dir / "g1_29dof_fake_hand.xml")
    images = helper.render_joint_values_for_views(
        joint_values={
            "left_shoulder_roll_joint": 1.2,
            "left_elbow_joint": 0.6,
        },
    )
    settings.pose_preview_dir.mkdir(parents=True, exist_ok=True)
    for camera_view, pixels in images.items():
        preview_path = (
            settings.pose_preview_dir / f"simulated_left_greeting_{camera_view.value}.png"
        )
        Image.fromarray(pixels).save(preview_path)
        LOGGER.info("Rendered %s G1 pose preview: %s", camera_view.value, preview_path)


def main() -> None:
    demo_mujoco_pose_helper()


if __name__ == "__main__":
    main()
