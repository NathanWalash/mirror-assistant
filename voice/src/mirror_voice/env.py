"""Secrets from the environment, or from the git-ignored `.env` file at the repo root.

.env is plain `NAME=value` lines (# comments, optional quotes, optional `export `).
A variable already set in the real environment wins over the file.
"""

from __future__ import annotations

import os
from pathlib import Path


def read_dotenv(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.is_file():
        return values
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.removeprefix("export ").split("=", 1)
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        values[name.strip()] = value
    return values


def get_secret(name: str, root: Path | None) -> str | None:
    """`name` from the environment, else from `<root>/.env`. None (not "") if unset."""
    value = os.environ.get(name) or (read_dotenv(root / ".env").get(name) if root else None)
    return value or None
