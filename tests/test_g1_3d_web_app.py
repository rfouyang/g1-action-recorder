"""Tests for the independent G1 3D UI and API presentation surfaces."""

from __future__ import annotations

import tempfile
import time
import unittest
import wave
from pathlib import Path

from fastapi.testclient import TestClient

from app.application import RobotApplication
from app.g1_3d_main import create_web_app
from component.common.g1_joint_schema import PoseType
from config.settings import AppSettings


class FakeBytePlusTtsHelper:
    speaker = "test-speaker"

    def generate(
        self,
        text: str,
        output_path: Path,
        *,
        speaker: str | None = None,
        tone: str | None = None,
        emotion_strength: int = 4,
        speech_rate: int = 0,
        loudness_rate: int = 0,
        pitch: int = 0,
        style_instruction: str = "",
    ) -> Path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with wave.open(str(output_path), "wb") as wav_file:
            wav_file.setnchannels(1)
            wav_file.setsampwidth(2)
            wav_file.setframerate(16_000)
            wav_file.writeframes(b"\x00\x00" * 20_000)
        return output_path


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
            tts_dir=temporary_root / "tts",
            byteplus_helper=FakeBytePlusTtsHelper(),
        )
        self.client = TestClient(
            create_web_app(robot_application=self.robot_application)
        )
        self.client.__enter__()

    def tearDown(self) -> None:
        self.client.__exit__(None, None, None)
        self.temporary_directory.cleanup()

    def test_ui_exposes_five_workspaces_and_six_camera_presets(self) -> None:
        response = self.client.get("/")

        self.assertEqual(response.status_code, 200)
        self.assertIn("Pose Recorder", response.text)
        self.assertIn("Pose Composer", response.text)
        self.assertIn("Action Composer", response.text)
        self.assertIn("Action Player", response.text)
        self.assertIn("Speech", response.text)
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

    def test_speech_panel_generates_lists_and_downloads_wav(self) -> None:
        page = self.client.get("/")
        generated = self.client.post(
            "/ui/g1-3d/tts",
            json={
                "name": "concierge_welcome",
                "text": "Hello, welcome to our demonstration.",
                "emotion_strength": 5,
                "speech_rate": 10,
                "loudness_rate": -5,
                "pitch": 1,
                "style_instruction": "Speak like a gracious host.",
                "overwrite": False,
            },
        )
        catalog = self.client.get("/ui/g1-3d/tts")
        audio = self.client.get(generated.json()["audio_url"])
        deleted = self.client.delete("/ui/g1-3d/tts/concierge_welcome")
        empty_catalog = self.client.get("/ui/g1-3d/tts")

        self.assertEqual(page.status_code, 200)
        self.assertIn('data-panel-target="speech"', page.text)
        self.assertIn('data-speech-panel', page.text)
        self.assertIn('id="speech-speaker"', page.text)
        self.assertIn('id="speech-tone"', page.text)
        self.assertIn('id="speech-emotion-strength"', page.text)
        self.assertIn('id="speech-rate"', page.text)
        self.assertIn('id="speech-loudness"', page.text)
        self.assertIn('id="speech-pitch"', page.text)
        self.assertIn('id="speech-style-instruction"', page.text)
        self.assertIn('data-workspace-viewer', page.text)
        self.assertIn("app.css?v=3", page.text)
        self.assertIn("app.js?v=3", page.text)
        self.assertIn("speech.js?v=5", page.text)
        self.assertEqual(generated.status_code, 200)
        self.assertEqual(generated.json()["wav_filename"], "concierge_welcome.wav")
        self.assertEqual(generated.json()["speaker_name"], "Kian (recommended)")
        self.assertEqual(generated.json()["tone_name"], "Warm")
        self.assertEqual(generated.json()["emotion_strength"], 5)
        self.assertEqual(generated.json()["speech_rate"], 10)
        self.assertEqual(generated.json()["loudness_rate"], -5)
        self.assertEqual(generated.json()["pitch"], 1)
        self.assertEqual(
            generated.json()["style_instruction"],
            "Speak like a gracious host.",
        )
        self.assertIn("?version=", generated.json()["audio_url"])
        self.assertAlmostEqual(generated.json()["duration_seconds"], 1.25)
        self.assertEqual(catalog.status_code, 200)
        self.assertTrue(catalog.json()["configured"])
        self.assertEqual(catalog.json()["clips"][0]["text"], generated.json()["text"])
        self.assertEqual(audio.status_code, 200)
        self.assertEqual(audio.headers["content-type"], "audio/wav")
        self.assertEqual(audio.headers["cache-control"], "no-store")
        self.assertGreater(len(audio.content), 40_000)
        self.assertEqual(deleted.status_code, 200)
        self.assertEqual(deleted.json(), {"deleted": "concierge_welcome"})
        self.assertEqual(empty_catalog.json()["clips"], [])

    def test_action_player_renders_import_and_joint_ownership_controls(self) -> None:
        response = self.client.get("/")

        self.assertEqual(response.status_code, 200)
        self.assertIn('id="action-player-format"', response.text)
        self.assertIn('id="action-player-file"', response.text)
        self.assertIn("Action Recorder NPZ", response.text)
        self.assertIn("Kimodo G1 NPZ", response.text)
        self.assertIn("ARDY session PKL", response.text)
        self.assertIn("Lower body", response.text)
        self.assertIn("Standing", response.text)
        self.assertIn('id="action-player-frame"', response.text)
        self.assertIn('id="action-player-save-left"', response.text)
        self.assertIn('id="action-player-save-right"', response.text)
        self.assertIn("action_player.js", response.text)

    def test_action_player_loads_native_npz_and_starts_playback(self) -> None:
        path = Path(__file__).resolve().parents[1] / "data/actions/trajectories/present_left.npz"
        loaded = self.client.post(
            "/ui/g1-3d/action-player/load",
            params={"source_format": "native_npz", "filename": path.name},
            content=path.read_bytes(),
            headers={"content-type": "application/octet-stream"},
        )

        self.assertEqual(loaded.status_code, 200)
        self.assertEqual(loaded.json()["arm_joint_count"], 14)
        started = self.client.post(
            "/ui/g1-3d/action-player/playback/play",
            json={"enabled": False},
        )
        self.assertEqual(started.status_code, 200)
        self.assertEqual(started.json()["state"], "playing")
        self.assertEqual(started.json()["source"], "uploaded")
        paused = self.client.post("/ui/g1-3d/action-player/playback/pause")
        selected = self.client.post(
            "/ui/g1-3d/action-player/playback/seek",
            json={"sample_index": 50},
        )
        saved = self.client.post(
            "/ui/g1-3d/action-player/poses",
            json={
                "pose_type": "left_arm",
                "name": "selected_action_frame",
                "notes": "Selected from uploaded motion",
                "overwrite": False,
            },
        )

        self.assertEqual(paused.json()["state"], "paused")
        self.assertEqual(selected.json()["sample_index"], 50)
        self.assertEqual(saved.status_code, 200)
        self.assertEqual(saved.json()["pose_type"], "left_arm")
        self.assertEqual(saved.json()["sample_index"], 50)
        self.client.post("/ui/g1-3d/action-player/playback/stop")

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
        self.assertIn('data-mirror-arm="left_arm"', response.text)
        self.assertIn('data-mirror-arm="right_arm"', response.text)
        self.assertIn("pose_recorder.js?v=2", response.text)
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

    def test_pose_recorder_mirrors_live_g1_arm_without_saving(self) -> None:
        self.robot_application.simulation.update_joint_positions(
            {"waist_yaw_joint": 0.2}
        )
        left_values = dict(
            zip(
                self.robot_application.joint_schema.LEFT_ARM_JOINT_NAMES,
                (0.4, 0.35, -0.3, 0.8, 0.25, -0.2, 0.3),
                strict=True,
            )
        )
        response = self.client.post(
            "/ui/g1-3d/pose-recorder/mirror-arm",
            json={
                "source_pose_type": "left_arm",
                "joint_positions": left_values,
            },
        )

        self.assertEqual(response.status_code, 200)
        result = response.json()
        self.assertEqual(result["target_pose_type"], "right_arm")
        self.assertEqual(result["source_joint_positions"], left_values)
        self.assertEqual(result["joint_positions"]["right_shoulder_pitch_joint"], 0.4)
        self.assertEqual(result["joint_positions"]["right_shoulder_roll_joint"], -0.35)
        self.assertEqual(result["joint_positions"]["right_wrist_roll_joint"], -0.25)
        self.assertEqual(result["joint_positions"]["right_wrist_pitch_joint"], -0.2)
        state = self.robot_application.simulation.snapshot().joint_position_map()
        self.assertEqual(state["waist_yaw_joint"], 0.2)
        self.assertEqual(state["left_shoulder_roll_joint"], 0.35)
        self.assertEqual(state["right_shoulder_roll_joint"], -0.35)
        self.assertEqual(
            self.robot_application.pose_service.list_poses(
                pose_type=PoseType.RIGHT_ARM
            ),
            (),
        )

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

    def test_action_composer_renders_complete_pose_sequence_controls(self) -> None:
        self._save_action_source()

        response = self.client.get("/")

        self.assertEqual(response.status_code, 200)
        self.assertIn("Action Composer", response.text)
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
        self.assertEqual(started.json()["source"], "compiled")
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
        self.assertIsNone(state["source"])
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
        self.assertIn("#panel-speech:not(.hidden)", response.text)

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
