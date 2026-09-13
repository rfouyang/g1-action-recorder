"""Atomic UTF-8 JSON file operations used by the pose repository."""

from __future__ import annotations

import json
import logging
import os
import tempfile
from collections.abc import Mapping
from pathlib import Path

LOGGER = logging.getLogger(__name__)


class PoseFileHelper:
    """Read and atomically write JSON objects without pose business rules."""

    def write_json(
        self,
        *,
        path: Path,
        payload: Mapping[str, object],
        overwrite: bool = False,
    ) -> Path:
        if path.suffix != ".json":
            raise ValueError(f"Pose JSON path must end in .json: {path}")
        path.parent.mkdir(parents=True, exist_ok=True)
        content = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"

        temporary_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=path.parent,
                prefix=f".{path.stem}.",
                suffix=".tmp",
                delete=False,
            ) as temporary_file:
                temporary_file.write(content)
                temporary_file.flush()
                os.fsync(temporary_file.fileno())
                temporary_path = Path(temporary_file.name)

            if overwrite:
                os.replace(temporary_path, path)
            else:
                os.link(temporary_path, path)
                temporary_path.unlink()
            return path
        finally:
            if temporary_path is not None and temporary_path.exists():
                temporary_path.unlink()

    def read_json(self, *, path: Path) -> dict[str, object]:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as error:
            raise ValueError(f"Invalid JSON in {path}: {error}") from error
        if not isinstance(payload, dict):
            raise ValueError(f"Pose JSON root must be an object: {path}")
        return payload

    def list_json_files(self, *, directory: Path) -> tuple[Path, ...]:
        if not directory.exists():
            return ()
        return tuple(sorted(directory.glob("*.json"), key=lambda path: path.name))


def demo_pose_file_helper() -> None:
    logging.basicConfig(level=logging.INFO)
    helper = PoseFileHelper()
    with tempfile.TemporaryDirectory() as temporary_directory:
        path = Path(temporary_directory) / "示例姿态.json"
        helper.write_json(path=path, payload={"name": "示例姿态"})
        LOGGER.info("Pose JSON round trip: %s", helper.read_json(path=path))


def main() -> None:
    demo_pose_file_helper()


if __name__ == "__main__":
    main()
