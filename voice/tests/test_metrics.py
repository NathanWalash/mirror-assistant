import pytest
from mirror_voice.metrics import (
    Column,
    ReplyTimings,
    format_table,
    medians,
    real_time_factor,
    shorten,
)


def test_real_time_factor():
    assert real_time_factor(1.0, 4.0) == 0.25
    assert real_time_factor(1.0, 0.0) is None


def test_reply_timings_use_llama_cpp_figures_when_sent():
    t = ReplyTimings(first_token=0.2, synth_seconds=1.0, audio_seconds=5.0)
    t.add_llm_stats({"predicted_n": 40, "predicted_per_second": 12.5, "prompt_ms": 150}, 38, 3.0)
    assert (t.tokens, t.tokens_per_second, t.prompt_seconds) == (40, 12.5, 0.15)
    assert t.tts_rtf == 0.2


def test_reply_timings_estimate_speed_from_the_stream_otherwise():
    t = ReplyTimings(first_token=1.0)
    t.add_llm_stats({}, streamed_chunks=11, elapsed=3.0)
    assert t.tokens == 11
    assert t.tokens_per_second == pytest.approx(5.0)  # 10 tokens after the first, in 2 s
    assert t.prompt_seconds is None
    assert t.tts_rtf is None  # no audio made


def test_medians_skip_missing_values():
    rows = [{"a": 1.0, "b": None}, {"a": 3.0}, {"a": 2.0, "b": "x"}]
    assert medians(rows, ["a", "b"]) == {"a": 2.0, "b": None}


def test_format_table_aligns_columns():
    rows = [{"name": "short", "s": 1.234}, {"name": "much longer", "s": None}]
    table = format_table(rows, [Column("name", "what"), Column("s", "secs")])
    assert table.splitlines() == [
        "what         secs",
        "-----------  ----",
        "short        1.23",
        "much longer     -",
    ]


def test_shorten():
    assert shorten("abc", 5) == "abc"
    assert shorten("abcdef", 4) == "abc…"
