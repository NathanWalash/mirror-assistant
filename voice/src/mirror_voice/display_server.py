"""Tiny local web server for the mirror display.

Serves `display/` as static files and pushes live events to the page with
Server-Sent Events at /events. Standard library only.

Events are small JSON objects, e.g.:
    {"state": "idle" | "listening" | "thinking" | "speaking"}
    {"level": 0.42}             # loudness 0..1 (your voice or Mirror's)
    {"heard": "what you're saying so far"}
    {"you": "what you said"}
    {"say": "one sentence Mirror is speaking"}
    {"widget": "weather", "status": "ok", "data": {...}, "updated": 1762770000.0}
                                # from the hub, see mirror_voice/hub/__init__.py
    {"display": {"night": {"start": "00:00", "end": "06:30", "brightness": 0.15}}}
                                # page settings from config.yaml, sent once on connect
"""

from __future__ import annotations

import json
import queue
import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import numpy as np


class Broadcaster:
    """Fan events out to every connected page."""

    def __init__(self, display: dict[str, object] | None = None) -> None:
        self._clients: set[queue.Queue[str]] = set()
        self._lock = threading.Lock()
        self._last_state = {"state": "idle"}
        self._last_widgets: dict[str, str] = {}  # widget name -> its latest event
        # Page settings from config.yaml `display:` (e.g. night dimming), sent on connect.
        self._display = json.dumps({"display": display}) if display is not None else None

    def subscribe(self) -> queue.Queue[str]:
        q: queue.Queue[str] = queue.Queue(maxsize=256)
        # New pages start in the right state and settings, with every widget filled in.
        q.put_nowait(json.dumps(self._last_state))
        if self._display:
            q.put_nowait(self._display)
        with self._lock:
            for data in self._last_widgets.values():
                q.put_nowait(data)
            self._clients.add(q)
        return q

    def unsubscribe(self, q: queue.Queue[str]) -> None:
        with self._lock:
            self._clients.discard(q)

    def publish(self, **event: object) -> None:
        if "state" in event:
            self._last_state = {"state": event["state"]}
        data = json.dumps(event)
        with self._lock:
            if "widget" in event:
                self._last_widgets[str(event["widget"])] = data
            clients = list(self._clients)
        for q in clients:
            try:
                q.put_nowait(data)
            except queue.Full:
                pass  # a stalled page just misses a few frames


def loudness(audio: np.ndarray) -> float:
    """Rough 0..1 loudness of a chunk of int16 or float audio, for animating the orb."""
    if audio.size == 0:
        return 0.0
    samples = audio.astype(np.float32)
    if audio.dtype == np.int16:
        samples /= 32768.0
    rms = float(np.sqrt(np.mean(samples**2)))
    return min(1.0, rms * 6.0)


def envelope(audio: np.ndarray, rate: int, step: float = 0.05) -> list[float]:
    """Loudness every `step` seconds, so the orb can pulse in time with speech."""
    hop = max(1, int(rate * step))
    return [loudness(audio[i : i + hop]) for i in range(0, len(audio), hop)]


class _Handler(SimpleHTTPRequestHandler):
    broadcaster: Broadcaster

    def log_message(self, *args: object) -> None:  # keep the terminal clean
        pass

    def _host_allowed(self) -> bool:
        # The event stream carries transcripts of what's said in the room. Only answer
        # requests addressed to this machine by name, which blocks DNS-rebinding attacks
        # (a web page pointing its own domain at 127.0.0.1 to read the stream).
        port = self.server.server_address[1]
        host = self.headers.get("Host", "")
        return host in {f"127.0.0.1:{port}", f"localhost:{port}"}

    def do_GET(self) -> None:
        if not self._host_allowed():
            self.send_error(403, "Forbidden host")
            return
        if self.path != "/events":
            return super().do_GET()
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        q = self.broadcaster.subscribe()
        try:
            while True:
                try:
                    data = q.get(timeout=15)
                    self.wfile.write(f"data: {data}\n\n".encode())
                except queue.Empty:
                    self.wfile.write(b": keep-alive\n\n")
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            pass
        finally:
            self.broadcaster.unsubscribe(q)


class DisplayServer:
    def __init__(self, static_dir: Path, port: int, broadcaster: Broadcaster) -> None:
        handler = type("Handler", (_Handler,), {"broadcaster": broadcaster})
        self.httpd = ThreadingHTTPServer(
            ("127.0.0.1", port), partial(handler, directory=str(static_dir))
        )
        self.httpd.daemon_threads = True

    @property
    def url(self) -> str:
        host, port = self.httpd.server_address[:2]
        return f"http://{host}:{port}/"

    def start(self) -> DisplayServer:
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        return self

    def stop(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()
