"""Load settings: shared defaults from config.example.yaml, your config.yaml on top.

config.example.yaml is committed. config.yaml is yours and git-ignored (scripts/setup.sh
creates it as a copy). Anything you leave out of config.yaml falls back to the example,
so new settings added to the example still reach everyone.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

EXAMPLE_CONFIG_NAME = "config.example.yaml"
CONFIG_NAME = "config.yaml"


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
    language: str
    speed: float
    volume: float


@dataclass(frozen=True)
class DisplayConfig:
    enabled: bool
    port: int
    open_browser: bool


@dataclass(frozen=True)
class WidgetConfig:
    """One block under `widgets:`. Everything except the two common keys is `settings`,
    which the widget's own module reads (e.g. latitude/longitude for weather)."""

    enabled: bool
    refresh_minutes: float | None  # None: the widget's DEFAULT_REFRESH_MINUTES
    settings: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_raw(cls, raw: dict[str, Any] | None) -> WidgetConfig:
        settings = dict(raw or {})
        enabled = bool(settings.pop("enabled", True))
        refresh = settings.pop("refresh_minutes", None)
        return cls(enabled, None if refresh is None else float(refresh), settings)


@dataclass(frozen=True)
class Config:
    root: Path
    persona: Path
    llm: LLMConfig
    stt: STTConfig
    tts: TTSConfig
    display: DisplayConfig
    widgets: dict[str, WidgetConfig] = field(default_factory=dict)


def find_repo_root(start: Path | None = None) -> Path:
    """Walk up from `start` (default: cwd) to the folder holding config.example.yaml."""
    here = (start or Path.cwd()).resolve()
    for folder in (here, *here.parents):
        if (folder / EXAMPLE_CONFIG_NAME).is_file():
            return folder
    raise FileNotFoundError(f"Couldn't find {EXAMPLE_CONFIG_NAME} in {here} or any parent.")


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
    raw = yaml.safe_load((root / EXAMPLE_CONFIG_NAME).read_text()) or {}
    mine = root / CONFIG_NAME
    if mine.is_file():
        raw = deep_merge(raw, yaml.safe_load(mine.read_text()) or {})

    llm, stt, tts = raw["llm"], raw["stt"], raw["tts"]
    display = raw.get("display", {})
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
            language=str(tts.get("language", "en-gb")),
            speed=float(tts.get("speed", 1.0)),
            volume=float(tts.get("volume", 1.0)),
        ),
        display=DisplayConfig(
            enabled=bool(display.get("enabled", True)),
            port=int(display.get("port", 8765)),
            open_browser=bool(display.get("open_browser", True)),
        ),
        widgets={
            name: WidgetConfig.from_raw(block) for name, block in (raw.get("widgets") or {}).items()
        },
    )
