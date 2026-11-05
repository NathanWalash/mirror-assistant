import json
import urllib.request

import numpy as np
from mirror_voice.config import find_repo_root
from mirror_voice.display_server import Broadcaster, DisplayServer, envelope, loudness


def test_new_subscriber_starts_with_current_state():
    b = Broadcaster()
    b.publish(state="thinking")
    q = b.subscribe()
    assert json.loads(q.get_nowait()) == {"state": "thinking"}


def test_publish_reaches_all_subscribers_until_they_leave():
    b = Broadcaster()
    q1, q2 = b.subscribe(), b.subscribe()
    q1.get_nowait(), q2.get_nowait()  # initial state
    b.publish(say="Ey up.")
    assert json.loads(q1.get_nowait()) == {"say": "Ey up."}
    assert json.loads(q2.get_nowait()) == {"say": "Ey up."}
    b.unsubscribe(q2)
    b.publish(level=0.5)
    assert json.loads(q1.get_nowait()) == {"level": 0.5}
    assert q2.empty()


def test_full_subscriber_queue_does_not_block_publishing():
    b = Broadcaster()
    b.subscribe()
    for i in range(1000):
        b.publish(level=i / 1000)  # would hang or raise if a full queue blocked


def test_loudness_range():
    assert loudness(np.zeros(100, dtype=np.int16)) == 0.0
    assert loudness(np.array([], dtype=np.int16)) == 0.0
    assert loudness(np.full(100, 32767, dtype=np.int16)) == 1.0
    quiet = loudness(np.full(100, 300, dtype=np.int16))
    assert 0.0 < quiet < 0.2


def test_envelope_has_one_value_per_step():
    audio = np.zeros(16000, dtype=np.int16)  # 1 second at 16 kHz
    assert len(envelope(audio, 16000, step=0.05)) == 20


def test_server_rejects_foreign_host_header():
    import urllib.error

    import pytest

    server = DisplayServer(find_repo_root() / "display", 0, Broadcaster()).start()
    try:
        for path in ("", "events"):
            req = urllib.request.Request(server.url + path, headers={"Host": "evil.example:80"})
            with pytest.raises(urllib.error.HTTPError) as err:
                urllib.request.urlopen(req, timeout=3)
            assert err.value.code == 403
        port = server.httpd.server_address[1]
        ok = urllib.request.Request(server.url, headers={"Host": f"localhost:{port}"})
        assert urllib.request.urlopen(ok, timeout=3).status == 200
    finally:
        server.stop()


def test_server_serves_page_and_events():
    b = Broadcaster()
    server = DisplayServer(find_repo_root() / "display", 0, b).start()
    try:
        page = urllib.request.urlopen(server.url, timeout=3).read().decode()
        assert "<canvas" in page

        with urllib.request.urlopen(server.url + "events", timeout=3) as stream:
            assert stream.headers["Content-Type"] == "text/event-stream"
            assert stream.readline() == b'data: {"state": "idle"}\n'
            stream.readline()  # blank line between events
            b.publish(you="hello")
            assert stream.readline() == b'data: {"you": "hello"}\n'
    finally:
        server.stop()
