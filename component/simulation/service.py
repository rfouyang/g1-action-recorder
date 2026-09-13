"""Own the current G1 MuJoCo state independently of any presentation layer."""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Mapping
from dataclasses import dataclass

import mujoco

from component.common.g1_joint_schema import G1JointSchema
from util.mujoco_pose_helper import MujocoPoseHelper

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class SimulationSnapshot:
    """Immutable joint and root transforms copied from one MuJoCo revision."""

    revision: int
    updated_at: float
    joint_names: tuple[str, ...]
    joint_positions: tuple[float, ...]
    base_position: tuple[float, float, float]
    base_wxyz: tuple[float, float, float, float]

    def joint_position_map(self) -> dict[str, float]:
        """Return positions keyed by canonical G1 joint name."""
        return dict(zip(self.joint_names, self.joint_positions, strict=True))


class SimulationService:
    """Apply validated joint positions and expose synchronized MuJoCo snapshots."""

    def __init__(
        self,
        *,
        schema: G1JointSchema,
        pose_helper: MujocoPoseHelper,
        initial_joint_positions: Mapping[str, object] | None = None,
    ) -> None:
        self.schema = schema
        self.pose_helper = pose_helper
        self._data = mujoco.MjData(pose_helper.model)
        self._condition = threading.Condition()
        self._revision = 0
        self._updated_at = time.time()
        self._joint_qpos_addresses = self._load_joint_qpos_addresses()
        self._pelvis_body_id = mujoco.mj_name2id(
            pose_helper.model,
            mujoco.mjtObj.mjOBJ_BODY,
            "pelvis",
        )
        mujoco.mj_forward(self.pose_helper.model, self._data)
        if initial_joint_positions:
            self.update_joint_positions(initial_joint_positions)

    def update_joint_positions(
        self,
        joint_positions: Mapping[str, object],
    ) -> SimulationSnapshot:
        """Apply a partial validated configuration and run MuJoCo kinematics."""
        if not joint_positions:
            raise ValueError("At least one joint position is required")
        unknown = sorted(set(joint_positions) - set(self.schema.DDS_JOINT_NAMES))
        if unknown:
            raise ValueError(f"Unknown G1 joints: {unknown}")

        with self._condition:
            self.pose_helper.apply_joint_values(
                data=self._data,
                joint_values=joint_positions,
            )
            mujoco.mj_forward(self.pose_helper.model, self._data)
            self._revision += 1
            self._updated_at = time.time()
            snapshot = self._snapshot_unlocked()
            self._condition.notify_all()
            return snapshot

    def snapshot(self) -> SimulationSnapshot:
        """Copy the latest complete state without exposing mutable MuJoCo data."""
        with self._condition:
            return self._snapshot_unlocked()

    def wait_for_revision(
        self,
        *,
        after_revision: int,
        timeout: float,
    ) -> SimulationSnapshot:
        """Wait for a newer state or return the current state after a timeout."""
        with self._condition:
            self._condition.wait_for(
                lambda: self._revision > after_revision,
                timeout=timeout,
            )
            return self._snapshot_unlocked()

    def _snapshot_unlocked(self) -> SimulationSnapshot:
        joint_positions = tuple(
            float(self._data.qpos[address])
            for address in self._joint_qpos_addresses
        )
        base_position = tuple(
            float(value) for value in self._data.xpos[self._pelvis_body_id]
        )
        base_wxyz = tuple(
            float(value) for value in self._data.xquat[self._pelvis_body_id]
        )
        return SimulationSnapshot(
            revision=self._revision,
            updated_at=self._updated_at,
            joint_names=self.schema.DDS_JOINT_NAMES,
            joint_positions=joint_positions,
            base_position=base_position,
            base_wxyz=base_wxyz,
        )

    def _load_joint_qpos_addresses(self) -> tuple[int, ...]:
        addresses = []
        for joint_name in self.schema.DDS_JOINT_NAMES:
            joint_id = mujoco.mj_name2id(
                self.pose_helper.model,
                mujoco.mjtObj.mjOBJ_JOINT,
                joint_name,
            )
            if joint_id < 0:
                raise ValueError(f"MuJoCo model is missing G1 joint: {joint_name}")
            addresses.append(int(self.pose_helper.model.jnt_qposadr[joint_id]))
        return tuple(addresses)


def demo_simulation_service() -> None:
    from component.common.g1_joint_schema import G1JointSchema
    from config.settings import AppSettings
    from util.g1_asset_helper import G1AssetHelper

    logging.basicConfig(level=logging.INFO)
    settings = AppSettings()
    assets = G1AssetHelper(asset_dir=settings.g1_asset_dir)
    schema = G1JointSchema(asset_helper=assets)
    service = SimulationService(
        schema=schema,
        pose_helper=MujocoPoseHelper(mjcf_path=assets.mjcf_path),
    )
    snapshot = service.update_joint_positions({"left_elbow_joint": 1.0})
    LOGGER.info("MuJoCo simulation revision %d", snapshot.revision)


def main() -> None:
    demo_simulation_service()


if __name__ == "__main__":
    main()
