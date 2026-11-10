"""The reply loop's prompt: persona first and unchanged, live info only on the new turn."""

import shutil
import time
from datetime import datetime
from zoneinfo import ZoneInfo

import numpy as np
from mirror_voice.app import Mirror
from mirror_voice.config import find_repo_root, load_config

NOW = datetime(2026, 11, 10, 8, 0, tzinfo=ZoneInfo("Europe/London"))
PERSONA = "You are Robin, a mirror."


class FakeVoice:
    def stream(self, text):
        yield np.zeros(10, dtype=np.int16), 24000


class FakeLLM:
    def __init__(self):
        self.seen = []
        self.last_timings = {}

    def stream(self, messages):
        self.seen.append(messages)
        yield "Aye, "
        yield "take a coat."


def make_mirror(tmp_path, board=None):
    shutil.copy(find_repo_root() / "config.example.yaml", tmp_path / "config.example.yaml")
    persona = tmp_path / "personality" / "personas" / "mirror.example.md"
    persona.parent.mkdir(parents=True)
    persona.write_text(PERSONA)
    mirror = Mirror(load_config(tmp_path), voice=FakeVoice(), llm=FakeLLM())
    if board is not None:
        mirror.board = lambda: board
    return mirror


WEATHER = {
    "status": "ok",
    "updated": NOW.timestamp(),
    "data": {
        "place": "Leeds",
        "temp": 7,
        "feels_like": 4,
        "condition": "Rain",
        "wind_mph": 3,
        "high": 9,
        "low": 3,
        "rain": {"summary": "Rain likely now"},
    },
}


def test_prompt_order_persona_history_then_question_with_note(tmp_path):
    mirror = make_mirror(tmp_path, {"weather": WEATHER})
    mirror.chat.add("user", "morning")
    mirror.chat.add("assistant", "Ey up.")
    messages = mirror.prompt("Do I need a coat?", NOW)
    assert [m["role"] for m in messages] == ["system", "user", "assistant", "user"]
    assert messages[0]["content"] == PERSONA  # no live data in the system prompt
    question = messages[-1]["content"]
    assert question.startswith("Do I need a coat?\n\n[Live info]\nNow: Tuesday 10 November")
    assert "Weather in Leeds: 7C" in question


def test_system_prompt_is_byte_identical_across_turns(tmp_path):
    mirror = make_mirror(tmp_path, {"weather": WEATHER})
    first = mirror.prompt("coat?", NOW)
    later = mirror.prompt("tell me a joke", datetime(2026, 11, 10, 9, 30, tzinfo=NOW.tzinfo))
    assert first[0] == later[0]


def test_history_keeps_the_plain_question_not_the_note(tmp_path):
    mirror = make_mirror(tmp_path, {"weather": WEATHER})
    timings = mirror.respond("Do I need a coat?", time.time(), play=False)
    assert timings.reply == ["Aye, take a coat."]
    assert "[Live info]" in mirror.llm.seen[0][-1]["content"]
    assert mirror.chat.messages == [
        {"role": "user", "content": "Do I need a coat?"},
        {"role": "assistant", "content": "Aye, take a coat."},
    ]
    mirror.respond("And tomorrow?", time.time(), play=False)
    second = mirror.llm.seen[1]
    assert second[1] == {"role": "user", "content": "Do I need a coat?"}  # no old note
    assert sum("[Live info]" in m["content"] for m in second) == 1  # only the new turn


def test_without_a_hub_the_note_is_just_the_time(tmp_path):
    mirror = make_mirror(tmp_path)
    question = mirror.prompt("give me a rundown", NOW)[-1]["content"]
    assert question == "give me a rundown\n\n[Live info]\nNow: Tuesday 10 November, 08:00."


def test_a_broken_board_never_stops_a_reply(tmp_path):
    mirror = make_mirror(tmp_path)

    def broken():
        raise RuntimeError("hub fell over")

    mirror.board = broken
    question = mirror.prompt("coat?", NOW)[-1]["content"]
    assert question.endswith("Now: Tuesday 10 November, 08:00.")
