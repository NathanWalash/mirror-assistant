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
class AssistantConfig:
    name: str
    # Everyone in the flat, with or without a calendar: lets the assistant tell
    # "Sam has no calendar here" from "Sam has nothing on". Also taught to STT.
    people: tuple[str, ...] = ()


@dataclass(frozen=True)
class STTConfig:
    model: str
    keyterms: tuple[str, ...] = ()


@dataclass(frozen=True)
class TTSConfig:
    voice: str
    language: str
    speed: float
    volume: float


@dataclass(frozen=True)
class NightConfig:
    """Dim the whole screen between `start` and `end` (local "HH:MM", may span midnight)."""

    start: str = "00:00"
    end: str = "06:30"
    brightness: float = 0.15  # 0 = black, 1 = no dimming

    @classmethod
    def from_raw(cls, raw: dict[str, Any] | bool | None) -> NightConfig | None:
        if raw is False:
            return None  # `night: false` turns dimming off
        raw = raw if isinstance(raw, dict) else {}
        night = cls(
            start=_hhmm(raw.get("start", cls.start)),
            end=_hhmm(raw.get("end", cls.end)),
            brightness=min(1.0, max(0.0, float(raw.get("brightness", cls.brightness)))),
        )
        return None if night.brightness >= 1 or night.start == night.end else night


def _hhmm(value: object) -> str:
    """ "6:30" or "06:30" -> "06:30"."""
    if isinstance(value, int) and not isinstance(value, bool):
        # YAML 1.1 reads an unquoted 06:30 as base-60 minutes (390), so undo that.
        hours, minutes = divmod(value, 60)
    else:
        try:
            hours, minutes = (int(part) for part in str(value).strip().split(":"))
        except ValueError:
            raise ValueError(f'display.night: times look like "06:30", got {value!r}') from None
    if not (0 <= hours <= 23 and 0 <= minutes <= 59):
        raise ValueError(f'display.night: times look like "06:30", got {value!r}')
    return f"{hours:02d}:{minutes:02d}"


@dataclass(frozen=True)
class DisplayConfig:
    enabled: bool
    port: int
    open_browser: bool
    night: NightConfig | None = NightConfig()

    def page_settings(self) -> dict[str, Any]:
        """What the page itself needs to know, sent when it connects."""
        night = self.night
        return {
            "night": None
            if night is None
            else {"start": night.start, "end": night.end, "brightness": night.brightness}
        }


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
    assistant: AssistantConfig
    llm: LLMConfig
    stt: STTConfig
    tts: TTSConfig
    display: DisplayConfig
    widgets: dict[str, WidgetConfig] = field(default_factory=dict)

    @property
    def keyterms(self) -> list[str]:
        """Words speech-to-text should listen out for: the assistant's name first."""
        return merge_keyterms(self.assistant.name, [*self.assistant.people, *self.stt.keyterms])


def merge_keyterms(name: str, extra: list[str] | tuple[str, ...]) -> list[str]:
    """`name` followed by `extra`, blanks dropped and duplicates (any case) removed."""
    out: list[str] = []
    seen: set[str] = set()
    for term in (name, *extra):
        term = term.strip()
        if term and term.lower() not in seen:
            seen.add(term.lower())
            out.append(term)
    return out


def parse_keyterms(raw: Any, key: str = "stt.keyterms") -> tuple[str, ...]:
    """A list of words/phrases from YAML, e.g. stt.keyterms (empty or missing means none)."""
    if raw is None:
        return ()
    if isinstance(raw, str) or not isinstance(raw, list):
        raise ValueError(f"{key} must be a list, e.g. [Alex, Sam], not {raw!r}")
    terms = tuple(str(term).strip() for term in raw)
    for term in terms:
        if "," in term:  # Moonshine uses commas to separate terms
            raise ValueError(f"{key} entries can't contain commas: {term!r}")
    return tuple(term for term in terms if term)


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
    assistant = raw.get("assistant") or {}
    name = str(assistant.get("name") or "Mirror").strip()
    if "," in name:
        raise ValueError(f"assistant.name can't contain commas: {name!r}")
    return Config(
        root=root,
        persona=root / raw["persona"],
        assistant=AssistantConfig(
            name=name, people=parse_keyterms(assistant.get("people"), "assistant.people")
        ),
        llm=LLMConfig(
            port=int(llm["port"]),
            model=str(llm["model"]),
            context_size=int(llm["context_size"]),
            temperature=float(llm["temperature"]),
            max_tokens=int(llm["max_tokens"]),
            history_turns=int(llm["history_turns"]),
        ),
        stt=STTConfig(model=str(stt["model"]), keyterms=parse_keyterms(stt.get("keyterms"))),
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
            night=NightConfig.from_raw(display.get("night")),
        ),
        widgets={
            name: WidgetConfig.from_raw(block) for name, block in (raw.get("widgets") or {}).items()
        },
    )
