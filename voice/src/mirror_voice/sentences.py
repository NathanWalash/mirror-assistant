"""Cut a streaming reply into sentences so speech can start before the reply is finished."""

from __future__ import annotations

import re

# A sentence is finished once its end punctuation is followed by whitespace,
# or at a line break. Waiting for the whitespace avoids splitting "3.5" or "...".
_BOUNDARY = re.compile(r"[.!?…]+[\"')\]]*\s+|\n+")


class SentenceSplitter:
    def __init__(self) -> None:
        self._buf = ""

    def feed(self, text: str) -> list[str]:
        """Add streamed text; return any sentences that are now complete."""
        self._buf += text
        done = []
        while match := _BOUNDARY.search(self._buf):
            sentence = self._buf[: match.end()].strip()
            self._buf = self._buf[match.end() :]
            if sentence:
                done.append(sentence)
        return done

    def flush(self) -> str | None:
        """Return whatever is left at the end of the reply."""
        rest, self._buf = self._buf.strip(), ""
        return rest or None
