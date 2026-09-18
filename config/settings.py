"""Central paths and runtime settings for the G1 Action Recorder."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

LOGGER = logging.getLogger(__name__)
PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONCIERGE_INITIAL_POSE_NAME = "concierge_init"


@dataclass(frozen=True, slots=True)
class AppSettings:
    """Resolve project paths from one explicit project root."""

    project_root: Path = PROJECT_ROOT
    g1_3d_host: str = "127.0.0.1"
    g1_3d_port: int = 8000
    viser_host: str = "127.0.0.1"
    viser_port: int = 8081
    initial_base_pose_name: str = CONCIERGE_INITIAL_POSE_NAME
    byteplus_api_key: str | None = None

    @classmethod
    def from_env(cls) -> AppSettings:
        """Load local application secrets without exposing them to callers."""
        load_dotenv(PROJECT_ROOT / ".env")
        return cls(
            byteplus_api_key=(
                os.getenv("BYTEPLUS_API_KEY")
                or os.getenv("BYTEPLUS_APY_KEY")
                or None
            )
        )

    @property
    def asset_dir(self) -> Path:
        return self.project_root / "asset"

    @property
    def g1_asset_dir(self) -> Path:
        return self.asset_dir / "g1"

    @property
    def data_dir(self) -> Path:
        return self.project_root / "data"

    @property
    def pose_dir(self) -> Path:
        return self.data_dir / "poses"

    @property
    def pose_preview_dir(self) -> Path:
        return self.data_dir / "pose_previews"

    @property
    def action_dir(self) -> Path:
        return self.data_dir / "actions"

    @property
    def action_definition_dir(self) -> Path:
        return self.action_dir / "definitions"

    @property
    def action_trajectory_dir(self) -> Path:
        return self.action_dir / "trajectories"

    @property
    def action_preview_dir(self) -> Path:
        return self.data_dir / "action_previews"

    @property
    def tts_dir(self) -> Path:
        return self.data_dir / "tts"

    @property
    def third_party_dir(self) -> Path:
        return self.project_root / "third_party"

    def ensure_runtime_directories(self) -> None:
        """Create directories that receive generated pose data and previews."""
        for directory in (
            self.pose_dir / "base",
            self.pose_dir / "left_arm",
            self.pose_dir / "right_arm",
            self.pose_dir / "composed",
            self.pose_preview_dir,
            self.action_definition_dir,
            self.action_trajectory_dir,
            self.action_preview_dir,
            self.tts_dir,
        ):
            directory.mkdir(parents=True, exist_ok=True)


def demo_settings() -> None:
    logging.basicConfig(level=logging.INFO)
    settings = AppSettings()
    settings.ensure_runtime_directories()
    LOGGER.info("G1 Action Recorder project root: %s", settings.project_root)


def main() -> None:
    demo_settings()


if __name__ == "__main__":
    main()
