"""Timing numbers for one reply, and small helpers to tabulate them (used by --bench)."""

from __future__ import annotations

import statistics
from collections.abc import Sequence
from dataclasses import dataclass, field


def real_time_factor(compute_seconds: float, audio_seconds: float) -> float | None:
    """Seconds of work per second of audio. Under 1 means faster than real time."""
    return compute_seconds / audio_seconds if audio_seconds > 0 else None


@dataclass
class ReplyTimings:
    """What one reply cost. Times are seconds since the reply was requested."""

    first_token: float | None = None  # LLM time to first token
    first_audio: float | None = None  # first chunk of voice ready to play
    llm_done: float | None = None
    tokens: int = 0  # generated tokens (llama.cpp's count, else streamed chunks)
    tokens_per_second: float | None = None  # llama.cpp's generation speed
    prompt_seconds: float | None = None  # llama.cpp reading the prompt
    synth_seconds: float = 0.0  # time spent producing audio
    audio_seconds: float = 0.0  # length of the audio produced
    reply: list[str] = field(default_factory=list)  # sentences, in order

    @property
    def tts_rtf(self) -> float | None:
        return real_time_factor(self.synth_seconds, self.audio_seconds)

    def add_llm_stats(self, timings: dict, streamed_chunks: int, elapsed: float) -> None:
        """Fill token counts from llama.cpp's `timings`, or estimate from the stream."""
        self.tokens = int(timings.get("predicted_n") or streamed_chunks)
        self.tokens_per_second = timings.get("predicted_per_second")
        if self.tokens_per_second is None and self.first_token is not None:
            gen = elapsed - self.first_token
            self.tokens_per_second = (self.tokens - 1) / gen if gen > 0 else None
        if (ms := timings.get("prompt_ms")) is not None:
            self.prompt_seconds = ms / 1000


@dataclass(frozen=True)
class Column:
    key: str
    header: str
    fmt: str = "{:.2f}"


def fmt_cell(value, fmt: str) -> str:
    if value is None:
        return "-"
    if isinstance(value, str):
        return value
    return fmt.format(value)


def medians(rows: Sequence[dict], keys: Sequence[str]) -> dict:
    """Median of each numeric column, ignoring missing values (None if there are none)."""
    out = {}
    for key in keys:
        values = [r[key] for r in rows if isinstance(r.get(key), int | float)]
        out[key] = statistics.median(values) if values else None
    return out


def format_table(rows: Sequence[dict], columns: Sequence[Column]) -> str:
    """Plain-text table, columns sized to fit, numbers right-aligned."""
    cells = [[c.header for c in columns]]
    cells += [[fmt_cell(r.get(c.key), c.fmt) for c in columns] for r in rows]
    widths = [max(len(row[i]) for row in cells) for i in range(len(columns))]
    numeric = [any(isinstance(r.get(c.key), int | float) for r in rows) for c in columns]

    def line(row: list[str]) -> str:
        parts = [
            cell.rjust(w) if num else cell.ljust(w)
            for cell, w, num in zip(row, widths, numeric, strict=True)
        ]
        return "  ".join(parts).rstrip()

    rule = "  ".join("-" * w for w in widths)
    return "\n".join([line(cells[0]), rule, *(line(row) for row in cells[1:])])


def shorten(text: str, width: int) -> str:
    return text if len(text) <= width else text[: width - 1] + "…"
