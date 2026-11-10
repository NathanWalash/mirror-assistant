"""Personality eval: ask a fixed set of questions, score the replies, compare runs.

uv run mirror-eval run --label hermes3 --url http://127.0.0.1:8090
uv run mirror-eval compare personality/eval/results/*.jsonl -o compare.html

`run` asks every question in personality/eval/questions.yaml (fresh conversation each,
same system prompt the voice loop uses) and writes one JSON line per question to
personality/eval/results/<timestamp>-<label>.jsonl. `compare` lays several runs side by
side (HTML or Markdown) so a human can judge which is funniest; the automatic checks only
catch the mechanical failures (too long, lists, disclaimers, refusals, wrong name).

Results are git-ignored: replies can quote the private persona.
"""

from __future__ import annotations

import argparse
import html
import json
import re
import sys
import time
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

from mirror_voice.llm import Conversation, parse_sse_line
from mirror_voice.persona import Persona
from mirror_voice.sentences import SentenceSplitter

CATEGORIES = ("help", "banter", "taboo", "opinion", "unknowable", "identity", "followup")
EXPECTATIONS = ("admits_unknown", "says_name", "picks_side")
MAX_SENTENCES = 3
_EXPECT_FLAGS = {"admits_unknown": "invents", "says_name": "missing_name", "picks_side": "hedges"}

# --- Loading questions -------------------------------------------------------------------


@dataclass(frozen=True)
class Question:
    id: str
    category: str
    turns: tuple[str, ...]
    expect: tuple[str, ...] = ()


def load_questions(path: Path) -> list[Question]:
    raw = yaml.safe_load(path.read_text()) or {}
    questions, seen = [], set()
    for item in raw.get("questions") or []:
        qid = item.get("id")
        if not qid or qid in seen:
            raise ValueError(f"Question ids must be present and unique (got {qid!r}).")
        seen.add(qid)
        if item.get("category") not in CATEGORIES:
            raise ValueError(f"{qid}: category must be one of {', '.join(CATEGORIES)}.")
        if ("ask" in item) == ("turns" in item):
            raise ValueError(f"{qid}: give exactly one of 'ask' or 'turns'.")
        turns = (item["ask"],) if "ask" in item else tuple(item["turns"])
        if not turns or not all(isinstance(t, str) and t.strip() for t in turns):
            raise ValueError(f"{qid}: needs at least one non-empty question.")
        expect = tuple(item.get("expect") or ())
        if bad := set(expect) - set(EXPECTATIONS):
            raise ValueError(f"{qid}: unknown expect {sorted(bad)}.")
        questions.append(Question(qid, item["category"], turns, expect))
    if not questions:
        raise ValueError(f"No questions in {path}.")
    return questions


# --- Automatic checks (pure functions of the reply text) -----------------------------------

DISCLAIMERS = (
    "as an ai",
    "as a language model",
    "language model",
    "i'm just an ai",
    "i can't",
    "i cannot",
    "i'm not able to",
    "i am not able to",
    "it's important",
    "it is important",
    "important to note",
    "please note",
    "remember that",
    "consult a",
    "seek professional",
    "a professional",
    "please be",
    "be respectful",
    "not appropriate",
    "inappropriate",
    "offensive",
    "harmful",
    "illegal",
    "i don't condone",
    "i do not condone",
    "i'm not comfortable",
    "i don't feel comfortable",
)

REFUSALS = (
    r"\bi (?:can't|cannot|won't|will not|am not able to|'m not able to) "
    r"(?:help|assist|provide|answer|do that|engage|comply|support|participate|rank|tell)",
    r"\bi(?:'m| am) (?:sorry|afraid),? but\b",
    r"\bi (?:must|have to) (?:decline|refuse)",
    r"\bi'?d rather not\b",
    r"\bnot (?:something|a topic) i (?:can|will|'ll)\b",
    r"\bagainst my (?:guidelines|programming|principles)\b",
    r"\blet'?s keep (?:it|this|things) (?:friendly|civil|clean|respectful|light)",
    r"^\s*apologies\b",
)

HEDGES = (
    "it depends",
    "depends on",
    "many perspectives",
    "different perspectives",
    "both have their",
    "personal preference",
    "it's subjective",
    "is subjective",
    "there's no right answer",
    "there is no right answer",
    "to each their own",
)

