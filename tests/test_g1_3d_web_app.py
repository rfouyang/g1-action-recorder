"""Tests for the independent G1 3D UI and API presentation surfaces."""

from __future__ import annotations

import tempfile
import time
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from app.application import RobotApplication
from app.g1_3d_main import create_web_app
from component.common.g1_joint_schema import PoseType
from config.settings import AppSettings


class G13DWebAppTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        temporary_root = Path(self.temporary_directory.name)
        settings = AppSettings(viser_port=0)
        self.robot_application = RobotApplication.create(
            settings=settings,
            pose_dir=temporary_root / "poses",
            action_definition_dir=temporary_root / "actions",
            action_trajectory_dir=temporary_root / "trajectories",
            action_preview_dir=temporary_root / "previews",
        )
        self.client = TestClient(
            create_web_app(robot_application=self.robot_application)
        )
        self.client.__enter__()

    def tearDown(self) -> None:
        self.client.__exit__(None, None, None)
        self.temporary_directory.cleanup()

    def test_ui_exposes_three_workspaces_and_six_camera_presets(self) -> None:
        response = self.client.get("/")

        self.assertEqual(response.status_code, 200)
        self.assertIn("Pose Recorder", response.text)
        self.assertIn("Pose Composer", response.text)
        self.assertIn("Action", response.text)
        for camera_label in (
            "Front",
            "Back",
            "Left",
            "Right",
            "Front-left 45°",
            "Front-right 45°",
        ):
            self.assertIn(camera_label, response.text)
        self.assertIn(
            f'data-viser-port="{self.client.app.state.viser.port}"',
            response.text,
        )
        self.assertNotIn("Viser scene connects in the next step", response.text)
        self.assertEqual(response.text.count("data-camera-view="), 6)

    def test_pose_recorder_renders_anatomical_joint_inspector(self) -> None:
        response = self.client.get("/")

        self.assertEqual(response.status_code, 200)
        self.assertIn('data-theme="wireframe"', response.text)
        self.assertIn('data-theme="dark"', response.text)
        self.assertIn("Base · complete upper body", response.text)
        self.assertIn("Robot-left arm", response.text)
        self.assertIn("Robot-right arm", response.text)
        self.assertIn("Target", response.text)
        self.assertIn("Actual", response.text)
        self.assertEqual(response.text.count("data-joint-row"), 17)
        self.assertEqual(response.text.count("data-joint-target\n"), 17)
        self.assertIn('data-joint-name="left_elbow_joint"', response.text)
        self.assertIn('data-joint-group="left_arm"', response.text)
        self.assertIn('data-joint-group="right_arm"', response.text)
        self.assertIn('badge-secondary badge-sm">Robot-left arm', response.text)
        self.assertIn('badge-accent badge-sm">Robot-right arm', response.text)
        self.assertIn("range-secondary", response.text)
        self.assertIn("range-accent", response.text)
        self.assertIn('value="concierge_init"', response.text)
        self.assertEqual(response.text.count("data-joint-reset"), 17)
        self.assertNotIn(
            'id="save-pose" class="btn btn-sm btn-neutral" type="button" disabled',
            response.text,
        )

    def test_pose_recorder_saves_selected_simulation_group(self) -> None:
        left_joint_positions = {
            name: 0.0
            for name in self.robot_application.joint_schema.LEFT_ARM_JOINT_NAMES
        }
        left_joint_positions["left_elbow_joint"] = 0.75

        response = self.client.post(
            "/ui/g1-3d/poses",
            json={
                "pose_type": "left_arm",
                "name": "saved_from_3d_ui",
                "notes": "UI save test",
                "joint_positions": left_joint_positions,
                "overwrite": False,
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["pose_type"], "left_arm")
        saved = self.robot_application.pose_service.load_pose(
            pose_type=PoseType.LEFT_ARM,
            name="saved_from_3d_ui",
        )
        self.assertEqual(saved.joint_values["left_elbow_joint"], 0.75)
        self.assertEqual(saved.notes, "UI save test")

    def test_pose_recorder_requires_explicit_replacement(self) -> None:
        left_joint_positions = {
            name: 0.0
            for name in self.robot_application.joint_schema.LEFT_ARM_JOINT_NAMES
        }
        command = {
            "pose_type": "left_arm",
            "name": "protected_pose",
            "notes": "",
            "joint_positions": left_joint_positions,
            "overwrite": False,
        }

        first = self.client.post("/ui/g1-3d/poses", json=command)
        second = self.client.post("/ui/g1-3d/poses", json=command)
        command["overwrite"] = True
        replacement = self.client.post("/ui/g1-3d/poses", json=command)

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 409)
        self.assertIn("already exists", second.json()["detail"])
        self.assertEqual(replacement.status_code, 200)

    def test_pose_composer_renders_saved_anatomical_sources(self) -> None:
        self._save_composer_sources()

        response = self.client.get("/")

        self.assertEqual(response.status_code, 200)
        self.assertIn("Robot-left arm override · optional", response.text)
        self.assertIn("Robot-right arm override · optional", response.text)
        self.assertIn('value="concierge_init" selected', response.text)
        self.assertIn('value="left_greeting"', response.text)
        self.assertIn('value="right_greeting"', response.text)
        self.assertIn("pose_composer.js", response.text)
        self.assertNotIn(
            'id="save-composition" class="btn btn-sm btn-neutral mt-3 w-full" '
            'type="button" disabled',
            response.text,
        )

    def test_pose_composer_preview_updates_mujoco_and_viser(self) -> None:
        self._save_composer_sources()

        response = self.client.post(
            "/ui/g1-3d/pose-composer/preview",
            json={
                "base_pose": "concierge_init",
                "left_arm_pose": "left_greeting",
                "right_arm_pose": "right_greeting",
            },
        )

        self.assertEqual(response.status_code, 200)
        result = response.json()
        self.assertEqual(
            result["source_parts"],
            {
                "base": "concierge_init",
                "left_arm": "left_greeting",
                "right_arm": "right_greeting",
            },
        )
        snapshot = self.robot_application.simulation.snapshot()
        self.assertEqual(
            snapshot.joint_position_map()["left_shoulder_roll_joint"],
            0.5,
        )
        self.assertEqual(
            snapshot.joint_position_map()["right_shoulder_roll_joint"],
            -0.5,
        )
        deadline = time.monotonic() + 1.0
        while (
            self.client.app.state.viser.synced_revision < result["revision"]
            and time.monotonic() < deadline
        ):
            time.sleep(0.01)
        self.assertEqual(
            self.client.app.state.viser.synced_revision,
            result["revision"],
        )

    def test_pose_composer_saves_final_pose_with_source_parts(self) -> None:
        self._save_composer_sources()
        command = {
            "base_pose": "concierge_init",
            "left_arm_pose": "left_greeting",
            "right_arm_pose": None,
            "name": "composed_greeting",
            "notes": "Keeps the base robot-right arm",
            "overwrite": False,
        }

        response = self.client.post(
            "/ui/g1-3d/pose-composer/save",
            json=command,
        )
        duplicate = self.client.post(
            "/ui/g1-3d/pose-composer/save",
            json=command,
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(duplicate.status_code, 409)
        saved = self.robot_application.pose_service.load_pose(
            pose_type=PoseType.COMPOSED,
            name="composed_greeting",
        )
        self.assertEqual(
            dict(saved.source_parts),
            {"base": "concierge_init", "left_arm": "left_greeting"},
        )
        self.assertEqual(saved.notes, "Keeps the base robot-right arm")

    def test_action_panel_renders_complete_pose_sequence_controls(self) -> None:
        self._save_action_source()

        response = self.client.get("/")

        self.assertEqual(response.status_code, 200)
        self.assertIn("Every action starts and returns to", response.text)
        self.assertIn("base/concierge_init", response.text)
        self.assertIn("Composed · composed_greeting", response.text)
        self.assertIn('id="action-add-frame"', response.text)
        self.assertIn('id="action-save"', response.text)
        self.assertIn('id="action-compile"', response.text)
        self.assertIn('id="action-play"', response.text)
        self.assertIn('id="action-pause"', response.text)
        self.assertIn('id="action-stop"', response.text)
        self.assertIn('id="action-playback-progress"', response.text)
        self.assertIn('id="action-playback-phase"', response.text)
        self.assertIn('id="action-playback-path"', response.text)
        self.assertIn("action.js", response.text)

    def test_action_definition_can_be_saved_and_loaded_for_editing(self) -> None:
        self._save_action_source()
        command = self._action_command(name="welcome_action")

        saved_response = self.client.post("/ui/g1-3d/action/save", json=command)
        duplicate_response = self.client.post("/ui/g1-3d/action/save", json=command)
        loaded_response = self.client.get(
            "/ui/g1-3d/action/definitions/welcome_action"
        )

        self.assertEqual(saved_response.status_code, 200)
        self.assertEqual(saved_response.json()["keyframe_count"], 3)
        self.assertEqual(duplicate_response.status_code, 409)
        self.assertEqual(loaded_response.status_code, 200)
        loaded = loaded_response.json()
        self.assertEqual(loaded["name"], "welcome_action")
        self.assertEqual(loaded["frames"], command["frames"])
        self.assertEqual(
            loaded["return_duration_seconds"],
            command["return_duration_seconds"],
        )
        action = self.robot_application.action_service.load_action(
            name="welcome_action"
        )
        self.assertEqual(action.initial_pose.name, "concierge_init")
        self.assertEqual(action.transitions[-1].target_pose.name, "concierge_init")

    def test_action_compiles_and_downloads_validated_npz(self) -> None:
        self._save_action_source()
        command = {
            **self._action_command(name="compiled_welcome"),
            "sample_frequency_hz": 10.0,
        }

        response = self.client.post("/ui/g1-3d/action/compile", json=command)

        self.assertEqual(response.status_code, 200)
        result = response.json()
        self.assertGreater(result["sample_count"], 2)
        self.assertEqual(result["sample_frequency_hz"], 10.0)
        trajectory = self.robot_application.action_service.load_trajectory(
            name="compiled_welcome"
        )
        self.assertEqual(trajectory.sample_count, result["sample_count"])
        download = self.client.get(result["download_url"])
        duplicate = self.client.post("/ui/g1-3d/action/compile", json=command)
        self.assertEqual(download.status_code, 200)
        self.assertEqual(download.content[:2], b"PK")
        self.assertEqual(duplicate.status_code, 409)
        self.assertIn(
            "compiled_welcome",
            self.client.get("/ui/g1-3d/action/sources").json()["compiled_actions"],
        )

    def test_action_frame_preview_updates_shared_simulation(self) -> None:
        self._save_action_source()

        response = self.client.post(
            "/ui/g1-3d/action/preview-pose",
            json={"pose_type": "composed", "name": "composed_greeting"},
        )

        self.assertEqual(response.status_code, 200)
        snapshot = self.robot_application.simulation.snapshot()
        self.assertEqual(
            snapshot.joint_position_map()["left_shoulder_roll_joint"],
            0.5,
        )

    def test_action_playback_routes_control_compiled_trajectory(self) -> None:
        self._save_action_source()
        command = {
            **self._action_command(name="playable_welcome"),
            "sample_frequency_hz": 10.0,
        }
        compiled = self.client.post("/ui/g1-3d/action/compile", json=command)
        self.assertEqual(compiled.status_code, 200)

        started = self.client.post(
            "/ui/g1-3d/action/playback/play",
            json={"action_name": "playable_welcome", "loop": True},
        )
        paused = self.client.post("/ui/g1-3d/action/playback/pause")
        resumed = self.client.post("/ui/g1-3d/action/playback/resume")
        stopped = self.client.post("/ui/g1-3d/action/playback/stop")

        self.assertEqual(started.json()["state"], "playing")
        self.assertEqual(started.json()["phase"], "keyframe")
        self.assertEqual(started.json()["target_pose_name"], "concierge_init")
        self.assertEqual(paused.json()["state"], "paused")
        self.assertEqual(resumed.json()["state"], "playing")
        self.assertEqual(stopped.json()["state"], "stopped")
        self.assertEqual(stopped.json()["sample_index"], 0)

    def test_action_playback_websocket_reports_initial_state(self) -> None:
        with self.client.websocket_connect(
            "/ui/g1-3d/action/playback/ws"
        ) as websocket:
            state = websocket.receive_json()

        self.assertEqual(state["type"], "action_playback")
        self.assertEqual(state["state"], "idle")
        self.assertEqual(state["progress"], 0.0)
        self.assertEqual(state["phase"], "none")
        self.assertIsNone(state["target_pose_name"])

    def test_ui_websocket_updates_simulation_without_api_dependency(self) -> None:
        with self.client.websocket_connect(
            "/ui/g1-3d/simulation/ws"
        ) as websocket:
            initial_state = websocket.receive_json()
            websocket.send_json(
                {"joint_positions": {"left_shoulder_roll_joint": 0.4}}
            )
            updated_state = websocket.receive_json()

        self.assertEqual(initial_state["type"], "simulation_state")
        self.assertEqual(updated_state["type"], "simulation_state")
        self.assertEqual(
            updated_state["joint_positions"]["left_shoulder_roll_joint"],
            0.4,
        )
        deadline = time.monotonic() + 1.0
        while (
            self.client.app.state.viser.synced_revision
            < updated_state["revision"]
            and time.monotonic() < deadline
        ):
            time.sleep(0.01)
        self.assertEqual(
            self.client.app.state.viser.synced_revision,
            updated_state["revision"],
        )

    def test_api_health_uses_the_shared_application(self) -> None:
        response = self.client.get("/api/g1/system/health")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {
                "status": "ok",
                "model_id": self.robot_application.joint_schema.model_id,
                "runtime": "simulation",
            },
        )

    def test_compiled_daisyui_styles_are_served_locally(self) -> None:
        response = self.client.get("/static/g1-3d/css/app.css")

        self.assertEqual(response.status_code, 200)
        self.assertIn(".navbar", response.text)
        self.assertIn(".viewer-grid", response.text)

    def test_rest_joint_update_reaches_mujoco_and_viser(self) -> None:
        response = self.client.put(
            "/api/g1/simulation/joints",
            json={"joint_positions": {"left_elbow_joint": 1.0}},
        )

        self.assertEqual(response.status_code, 200)
        state = response.json()
        self.assertEqual(state["joint_positions"]["left_elbow_joint"], 1.0)

        deadline = time.monotonic() + 1.0
        while (
            self.client.app.state.viser.synced_revision < state["revision"]
            and time.monotonic() < deadline
        ):
            time.sleep(0.01)
        self.assertEqual(
            self.client.app.state.viser.synced_revision,
            state["revision"],
        )

    def test_websocket_accepts_joint_updates_and_streams_state(self) -> None:
        with self.client.websocket_connect("/api/g1/simulation/ws") as websocket:
            initial_state = websocket.receive_json()
            websocket.send_json(
                {"joint_positions": {"right_elbow_joint": 0.8}}
            )
            updated_state = websocket.receive_json()

        self.assertEqual(initial_state["type"], "simulation_state")
        self.assertEqual(updated_state["type"], "simulation_state")
        self.assertGreater(updated_state["revision"], initial_state["revision"])
        self.assertEqual(
            updated_state["joint_positions"]["right_elbow_joint"],
            0.8,
        )

    def test_camera_endpoint_accepts_all_robot_relative_views(self) -> None:
        for camera_view in (
            "front",
            "back",
            "left",
            "right",
            "front_left_45",
            "front_right_45",
        ):
            with self.subTest(camera_view=camera_view):
                response = self.client.post(
                    f"/ui/g1-3d/viewer/camera/{camera_view}"
                )
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json()["camera_view"], camera_view)

    def _save_composer_sources(self) -> None:
        schema = self.robot_application.joint_schema
        service = self.robot_application.pose_service
        base = service.create_simulated_pose(
            name="concierge_init",
            pose_type=PoseType.BASE,
            joint_values=schema.neutral_values(PoseType.BASE),
        )
        left_values = schema.neutral_values(PoseType.LEFT_ARM)
        left_values["left_shoulder_roll_joint"] = 0.5
        left = service.create_simulated_pose(
            name="left_greeting",
            pose_type=PoseType.LEFT_ARM,
            joint_values=left_values,
        )
        right = service.mirror_arm_pose(
            source_pose=left,
            name="right_greeting",
        )
        for pose in (base, left, right):
            service.save_pose(pose=pose)

    def _save_action_source(self) -> None:
        self._save_composer_sources()
        response = self.client.post(
            "/ui/g1-3d/pose-composer/save",
            json={
                "base_pose": "concierge_init",
                "left_arm_pose": "left_greeting",
                "right_arm_pose": "right_greeting",
                "name": "composed_greeting",
                "notes": "Complete intermediate action pose",
                "overwrite": False,
            },
        )
        self.assertEqual(response.status_code, 200)

    def _action_command(self, *, name: str) -> dict[str, object]:
        return {
            "name": name,
            "notes": "Action route test",
            "frames": [
                {
                    "pose_type": "composed",
                    "name": "composed_greeting",
                    "duration_seconds": 1.2,
                    "hold_seconds": 0.3,
                }
            ],
            "return_duration_seconds": 0.8,
            "overwrite": False,
        }


def demo_test_g1_3d_web_app() -> None:
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(G13DWebAppTest)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    if not result.wasSuccessful():
        raise SystemExit(1)


def main() -> None:
    demo_test_g1_3d_web_app()


if __name__ == "__main__":
    main()
