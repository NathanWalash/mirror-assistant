"""Talk to the local llama.cpp server (OpenAI-compatible API), streaming the reply."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from collections.abc import Iterator

from mirror_voice.config import LLMConfig


class LLMUnavailable(RuntimeError):
    pass


def parse_sse_event(line: str) -> dict:
    """The JSON object in one `data: {...}` streaming line ({} for anything else)."""
    line = line.strip()
    if not line.startswith("data: ") or line == "data: [DONE]":
        return {}
    return json.loads(line[len("data: ") :])


def delta_text(event: dict) -> str:
    """The new reply text in a streamed chunk ('' if none)."""
    choices = event.get("choices") or [{}]
    return choices[0].get("delta", {}).get("content") or ""


def parse_sse_line(line: str) -> str:
    """Extract the text delta from one `data: {...}` streaming line ('' if none)."""
    return delta_text(parse_sse_event(line))


class Conversation:
    """Short rolling memory of the chat, so Mirror can follow up on what was said."""

    def __init__(self, max_messages: int) -> None:
        self.max_messages = max_messages
        self.messages: list[dict[str, str]] = []

    def add(self, role: str, content: str) -> None:
        self.messages.append({"role": role, "content": content})
        del self.messages[: -self.max_messages]

    def build(self, system_prompt: str) -> list[dict[str, str]]:
        return [{"role": "system", "content": system_prompt}, *self.messages]


class LLMClient:
    def __init__(self, cfg: LLMConfig) -> None:
        self.cfg = cfg
        # llama.cpp's own speed figures for the last reply (prompt_ms, predicted_n,
        # predicted_per_second, ...), from the final streamed chunk. {} if not sent.
        self.last_timings: dict = {}

    def check(self) -> None:
        try:
            with urllib.request.urlopen(f"{self.cfg.base_url}/health", timeout=3) as r:
                if r.status == 200:
                    return
        except (urllib.error.URLError, OSError):
            pass
        raise LLMUnavailable(
            f"No model server at {self.cfg.base_url}. Start everything with scripts/talk.sh."
        )

    def stream(self, messages: list[dict[str, str]]) -> Iterator[str]:
        body = json.dumps(
            {
                "messages": messages,
                "stream": True,
                "max_tokens": self.cfg.max_tokens,
                "temperature": self.cfg.temperature,
            }
        ).encode()
        req = urllib.request.Request(
            f"{self.cfg.base_url}/v1/chat/completions",
            body,
            {"Content-Type": "application/json"},
        )
        self.last_timings = {}
        with urllib.request.urlopen(req) as resp:
            for raw in resp:
                event = parse_sse_event(raw.decode("utf-8", "replace"))
                if timings := event.get("timings"):
                    self.last_timings = timings
                if delta := delta_text(event):
                    yield delta
