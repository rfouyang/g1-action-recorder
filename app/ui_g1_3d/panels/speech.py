"""View data and commands for the speech asset workspace."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from app.ui_g1_3d.context import UIContext
from component.tts import TtsClip, TtsService
from util.byteplus_tts_helper import BytePlusTtsHelper


class GenerateSpeechCommand(BaseModel):
    """One named text prompt to synthesize as a WAV asset."""

    model_config = ConfigDict(extra="forbid")

    name: str
    text: str = Field(min_length=1, max_length=TtsService.MAX_TEXT_CHARACTERS)
    speaker: str = BytePlusTtsHelper.DEFAULT_SPEAKER
    tone: str = BytePlusTtsHelper.DEFAULT_TONE
    emotion_strength: int = Field(default=4, ge=1, le=5)
    speech_rate: int = Field(default=0, ge=-50, le=100)
    loudness_rate: int = Field(default=0, ge=-50, le=100)
    pitch: int = Field(default=0, ge=-12, le=12)
    style_instruction: str = Field(default="", max_length=300)
    overwrite: bool = False


class SpeechPanel:
    """Generate and browse reusable G1 speech assets."""

    name = "Speech"
    template = "panels/speech.html"

    @staticmethod
    def template_context(context: UIContext) -> dict[str, object]:
        service = context.app.tts_service
        return {
            "tts_configured": service.configured,
            "tts_speakers": service.speaker_options,
            "tts_tones": service.tone_options,
            "tts_default_speaker": BytePlusTtsHelper.DEFAULT_SPEAKER,
            "tts_default_tone": BytePlusTtsHelper.DEFAULT_TONE,
        }

    @staticmethod
    def generate(
        *,
        context: UIContext,
        command: GenerateSpeechCommand,
    ) -> TtsClip:
        return context.app.tts_service.generate(
            name=command.name,
            text=command.text,
            speaker=command.speaker,
            tone=command.tone,
            emotion_strength=command.emotion_strength,
            speech_rate=command.speech_rate,
            loudness_rate=command.loudness_rate,
            pitch=command.pitch,
            style_instruction=command.style_instruction,
            overwrite=command.overwrite,
        )

    @staticmethod
    def delete(*, context: UIContext, name: str) -> TtsClip:
        return context.app.tts_service.delete(name=name)
