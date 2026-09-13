"""Atomically persist safe, non-object NumPy array archives."""

from __future__ import annotations

import logging
import os
import tempfile
from collections.abc import Mapping
from pathlib import Path

import numpy as np
from numpy.typing import NDArray

LOGGER = logging.getLogger(__name__)


class NumpyArchiveHelper:
    """Read and atomically write NPZ archives without enabling pickle."""

    def write_npz(
        self,
        *,
        path: Path,
        arrays: Mapping[str, object],
        overwrite: bool = False,
    ) -> Path:
        if path.suffix.lower() != ".npz":
            raise ValueError(f"NumPy archive path must end in .npz: {path}")
        validated_arrays = self._validated_arrays(arrays)
        path.parent.mkdir(parents=True, exist_ok=True)

        temporary_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w+b",
                dir=path.parent,
                prefix=f".{path.stem}.",
                suffix=".tmp.npz",
                delete=False,
            ) as temporary_file:
                np.savez(temporary_file, **validated_arrays)
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

    def read_npz(self, *, path: Path) -> dict[str, NDArray[np.generic]]:
        if path.suffix.lower() != ".npz":
            raise ValueError(f"NumPy archive path must end in .npz: {path}")
        with np.load(path, allow_pickle=False) as archive:
            return {name: archive[name].copy() for name in archive.files}

    def list_npz_files(self, *, directory: Path) -> tuple[Path, ...]:
        if not directory.exists():
            return ()
        return tuple(sorted(directory.glob("*.npz"), key=lambda path: path.name))

    def _validated_arrays(self, arrays: Mapping[str, object]) -> dict[str, np.ndarray]:
        if not arrays:
            raise ValueError("NumPy archive must contain at least one array")
        validated_arrays: dict[str, np.ndarray] = {}
        for name, raw_array in arrays.items():
            if not isinstance(name, str) or not name or "/" in name or "\\" in name:
                raise ValueError(f"Invalid NumPy archive array name: {name!r}")
            array = np.asarray(raw_array)
            if array.dtype.hasobject:
                raise ValueError(f"NumPy archive array {name} cannot use object dtype")
            validated_arrays[name] = array
        return validated_arrays


def demo_numpy_archive_helper() -> None:
    logging.basicConfig(level=logging.INFO)
    helper = NumpyArchiveHelper()
    with tempfile.TemporaryDirectory() as temporary_directory:
        path = Path(temporary_directory) / "trajectory.npz"
        helper.write_npz(
            path=path,
            arrays={
                "fps": np.asarray(25.0),
                "joint_positions": np.zeros((3, 17), dtype=np.float64),
            },
        )
        arrays = helper.read_npz(path=path)
        LOGGER.info("NPZ round trip keys: %s", sorted(arrays))


def main() -> None:
    demo_numpy_archive_helper()


if __name__ == "__main__":
    main()