ADMITS_UNKNOWN = (
    "don't know",
    "do not know",
    "dunno",
    "no idea",
    "not a clue",
    "no clue",
    "haven't a clue",
    "haven't got a clue",
    "not sure",
    "can't see",
    "can't tell",
    "can't check",
    "cannot see",
    "can't know",
    "couldn't tell",
    "no window",
    "no internet",
    "not connected",
    "haven't got",
    "don't have",
    "look out the window",
    "look outside",
    "check your phone",
    "check the",
    "i'm a mirror",
    "i'm just a mirror",
    "stuck on a wall",
    "stuck on this wall",
    "no access",
)

# Names it might wrongly call itself (the persona's own name is removed from this list).
OTHER_IDENTITIES = (
    "ChatGPT",
    "GPT",
    "OpenAI",
    "Hermes",
    "Nous",
    "Qwen",
    "Alibaba",
    "Gemma",
    "Gemini",
    "Google",
    "Llama",
    "Meta AI",
    "Claude",
    "Anthropic",
    "Mirror",
    "Siri",
    "Alexa",
)

_EMOJI = re.compile(
    "[\U0001f000-\U0001faff\U00002600-\U000027bf\U0001f900-\U0001f9ff\u2b50\u2b55\u203c\u2049]"
)
_LIST_LINE = re.compile(r"^\s*(?:[-*•]|\d+[.)])\s+", re.M)
_STAGE = re.compile(r"\*[^*\n]+\*|\([^)\n]*\)|\[[^\]\n]*\]")
_SELF_NAME = re.compile(
    r"\b(?:my name is|my name's|i'm called|i am called|call me)\s+([A-Z][\w-]+)", re.I
)
_THINK = re.compile(r"<think>.*?(?:</think>|$)", re.S)
# "Mirror: ..." or "User: ..." - the model is writing a script instead of talking.
_SPEAKER_LABEL = re.compile(r"^\s*[A-Z]\w{0,20}:\s", re.M)


def persona_name(system_prompt: str) -> str | None:
    """The assistant's name, from 'Your name is X' or 'You are X'."""
    for pattern in (r"\byour name is ([A-Z][\w-]+)", r"\byou are ([A-Z][\w-]+)"):
        if m := re.search(pattern, system_prompt, re.I):
            name = m.group(1)
            if name[0].isupper() and name.lower() not in {"a", "an", "the"}:
                return name
    return None


def strip_thinking(reply: str) -> tuple[str, bool]:
    """Remove any <think>...</think> block a reasoning model leaked into the reply."""
    cleaned = _THINK.sub("", reply)
    return cleaned.strip(), cleaned != reply


def count_sentences(text: str) -> int:
    splitter = SentenceSplitter()
    parts = splitter.feed(text)
    if rest := splitter.flush():
        parts.append(rest)
    return len(parts)


def _found(text: str, phrases: tuple[str, ...]) -> list[str]:
    low = text.lower().replace("’", "'")
    return [p for p in phrases if p in low]


def check_reply(
    reply: str, name: str | None = None, expect: tuple[str, ...] = (), question: str = ""
) -> dict:
    """Mechanical checks on one reply. Every `True` flag is a problem.

    Names that appear in the question don't count as wrong names ("No, I'm not ChatGPT").
    """
    low = reply.lower().replace("’", "'")
    sentences = count_sentences(reply)
    wrong_names = [
        n
        for n in OTHER_IDENTITIES
        if (not name or n.lower() != name.lower())
        and n.lower() not in question.lower()
        and re.search(rf"\b{re.escape(n)}\b", reply)
    ]
    wrong_names += [
        m.group(1)
        for m in _SELF_NAME.finditer(reply)
        if not name or m.group(1).lower() != name.lower()
    ]
    flags: dict[str, Any] = {
        "too_long": sentences > MAX_SENTENCES,
        "list": bool(_LIST_LINE.search(reply)),
        "emoji": bool(_EMOJI.search(reply)),
        "asterisk": "*" in reply,
        "stage_directions": bool(_STAGE.search(reply)),
        "disclaimer": [
            d
            for d in _found(reply, DISCLAIMERS)
            # "I can't see outside" is the right answer to a live-data question
            if not ("admits_unknown" in expect and d in ("i can't", "i cannot"))
        ],
        # "I can't tell you the news" is the right answer when it can't know
        "refusal": "admits_unknown" not in expect and any(re.search(p, low) for p in REFUSALS),
        "wrong_name": sorted(set(wrong_names)),
        "speaker_label": bool(_SPEAKER_LABEL.search(reply)),
        "empty": not reply.strip(),
    }
    if "says_name" in expect:
        flags["missing_name"] = bool(name) and name.lower() not in low
    if "admits_unknown" in expect:
        flags["invents"] = not _found(reply, ADMITS_UNKNOWN)
    if "picks_side" in expect:
        flags["hedges"] = _found(reply, HEDGES)
    return {
        "sentences": sentences,
        "words": len(reply.split()),
        "flags": flags,
        "problems": sorted(k for k, v in flags.items() if v),
    }


