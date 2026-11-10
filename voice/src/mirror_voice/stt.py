"""Speech to text via Moonshine, plus the "synthetic voice" path used by --selftest/--bench."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import numpy as np

if TYPE_CHECKING:
    from mirror_voice.tts import Voice

STT_RATE = 16000


def stt_arch(name: str):
    from moonshine_voice import ModelArch

    try:
        return ModelArch[name.upper()]
    except KeyError:
        options = ", ".join(a.name.lower() for a in ModelArch)
        raise SystemExit(f"Unknown stt.model {name!r}. Options: {options}") from None


def apply_keyterms(transcriber: Any, keyterms: list[str]) -> None:
    """Bias a Moonshine Transcriber or MicTranscriber towards `keyterms` (names etc.).

    Only the *_streaming models support this; others just carry on without it.
    """
    from moonshine_voice import MoonshineError

    try:
        transcriber.set_keyterms(keyterms or None)
    except MoonshineError as e:
        print(f"(speech-to-text won't listen out for names: {e})")


def to_stt_audio(audio: np.ndarray, rate: int) -> np.ndarray:
    """int16 audio at any rate -> float 16 kHz with silence around it, like a real mic.

    Without the padding Moonshine garbles the last word.
    """
    pcm = audio.astype(np.float32) / 32768.0
    n = int(len(pcm) * STT_RATE / rate)
    resampled = np.interp(np.linspace(0, len(pcm) - 1, n), np.arange(len(pcm)), pcm)
    return np.concatenate([np.zeros(STT_RATE // 4), resampled, np.zeros(STT_RATE // 2)])


@dataclass(frozen=True)
class Heard:
    text: str
    stt_seconds: float  # time to transcribe the whole utterance
    audio_seconds: float  # length of the spoken question


class SpeechToText:
    """Batch transcriber for pre-recorded audio (the live loop uses MicTranscriber)."""

    def __init__(self, model: str, keyterms: list[str]) -> None:
        from moonshine_voice import get_model_for_language
        from moonshine_voice.transcriber import Transcriber

        model_path, arch = get_model_for_language("en", stt_arch(model))
        self._stt = Transcriber(model_path, arch)
        apply_keyterms(self._stt, keyterms)

    def transcribe(self, pcm16k: np.ndarray) -> str:
        lines = self._stt.transcribe_without_streaming(pcm16k.tolist(), STT_RATE).lines
        return " ".join(line.text for line in lines).strip()

    def hear(self, voice: Voice, text: str) -> Heard:
        """Say `text` in a synthetic voice and transcribe it, as if someone spoke it."""
        audio, rate = voice.synth(text)
        pcm = to_stt_audio(audio, rate)
        started = time.perf_counter()
        heard = self.transcribe(pcm)
        return Heard(heard, time.perf_counter() - started, len(audio) / rate)
