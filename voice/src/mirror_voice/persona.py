"""Mirror's personality, read fresh from a Markdown file on every reply."""

from __future__ import annotations

import re
from pathlib import Path

_COMMENT = re.compile(r"<!--.*?-->", re.S)


def example_for(path: Path) -> Path:
    """mirror.md -> mirror.example.md"""
    return path.with_name(f"{path.stem}.example{path.suffix}")


class Persona:
    """Loads the system prompt each time it's asked, so edits apply without a restart.

    Falls back to the shared `*.example.md` template if the private copy doesn't exist yet.
    HTML comments are notes for humans and are stripped before the model sees the text.
    """

    def __init__(self, path: Path) -> None:
        self.path = path

    @property
    def source(self) -> Path:
        if self.path.is_file():
            return self.path
        example = example_for(self.path)
        if example.is_file():
            return example
        raise FileNotFoundError(f"No persona at {self.path} (or {example.name}).")

    def system_prompt(self) -> str:
        text = _COMMENT.sub("", self.source.read_text())
        return re.sub(r"\n{3,}", "\n\n", text).strip()
