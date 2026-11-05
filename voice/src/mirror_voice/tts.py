"""Text to speech via Moonshine, which runs Kokoro, Piper and ZipVoice voices.

The voice id's prefix picks the engine: kokoro_*, piper_* or zipvoice_*.
Voices download automatically the first time they're used.
"""

from __future__ import annotations

from collections.abc import Iterator

import numpy as np

from mirror_voice.config import TTSConfig


def to_int16(samples, gain: float = 1.0) -> np.ndarray:
    """Float samples in -1..1 to int16 PCM, applying `gain` and clipping."""
    audio = np.clip(np.asarray(samples, dtype=np.float32) * gain, -1.0, 1.0)
    return (audio * 32767).astype(np.int16)


def available_voices(language: str) -> list[str]:
    from moonshine_voice import list_tts_voices

    found = list_tts_voices(language)
    return sorted(set(found["present"]) | set(found["downloadable"]))


class Voice:
    def __init__(self, cfg: TTSConfig) -> None:
        from moonshine_voice.tts import TextToSpeech

        self.cfg = cfg
        self._tts = (
            TextToSpeech()
            .language(cfg.language)
            .voice(cfg.voice)
            .options({"speed": str(cfg.speed)})
            .load()
        )

    def stream(self, text: str) -> Iterator[tuple[np.ndarray, int]]:
        """Yield (int16 audio, sample rate) chunks as soon as each is ready.

        The first chunk arrives well before the whole sentence is done, which is
        what keeps the slower, nicer voices (Kokoro) feeling responsive.
        """
        for chunk in self._tts.stream(text):
            if chunk.samples:
                yield to_int16(chunk.samples, self.cfg.volume), chunk.sample_rate

    def synth(self, text: str) -> tuple[np.ndarray, int]:
        """Return the whole of `text` as (int16 audio, sample rate)."""
        chunks = list(self.stream(text))
        if not chunks:
            return np.zeros(0, dtype=np.int16), 24000
        return np.concatenate([audio for audio, _ in chunks]), chunks[0][1]
