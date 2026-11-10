"""`mirror-talk --bench`: time each stage of the pipeline, without a mic or speakers.

Built for deciding model and voice sizes on the Pi. Fixed questions are spoken by the
configured voice, transcribed, answered and voiced, and every stage is timed:

  all  speech-to-text -> LLM -> TTS, as in a real chat (needs the model server)
  tts  the voice alone on fixed reply sentences (no model server needed)
  stt  speech-to-text alone on the fixed questions (no model server needed)

Prints a table (with medians) and appends one JSON line per run to models/bench.jsonl.
"""

from __future__ import annotations

import datetime as dt
import json
import platform
import time
from pathlib import Path
from typing import TYPE_CHECKING

from mirror_voice.config import Config
from mirror_voice.metrics import Column, format_table, medians, real_time_factor, shorten
from mirror_voice.stt import SpeechToText

if TYPE_CHECKING:
    from mirror_voice.app import Mirror

MODES = ("all", "tts", "stt")
RESULTS_NAME = "bench.jsonl"

# Spoken to the assistant. {name} is assistant.name, so the name check means something.
QUESTIONS = (
    "Morning {name}. Should I bring a coat today?",
    "{name}, what should I have for tea tonight?",
    "Hey {name}, tell me a joke about Bradford.",
    "{name}, how do I look this morning?",
    "What's a good film for a rainy Sunday, {name}?",
)

# Typical reply sentences, short to long, for timing the voice on its own.
TTS_SENTENCES = (
    "Ey up.",
    "Aye, take a coat, it's chucking it down.",
    "You look like you've been dragged through a hedge backwards, but a brew will sort that.",
    "Fish and chips, obviously. It's Friday, and I don't make the rules.",
    "If you're after a film, I'd go for something long and daft, because the weather "
    "isn't going anywhere and neither are you.",
)

STT_COLUMNS = [
    Column("heard", "heard"),
    Column("name_heard", "name?"),
    Column("audio_s", "speech s"),
    Column("stt_s", "STT s"),
    Column("stt_rtf", "STT RTF"),
]
TTS_COLUMNS = [
    Column("text", "sentence"),
    Column("audio_s", "audio s"),
    Column("first_chunk_s", "1st chunk s"),
    Column("synth_s", "synth s"),
    Column("tts_rtf", "TTS RTF"),
]
ALL_COLUMNS = [
    Column("heard", "heard"),
    Column("name_heard", "name?"),
    Column("stt_s", "STT s"),
    Column("ttft_s", "LLM 1st tok s"),
    Column("tokens", "tokens", "{:.0f}"),
    Column("tok_per_s", "tok/s", "{:.1f}"),
    Column("tts_rtf", "TTS RTF"),
    Column("first_audio_s", "1st audio s"),
    Column("speech_to_audio_s", "end-to-end s"),
]
COLUMNS = {"all": ALL_COLUMNS, "tts": TTS_COLUMNS, "stt": STT_COLUMNS}

NOTES = {
    "all": (
        "STT s: transcribing the whole question after it ends (the live loop streams, so "
        "it's usually quicker).\n"
        "1st audio s: from the question's text to the first voice audio "
        "(LLM's first sentence + TTS first chunk).\n"
        "end-to-end s: STT s + 1st audio s, i.e. you stop talking -> it starts talking.\n"
        "TTS RTF: seconds of synthesis per second of speech while the LLM runs too; "
        "under 1 keeps up."
    ),
    "tts": (
        "1st chunk s: wait before the first audio of a sentence can play.\n"
        "TTS RTF: seconds of synthesis per second of speech; under 1 is faster than "
        "real time, so speech never stalls."
    ),
    "stt": "STT RTF: seconds of transcription per second of speech (lower is better).",
}


def questions(name: str) -> list[str]:
    return [q.format(name=name) for q in QUESTIONS]


def name_heard(name: str, heard: str) -> str:
    return "yes" if name.lower() in heard.lower() else "no"


