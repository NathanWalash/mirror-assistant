import json
import re
import threading
from types import SimpleNamespace

import yaml
from mirror_voice.config import WidgetConfig, find_repo_root
from mirror_voice.display_server import Broadcaster
from mirror_voice.hub import WIDGETS, Hub, Refresher


class Recorder:
    def __init__(self):
        self.events = []

    def __call__(self, **event):
        self.events.append(event)


def test_refresh_publishes_data():
    pub = Recorder()
    r = Refresher("demo", lambda s: {"n": s["n"]}, {"n": 3}, 60, pub)
    assert r.refresh() is True
    [event] = pub.events
    assert event["widget"] == "demo" and event["status"] == "ok"
    assert event["data"] == {"n": 3} and event["updated"] > 0


def test_failure_before_any_data_is_an_error():
    pub = Recorder()

    def broken(settings):
        raise OSError("network down")

    r = Refresher("demo", broken, {}, 60, pub)
    assert r.refresh() is False  # and did not raise
    assert pub.events[-1] == {
        "widget": "demo",
        "status": "error",
        "data": None,
        "updated": None,
        "error": "network down",
    }


def test_failure_after_success_keeps_last_data_as_stale():
    pub = Recorder()
    results = iter([{"temp": 7}, ValueError("bad json")])

    def flaky(settings):
        result = next(results)
        if isinstance(result, Exception):
            raise result
        return result

    r = Refresher("demo", flaky, {}, 60, pub)
    r.refresh()
    good_at = pub.events[-1]["updated"]
    r.refresh()
    stale = pub.events[-1]
    assert stale["status"] == "stale"
    assert stale["data"] == {"temp": 7} and stale["updated"] == good_at


def test_background_thread_fetches_and_stops():
    fetched = threading.Event()
    pub = Recorder()

    def fetch(settings):
        fetched.set()
        return {}

    r = Refresher("demo", fetch, {}, 3600, pub).start()
    assert fetched.wait(timeout=3)
    r.stop()


def test_hub_skips_disabled_and_unknown_widgets():
    demo = SimpleNamespace(DEFAULT_REFRESH_MINUTES=5.0, fetch=lambda s: {"ok": True})
    hub = Hub(
        {
            "demo": WidgetConfig(True, None, {"x": 1}),
            "off": WidgetConfig(False, 1.0, {}),
            "mystery": WidgetConfig(True, 1.0, {}),
        },
        Recorder(),
        registry={"demo": demo, "off": demo},
    )
    assert list(hub.refreshers) == ["demo"]
    assert hub.refreshers["demo"].interval == 300  # module default when not configured
    assert hub.refreshers["demo"].settings == {"x": 1}
    assert hub.snapshot() == {"demo": None}
    hub.refreshers["demo"].refresh()
    assert hub.snapshot() == {"demo": {"ok": True}}


def test_new_subscribers_get_latest_widget_data():
    b = Broadcaster()
    b.publish(widget="weather", status="ok", data={"temp": 5})
    b.publish(widget="weather", status="ok", data={"temp": 6})
    b.publish(widget="bus", status="error", data=None)
    q = b.subscribe()
    sent = [json.loads(q.get_nowait()) for _ in range(q.qsize())]
    assert sent[0] == {"state": "idle"}
    assert {"widget": "weather", "status": "ok", "data": {"temp": 6}} in sent
    assert {"widget": "bus", "status": "error", "data": None} in sent
    assert len(sent) == 3


def test_every_hub_widget_has_example_config_and_a_display_file():
    root = find_repo_root()
    example = yaml.safe_load((root / "config.example.yaml").read_text())["widgets"]
    page = (root / "display" / "index.html").read_text()
    for name, module in WIDGETS.items():
        assert name in example, f"add a widgets.{name} block to config.example.yaml"
        assert callable(module.fetch) and module.DEFAULT_REFRESH_MINUTES > 0
        assert f'src="widgets/{name}.js"' in page, f"add widgets/{name}.js to index.html"


def test_every_display_widget_file_is_loaded_and_registered():
    root = find_repo_root()
    page = (root / "display" / "index.html").read_text()
    for js in sorted((root / "display" / "widgets").glob("*.js")):
        assert f'src="widgets/{js.name}"' in page, f"index.html doesn't load {js.name}"
        if js.stem != "widgets":
            registered = re.search(r'Widgets\.register\("([\w-]+)"', js.read_text())
            assert registered and registered.group(1) == js.stem
