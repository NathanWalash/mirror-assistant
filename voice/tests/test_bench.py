import datetime as dt
import json

import numpy as np
import pytest
from mirror_voice import bench
from mirror_voice.config import find_repo_root, load_config
from mirror_voice.stt import STT_RATE, to_stt_audio


def test_questions_use_the_assistants_name():
    qs = bench.questions("Robin")
    assert len(qs) == len(bench.QUESTIONS)
    assert all("Robin" in q and "{" not in q for q in qs)


def test_name_heard_ignores_case():
    assert bench.name_heard("Robin", "morning robin") == "yes"
    assert bench.name_heard("Robin", "morning robbing") == "no"


def test_every_mode_has_columns_and_notes():
    assert set(bench.MODES) == set(bench.COLUMNS) == set(bench.NOTES)


def test_bench_record_is_json_with_medians():
    cfg = load_config(find_repo_root())
    rows = [
        {"heard": "a", "name_heard": "yes", "stt_s": 0.2, "ttft_s": 0.1, "tokens": 10},
        {"heard": "b", "name_heard": "no", "stt_s": 0.4, "ttft_s": None, "tokens": 20},
    ]
    record = bench.bench_record("all", cfg, rows, dt.datetime(2026, 1, 2, 3, 4, 5))
    assert record["when"] == "2026-01-02T03:04:05"
    assert record["median"]["stt_s"] == pytest.approx(0.3)
    assert record["median"]["ttft_s"] == 0.1
    assert record["median"]["tokens"] == 15
    assert "heard" not in record["median"]
    assert record["settings"]["voice"] == cfg.tts.voice
    json.dumps(record)  # must be saveable as one line


def test_tts_record_leaves_out_the_llm():
    record = bench.bench_record("tts", load_config(find_repo_root()), [], dt.datetime.now())
    assert record["settings"]["llm_model"] is None


def test_save_appends_one_line_per_run(tmp_path):
    out = tmp_path / "models" / "bench.jsonl"
    bench.save(out, {"run": 1})
    bench.save(out, {"run": 2})
    assert [json.loads(line)["run"] for line in out.read_text().splitlines()] == [1, 2]


def test_to_stt_audio_resamples_and_pads_with_silence():
    one_second = (np.ones(24000) * 16384).astype(np.int16)
    pcm = to_stt_audio(one_second, 24000)
    pad_before, pad_after = STT_RATE // 4, STT_RATE // 2
    assert len(pcm) == pad_before + STT_RATE + pad_after
    assert pcm[:pad_before].max() == 0 and pcm[-pad_after:].max() == 0
    assert np.allclose(pcm[pad_before : pad_before + STT_RATE], 0.5)
