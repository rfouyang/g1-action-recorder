"""Shared Viser runtime for the live G1 MuJoCo scene."""

from __future__ import annotations

import logging
import math
import threading
import time
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

import numpy as np
import viser
from viser.extras import ViserUrdf

from component.common.g1_joint_schema import G1JointSchema
from component.simulation import SimulationService, SimulationSnapshot

LOGGER = logging.getLogger(__name__)


class RobotCameraView(str, Enum):
    """Robot-relative camera presets exposed by the browser UI."""

    FRONT = "front"
    BACK = "back"
    LEFT = "left"
    RIGHT = "right"
    FRONT_LEFT_45 = "front_left_45"
    FRONT_RIGHT_45 = "front_right_45"


@dataclass(frozen=True, slots=True)
class CameraPreset:
    """Position and focus point for one fixed Viser camera view."""

    position: tuple[float, float, float]
    look_at: tuple[float, float, float] = (0.0, 0.0, 0.68)
    up: tuple[float, float, float] = (0.0, 0.0, 1.0)
    vertical_fov: float = math.radians(45.0)


class ViserManager:
    """Load the G1 once and synchronize it from shared MuJoCo snapshots."""

    # G1 model coordinates: the robot faces +X, anatomical left is +Y, and
    # anatomical right is -Y. Every label below is from the robot's perspective.
    _CAMERA_DISTANCE = 2.30
    _CAMERA_DIAGONAL = _CAMERA_DISTANCE / math.sqrt(2.0)
    _CAMERA_HEIGHT = 0.91
    CAMERA_PRESETS = {
        RobotCameraView.FRONT: CameraPreset(
            (_CAMERA_DISTANCE, 0.0, _CAMERA_HEIGHT)
        ),
        RobotCameraView.BACK: CameraPreset(
            (-_CAMERA_DISTANCE, 0.0, _CAMERA_HEIGHT)
        ),
        RobotCameraView.LEFT: CameraPreset(
            (0.0, _CAMERA_DISTANCE, _CAMERA_HEIGHT)
        ),
        RobotCameraView.RIGHT: CameraPreset(
            (0.0, -_CAMERA_DISTANCE, _CAMERA_HEIGHT)
        ),
        RobotCameraView.FRONT_LEFT_45: CameraPreset(
            (_CAMERA_DIAGONAL, _CAMERA_DIAGONAL, _CAMERA_HEIGHT)
        ),
        RobotCameraView.FRONT_RIGHT_45: CameraPreset(
            (_CAMERA_DIAGONAL, -_CAMERA_DIAGONAL, _CAMERA_HEIGHT)
        ),
    }

    def __init__(
        self,
        *,
        simulation: SimulationService,
        schema: G1JointSchema,
        urdf_path: Path,
        host: str,
        port: int,
        update_hz: float = 30.0,
        camera_transition_seconds: float = 0.7,
        camera_transition_hz: float = 60.0,
    ) -> None:
        if update_hz <= 0:
            raise ValueError("Viser update frequency must be positive")
        if camera_transition_seconds < 0:
            raise ValueError("Camera transition duration cannot be negative")
        if camera_transition_hz <= 0:
            raise ValueError("Camera transition frequency must be positive")
        self.simulation = simulation
        self.schema = schema
        self.urdf_path = urdf_path
        self.host = host
        self.requested_port = port
        self.update_hz = update_hz
        self.camera_transition_seconds = camera_transition_seconds
        self.camera_transition_hz = camera_transition_hz
        self._lifecycle_lock = threading.Lock()
        self._camera_transition_lock = threading.Lock()
        self._stop_event = threading.Event()
        self._server: viser.ViserServer | None = None
        self._robot_root: viser.FrameHandle | None = None
        self._robot: ViserUrdf | None = None
        self._sync_thread: threading.Thread | None = None
        self._camera_transition_generation = 0
        self._camera_transition_threads: set[threading.Thread] = set()
        self._synced_revision = -1

    @property
    def port(self) -> int:
        """Return the actual bound port, including when zero selected a free port."""
        if self._server is None:
            raise RuntimeError("Viser runtime has not been started")
        return self._server.get_port()

    @property
    def connected_client_count(self) -> int:
        """Return the number of active Viser browser clients."""
        if self._server is None:
            return 0
        return len(self._server.get_clients())

    @property
    def synced_revision(self) -> int:
        """Return the latest MuJoCo revision applied to the Viser robot."""
        return self._synced_revision

    def start(self) -> None:
        """Start Viser, build the shared scene once, and begin state syncing."""
        with self._lifecycle_lock:
            if self._server is not None:
                return
            server = viser.ViserServer(
                host=self.host,
                port=self.requested_port,
                label="G1 Action Recorder Scene",
                verbose=False,
            )
            try:
                self._configure_scene(server)
                robot_root = server.scene.add_frame(
                    "/scene/robot",
                    show_axes=False,
                )
                robot = ViserUrdf(
                    server,
                    self.urdf_path,
                    root_node_name="/scene/robot",
                )
                if robot.get_actuated_joint_names() != self.schema.DDS_JOINT_NAMES:
                    raise ValueError("Viser URDF joint order does not match the G1 schema")

                self._server = server
                self._robot_root = robot_root
                self._robot = robot
                snapshot = self.simulation.snapshot()
                self._apply_snapshot(snapshot)
                self._install_client_defaults(server)
                self._stop_event.clear()
                self._sync_thread = threading.Thread(
                    target=self._sync_loop,
                    args=(snapshot.revision,),
                    name="g1-viser-sync",
                    daemon=True,
                )
                self._sync_thread.start()
                LOGGER.info("Viser G1 scene ready at http://%s:%d", self.host, self.port)
            except Exception:
                self._server = None
                self._robot_root = None
                self._robot = None
                server.stop()
                raise

    def stop(self) -> None:
        """Stop pose synchronization and release the Viser server port."""
        with self._lifecycle_lock:
            server = self._server
            thread = self._sync_thread
            if server is None:
                return
            self._stop_event.set()
            with self._camera_transition_lock:
                self._camera_transition_generation += 1
                camera_threads = tuple(self._camera_transition_threads)
            if thread is not None:
                thread.join(timeout=max(1.0, 2.0 / self.update_hz))
            for camera_thread in camera_threads:
                camera_thread.join(timeout=max(0.1, 2.0 / self.camera_transition_hz))
            server.stop()
            self._server = None
            self._robot_root = None
            self._robot = None
            self._sync_thread = None
            with self._camera_transition_lock:
                self._camera_transition_threads.clear()
            self._synced_revision = -1

    def set_camera_view(self, camera_view: RobotCameraView) -> int:
        """Apply one robot-relative preset to every connected embedded client."""
        if self._server is None:
            raise RuntimeError("Viser runtime has not been started")
        preset = self.CAMERA_PRESETS[camera_view]
        clients = tuple(self._server.get_clients().values())
        with self._camera_transition_lock:
            self._camera_transition_generation += 1
            generation = self._camera_transition_generation
        for client in clients:
            self._start_camera_transition(
                client=client,
                preset=preset,
                generation=generation,
            )
        return len(clients)

    def _configure_scene(self, server: viser.ViserServer) -> None:
        server.gui.configure_theme(
            dark_mode=True,
            show_logo=False,
            show_share_button=False,
            brand_color=(245, 158, 11),
        )
        server.gui.main_panel.minimize()
        server.scene.set_up_direction("+z")
        server.scene.world_axes.visible = False
        server.scene.add_grid(
            "/scene/ground",
            width=8.0,
            height=8.0,
            cell_size=0.25,
            section_size=1.0,
            cell_color=(65, 70, 78),
            section_color=(100, 108, 120),
            plane_color=(16, 19, 24),
            plane_opacity=0.85,
            shadow_opacity=0.35,
        )
        front = self.CAMERA_PRESETS[RobotCameraView.FRONT]
        server.initial_camera.position = front.position
        server.initial_camera.look_at = front.look_at
        server.initial_camera.up = front.up
        server.initial_camera.fov = front.vertical_fov
        server.initial_camera.near = 0.01
        server.initial_camera.far = 100.0

    def _install_client_defaults(self, server: viser.ViserServer) -> None:
        @server.on_client_connect
        def initialize_client(client: viser.ClientHandle) -> None:
            self._apply_camera(
                client=client,
                preset=self.CAMERA_PRESETS[RobotCameraView.FRONT],
            )

    def _apply_camera(
        self,
        *,
        client: viser.ClientHandle,
        preset: CameraPreset,
    ) -> None:
        with client.atomic():
            client.camera.position = preset.position
            client.camera.look_at = preset.look_at
            client.camera.up_direction = preset.up
            client.camera.fov = preset.vertical_fov

    def _start_camera_transition(
        self,
        *,
        client: viser.ClientHandle,
        preset: CameraPreset,
        generation: int,
    ) -> None:
        if self.camera_transition_seconds == 0:
            self._apply_camera(client=client, preset=preset)
            return

        thread = threading.Thread(
            target=self._animate_camera,
            args=(client, preset, generation),
            name="g1-viser-camera",
            daemon=True,
        )
        with self._camera_transition_lock:
            self._camera_transition_threads.add(thread)
        thread.start()

    def _animate_camera(
        self,
        client: viser.ClientHandle,
        preset: CameraPreset,
        generation: int,
    ) -> None:
        current_thread = threading.current_thread()
        try:
            start_position = np.asarray(client.camera.position, dtype=float).copy()
            start_look_at = np.asarray(client.camera.look_at, dtype=float).copy()
            start_up = np.asarray(client.camera.up_direction, dtype=float).copy()
            started_at = time.monotonic()
            frame_seconds = 1.0 / self.camera_transition_hz

            while True:
                if self._camera_transition_cancelled(generation):
                    return
                elapsed = time.monotonic() - started_at
                progress = min(1.0, elapsed / self.camera_transition_seconds)
                position, look_at, up = self._interpolate_camera(
                    start_position=start_position,
                    start_look_at=start_look_at,
                    start_up=start_up,
                    preset=preset,
                    progress=progress,
                )
                self._apply_camera(
                    client=client,
                    preset=CameraPreset(
                        position=tuple(position),
                        look_at=tuple(look_at),
                        up=tuple(up),
                        vertical_fov=preset.vertical_fov,
                    ),
                )
                if progress >= 1.0:
                    return
                if self._stop_event.wait(frame_seconds):
                    return
        except (AssertionError, ValueError):
            LOGGER.debug("Could not animate a Viser camera", exc_info=True)
            if not self._camera_transition_cancelled(generation):
                self._apply_camera(client=client, preset=preset)
        finally:
            with self._camera_transition_lock:
                self._camera_transition_threads.discard(current_thread)

    def _camera_transition_cancelled(self, generation: int) -> bool:
        if self._stop_event.is_set():
            return True
        with self._camera_transition_lock:
            return generation != self._camera_transition_generation

    @staticmethod
    def _interpolate_camera(
        *,
        start_position: np.ndarray,
        start_look_at: np.ndarray,
        start_up: np.ndarray,
        preset: CameraPreset,
        progress: float,
    ) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """Interpolate along an eased orbit that stays clear of the robot."""
        eased = progress * progress * (3.0 - 2.0 * progress)
        end_position = np.asarray(preset.position, dtype=float)
        end_look_at = np.asarray(preset.look_at, dtype=float)
        end_up = np.asarray(preset.up, dtype=float)
        look_at = start_look_at + eased * (end_look_at - start_look_at)

        start_offset = start_position - start_look_at
        end_offset = end_position - end_look_at
        start_radius = float(np.linalg.norm(start_offset[:2]))
        end_radius = float(np.linalg.norm(end_offset[:2]))
        if start_radius > 1e-6 and end_radius > 1e-6:
            start_angle = math.atan2(start_offset[1], start_offset[0])
            end_angle = math.atan2(end_offset[1], end_offset[0])
            angle_delta = (end_angle - start_angle + math.pi) % (
                2.0 * math.pi
            ) - math.pi
            if math.isclose(angle_delta, -math.pi):
                angle_delta = math.pi
            angle = start_angle + eased * angle_delta
            radius = start_radius + eased * (end_radius - start_radius)
            height = start_offset[2] + eased * (end_offset[2] - start_offset[2])
            position = look_at + np.array(
                [radius * math.cos(angle), radius * math.sin(angle), height]
            )
        else:
            position = start_position + eased * (end_position - start_position)

        up = start_up + eased * (end_up - start_up)
        up_norm = float(np.linalg.norm(up))
        up = end_up if up_norm < 1e-6 else up / up_norm
        return position, look_at, up

    def _sync_loop(self, revision: int) -> None:
        timeout = 1.0 / self.update_hz
        while not self._stop_event.is_set():
            snapshot = self.simulation.wait_for_revision(
                after_revision=revision,
                timeout=timeout,
            )
            if self._stop_event.is_set():
                break
            if snapshot.revision == revision:
                continue
            self._apply_snapshot(snapshot)
            revision = snapshot.revision

    def _apply_snapshot(self, snapshot: SimulationSnapshot) -> None:
        if self._server is None or self._robot is None or self._robot_root is None:
            return
        with self._server.atomic():
            self._robot_root.position = snapshot.base_position
            self._robot_root.wxyz = snapshot.base_wxyz
            self._robot.update_cfg(np.asarray(snapshot.joint_positions))
        self._synced_revision = snapshot.revision


def demo_viser_manager() -> None:
    import time

    from app.application import RobotApplication

    logging.basicConfig(level=logging.INFO)
    application = RobotApplication.create()
    manager = ViserManager(
        simulation=application.simulation,
        schema=application.joint_schema,
        urdf_path=application.settings.g1_asset_dir / "g1_29dof_fake_hand.urdf",
        host=application.settings.viser_host,
        port=application.settings.viser_port,
    )
    manager.start()
    try:
        LOGGER.info("Open http://%s:%d", manager.host, manager.port)
        while True:
            time.sleep(10.0)
    except KeyboardInterrupt:
        pass
    finally:
        manager.stop()


def main() -> None:
    demo_viser_manager()


if __name__ == "__main__":
    main()
