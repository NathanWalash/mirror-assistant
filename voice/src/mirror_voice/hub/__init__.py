"""The hub: background fetchers for the info widgets around the orb.

Each widget is a module in this package with:
    DEFAULT_REFRESH_MINUTES: float
    fetch(settings: dict) -> dict      # JSON-able data for the display; raise on failure

and an entry in WIDGETS below. The hub runs one thread per enabled widget, calls
`fetch` every `refresh_minutes`, and publishes the result to the display as
    {"widget": name, "status": "ok" | "stale" | "error", "data": {...} | None,
     "updated": unix time of the last good fetch | None, "error": "..."}  # error: only if failed
A failed fetch keeps showing the last good data marked "stale" ("error" if there is
none yet) and is retried sooner. Nothing a widget does can crash the voice loop.

See docs/widgets.md for how to add one.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable, Mapping
from types import ModuleType
from typing import Any

from mirror_voice.config import WidgetConfig
from mirror_voice.hub import bus, calendar, weather

log = logging.getLogger(__name__)

# name in config.yaml `widgets:` -> module with DEFAULT_REFRESH_MINUTES and fetch(settings)
WIDGETS: dict[str, ModuleType] = {
    "weather": weather,
    "calendar": calendar,
    "bus": bus,
}

RETRY_SECONDS = 60.0  # after a failure, try again this soon (or at the normal interval if sooner)

Publish = Callable[..., None]


class Refresher:
    """Fetches one widget on a timer and publishes the result."""

    def __init__(
        self,
        name: str,
        fetch: Callable[[dict[str, Any]], dict[str, Any]],
        settings: dict[str, Any],
        interval: float,
        publish: Publish,
    ) -> None:
        self.name = name
        self._fetch = fetch
        self.settings = settings
        self.interval = interval
        self._publish = publish
        self.data: dict[str, Any] | None = None  # last good result
        self.updated: float | None = None
        self.status = "pending"  # ok | stale | error, as last published
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._loop, name=f"hub-{name}", daemon=True)

    def refresh(self) -> bool:
        """Fetch once and publish. Returns whether it worked. Never raises."""
        try:
            self.data = self._fetch(self.settings)
            self.updated = time.time()
        except Exception as e:  # any widget bug or network blip: show stale, carry on
            log.warning("%s widget: fetch failed: %s", self.name, e)
            self.status = "stale" if self.data is not None else "error"
            self._publish(
                widget=self.name,
                status=self.status,
                data=self.data,
                updated=self.updated,
                error=str(e)[:200],
            )
            return False
        self.status = "ok"
        self._publish(widget=self.name, status="ok", data=self.data, updated=self.updated)
        return True

    def _loop(self) -> None:
        while not self._stop.is_set():
            ok = self.refresh()
            self._stop.wait(self.interval if ok else min(self.interval, RETRY_SECONDS))

    def start(self) -> Refresher:
        self._thread.start()
        return self

    def stop(self) -> None:
        self._stop.set()


class Hub:
    """All enabled widgets, each refreshing on its own thread."""

    def __init__(
        self,
        widgets: Mapping[str, WidgetConfig],
        publish: Publish,
        registry: Mapping[str, ModuleType] = WIDGETS,
    ) -> None:
        self.refreshers: dict[str, Refresher] = {}
        for name, wc in widgets.items():
            if not wc.enabled:
                continue
            module = registry.get(name)
            if module is None:
                log.warning("Unknown widget %r in config (known: %s)", name, ", ".join(registry))
                continue
            minutes = wc.refresh_minutes or module.DEFAULT_REFRESH_MINUTES
            self.refreshers[name] = Refresher(
                name, module.fetch, dict(wc.settings), minutes * 60, publish
            )

    def start(self) -> Hub:
        for r in self.refreshers.values():
            r.start()
        return self

    def stop(self) -> None:
        for r in self.refreshers.values():
            r.stop()

    def snapshot(self) -> dict[str, dict[str, Any] | None]:
        """Latest good data per widget (e.g. for Mirror to answer "what's the weather?")."""
        return {name: r.data for name, r in self.refreshers.items()}

    def board(self) -> dict[str, dict[str, Any]]:
        """Everything the screen shows, with how fresh it is: per widget
        {"status": "pending" | "ok" | "stale" | "error", "data": ..., "updated": ...}.
        What the assistant reads to answer from (see mirror_voice.context)."""
        return {
            name: {"status": r.status, "data": r.data, "updated": r.updated}
            for name, r in self.refreshers.items()
        }
