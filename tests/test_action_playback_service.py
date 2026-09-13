"""Tests for timed action playback into the shared MuJoCo simulation."""

from __future__ import annotations

import time
import unittest

import numpy as np

from component.action_playback_service import (
    ActionPlaybackService,
    ActionPlaybackState,
)
from component.common.action_models import ActionTrajectory
from component.common.g1_joint_schema import G1JointSchema, PoseType
from component.simulation import SimulationService
from config.settings import AppSettings
from util.g1_asset_helper import G1AssetHelper
from util.mujoco_pose_helper import MujocoPoseHelper


class ActionPlaybackServiceTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        settings = AppSettings()
        assets = G1AssetHelper(asset_dir=settings.g1_asset_dir)
        cls.schema = G1JointSchema(asset_helper=assets)
        cls.pose_helper = MujocoPoseHelper(mjcf_path=assets.mjcf_path)

    def setUp(self) -> None:
        self.simulation = SimulationService(
            schema=self.schema,
            pose_helper=self.pose_helper,
        )
        self.playback = ActionPlaybackService(simulation=self.simulation)

    def tearDown(self) -> None:
        self.playback.close()

    def test_playback_reaches_every_sample_and_completes(self) -> None:
        trajectory = self._trajectory(step_seconds=0.04)

        started = self.playback.play(trajectory=trajectory)
        completed = self._wait_for_state(ActionPlaybackState.COMPLETED)

        self.assertEqual(started.state, ActionPlaybackState.PLAYING)
        self.assertEqual(started.phase.value, "keyframe")
        self.assertEqual(started.target_pose_name, "concierge_init")
        self.assertEqual(completed.sample_index, trajectory.sample_count - 1)
        self.assertEqual(completed.progress, 1.0)
        self.assertEqual(completed.keyframe_index, 2)
        self.assertEqual(completed.target_pose_name, "concierge_init")
        self.assertAlmostEqual(
            self.simulation.snapshot().joint_position_map()["left_elbow_joint"],
            0.0,
        )

    def test_pause_holds_current_sample_until_resume(self) -> None:
        trajectory = self._trajectory(step_seconds=0.15)
        self.playback.play(trajectory=trajectory)
        moving = self._wait_for_sample(1)

        paused = self.playback.pause()
        time.sleep(0.2)
        still_paused = self.playback.snapshot()

        self.assertEqual(paused.state, ActionPlaybackState.PAUSED)
        self.assertEqual(moving.phase.value, "transition")
        self.assertEqual(moving.from_pose_name, "concierge_init")
        self.assertEqual(moving.target_pose_name, "middle")
        self.assertEqual(still_paused.sample_index, paused.sample_index)
        self.assertEqual(still_paused.state, ActionPlaybackState.PAUSED)
        self.playback.resume()
        self.assertEqual(
            self._wait_for_state(ActionPlaybackState.COMPLETED).state,
            ActionPlaybackState.COMPLETED,
        )

    def test_stop_returns_to_first_sample(self) -> None:
        trajectory = self._trajectory(step_seconds=0.08)
        self.playback.play(trajectory=trajectory)
        self._wait_for_sample(1)

        stopped = self.playback.stop()

        self.assertEqual(stopped.state, ActionPlaybackState.STOPPED)
        self.assertEqual(stopped.sample_index, 0)
        self.assertEqual(stopped.elapsed_seconds, 0.0)
        self.assertAlmostEqual(
            self.simulation.snapshot().joint_position_map()["left_elbow_joint"],
            0.0,
        )

    def test_hold_samples_report_the_reached_keyframe(self) -> None:
        trajectory = self._trajectory(step_seconds=0.05, hold_seconds=0.1)
        self.playback.play(trajectory=trajectory)

        holding = self._wait_for_sample(3)

        self.assertEqual(holding.phase.value, "hold")
        self.assertEqual(holding.keyframe_index, 1)
        self.assertEqual(holding.from_pose_name, "middle")
        self.assertEqual(holding.target_pose_name, "middle")

    def test_loop_remains_active_until_stopped(self) -> None:
        trajectory = self._trajectory(step_seconds=0.03)

        self.playback.play(trajectory=trajectory, loop=True)
        time.sleep(0.16)
        looping = self.playback.snapshot()

        self.assertEqual(looping.state, ActionPlaybackState.PLAYING)
        self.assertTrue(looping.loop)
        self.assertGreater(looping.revision, 4)
        self.assertEqual(self.playback.stop().state, ActionPlaybackState.STOPPED)

    def _trajectory(
        self,
        *,
        step_seconds: float,
        hold_seconds: float = 0.0,
    ) -> ActionTrajectory:
        neutral_values = self.schema.neutral_values(PoseType.BASE)
        neutral = np.asarray(
            [neutral_values[name] for name in self.schema.BASE_JOINT_NAMES],
            dtype=np.float64,
        )
        middle = neutral.copy()
        middle[self.schema.BASE_JOINT_NAMES.index("left_elbow_joint")] = 0.5
        halfway = (neutral + middle) / 2.0
        if hold_seconds > 0.0:
            timestamps = [
                0.0,
                step_seconds,
                step_seconds * 2.0,
                step_seconds * 2.0 + hold_seconds / 2.0,
                step_seconds * 2.0 + hold_seconds,
                step_seconds * 3.0 + hold_seconds,
                step_seconds * 4.0 + hold_seconds,
            ]
            positions = (neutral, halfway, middle, middle, middle, halfway, neutral)
            keyframe_indices = (0, 2, 6)
        else:
            timestamps = [
                0.0,
                step_seconds,
                step_seconds * 2.0,
                step_seconds * 3.0,
                step_seconds * 4.0,
            ]
            positions = (neutral, halfway, middle, halfway, neutral)
            keyframe_indices = (0, 2, 4)
        return ActionTrajectory(
            action_name="playback_test",
            robot_model_id=self.schema.model_id,
            joint_names=self.schema.BASE_JOINT_NAMES,
            timestamps=np.asarray(timestamps, dtype=np.float64),
            joint_positions=np.stack(positions),
            keyframe_sample_indices=keyframe_indices,
            source_pose_names=("concierge_init", "middle", "concierge_init"),
            keyframe_hold_seconds=(0.0, hold_seconds, 0.0),
            requested_sample_frequency_hz=1.0 / step_seconds,
            max_tracking_error=0.0,
        )

    def _wait_for_state(
        self,
        state: ActionPlaybackState,
        timeout: float = 1.5,
    ):
        deadline = time.monotonic() + timeout
        snapshot = self.playback.snapshot()
        while snapshot.state is not state and time.monotonic() < deadline:
            snapshot = self.playback.wait_for_revision(
                after_revision=snapshot.revision,
                timeout=0.05,
            )
        self.assertEqual(snapshot.state, state)
        return snapshot

    def _wait_for_sample(self, sample_index: int, timeout: float = 1.0):
        deadline = time.monotonic() + timeout
        snapshot = self.playback.snapshot()
        while snapshot.sample_index < sample_index and time.monotonic() < deadline:
            snapshot = self.playback.wait_for_revision(
                after_revision=snapshot.revision,
                timeout=0.05,
            )
        self.assertGreaterEqual(snapshot.sample_index, sample_index)
        return snapshot


if __name__ == "__main__":
    unittest.main()
