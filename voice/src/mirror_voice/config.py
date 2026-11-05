"""Load config.yaml, with optional private overrides from config.local.yaml."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

CONFIG_NAME = "config.yaml"
LOCAL_CONFIG_NAME = "config.local.yaml"


@dataclass(frozen=True)
class LLMConfig:
    port: int
    model: str
    context_size: int
    temperature: float
    max_tokens: int
    history_turns: int

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.port}"


@dataclass(frozen=True)
class STTConfig:
    model: str


@dataclass(frozen=True)
class TTSConfig:
    voice: str
    voices_dir: Path
    length_scale: float
    volume: float

    @property
    def voice_path(self) -> Path:
        return self.voices_dir / f"{self.voice}.onnx"


@dataclass(frozen=True)
class Config:
    root: Path
    persona: Path
    llm: LLMConfig
    stt: STTConfig
    tts: TTSConfig


def find_repo_root(start: Path | None = None) -> Path:
    """Walk up from `start` (default: cwd) to the folder holding config.yaml."""
    here = (start or Path.cwd()).resolve()
    for folder in (here, *here.parents):
        if (folder / CONFIG_NAME).is_file():
            return folder
    raise FileNotFoundError(f"Couldn't find {CONFIG_NAME} in {here} or any parent folder.")


def deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """Return `base` with `override` laid on top, merging nested dicts key by key."""
    merged = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def load_config(root: Path | None = None) -> Config:
    root = root or find_repo_root()
    raw = yaml.safe_load((root / CONFIG_NAME).read_text()) or {}
    local = root / LOCAL_CONFIG_NAME
    if local.is_file():
        raw = deep_merge(raw, yaml.safe_load(local.read_text()) or {})

    llm, stt, tts = raw["llm"], raw["stt"], raw["tts"]
    return Config(
        root=root,
        persona=root / raw["persona"],
        llm=LLMConfig(
            port=int(llm["port"]),
            model=str(llm["model"]),
            context_size=int(llm["context_size"]),
            temperature=float(llm["temperature"]),
            max_tokens=int(llm["max_tokens"]),
            history_turns=int(llm["history_turns"]),
        ),
        stt=STTConfig(model=str(stt["model"])),
        tts=TTSConfig(
            voice=str(tts["voice"]),
            voices_dir=root / tts["voices_dir"],
            length_scale=float(tts["length_scale"]),
            volume=float(tts["volume"]),
        ),
    )
