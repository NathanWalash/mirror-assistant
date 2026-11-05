"""Text to speech with Piper."""

from __future__ import annotations

import shutil
from pathlib import Path

import numpy as np
from piper import PiperVoice, SynthesisConfig
from piper.phonemize_espeak import ESPEAK_DATA_DIR

from mirror_voice.config import TTSConfig

# espeak-ng (used by Piper for pronunciation) silently ignores long data paths and falls
# back to a path from Piper's build machine. Keep a copy of its data somewhere short.
SHORT_ESPEAK_DIR = Path.home() / ".cache" / "mirror-assistant" / "espeak-ng-data"


def short_espeak_dir() -> Path:
    if not (SHORT_ESPEAK_DIR / "phontab").is_file():
        shutil.copytree(ESPEAK_DATA_DIR, SHORT_ESPEAK_DIR, dirs_exist_ok=True)
    return SHORT_ESPEAK_DIR


class Voice:
    def __init__(self, cfg: TTSConfig) -> None:
        if not cfg.voice_path.is_file():
            raise FileNotFoundError(
                f"Voice {cfg.voice!r} not found in {cfg.voices_dir}. Run scripts/setup.sh."
            )
        self._voice = PiperVoice.load(str(cfg.voice_path), espeak_data_dir=short_espeak_dir())
        self._syn = SynthesisConfig(length_scale=cfg.length_scale, volume=cfg.volume)

    def synth(self, text: str) -> tuple[np.ndarray, int]:
        """Return (int16 audio, sample rate) for `text`."""
        chunks = list(self._voice.synthesize(text, self._syn))
        if not chunks:
            return np.zeros(0, dtype=np.int16), self._voice.config.sample_rate
        return np.concatenate([c.audio_int16_array for c in chunks]), chunks[0].sample_rate
