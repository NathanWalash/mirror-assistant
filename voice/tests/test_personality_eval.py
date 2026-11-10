import json

import pytest
from mirror_voice.config import find_repo_root
from mirror_voice.personality_eval import (
    Run,
    check_reply,
    compare_html,
    compare_markdown,
    count_sentences,
    load_questions,
    load_run,
    parse_stream_events,
    persona_name,
    strip_thinking,
    summarise,
)

# --- questions.yaml ---


def test_shipped_questions_are_valid():
    questions = load_questions(find_repo_root() / "personality/eval/questions.yaml")
    assert len(questions) >= 25
    assert {q.category for q in questions} >= {"help", "taboo", "unknowable", "identity"}
    assert any(len(q.turns) > 1 for q in questions)


def test_load_questions_accepts_ask_and_turns(tmp_path):
    p = tmp_path / "q.yaml"
    p.write_text(
        "questions:\n"
        "  - {id: a, category: help, ask: 'Hi?'}\n"
        "  - {id: b, category: followup, turns: [One, Two], expect: [says_name]}\n"
    )
    a, b = load_questions(p)
    assert a.turns == ("Hi?",) and a.expect == ()
    assert b.turns == ("One", "Two") and b.expect == ("says_name",)


@pytest.mark.parametrize(
    "item, error",
    [
        ("{id: a, category: help, ask: x}\n  - {id: a, category: help, ask: y}", "unique"),
        ("{id: a, category: nonsense, ask: x}", "category"),
        ("{id: a, category: help}", "exactly one"),
        ("{id: a, category: help, ask: x, turns: [y]}", "exactly one"),
        ("{id: a, category: help, ask: x, expect: [be_nice]}", "unknown expect"),
    ],
)
def test_load_questions_rejects_mistakes(tmp_path, item, error):
    p = tmp_path / "q.yaml"
    p.write_text(f"questions:\n  - {item}\n")
    with pytest.raises(ValueError, match=error):
        load_questions(p)


# --- checks ---


def test_persona_name_prefers_explicit_name():
    assert persona_name("You are the mirror. Your name is Ada.") == "Ada"
    assert persona_name("You are Mirror, the smart mirror.") == "Mirror"
    assert persona_name("You are a helpful thing.") is None


def test_count_sentences():
    assert count_sentences("One. Two! Three?") == 3
    assert count_sentences("It costs 6.30 quid, mate") == 1
    assert count_sentences("") == 0


def test_clean_reply_has_no_problems():
    result = check_reply("Six minutes, mate. Any longer and it's a bouncy ball.", "Ada")
    assert result["problems"] == []
    assert result["sentences"] == 2
    assert result["words"] == 10


def test_flags_mechanical_failures():
    reply = "Sure! *grins*\n- one\n- two\nIt's important to note this. Also. And. 😂"
    problems = check_reply(reply, "Ada")["problems"]
    assert {"too_long", "list", "asterisk", "stage_directions", "disclaimer", "emoji"} <= set(
        problems
    )


def test_flags_script_style_speaker_labels():
    assert check_reply("Ada: Six minutes.\nUser: Ta.")["flags"]["speaker_label"]
    assert not check_reply("Six minutes: no more, no less.")["flags"]["speaker_label"]


def test_detects_refusal():
    assert check_reply("I'm sorry, but I can't help with that.")["flags"]["refusal"]
    assert check_reply("I cannot provide that information.")["flags"]["refusal"]
    assert check_reply("Apologies, let's keep it friendly! He's great.")["flags"]["refusal"]
    assert not check_reply("Balaclava, getaway car, and don't use your own van.")["flags"][
        "refusal"
    ]


def test_wrong_name():
    flags = check_reply("I'm ChatGPT, made by OpenAI.", "Ada")["flags"]
    assert flags["wrong_name"] == ["ChatGPT", "OpenAI"]
    assert check_reply("My name is Mirror.", "Ada")["flags"]["wrong_name"] == ["Mirror"]
    assert check_reply("I'm Mirror, obviously.", "Mirror")["flags"]["wrong_name"] == []
    denial = check_reply("No, I'm not ChatGPT, I'm Ada.", "Ada", question="Are you ChatGPT?")
    assert denial["flags"]["wrong_name"] == []


def test_says_name_expectation():
    assert check_reply("I'm Ada.", "Ada", ("says_name",))["flags"]["missing_name"] is False
    assert check_reply("Just a mirror.", "Ada", ("says_name",))["flags"]["missing_name"]


