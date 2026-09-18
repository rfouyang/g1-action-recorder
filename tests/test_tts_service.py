"""Tests for local speech generation and catalog persistence."""

from __future__ import annotations

import tempfile
import unittest
import wave
from pathlib import Path

from component.tts import TtsService
from util.byteplus_tts_helper import BytePlusTtsHelper
from util.tts_file_helper import TtsFileHelper


class FakeBytePlusTtsHelper:
    speaker = "test-speaker"

    def __init__(self, *, duration_seconds: float = 1.25) -> None:
        self.duration_seconds = duration_seconds
        self.requests: list[dict[str, object]] = []

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
        self.requests.append(
            {
                "text": text,
                "output_path": output_path,
                "speaker": speaker,
                "tone": tone,
                "emotion_strength": emotion_strength,
                "speech_rate": speech_rate,
                "loudness_rate": loudness_rate,
                "pitch": pitch,
                "style_instruction": style_instruction,
            }
        )
        output_path.parent.mkdir(parents=True, exist_ok=True)
        frame_count = round(16_000 * self.duration_seconds)
        with wave.open(str(output_path), "wb") as wav_file:
            wav_file.setnchannels(1)
            wav_file.setsampwidth(2)
            wav_file.setframerate(16_000)
            wav_file.writeframes(b"\x00\x00" * frame_count)
        return output_path


class TtsServiceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.tts_dir = Path(self.temporary_directory.name)
        self.byteplus = FakeBytePlusTtsHelper()
        self.service = TtsService(
            tts_dir=self.tts_dir,
            file_helper=TtsFileHelper(),
            byteplus_helper=self.byteplus,
        )

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def test_generate_load_list_and_measure_actual_wav_duration(self) -> None:
        clip = self.service.generate(
            name="欢迎",
            text="你好，welcome to G1 Guide.",
        )

        self.assertEqual(clip.name, "欢迎")
        self.assertEqual(clip.text, "你好，welcome to G1 Guide.")
        self.assertEqual(clip.wav_filename, "欢迎.wav")
        self.assertAlmostEqual(clip.duration_seconds, 1.25)
        self.assertEqual(clip.sample_rate_hz, 16_000)
        self.assertEqual(clip.channels, 1)
        self.assertEqual(clip.sample_width_bytes, 2)
        self.assertEqual(clip.speaker, BytePlusTtsHelper.DEFAULT_SPEAKER)
        self.assertEqual(clip.speaker_name, "Kian (recommended)")
        self.assertEqual(clip.tone, BytePlusTtsHelper.DEFAULT_TONE)
        self.assertEqual(clip.tone_name, "Warm")
        self.assertTrue((self.tts_dir / "欢迎.wav").is_file())
        self.assertTrue((self.tts_dir / "欢迎.json").is_file())
        self.assertEqual(self.service.load(name="欢迎"), clip)
        self.assertEqual(self.service.list_clips(), (clip,))
        self.assertEqual(self.service.audio_path(name="欢迎"), self.tts_dir / "欢迎.wav")

    def test_selected_bilingual_speaker_and_tone_are_persisted(self) -> None:
        clip = self.service.generate(
            name="energetic_tim",
            text="你好，welcome!",
            speaker="en_male_tim_uranus_bigtts",
            tone="energetic",
            emotion_strength=5,
            speech_rate=15,
            loudness_rate=10,
            pitch=2,
            style_instruction="Sound like a stage host.",
        )

        self.assertEqual(clip.speaker_name, "Tim")
        self.assertEqual(clip.tone_name, "Energetic")
        self.assertEqual(clip.emotion_strength, 5)
        self.assertEqual(clip.speech_rate, 15)
        self.assertEqual(clip.loudness_rate, 10)
        self.assertEqual(clip.pitch, 2)
        self.assertEqual(clip.style_instruction, "Sound like a stage host.")
        self.assertEqual(
            self.byteplus.requests[-1],
            {
                "text": "你好，welcome!",
                "output_path": self.tts_dir / "energetic_tim.wav",
                "speaker": "en_male_tim_uranus_bigtts",
                "tone": "energetic",
                "emotion_strength": 5,
                "speech_rate": 15,
                "loudness_rate": 10,
                "pitch": 2,
                "style_instruction": "Sound like a stage host.",
            },
        )

    def test_duplicate_requires_explicit_overwrite(self) -> None:
        self.service.generate(name="welcome", text="First")
        with self.assertRaises(FileExistsError):
            self.service.generate(name="welcome", text="Second")

        replacement = self.service.generate(
            name="welcome",
            text="Second",
            overwrite=True,
        )

        self.assertEqual(replacement.text, "Second")
        self.assertEqual(self.service.load(name="welcome").text, "Second")

    def test_delete_removes_wav_and_metadata(self) -> None:
        clip = self.service.generate(name="temporary", text="Delete me")

        deleted = self.service.delete(name=clip.name)

        self.assertEqual(deleted, clip)
        self.assertFalse((self.tts_dir / "temporary.wav").exists())
        self.assertFalse((self.tts_dir / "temporary.json").exists())
        self.assertEqual(self.service.list_clips(), ())
        with self.assertRaises(FileNotFoundError):
            self.service.delete(name=clip.name)

    def test_invalid_name_text_and_unconfigured_generation_are_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "path-unsafe"):
            self.service.generate(name="../escape", text="Hello")
        with self.assertRaisesRegex(ValueError, "cannot be empty"):
            self.service.generate(name="empty", text="  ")

        unconfigured = TtsService(
            tts_dir=self.tts_dir,
            file_helper=TtsFileHelper(),
            byteplus_helper=None,
        )
        self.assertFalse(unconfigured.configured)
        with self.assertRaisesRegex(RuntimeError, "not configured"):
            unconfigured.generate(name="missing_key", text="Hello")


def demo_test_tts_service() -> None:
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(TtsServiceTest)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    if not result.wasSuccessful():
        raise SystemExit(1)


def main() -> None:
    demo_test_tts_service()


if __name__ == "__main__":
    main()
