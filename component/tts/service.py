"""Generate and catalog G1-compatible speech clips."""

from __future__ import annotations

import math
import threading
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path

from util.byteplus_tts_helper import BytePlusTtsHelper
from util.tts_file_helper import TtsFileHelper


@dataclass(frozen=True, slots=True)
class TtsClip:
    """One persisted text prompt and its generated WAV asset."""

    schema_version: int
    name: str
    text: str
    wav_filename: str
    duration_seconds: float
    sample_rate_hz: int
    channels: int
    sample_width_bytes: int
    speaker: str
    speaker_name: str
    tone: str
    tone_name: str
    emotion_strength: int
    speech_rate: int
    loudness_rate: int
    pitch: int
    style_instruction: str
    created_at: datetime

    def __post_init__(self) -> None:
        normalized_name = TtsService.validate_name(self.name)
        if self.schema_version != 1:
            raise ValueError(f"Unsupported TTS schema version: {self.schema_version}")
        if self.wav_filename != f"{normalized_name}.wav":
            raise ValueError("TTS WAV filename must match the clip name")
        if not self.text.strip():
            raise ValueError("TTS text cannot be empty")
        if not math.isfinite(self.duration_seconds) or self.duration_seconds <= 0.0:
            raise ValueError("TTS duration must be positive and finite")
        if self.sample_rate_hz != 16_000:
            raise ValueError("G1 speech WAV files must use a 16000 Hz sample rate")
        if self.channels != 1 or self.sample_width_bytes != 2:
            raise ValueError("G1 speech WAV files must use mono 16-bit PCM")
        if self.created_at.tzinfo is None or self.created_at.utcoffset() is None:
            raise ValueError("TTS created_at must include a timezone")
        BytePlusTtsHelper.validate_delivery_parameters(
            emotion_strength=self.emotion_strength,
            speech_rate=self.speech_rate,
            loudness_rate=self.loudness_rate,
            pitch=self.pitch,
            style_instruction=self.style_instruction,
        )
        object.__setattr__(self, "name", normalized_name)
        object.__setattr__(self, "text", self.text.strip())

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "name": self.name,
            "text": self.text,
            "wav_filename": self.wav_filename,
            "duration_seconds": self.duration_seconds,
            "sample_rate_hz": self.sample_rate_hz,
            "channels": self.channels,
            "sample_width_bytes": self.sample_width_bytes,
            "speaker": self.speaker,
            "speaker_name": self.speaker_name,
            "tone": self.tone,
            "tone_name": self.tone_name,
            "emotion_strength": self.emotion_strength,
            "speech_rate": self.speech_rate,
            "loudness_rate": self.loudness_rate,
            "pitch": self.pitch,
            "style_instruction": self.style_instruction,
            "created_at": self.created_at.astimezone(timezone.utc)
            .isoformat()
            .replace("+00:00", "Z"),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, object]) -> TtsClip:
        required = {
            "schema_version",
            "name",
            "text",
            "wav_filename",
            "duration_seconds",
            "sample_rate_hz",
            "channels",
            "sample_width_bytes",
            "speaker",
            "created_at",
        }
        missing = sorted(required - set(payload))
        if missing:
            raise ValueError(f"TTS metadata is missing fields: {missing}")
        created_at = datetime.fromisoformat(
            str(payload["created_at"]).replace("Z", "+00:00")
        )
        return cls(
            schema_version=int(payload["schema_version"]),
            name=str(payload["name"]),
            text=str(payload["text"]),
            wav_filename=str(payload["wav_filename"]),
            duration_seconds=float(payload["duration_seconds"]),
            sample_rate_hz=int(payload["sample_rate_hz"]),
            channels=int(payload["channels"]),
            sample_width_bytes=int(payload["sample_width_bytes"]),
            speaker=str(payload["speaker"]),
            speaker_name=str(payload.get("speaker_name", payload["speaker"])),
            tone=str(payload.get("tone", "legacy")),
            tone_name=str(payload.get("tone_name", "Previous default")),
            emotion_strength=int(payload.get("emotion_strength", 4)),
            speech_rate=int(payload.get("speech_rate", 0)),
            loudness_rate=int(payload.get("loudness_rate", 0)),
            pitch=int(payload.get("pitch", 0)),
            style_instruction=str(payload.get("style_instruction", "")),
            created_at=created_at,
        )