# --- Talking to the server ---------------------------------------------------------------


@dataclass
class Completion:
    text: str
    seconds: float
    first_token_seconds: float | None
    tokens: int | None = None
    tokens_per_second: float | None = None
    finish_reason: str | None = None
    raw: list[dict] = field(default_factory=list, repr=False)


def parse_stream_events(lines: list[str]) -> tuple[str, dict]:
    """Join streamed deltas; also return the last usage/timings/finish info seen."""
    text, info = "", {}
    for line in lines:
        text += parse_sse_line(line)
        line = line.strip()
        if not line.startswith("data: ") or line == "data: [DONE]":
            continue
        event = json.loads(line[len("data: ") :])
        for choice in event.get("choices") or []:
            if choice.get("finish_reason"):
                info["finish_reason"] = choice["finish_reason"]
        if event.get("timings"):
            info["timings"] = event["timings"]
        if event.get("usage"):
            info["usage"] = event["usage"]
    return text, info


def complete(url: str, messages: list[dict], params: dict, timeout: float = 300) -> Completion:
    body = json.dumps({"messages": messages, "stream": True, **params}).encode()
    req = urllib.request.Request(
        f"{url}/v1/chat/completions", body, {"Content-Type": "application/json"}
    )
    start = time.perf_counter()
    first: float | None = None
    lines: list[str] = []
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        for raw in resp:
            line = raw.decode("utf-8", "replace")
            lines.append(line)
            if first is None and parse_sse_line(line):
                first = time.perf_counter() - start
    seconds = time.perf_counter() - start
    text, info = parse_stream_events(lines)
    timings = info.get("timings") or {}
    usage = info.get("usage") or {}
    return Completion(
        text=text,
        seconds=seconds,
        first_token_seconds=first,
        tokens=timings.get("predicted_n") or usage.get("completion_tokens"),
        tokens_per_second=timings.get("predicted_per_second"),
        finish_reason=info.get("finish_reason"),
    )


def server_model(url: str) -> str | None:
    try:
        with urllib.request.urlopen(f"{url}/v1/models", timeout=5) as r:
            data = json.load(r)
        return (data.get("data") or [{}])[0].get("id")
    except (OSError, ValueError):
        return None


def ask(question: Question, system_prompt: str, url: str, params: dict) -> dict:
    """One fresh conversation: say each turn, keep the replies, judge the last one."""
    chat = Conversation(max_messages=100)
    replies, completion = [], None
    for turn in question.turns:
        chat.add("user", turn)
        completion = complete(url, chat.build(system_prompt), params)
        reply, _ = strip_thinking(completion.text)
        chat.add("assistant", reply)
        replies.append(reply)
    assert completion is not None
    reply, leaked = strip_thinking(completion.text)
    return {
        "replies": replies,
        "reply": reply,
        "thinking_leaked": leaked,
        "seconds": round(completion.seconds, 3),
        "first_token_seconds": (
            round(completion.first_token_seconds, 3) if completion.first_token_seconds else None
        ),
        "tokens": completion.tokens,
        "tokens_per_second": (
            round(completion.tokens_per_second, 1) if completion.tokens_per_second else None
        ),
        "finish_reason": completion.finish_reason,
        "hit_token_cap": completion.finish_reason == "length",
    }


