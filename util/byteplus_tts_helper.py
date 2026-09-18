from __future__ import annotations

import base64
import json
import os
import wave
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import uuid4

import requests
from loguru import logger


class BytePlusTtsError(RuntimeError):
    """Raised when BytePlus does not return valid synthesized audio."""


@dataclass(frozen=True, slots=True)
class TtsSpeaker:
    id: str
    name: str
    description: str


@dataclass(frozen=True, slots=True)
class TtsTone:
    id: str
    name: str
    instruction: str


class BytePlusTtsHelper:
    """Generate a 16 kHz mono WAV file with BytePlus TTS 2.0."""

    URL = "https://voice.ap-southeast-1.bytepluses.com/api/v3/tts/unidirectional"
    RESOURCE_ID = "seed-tts-2.0"
    APP_KEY = "aGjiRDfUWi"
    DEFAULT_SPEAKER = "zh_male_m191_uranus_bigtts"
    DEFAULT_TONE = "warm"
    SPEAKERS = (
        TtsSpeaker(DEFAULT_SPEAKER, "Kian (recommended)", "Male · steady and clear"),
        TtsSpeaker(
            "zh_female_cancan_uranus_bigtts",
            "Corinne",
            "Female · vivid and energetic",
        ),
        TtsSpeaker(
            "zh_female_shuangkuaisisi_uranus_bigtts",
            "Gigi",
            "Female · steady and composed",
        ),
        TtsSpeaker(
            "zh_female_yingyujiaoxue_uranus_bigtts",
            "Jean",
            "Female · clear and encouraging",
        ),
        TtsSpeaker(
            "en_male_tim_uranus_bigtts",
            "Tim",
            "Male · clear and friendly",
        ),
    )
    TONES = (
        TtsTone(
            "natural",
            "Natural",
            "请自然、清晰地朗读。Speak naturally with clear, balanced delivery.",
        ),
        TtsTone(
            "warm",
            "Warm",
            "请用明显温暖、友好、亲切的语气朗读。"
            "Speak with an unmistakably warm and friendly tone.",
        ),
        TtsTone(
            "cheerful",
            "Cheerful",
            "请带着笑意，用明显欢快、活泼的语气朗读。"
            "Speak with a clearly cheerful, smiling, upbeat emotion and lively "
            "intonation.",
        ),
        TtsTone(
            "calm",
            "Calm",
            "请用明显平静、舒缓、令人安心的语气慢稳地朗读。"
            "Speak calmly with soothing, reassuring, steady delivery.",
        ),
        TtsTone(
            "energetic",
            "Energetic",
            "请用明显有活力、兴奋、充满热情的语气朗读。"
            "Speak with strongly energetic, excited enthusiasm and dynamic "
            "intonation.",
        ),
        TtsTone(
            "serious",
            "Serious",
            "请用明显严肃、沉稳、权威的语气朗读。"
            "Speak with a distinctly serious, composed, authoritative tone.",
        ),
    )

    def __init__(self, api_key: str, **kwargs: object) -> None:
        self.api_key = api_key.strip()
        self.speaker = str(kwargs.get("speaker", self.DEFAULT_SPEAKER))
        self.sample_rate = int(kwargs.get("sample_rate", 16000))
        self.timeout = kwargs.get("timeout", (5.0, 60.0))
        self.session = kwargs.get("session") or requests.Session()

        if not self.api_key:
            raise ValueError("BytePlus api_key cannot be empty")
        if self.sample_rate != 16000:
            raise ValueError("G1 playback requires a 16000 Hz sample rate")
        self.speaker_option(self.speaker)

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
        spoken_text = text.strip()
        audio_path = output_path.resolve()
        selected_speaker = self.speaker_option(speaker or self.speaker)
        selected_tone = self.tone_option(tone or self.DEFAULT_TONE)
        self.validate_delivery_parameters(
            emotion_strength=emotion_strength,
            speech_rate=speech_rate,
            loudness_rate=loudness_rate,
            pitch=pitch,
            style_instruction=style_instruction,
        )
        if not spoken_text:
            raise ValueError("TTS text cannot be empty")
        if audio_path.suffix.lower() != ".wav":
            raise ValueError("BytePlus TTS output must use the .wav extension")

        pcm_audio = self._request_pcm(
            spoken_text,
            speaker=selected_speaker.id,
            tone=selected_tone,
            emotion_strength=emotion_strength,
            speech_rate=speech_rate,
            loudness_rate=loudness_rate,
            pitch=pitch,
            style_instruction=style_instruction,
        )
        self._write_wav(audio_path, pcm_audio)
        logger.info("BytePlus generated audio file {}", audio_path)
        return audio_path

    def _request_pcm(
        self,
        text: str,
        *,
        speaker: str,
        tone: TtsTone,
        emotion_strength: int,
        speech_rate: int,
        loudness_rate: int,
        pitch: int,
        style_instruction: str,
    ) -> bytes:
        logger.info(
            "Requesting BytePlus TTS 2.0 speaker {} for {} characters",
            speaker,
            len(text),
        )
        try:
            response = self.session.post(
                self.URL,
                headers=self._headers(),
                json=self._payload(
                    text,
                    speaker=speaker,
                    tone=tone.id,
                    emotion_strength=emotion_strength,
                    speech_rate=speech_rate,
                    loudness_rate=loudness_rate,
                    pitch=pitch,
                    style_instruction=style_instruction,
                ),
                stream=True,
                timeout=self.timeout,
            )
        except requests.RequestException as error:
            raise BytePlusTtsError(
                "Could not connect to the BytePlus TTS service"
            ) from error
        pcm_audio = bytearray()
        try:
            response.raise_for_status()
            response.encoding = "utf-8"
            for event in self._events(response):
                response_code = int(event.get("code", 0))
                if response_code == 20000000:
                    break
                if response_code != 0:
                    message = event.get("message", "unknown error")
                    raise BytePlusTtsError(
                        f"BytePlus TTS failed with code {response_code}: {message}"
                    )
                encoded_audio = event.get("data")
                if encoded_audio:
                    pcm_audio.extend(base64.b64decode(encoded_audio, validate=True))
        except requests.RequestException as error:
            raise BytePlusTtsError("BytePlus TTS request failed") from error
        except (ValueError, json.JSONDecodeError) as error:
            raise BytePlusTtsError("BytePlus returned malformed audio data") from error
        finally:
            response.close()

        if not pcm_audio:
            raise BytePlusTtsError("BytePlus returned no audio")

        complete_pcm_audio = bytes(pcm_audio)
        return complete_pcm_audio

    def _write_wav(self, audio_path: Path, pcm_audio: bytes) -> None:
        audio_path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = audio_path.with_suffix(f".{uuid4().hex}.tmp")
        try:
            with wave.open(str(temporary_path), "wb") as wav_file:
                wav_file.setnchannels(1)
                wav_file.setsampwidth(2)
                wav_file.setframerate(self.sample_rate)
                wav_file.writeframes(pcm_audio)
            os.replace(temporary_path, audio_path)
        finally:
            temporary_path.unlink(missing_ok=True)

    def _headers(self) -> dict[str, str]:
        request_headers = {
            "X-Api-Key": self.api_key,
            "X-Api-Resource-Id": self.RESOURCE_ID,
            "X-Api-App-Key": self.APP_KEY,
            "X-Api-Request-Id": str(uuid4()),
            "Content-Type": "application/json",
            "Connection": "keep-alive",
        }
        return request_headers

    def _payload(
        self,
        text: str,
        *,
        speaker: str | None = None,
        tone: str | None = None,
        emotion_strength: int = 4,
        speech_rate: int = 0,
        loudness_rate: int = 0,
        pitch: int = 0,
        style_instruction: str = "",
    ) -> dict[str, Any]:
        selected_speaker = self.speaker_option(speaker or self.speaker)
        selected_tone = self.tone_option(tone or self.DEFAULT_TONE)
        self.validate_delivery_parameters(
            emotion_strength=emotion_strength,
            speech_rate=speech_rate,
            loudness_rate=loudness_rate,
            pitch=pitch,
            style_instruction=style_instruction,
        )
        context_instruction = self._context_instruction(
            tone=selected_tone,
            emotion_strength=emotion_strength,
            style_instruction=style_instruction,
        )
        additions = {
            "enable_language_detector": True,
            "disable_markdown_filter": True,
            "disable_emoji_filter": False,
            "max_length_to_filter_parenthesis": 0,
            "cache_config": {"text_type": 1, "use_cache": False},
            "post_process": {"pitch": pitch},
            "context_texts": [context_instruction],
        }
        request_payload = {
            "req_params": {
                "text": text,
                "speaker": selected_speaker.id,
                "audio_params": {
                    "format": "pcm",
                    "sample_rate": self.sample_rate,
                    "speech_rate": speech_rate,
                    "loudness_rate": loudness_rate,
                },
                "additions": json.dumps(additions),
            }
        }
        return request_payload

    @staticmethod
    def validate_delivery_parameters(
        *,
        emotion_strength: int,
        speech_rate: int,
        loudness_rate: int,
        pitch: int,
        style_instruction: str,
    ) -> None:
        if not 1 <= emotion_strength <= 5:
            raise ValueError("Emotion strength must be between 1 and 5")
        if not -50 <= speech_rate <= 100:
            raise ValueError("Speech rate must be between -50 and 100")
        if not -50 <= loudness_rate <= 100:
            raise ValueError("Loudness rate must be between -50 and 100")
        if not -12 <= pitch <= 12:
            raise ValueError("Pitch must be between -12 and 12")
        if len(style_instruction.strip()) > 300:
            raise ValueError("Style instruction cannot exceed 300 characters")

    @staticmethod
    def _context_instruction(
        *,
        tone: TtsTone,
        emotion_strength: int,
        style_instruction: str,
    ) -> str:
        parts = [
            tone.instruction,
            (
                f"情绪表达强度为 {emotion_strength}/5。"
                f"Use an emotion intensity of {emotion_strength} out of 5."
            ),
        ]
        custom_instruction = style_instruction.strip()
        if custom_instruction:
            parts.append(custom_instruction)
        return " ".join(parts)

    @classmethod
    def speaker_option(cls, speaker: str) -> TtsSpeaker:
        for option in cls.SPEAKERS:
            if option.id == speaker:
                return option
        raise ValueError(f"Unsupported bilingual BytePlus speaker: {speaker}")

    @classmethod
    def tone_option(cls, tone: str) -> TtsTone:
        for option in cls.TONES:
            if option.id == tone:
                return option
        raise ValueError(f"Unsupported BytePlus speech tone: {tone}")

    def _events(self, response: Any) -> Iterator[dict[str, Any]]:
        decoder = json.JSONDecoder()
        response_buffer = ""
        for response_chunk in response.iter_content(
            chunk_size=4096,
            decode_unicode=True,
        ):
            response_buffer += response_chunk
            while response_buffer.strip():
                stripped_buffer = response_buffer.lstrip()
                try:
                    event, event_end = decoder.raw_decode(stripped_buffer)
                except json.JSONDecodeError:
                    break
                yield event
                response_buffer = stripped_buffer[event_end:]

        if response_buffer.strip():
            raise BytePlusTtsError("BytePlus returned an incomplete JSON event")


def demo_byteplus_tts_helper() -> None:
    helper = BytePlusTtsHelper(api_key="offline-demo-key")
    request_payload = helper._payload("你好，welcome to G1 Guide.")
    request_parameters = request_payload["req_params"]
    assert request_parameters["speaker"] == BytePlusTtsHelper.DEFAULT_SPEAKER
    assert request_parameters["audio_params"]["sample_rate"] == 16000
    print("BytePlus TTS helper: bilingual WAV output configured")


def main() -> None:
    demo_byteplus_tts_helper()


if __name__ == "__main__":
    main()