def bench_record(mode: str, cfg: Config, rows: list[dict], when: dt.datetime) -> dict:
    """One JSON-able result: what was run, on what, with every row and the medians."""
    numeric = [c.key for c in COLUMNS[mode] if c.key not in ("heard", "text", "name_heard")]
    return {
        "when": when.isoformat(timespec="seconds"),
        "mode": mode,
        "machine": {
            "platform": platform.platform(),
            "arch": platform.machine(),
            "python": platform.python_version(),
        },
        "settings": {
            "stt_model": cfg.stt.model,
            "stt_keyterms": len(cfg.keyterms),
            "llm_model": cfg.llm.model if mode == "all" else None,
            "max_tokens": cfg.llm.max_tokens if mode == "all" else None,
            "voice": cfg.tts.voice if mode != "stt" else None,
            "speed": cfg.tts.speed if mode != "stt" else None,
        },
        "median": medians(rows, numeric),
        "rows": rows,
    }


def run(mirror: Mirror, mode: str, rounds: int = 1) -> dict:
    cfg = mirror.cfg
    print(f"Benchmark: {mode} x{rounds}  |  STT {cfg.stt.model}  |  voice {cfg.tts.voice}", end="")
    print(f"  |  LLM {cfg.llm.model}" if mode == "all" else "")
    print(f"Machine: {platform.platform()}\n")

    mirror.voice.synth("Warming up.")  # the first synthesis pays one-off costs
    stt = SpeechToText(cfg.stt.model, cfg.keyterms) if mode != "tts" else None

    rows: list[dict] = []
    for _ in range(max(1, rounds)):
        if mode == "tts":
            rows += [time_tts(mirror, text) for text in TTS_SENTENCES]
            continue
        for question in questions(mirror.name):
            heard = stt.hear(mirror.voice, question)
            row = {
                "asked": question,
                "heard": heard.text,
                "name_heard": name_heard(mirror.name, heard.text),
                "audio_s": heard.audio_seconds,
                "stt_s": heard.stt_seconds,
                "stt_rtf": real_time_factor(heard.stt_seconds, heard.audio_seconds),
            }
            if mode == "all":
                row |= time_reply(mirror, heard.text or question)
                if row["first_audio_s"] is not None:
                    row["speech_to_audio_s"] = heard.stt_seconds + row["first_audio_s"]
            rows.append(row)

    record = bench_record(mode, cfg, rows, dt.datetime.now())
    label = "text" if mode == "tts" else "heard"
    shown = [{**r, label: shorten(r[label], 34)} for r in rows]
    shown.append({label: "median", **record["median"]})
    print()
    print(format_table(shown, COLUMNS[mode]))
    print(f"\n{NOTES[mode]}")
    out = save(cfg.root / "models" / RESULTS_NAME, record)
    print(f"\nSaved to {out}")
    return record


def time_tts(mirror: Mirror, text: str) -> dict:
    started = time.perf_counter()
    first_chunk, audio_s = None, 0.0
    for audio, rate in mirror.voice.stream(text):
        if first_chunk is None:
            first_chunk = time.perf_counter() - started
        audio_s += len(audio) / rate
    synth_s = time.perf_counter() - started
    row = {
        "text": text,
        "audio_s": audio_s,
        "first_chunk_s": first_chunk,
        "synth_s": synth_s,
        "tts_rtf": real_time_factor(synth_s, audio_s),
    }
    print(f"  {row['tts_rtf']:.2f}x  {text}")
    return row


def time_reply(mirror: Mirror, text: str) -> dict:
    """Answer `text` from a blank conversation, timing each stage, with no audio out."""
    mirror.chat.messages.clear()  # every question starts the same way
    t = mirror.respond(text, time.time(), play=False)
    return {
        "reply": " ".join(t.reply),
        "ttft_s": t.first_token,
        "prompt_s": t.prompt_seconds,
        "llm_s": t.llm_done,
        "tokens": t.tokens,
        "tok_per_s": t.tokens_per_second,
        "synth_s": t.synth_seconds,
        "reply_audio_s": t.audio_seconds,
        "tts_rtf": t.tts_rtf,
        "first_audio_s": t.first_audio,
    }


def save(path: Path, record: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as f:
        f.write(json.dumps(record) + "\n")
    return path