def score(record: dict, name: str | None) -> dict:
    """Add (or refresh) the automatic checks on a saved result."""
    expect = record.get("expect")
    if expect is None:  # older files: recover it from which expectation flags exist
        flags = record.get("flags", {})
        expect = [e for e, flag in _EXPECT_FLAGS.items() if flag in flags]
    question = " ".join(record.get("turns") or ())
    checks = check_reply(record["reply"], name, tuple(expect), question)
    for problem in ("hit_token_cap", "thinking_leaked"):
        if record.get(problem):
            checks["problems"].append(problem)
    return {**record, **checks}


def run_eval(
    questions: list[Question],
    persona: Persona,
    url: str,
    label: str,
    params: dict,
    out: Path,
    model: str | None = None,
    echo=print,
) -> Path:
    system_prompt = persona.system_prompt()
    name = persona_name(system_prompt)
    out.parent.mkdir(parents=True, exist_ok=True)
    meta = {
        "type": "meta",
        "label": label,
        "model": model or server_model(url),
        "persona": persona.source.name,
        "persona_name": name,
        "url": url,
        "params": params,
        "started": datetime.now().isoformat(timespec="seconds"),
    }
    with out.open("w") as f:
        f.write(json.dumps(meta) + "\n")
        for i, q in enumerate(questions, 1):
            record = {
                "type": "result",
                "label": label,
                "id": q.id,
                "category": q.category,
                "turns": list(q.turns),
                "expect": list(q.expect),
                **ask(q, system_prompt, url, params),
            }
            record = score(record, name)
            f.write(json.dumps(record) + "\n")
            f.flush()
            problems = ", ".join(record["problems"]) or "ok"
            echo(f"[{i}/{len(questions)}] {q.id} ({record['seconds']}s) {problems}")
            echo(f"    {record['reply']}")
    return out


# --- Comparing runs ----------------------------------------------------------------------


@dataclass
class Run:
    meta: dict
    results: dict[str, dict]  # by question id, in question order

    @property
    def label(self) -> str:
        return self.meta.get("label", "?")


def load_run(path: Path) -> Run:
    meta: dict = {}
    results: dict[str, dict] = {}
    for line in path.read_text().splitlines():
        if not line.strip():
            continue
        record = json.loads(line)
        if record.get("type") == "meta":
            meta = record
        else:
            results[record["id"]] = record
    meta.setdefault("label", path.stem)
    # Re-score with today's checks, so runs saved before a check changed still line up.
    for qid, record in results.items():
        if "reply" in record:
            results[qid] = score(record, meta.get("persona_name"))
    return Run(meta, results)


def _mean(values: list[float]) -> float | None:
    values = [v for v in values if v is not None]
    return round(sum(values) / len(values), 2) if values else None


def summarise(run: Run) -> dict:
    """One row of numbers per run: averages and how many replies broke each rule."""
    rs = list(run.results.values())

    def count(problem: str) -> int:
        return sum(problem in r.get("problems", []) for r in rs)

    def expected(flag: str) -> int:
        return sum(flag in r.get("flags", {}) for r in rs)

    return {
        "label": run.label,
        "model": run.meta.get("model"),
        "questions": len(rs),
        "avg_seconds": _mean([r.get("seconds") for r in rs]),
        "avg_first_token": _mean([r.get("first_token_seconds") for r in rs]),
        "avg_tokens_per_second": _mean([r.get("tokens_per_second") for r in rs]),
        "avg_words": _mean([r.get("words") for r in rs]),
        "avg_sentences": _mean([r.get("sentences") for r in rs]),
        "too_long": count("too_long"),
        "hit_token_cap": count("hit_token_cap"),
        "formatting": sum(
            any(p in r.get("problems", []) for p in ("list", "emoji", "asterisk")) for r in rs
        ),
        "stage_directions": count("stage_directions"),
        "disclaimer": count("disclaimer"),
        "refusal": count("refusal"),
        "wrong_name": count("wrong_name") + count("missing_name"),
        "invents": f"{count('invents')}/{expected('invents')}",
        "hedges": f"{count('hedges')}/{expected('hedges')}",
        "clean": sum(not r.get("problems") for r in rs),
    }


SUMMARY_COLUMNS = (
    ("label", "Run"),
    ("avg_seconds", "Avg s"),
    ("avg_first_token", "1st token s"),
    ("avg_tokens_per_second", "Tok/s"),
    ("avg_words", "Words"),
    ("too_long", ">3 sent."),
    ("hit_token_cap", "Hit cap"),
    ("formatting", "Lists/emoji/*"),
    ("stage_directions", "Brackets"),
    ("disclaimer", "Disclaimer"),
    ("refusal", "Refusal"),
    ("wrong_name", "Wrong name"),
    ("invents", "Invents live info"),
    ("hedges", "Hedges"),
    ("clean", "Clean replies"),
)


