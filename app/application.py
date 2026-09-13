"""Assemble the long-lived business capabilities for the G1 application."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from component.action_playback_service import ActionPlayback
from component.action_player_service import ActionPlayerService
from component.action_service import ActionService
from component.common.g1_joint_schema import G1JointSchema
from component.pose_service import PoseService
from component.simulation import SimulationService
from config.settings import AppSettings
from util.ardy_action_helper import ArdyActionHelper
from util.g1_asset_helper import G1AssetHelper
from util.g1_motion_conversion_helper import G1MotionConversionHelper
from util.kimodo_action_helper import KimodoActionHelper
from util.mujoco_action_helper import MujocoActionHelper
from util.mujoco_pose_helper import MujocoPoseHelper
from util.numpy_archive_helper import NumpyArchiveHelper
from util.pink_ik_helper import PinkIKHelper
from util.pose_file_helper import PoseFileHelper

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class RobotApplication:
    """Own the shared G1 business services used by presentation surfaces."""

    settings: AppSettings
    joint_schema: G1JointSchema
    simulation: SimulationService
    pose_service: PoseService
    action_service: ActionService
    action_player: ActionPlayerService

    @classmethod
    def create(
        cls,
        *,
        settings: AppSettings | None = None,
        pose_dir: Path | None = None,
        action_definition_dir: Path | None = None,
        action_trajectory_dir: Path | None = None,
        action_preview_dir: Path | None = None,
    ) -> RobotApplication:
        """Build the current pose and action capabilities from one configuration."""
        resolved_settings = settings or AppSettings()
        resolved_settings.ensure_runtime_directories()

        asset_helper = G1AssetHelper(asset_dir=resolved_settings.g1_asset_dir)
        joint_schema = G1JointSchema(asset_helper=asset_helper)
        simulation_helper = MujocoPoseHelper(mjcf_path=asset_helper.mjcf_path)
        file_helper = PoseFileHelper()
        pose_service = PoseService(
            schema=joint_schema,
            pose_dir=pose_dir or resolved_settings.pose_dir,
            file_helper=file_helper,
            simulation_helper=simulation_helper,
        )
        initial_pose = pose_service.load_initial_base_pose(
            name=resolved_settings.initial_base_pose_name
        )
        simulation = SimulationService(
            schema=joint_schema,
            pose_helper=simulation_helper,
            initial_joint_positions=initial_pose.joint_values,
        )
        archive_helper = NumpyArchiveHelper()
        action_service = ActionService(
            schema=joint_schema,
            action_definition_dir=(
                action_definition_dir or resolved_settings.action_definition_dir
            ),
            file_helper=file_helper,
            pose_service=pose_service,
            ik_helper=PinkIKHelper(urdf_path=asset_helper.urdf_path),
            action_trajectory_dir=(
                action_trajectory_dir or resolved_settings.action_trajectory_dir
            ),
            archive_helper=archive_helper,
            action_preview_helper=MujocoActionHelper(pose_helper=simulation_helper),
            action_preview_dir=action_preview_dir or resolved_settings.action_preview_dir,
        )
        conversion_helper = G1MotionConversionHelper(
            schema=joint_schema,
            mjcf_path=asset_helper.mjcf_path,
        )
        initial_joint_positions = simulation.snapshot().joint_position_map()
        playback = ActionPlayback(
            simulation=simulation,
            locked_joint_positions={
                **{
                    name: initial_joint_positions[name]
                    for name in joint_schema.LEG_JOINT_NAMES
                },
                **{
                    name: initial_pose.joint_values[name]
                    for name in joint_schema.WAIST_JOINT_NAMES
                },
            },
        )
        action_player = ActionPlayerService(
            schema=joint_schema,
            initial_pose=initial_pose,
            action_service=action_service,
            playback=playback,
            pose_service=pose_service,
            kimodo_helper=KimodoActionHelper(
                archive_helper=archive_helper,
                conversion_helper=conversion_helper,
            ),
            ardy_helper=ArdyActionHelper(conversion_helper=conversion_helper),
        )
        return cls(
            settings=resolved_settings,
            joint_schema=joint_schema,
            simulation=simulation,
            pose_service=pose_service,
            action_service=action_service,
            action_player=action_player,
        )


def demo_robot_application() -> None:
    logging.basicConfig(level=logging.INFO)
    application = RobotApplication.create()
    LOGGER.info(
        "Created G1 application for %s with %d joints",
        application.joint_schema.model_id,
        len(application.joint_schema.definitions),
    )


def main() -> None:
    demo_robot_application()


if __name__ == "__main__":
    main()