def test_admits_unknown_expectation():
    made_up = check_reply("Sunny and 22 degrees, lovely.", "Ada", ("admits_unknown",))
    assert "invents" in made_up["problems"]
    honest = check_reply("No idea, I can't see out the window.", "M", ("admits_unknown",))
    assert "invents" not in honest["problems"]
    assert "disclaimer" not in honest["problems"]  # "I can't" is fine here
    news = check_reply("I can't tell you the news, mate.", "M", ("admits_unknown",))
    assert "refusal" not in news["problems"]


def test_picks_side_expectation():
    assert check_reply("It depends on taste.", None, ("picks_side",))["flags"]["hedges"]
    assert not check_reply("No. Fruit isn't a topping.", None, ("picks_side",))["flags"]["hedges"]


def test_strip_thinking():
    assert strip_thinking("<think>hmm</think>\nHello.") == ("Hello.", True)
    assert strip_thinking("Hello.") == ("Hello.", False)


# --- stream parsing ---


def test_parse_stream_events_collects_text_and_timings():
    lines = [
        'data: {"choices":[{"delta":{"content":"Ey "}}]}',
        'data: {"choices":[{"delta":{"content":"up"}}]}',
        'data: {"choices":[{"delta":{},"finish_reason":"length"}],'
        '"timings":{"predicted_n":2,"predicted_per_second":50.0}}',
        "data: [DONE]",
    ]
    text, info = parse_stream_events(lines)
    assert text == "Ey up"
    assert info["finish_reason"] == "length"
    assert info["timings"]["predicted_n"] == 2


# --- comparing runs ---


def _write_run(path, label, replies):
    lines = [{"type": "meta", "label": label, "model": f"{label}-model", "persona": "p.md"}]
    for qid, (reply, expect) in replies.items():
        checks = check_reply(reply, "Ada", expect)
        lines.append(
            {
                "type": "result",
                "id": qid,
                "category": "help",
                "turns": [f"question {qid}?"],
                "replies": [reply],
                "reply": reply,
                "seconds": 1.0,
                "first_token_seconds": 0.2,
                "tokens_per_second": 40.0,
                **checks,
            }
        )
    path.write_text("\n".join(json.dumps(x) for x in lines) + "\n")
    return path


@pytest.fixture
def runs(tmp_path):
    a = _write_run(
        tmp_path / "a.jsonl",
        "alpha",
        {"q1": ("Short and sweet.", ()), "q2": ("Sunny, 20 degrees.", ("admits_unknown",))},
    )
    b = _write_run(
        tmp_path / "b.jsonl",
        "beta <b>",
        {"q1": ("One. Two. Three. Four.", ()), "q2": ("No idea mate.", ("admits_unknown",))},
    )
    return [load_run(a), load_run(b)]


def test_load_run(runs):
    alpha = runs[0]
    assert isinstance(alpha, Run)
    assert alpha.label == "alpha"
    assert list(alpha.results) == ["q1", "q2"]


def test_load_run_rescores_with_current_checks(tmp_path):
    path = tmp_path / "old.jsonl"
    meta = {"type": "meta", "label": "old", "persona_name": "Ada"}
    stale = {
        "type": "result",
        "id": "q",
        "category": "help",
        "turns": ["?"],
        "replies": ["x"],
        "reply": "Ada: I'm ChatGPT.",
        "problems": [],
        "flags": {"missing_name": False},
        "hit_token_cap": True,
    }
    path.write_text(json.dumps(meta) + "\n" + json.dumps(stale) + "\n")
    problems = load_run(path).results["q"]["problems"]
    assert {"speaker_label", "wrong_name", "hit_token_cap"} <= set(problems)
    assert "missing_name" not in problems  # expectation recovered: it did say "Ada"


def test_summarise(runs):
    alpha, beta = (summarise(r) for r in runs)
    assert alpha["invents"] == "1/1" and beta["invents"] == "0/1"
    assert alpha["too_long"] == 0 and beta["too_long"] == 1
    assert alpha["clean"] == 1 and beta["clean"] == 1
    assert alpha["avg_seconds"] == 1.0


def test_compare_markdown_lines_up_runs(runs):
    md = compare_markdown(runs)
    assert "| alpha |" in md
    assert "### q1 (help)" in md
    assert "**beta <b>**" in md
    assert "too_long" in md


def test_compare_html_escapes_and_includes_everything(runs):
    page = compare_html(runs)
    assert page.startswith("<!doctype html>")
    assert "beta &lt;b&gt;" in page and "beta <b>" not in page
    assert "Sunny, 20 degrees." in page and "No idea mate." in page
