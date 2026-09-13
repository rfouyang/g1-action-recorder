"""Validate and render the canonical Unitree G1 robot assets."""

from __future__ import annotations

import json
import logging
import math
import xml.etree.ElementTree as element_tree
from dataclasses import dataclass
from pathlib import Path

import mujoco
import numpy as np

from config.settings import AppSettings
from util.mujoco_pose_helper import MujocoPoseHelper

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class G1AssetReport:
    """Summary of the validated G1 model contract."""

    robot_joint_count: int
    upper_body_joint_count: int
    actuator_count: int
    mesh_count: int


@dataclass(frozen=True, slots=True)
class G1ModelJointSpec:
    """Joint information read from the canonical G1 URDF."""

    name: str
    axis: tuple[float, float, float]
    lower_limit: float
    upper_limit: float


class G1AssetHelper:
    """Check agreement between the G1 URDF, MJCF, and mesh files."""

    EXPECTED_ROBOT_JOINT_COUNT = 29
    EXPECTED_UPPER_BODY_JOINT_COUNT = 17
    UPPER_BODY_PREFIXES = ("waist_", "left_shoulder_", "left_elbow_", "left_wrist_")
    RIGHT_ARM_PREFIXES = ("right_shoulder_", "right_elbow_", "right_wrist_")
    FAKE_HAND_LINKS = frozenset({"left_rubber_hand", "right_rubber_hand"})

    def __init__(self, *, asset_dir: Path) -> None:
        self.asset_dir = asset_dir
        self.urdf_path = asset_dir / "g1_29dof_fake_hand.urdf"
        self.mjcf_path = asset_dir / "g1_29dof_fake_hand.xml"
        self.mesh_dir = asset_dir / "meshes"

    def validate(self) -> G1AssetReport:
        """Raise a descriptive error when the two model formats disagree."""
        urdf_root = element_tree.parse(self.urdf_path).getroot()
        model = mujoco.MjModel.from_xml_path(str(self.mjcf_path))

        urdf_joints = self._urdf_movable_joints(urdf_root)
        mjcf_joints = self._mjcf_movable_joints(model)
        if len(urdf_joints) != self.EXPECTED_ROBOT_JOINT_COUNT:
            raise ValueError(f"URDF has {len(urdf_joints)} movable joints; expected 29")
        if len(mjcf_joints) != self.EXPECTED_ROBOT_JOINT_COUNT:
            raise ValueError(f"MJCF has {len(mjcf_joints)} movable joints; expected 29")
        if set(urdf_joints) != set(mjcf_joints):
            raise ValueError("URDF and MJCF movable joint names do not match")

        for joint_name, urdf_joint in urdf_joints.items():
            mjcf_joint = mjcf_joints[joint_name]
            self._validate_joint_contract(joint_name, urdf_joint, mjcf_joint)

        self._validate_fake_hands(urdf_root, urdf_joints, model)
        referenced_meshes = self._referenced_meshes(urdf_root)
        missing_meshes = sorted(
            mesh_name
            for mesh_name in referenced_meshes
            if not (self.mesh_dir / mesh_name).is_file()
        )
        if missing_meshes:
            raise ValueError(f"Missing G1 meshes: {', '.join(missing_meshes)}")

        actuator_joint_names = {
            mujoco.mj_id2name(model, mujoco.mjtObj.mjOBJ_JOINT, int(joint_id))
            for joint_id in model.actuator_trnid[:, 0]
        }
        if actuator_joint_names != set(mjcf_joints):
            raise ValueError("MJCF actuators do not cover exactly the 29 movable robot joints")

        upper_body_joint_count = sum(
            joint_name.startswith(self.UPPER_BODY_PREFIXES + self.RIGHT_ARM_PREFIXES)
            for joint_name in urdf_joints
        )
        if upper_body_joint_count != self.EXPECTED_UPPER_BODY_JOINT_COUNT:
            raise ValueError(f"Model has {upper_body_joint_count} upper-body joints; expected 17")

        return G1AssetReport(
            robot_joint_count=len(urdf_joints),
            upper_body_joint_count=upper_body_joint_count,
            actuator_count=model.nu,
            mesh_count=len(referenced_meshes),
        )

    def load_joint_specs(self) -> dict[str, G1ModelJointSpec]:
        """Load movable joint axes and limits from the canonical URDF."""
        urdf_root = element_tree.parse(self.urdf_path).getroot()
        urdf_joints = self._urdf_movable_joints(urdf_root)
        return {
            joint_name: G1ModelJointSpec(
                name=joint_name,
                axis=tuple(float(value) for value in axis),
                lower_limit=limits[0],
                upper_limit=limits[1],
            )
            for joint_name, (axis, limits) in urdf_joints.items()
        }

    def load_metadata(self) -> dict[str, object]:
        """Load the checked-in model metadata document."""
        metadata_path = self.asset_dir / "model_metadata.json"
        return json.loads(metadata_path.read_text(encoding="utf-8"))

    def render_neutral_pose(
        self,
        *,
        output_path: Path,
        width: int = 640,
        height: int = 480,
    ) -> Path:
        """Render the model's neutral configuration without advancing physics."""
        return MujocoPoseHelper(mjcf_path=self.mjcf_path).render_joint_values_to_file(
            joint_values={},
            output_path=output_path,
            width=width,
            height=height,
        )

    def _urdf_movable_joints(
        self, urdf_root: element_tree.Element
    ) -> dict[str, tuple[np.ndarray, tuple[float, float]]]:
        joints: dict[str, tuple[np.ndarray, tuple[float, float]]] = {}
        for joint in urdf_root.findall("joint"):
            if joint.attrib["type"] in {"fixed", "floating"}:
                continue
            axis_element = joint.find("axis")
            limit_element = joint.find("limit")
            if axis_element is None or limit_element is None:
                raise ValueError(f"URDF joint {joint.attrib['name']} lacks axis or limits")
            joints[joint.attrib["name"]] = (
                np.fromstring(axis_element.attrib["xyz"], sep=" "),
                (float(limit_element.attrib["lower"]), float(limit_element.attrib["upper"])),
            )
        return joints

    def _mjcf_movable_joints(
        self, model: mujoco.MjModel
    ) -> dict[str, tuple[np.ndarray, tuple[float, float]]]:
        joints: dict[str, tuple[np.ndarray, tuple[float, float]]] = {}
        for joint_id in range(model.njnt):
            if model.jnt_type[joint_id] == mujoco.mjtJoint.mjJNT_FREE:
                continue
            joint_name = mujoco.mj_id2name(model, mujoco.mjtObj.mjOBJ_JOINT, joint_id)
            if joint_name is None:
                raise ValueError(f"MJCF joint {joint_id} has no name")
            joints[joint_name] = (
                model.jnt_axis[joint_id].copy(),
                tuple(float(value) for value in model.jnt_range[joint_id]),
            )
        return joints

    def _validate_joint_contract(
        self,
        joint_name: str,
        urdf_joint: tuple[np.ndarray, tuple[float, float]],
        mjcf_joint: tuple[np.ndarray, tuple[float, float]],
    ) -> None:
        urdf_axis, urdf_limits = urdf_joint
        mjcf_axis, mjcf_limits = mjcf_joint
        if not np.allclose(urdf_axis, mjcf_axis, atol=1e-7):
            raise ValueError(f"Joint axis mismatch for {joint_name}")
        if not all(
            math.isclose(urdf_value, mjcf_value, abs_tol=1e-5)
            for urdf_value, mjcf_value in zip(urdf_limits, mjcf_limits, strict=True)
        ):
            raise ValueError(f"Joint limit mismatch for {joint_name}")

    def _validate_fake_hands(
        self,
        urdf_root: element_tree.Element,
        urdf_joints: dict[str, tuple[np.ndarray, tuple[float, float]]],
        model: mujoco.MjModel,
    ) -> None:
        fixed_hand_links = {
            child.attrib["link"]
            for joint in urdf_root.findall("joint")
            if joint.attrib["type"] == "fixed"
            for child in joint.findall("child")
            if child.attrib.get("link") in self.FAKE_HAND_LINKS
        }
        if fixed_hand_links != self.FAKE_HAND_LINKS:
            raise ValueError("URDF rubber hands are not both attached with fixed joints")
        if any("hand" in joint_name or "rubber" in joint_name for joint_name in urdf_joints):
            raise ValueError("URDF fake hands unexpectedly add movable joints")

        mesh_names = {
            mujoco.mj_id2name(model, mujoco.mjtObj.mjOBJ_MESH, mesh_id)
            for mesh_id in range(model.nmesh)
        }
        if not self.FAKE_HAND_LINKS.issubset(mesh_names):
            raise ValueError("MJCF does not contain both rubber-hand meshes")

    def _referenced_meshes(self, urdf_root: element_tree.Element) -> set[str]:
        urdf_meshes = {
            Path(mesh.attrib["filename"]).name
            for mesh in urdf_root.findall(".//mesh")
            if "filename" in mesh.attrib
        }
        mjcf_root = element_tree.parse(self.mjcf_path).getroot()
        mjcf_meshes = {
            Path(mesh.attrib["file"]).name
            for mesh in mjcf_root.findall(".//mesh")
            if "file" in mesh.attrib
        }
        if urdf_meshes != mjcf_meshes:
            raise ValueError("URDF and MJCF mesh references do not match")
        return urdf_meshes


def demo_g1_asset_helper() -> None:
    logging.basicConfig(level=logging.INFO)
    settings = AppSettings()
    helper = G1AssetHelper(asset_dir=settings.g1_asset_dir)
    report = helper.validate()
    preview_path = helper.render_neutral_pose(
        output_path=settings.pose_preview_dir / "neutral_pose.png"
    )
    LOGGER.info("Validated G1 assets: %s", report)
    LOGGER.info("Neutral pose preview: %s", preview_path)


def main() -> None:
    demo_g1_asset_helper()


if __name__ == "__main__":
    main()
