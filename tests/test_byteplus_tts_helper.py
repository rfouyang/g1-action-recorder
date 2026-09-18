"""Offline contract tests for the BytePlus TTS adapter."""

from __future__ import annotations

import base64
import json
import tempfile
import unittest
import wave
from pathlib import Path

import requests

from util.byteplus_tts_helper import BytePlusTtsError, BytePlusTtsHelper


class FakeResponse:
    def __init__(self, chunks: tuple[str, ...]) -> None:
        self.chunks = chunks
        self.encoding = None
        self.closed = False

    def raise_for_status(self) -> None:
        return None

    def iter_content(self, *, chunk_size: int, decode_unicode: bool):
        self.chunk_size = chunk_size
        self.decode_unicode = decode_unicode
        yield from self.chunks

    def close(self) -> None:
        self.closed = True


class FakeSession:
    def __init__(self, response: FakeResponse) -> None:
        self.response = response
        self.calls: list[dict[str, object]] = []

    def post(self, url: str, **kwargs: object) -> FakeResponse:
        self.calls.append({"url": url, **kwargs})
        return self.response


class FailingSession:
    def post(self, url: str, **kwargs: object) -> FakeResponse:
        raise requests.ConnectionError("offline")


class BytePlusTtsHelperTest(unittest.TestCase):
    def test_generate_decodes_streamed_pcm_into_g1_wav(self) -> None:
        pcm = b"\x00\x00\x01\x00"
        encoded = base64.b64encode(pcm).decode("ascii")
        response = FakeResponse(
            (
                '{"code":0,"data":"',
                encoded,
                '"}{"code":20000000}',
            )
        )
        session = FakeSession(response)
        helper = BytePlusTtsHelper(api_key="test-key", session=session)

        with tempfile.TemporaryDirectory() as temporary_directory:
            path = helper.generate(
                "你好，G1.",
                Path(temporary_directory) / "speech.wav",
                speaker="zh_female_cancan_uranus_bigtts",
                tone="calm",
                emotion_strength=5,
                speech_rate=20,
                loudness_rate=-10,
                pitch=2,
                style_instruction="Sound reassuring.",
            )
            with wave.open(str(path), "rb") as wav_file:
                self.assertEqual(wav_file.getframerate(), 16_000)
                self.assertEqual(wav_file.getnchannels(), 1)
                self.assertEqual(wav_file.getsampwidth(), 2)
                self.assertEqual(wav_file.readframes(wav_file.getnframes()), pcm)

        self.assertTrue(response.closed)
        self.assertEqual(session.calls[0]["url"], BytePlusTtsHelper.URL)
        headers = session.calls[0]["headers"]
        self.assertEqual(headers["X-Api-Key"], "test-key")
        request_parameters = session.calls[0]["json"]["req_params"]
        self.assertEqual(
            request_parameters["speaker"],
            "zh_female_cancan_uranus_bigtts",
        )
        additions = json.loads(request_parameters["additions"])
        self.assertNotIn("explicit_language", additions)
        self.assertFalse(additions["cache_config"]["use_cache"])
        self.assertEqual(additions["post_process"]["pitch"], 2)
        self.assertIn("calm", additions["context_texts"][0].lower())
        self.assertIn("5 out of 5", additions["context_texts"][0])
        self.assertIn("Sound reassuring.", additions["context_texts"][0])
        self.assertEqual(request_parameters["audio_params"]["speech_rate"], 20)
        self.assertEqual(request_parameters["audio_params"]["loudness_rate"], -10)

    def test_delivery_parameters_are_validated(self) -> None:
        helper = BytePlusTtsHelper(api_key="test-key", session=FakeSession(FakeResponse(())))

        with self.assertRaisesRegex(ValueError, "Speech rate"):
            helper._payload("Hello", speech_rate=101)
        with self.assertRaisesRegex(ValueError, "Emotion strength"):
            helper._payload("Hello", emotion_strength=0)
        with self.assertRaisesRegex(ValueError, "Pitch"):
            helper._payload("Hello", pitch=-13)

    def test_generate_rejects_incomplete_stream(self) -> None:
        response = FakeResponse(('{"code":0,"data":"unfinished',))
        helper = BytePlusTtsHelper(
            api_key="test-key",
            session=FakeSession(response),
        )

        with tempfile.TemporaryDirectory() as temporary_directory:
            with self.assertRaisesRegex(BytePlusTtsError, "incomplete"):
                helper.generate(
                    "Hello",
                    Path(temporary_directory) / "speech.wav",
                )

    def test_generate_translates_network_failures(self) -> None:
        helper = BytePlusTtsHelper(
            api_key="test-key",
            session=FailingSession(),
        )

        with tempfile.TemporaryDirectory() as temporary_directory:
            with self.assertRaisesRegex(BytePlusTtsError, "Could not connect"):
                helper.generate(
                    "Hello",
                    Path(temporary_directory) / "speech.wav",
                )


def demo_test_byteplus_tts_helper() -> None:
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(BytePlusTtsHelperTest)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    if not result.wasSuccessful():
        raise SystemExit(1)


def main() -> None:
    demo_test_byteplus_tts_helper()


if __name__ == "__main__":
    main()