def _question_order(runs: list[Run]) -> list[str]:
    order: list[str] = []
    for run in runs:
        order += [qid for qid in run.results if qid not in order]
    return order


def compare_markdown(runs: list[Run]) -> str:
    def cell(value: Any) -> str:
        return str("" if value is None else value).replace("|", "\\|").replace("\n", " ")

    out = ["# Personality eval comparison", "", "## Summary", ""]
    out.append("| " + " | ".join(h for _, h in SUMMARY_COLUMNS) + " |")
    out.append("|" + "---|" * len(SUMMARY_COLUMNS))
    for run in runs:
        s = summarise(run)
        out.append("| " + " | ".join(cell(s[k]) for k, _ in SUMMARY_COLUMNS) + " |")
    out += ["", "## Replies", ""]
    for qid in _question_order(runs):
        first = next(r.results[qid] for r in runs if qid in r.results)
        out.append(f"### {qid} ({first['category']})")
        out.append("")
        out.append("> " + "<br>> ".join(cell(t) for t in first["turns"]))
        out.append("")
        for run in runs:
            r = run.results.get(qid)
            if not r:
                out.append(f"- **{run.label}**: (not asked)")
                continue
            problems = ", ".join(r.get("problems", [])) or "ok"
            out.append(
                f"- **{run.label}** ({r.get('seconds')}s, {r.get('words')} words; {problems}): "
                f"{cell(r['reply'])}"
            )
        out.append("")
    return "\n".join(out)


_HTML_STYLE = """
:root { --bg:#fbfaf7; --fg:#1d1d1f; --muted:#6b6b70; --line:#e2e0da; --bad:#b3261e;
        --bad-bg:#fde8e6; --ok:#1b6e3a; --ok-bg:#e3f4e8; --head:#f1efe9; }
@media (prefers-color-scheme: dark) {
  :root { --bg:#16161a; --fg:#ececf0; --muted:#9a9aa3; --line:#2c2c33; --bad:#ffb4ab;
          --bad-bg:#4a1d1a; --ok:#9be1b0; --ok-bg:#173823; --head:#202027; } }
body { background:var(--bg); color:var(--fg); font:15px/1.45 system-ui, sans-serif;
       margin:0; padding:16px; }
h1 { font-size:1.4rem; } h2 { font-size:1.1rem; margin-top:2rem; }
.wrap { overflow-x:auto; }
table { border-collapse:collapse; width:100%; }
th, td { border:1px solid var(--line); padding:8px; vertical-align:top; text-align:left; }
th { background:var(--head); position:sticky; top:0; }
td.q { min-width:12rem; max-width:16rem; }
td.r { min-width:16rem; }
.meta { color:var(--muted); font-size:.8rem; margin-top:4px; }
.cat { color:var(--muted); font-size:.8rem; }
.tag { display:inline-block; border-radius:4px; padding:0 5px; margin:2px 2px 0 0;
       font-size:.75rem; background:var(--bad-bg); color:var(--bad); }
.tag.ok { background:var(--ok-bg); color:var(--ok); }
.prior { color:var(--muted); font-size:.85rem; border-left:2px solid var(--line);
         padding-left:6px; margin-bottom:6px; }
"""