class TtsService:
    """Coordinate BytePlus generation and the local speech asset catalog."""

    MAX_TEXT_CHARACTERS = 5_000

    def __init__(
        self,
        *,
        tts_dir: Path,
        file_helper: TtsFileHelper,
        byteplus_helper: BytePlusTtsHelper | None,
    ) -> None:
        self.tts_dir = tts_dir
        self.file_helper = file_helper
        self.byteplus_helper = byteplus_helper
        self._generation_lock = threading.Lock()

    @property
    def configured(self) -> bool:
        return self.byteplus_helper is not None

    @property
    def speaker_options(self) -> tuple[dict[str, str], ...]:
        return tuple(
            {
                "id": option.id,
                "name": option.name,
                "description": option.description,
            }
            for option in BytePlusTtsHelper.SPEAKERS
        )

    @property
    def tone_options(self) -> tuple[dict[str, str], ...]:
        return tuple(
            {"id": option.id, "name": option.name}
            for option in BytePlusTtsHelper.TONES
        )

    def generate(
        self,
        *,
        name: str,
        text: str,
        speaker: str = BytePlusTtsHelper.DEFAULT_SPEAKER,
        tone: str = BytePlusTtsHelper.DEFAULT_TONE,
        emotion_strength: int = 4,
        speech_rate: int = 0,
        loudness_rate: int = 0,
        pitch: int = 0,
        style_instruction: str = "",
        overwrite: bool = False,
    ) -> TtsClip:
        normalized_name = self.validate_name(name)
        spoken_text = self.validate_text(text)
        if self.byteplus_helper is None:
            raise RuntimeError("BytePlus TTS is not configured")
        speaker_option = BytePlusTtsHelper.speaker_option(speaker)
        tone_option = BytePlusTtsHelper.tone_option(tone)
        BytePlusTtsHelper.validate_delivery_parameters(
            emotion_strength=emotion_strength,
            speech_rate=speech_rate,
            loudness_rate=loudness_rate,
            pitch=pitch,
            style_instruction=style_instruction,
        )

        wav_path = self.tts_dir / f"{normalized_name}.wav"
        metadata_path = self.tts_dir / f"{normalized_name}.json"
        with self._generation_lock:
            if not overwrite and (wav_path.exists() or metadata_path.exists()):
                raise FileExistsError(f"TTS clip {normalized_name!r} already exists")
            self.byteplus_helper.generate(
                spoken_text,
                wav_path,
                speaker=speaker_option.id,
                tone=tone_option.id,
                emotion_strength=emotion_strength,
                speech_rate=speech_rate,
                loudness_rate=loudness_rate,
                pitch=pitch,
                style_instruction=style_instruction,
            )
            wav_info = self.file_helper.inspect_wav(path=wav_path)
            clip = TtsClip(
                schema_version=1,
                name=normalized_name,
                text=spoken_text,
                wav_filename=wav_path.name,
                duration_seconds=wav_info.duration_seconds,
                sample_rate_hz=wav_info.sample_rate_hz,
                channels=wav_info.channels,
                sample_width_bytes=wav_info.sample_width_bytes,
                speaker=speaker_option.id,
                speaker_name=speaker_option.name,
                tone=tone_option.id,
                tone_name=tone_option.name,
                emotion_strength=emotion_strength,
                speech_rate=speech_rate,
                loudness_rate=loudness_rate,
                pitch=pitch,
                style_instruction=style_instruction.strip(),
                created_at=datetime.now(timezone.utc),
            )
            try:
                self.file_helper.write_metadata(
                    path=metadata_path,
                    payload=clip.to_dict(),
                    overwrite=overwrite,
                )
            except Exception:
                if not overwrite:
                    wav_path.unlink(missing_ok=True)
                raise
            return clip

    def list_clips(self) -> tuple[TtsClip, ...]:
        return tuple(
            self.load(name=path.stem)
            for path in self.file_helper.list_metadata_files(directory=self.tts_dir)
        )

    def load(self, *, name: str) -> TtsClip:
        normalized_name = self.validate_name(name)
        metadata_path = self.tts_dir / f"{normalized_name}.json"
        clip = TtsClip.from_dict(
            self.file_helper.read_metadata(path=metadata_path)
        )
        if clip.name != normalized_name:
            raise ValueError(
                f"TTS metadata {metadata_path} contains a different clip name"
            )
        wav_path = self.tts_dir / clip.wav_filename
        if not wav_path.is_file():
            raise FileNotFoundError(f"TTS audio file is missing: {wav_path}")
        wav_info = self.file_helper.inspect_wav(path=wav_path)
        return replace(
            clip,
            duration_seconds=wav_info.duration_seconds,
            sample_rate_hz=wav_info.sample_rate_hz,
            channels=wav_info.channels,
            sample_width_bytes=wav_info.sample_width_bytes,
        )

    def audio_path(self, *, name: str) -> Path:
        clip = self.load(name=name)
        return self.tts_dir / clip.wav_filename

    def delete(self, *, name: str) -> TtsClip:
        """Delete one catalogued clip and its metadata sidecar."""
        normalized_name = self.validate_name(name)
        with self._generation_lock:
            clip = self.load(name=normalized_name)
            metadata_path = self.tts_dir / f"{normalized_name}.json"
            wav_path = self.tts_dir / clip.wav_filename
            metadata_path.unlink()
            wav_path.unlink()
            return clip

    @staticmethod
    def validate_name(name: str) -> str:
        if not isinstance(name, str):
            raise ValueError("TTS clip name must be a string")
        normalized_name = name.strip()
        if not normalized_name:
            raise ValueError("TTS clip name cannot be empty")
        if len(normalized_name) > 100:
            raise ValueError("TTS clip name cannot exceed 100 characters")
        if normalized_name in {".", ".."} or any(
            character in normalized_name for character in '<>:"/\\|?*'
        ):
            raise ValueError("TTS clip name contains a path-unsafe character")
        if any(ord(character) < 32 for character in normalized_name):
            raise ValueError("TTS clip name contains a control character")
        return normalized_name

    @classmethod
    def validate_text(cls, text: str) -> str:
        if not isinstance(text, str):
            raise ValueError("TTS text must be a string")
        spoken_text = text.strip()
        if not spoken_text:
            raise ValueError("TTS text cannot be empty")
        if len(spoken_text) > cls.MAX_TEXT_CHARACTERS:
            raise ValueError(
                f"TTS text cannot exceed {cls.MAX_TEXT_CHARACTERS} characters"
            )
        return spoken_text
