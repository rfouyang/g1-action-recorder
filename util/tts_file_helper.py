"""Atomic TTS metadata persistence and WAV inspection."""

from __future__ import annotations

import json
import os
import tempfile
import wave
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class WavInfo:
    """Audio properties read from a PCM WAV file."""

    duration_seconds: float
    sample_rate_hz: int
    channels: int
    sample_width_bytes: int
    frame_count: int


class TtsFileHelper:
    """Read TTS sidecars and inspect their corresponding WAV files."""

    def write_metadata(
        self,
        *,
        path: Path,
        payload: dict[str, object],
        overwrite: bool,
    ) -> Path:
        if path.suffix.lower() != ".json":
            raise ValueError(f"TTS metadata path must end in .json: {path}")
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
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)

    def read_metadata(self, *, path: Path) -> dict[str, object]:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as error:
            raise ValueError(f"Invalid TTS metadata in {path}: {error}") from error
        if not isinstance(payload, dict):
            raise ValueError(f"TTS metadata root must be an object: {path}")
        return payload

    def list_metadata_files(self, *, directory: Path) -> tuple[Path, ...]:
        if not directory.exists():
            return ()
        return tuple(sorted(directory.glob("*.json"), key=lambda path: path.name))

    def inspect_wav(self, *, path: Path) -> WavInfo:
        try:
            with wave.open(str(path), "rb") as wav_file:
                frame_count = wav_file.getnframes()
                sample_rate_hz = wav_file.getframerate()
                channels = wav_file.getnchannels()
                sample_width_bytes = wav_file.getsampwidth()
        except (EOFError, wave.Error) as error:
            raise ValueError(f"Invalid WAV file {path}: {error}") from error
        if sample_rate_hz <= 0:
            raise ValueError(f"WAV sample rate must be positive: {path}")
        return WavInfo(
            duration_seconds=frame_count / sample_rate_hz,
            sample_rate_hz=sample_rate_hz,
            channels=channels,
            sample_width_bytes=sample_width_bytes,
            frame_count=frame_count,
        )