def compare_html(runs: list[Run]) -> str:
    e = html.escape
    rows = []
    for run in runs:
        s = summarise(run)
        rows.append("<tr>" + "".join(f"<td>{e(str(s[k]))}</td>" for k, _ in SUMMARY_COLUMNS))
    summary = (
        "<table><tr>"
        + "".join(f"<th>{e(h)}</th>" for _, h in SUMMARY_COLUMNS)
        + "</tr>"
        + "".join(rows)
        + "</table>"
    )
    models = "".join(
        f"<li><b>{e(r.label)}</b>: {e(str(r.meta.get('model')))}, persona "
        f"{e(str(r.meta.get('persona')))}</li>"
        for r in runs
    )
    head = "<tr><th>Question</th>" + "".join(f"<th>{e(r.label)}</th>" for r in runs) + "</tr>"
    body = []
    for qid in _question_order(runs):
        first = next(r.results[qid] for r in runs if qid in r.results)
        turns = "<br>".join(e(t) for t in first["turns"])
        cells = [
            f'<td class="q"><b>{turns}</b><div class="cat">{e(qid)} · {e(first["category"])}'
            "</div></td>"
        ]
        for run in runs:
            r = run.results.get(qid)
            if not r:
                cells.append('<td class="r">(not asked)</td>')
                continue
            prior = "".join(f'<div class="prior">{e(p)}</div>' for p in r["replies"][:-1])
            tags = "".join(f'<span class="tag">{e(p)}</span>' for p in r.get("problems", []))
            tags = tags or '<span class="tag ok">ok</span>'
            meta = f"{r.get('seconds')}s · {r.get('words')} words · {r.get('sentences')} sent."
            cells.append(
                f'<td class="r">{prior}{e(r["reply"])}<div class="meta">{meta}</div>{tags}</td>'
            )
        body.append("<tr>" + "".join(cells) + "</tr>")
    return (
        "<!doctype html><html><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width, initial-scale=1'>"
        f"<title>Personality eval</title><style>{_HTML_STYLE}</style></head><body>"
        f"<h1>Personality eval</h1><ul>{models}</ul><h2>Summary</h2><div class='wrap'>"
        f"{summary}</div><h2>Replies</h2><div class='wrap'><table>{head}{''.join(body)}"
        "</table></div></body></html>"
    )


# --- Command line ------------------------------------------------------------------------


def _slug(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "-", text).strip("-") or "run"


def main(argv: list[str] | None = None) -> None:
    from mirror_voice.config import load_config

    cfg = load_config()
    eval_dir = cfg.root / "personality/eval"
    parser = argparse.ArgumentParser(prog="mirror-eval", description=__doc__.split("\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)

    run_p = sub.add_parser("run", help="ask every question and save the replies")
    run_p.add_argument("--label", required=True, help="name for this run, e.g. qwen3-4b")
    run_p.add_argument("--url", default=cfg.llm.base_url, help="llama-server address")
    run_p.add_argument("--persona", type=Path, default=cfg.persona)
    run_p.add_argument("--questions", type=Path, default=eval_dir / "questions.yaml")
    run_p.add_argument("--only", nargs="*", help="only these categories or question ids")
    run_p.add_argument("--model", help="model label to record (default: ask the server)")
    run_p.add_argument("--temperature", type=float, default=cfg.llm.temperature)
    run_p.add_argument("--max-tokens", type=int, default=cfg.llm.max_tokens)
    run_p.add_argument("--seed", type=int, default=42, help="-1 for random")
    run_p.add_argument(
        "--no-think",
        action="store_true",
        help="ask hybrid reasoning models (Qwen3) not to think: chat_template_kwargs",
    )
    run_p.add_argument("--out-dir", type=Path, default=eval_dir / "results")

    cmp_p = sub.add_parser("compare", help="side-by-side view of several runs")
    cmp_p.add_argument("runs", nargs="+", type=Path, help="results .jsonl files")
    cmp_p.add_argument(
        "-o", "--output", type=Path, help=".html or .md (default: Markdown to stdout)"
    )

    args = parser.parse_args(argv)
    if args.command == "compare":
        runs = [load_run(p) for p in args.runs]
        if args.output and args.output.suffix == ".html":
            args.output.write_text(compare_html(runs))
        elif args.output:
            args.output.write_text(compare_markdown(runs))
        else:
            print(compare_markdown(runs))
        if args.output:
            print(f"Wrote {args.output}")
        return

    questions = load_questions(args.questions)
    if args.only:
        questions = [q for q in questions if q.id in args.only or q.category in args.only]
    params: dict[str, Any] = {"temperature": args.temperature, "max_tokens": args.max_tokens}
    if args.seed >= 0:
        params["seed"] = args.seed
    if args.no_think:
        params["chat_template_kwargs"] = {"enable_thinking": False}
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    out = args.out_dir / f"{stamp}-{_slug(args.label)}.jsonl"
    try:
        run_eval(questions, Persona(args.persona), args.url, args.label, params, out, args.model)
    except OSError as err:
        sys.exit(f"Couldn't reach the model server at {args.url}: {err}")
    print(f"\nSaved {out}")


if __name__ == "__main__":
    main()
