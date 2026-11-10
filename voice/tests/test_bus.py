import json
import logging
import shutil
import struct
import urllib.error
import zipfile
from datetime import date, datetime, timedelta
from pathlib import Path

import pytest
from mirror_voice import env
from mirror_voice.hub import bus, bus_timetable, gtfs_rt

GTFS_DIR = Path(__file__).parent / "fixtures" / "gtfs_mini"
OUR_STOP = "450000002"
TUESDAY = date(2026, 11, 10)
SETTINGS = {"stops": [OUR_STOP], "max_departures": 5, "horizon_minutes": 90}


def at(hh: int, mm: int, ss: int = 0, day: date = TUESDAY) -> datetime:
    return datetime(day.year, day.month, day.day, hh, mm, ss, tzinfo=bus.TZ)


@pytest.fixture
def gtfs_zip(tmp_path):
    path = tmp_path / "gtfs.zip"
    with zipfile.ZipFile(path, "w") as zf:
        for f in GTFS_DIR.glob("*.txt"):
            zf.write(f, f.name)
    return path


@pytest.fixture
def timetable(gtfs_zip):
    return bus_timetable.build(gtfs_zip, [OUR_STOP], TUESDAY)


def by_id(tt):
    return {t["id"]: t for t in tt["trips"]}


# ---- Timetable (daily cut-down of the GTFS) ----


def test_gtfs_times_can_run_past_midnight():
    assert bus_timetable.gtfs_seconds("10:10:00") == 36600
    assert bus_timetable.gtfs_seconds("25:10:00") == 90600


def test_build_keeps_only_trips_you_can_board_at_your_stop(timetable):
    # T3: no pickup at our stop. T4: Sundays only. T5: terminates at our stop.
    # T8: never calls at our stop.
    assert set(by_id(timetable)) == {"T1", "T2", "T6", "T7"}
    assert timetable["feed_version"] == "test_feed_1"
    assert timetable["stop_ids"] == [OUR_STOP]
    assert timetable["stops"][OUR_STOP]["name"] == "Our Stop"
    assert "450000009" not in timetable["stops"]  # only stops on kept trips


def test_build_orders_calls_and_fills_in_destination(timetable):
    trips = by_id(timetable)
    t2 = trips["T2"]  # stop_times rows out of order, no headsign
    assert [s for s, _ in t2["calls"]] == ["450000001", "450000002", "450000003"]
    assert t2["at"] == [1]
    assert t2["headsign"] == "Seacroft"  # last stop's name
    assert trips["T1"]["headsign"] == "Leeds Bus Stn"
    assert trips["T1"]["route"] == "33"


def test_build_applies_calendar_and_exceptions(timetable):
    trips = by_id(timetable)
    # Window is yesterday..today+2. Weekday service, but removed on Wednesday 11th.
    assert trips["T1"]["dates"] == ["2026-11-09", "2026-11-10", "2026-11-12"]
    assert trips["T6"]["dates"] == ["2026-11-10"]  # added by calendar_dates only


def test_needs_rebuild():
    good = {
        "version": bus_timetable.CACHE_VERSION,
        "stop_ids": [OUR_STOP],
        "dates": ["2026-11-09", "2026-11-10", "2026-11-11", "2026-11-12"],
        "built": "2026-11-10T06:00:00+00:00",
    }
    assert not bus_timetable.needs_rebuild(good, [OUR_STOP], at(23, 0))
    assert bus_timetable.needs_rebuild(None, [OUR_STOP], at(23, 0))
    assert bus_timetable.needs_rebuild(good, ["450000003"], at(23, 0))  # stops changed
    tomorrow = TUESDAY + timedelta(days=1)
    # Next day: keep yesterday's until the overnight files are published, then rebuild.
    assert not bus_timetable.needs_rebuild(good, [OUR_STOP], at(1, 0, day=tomorrow))
    assert bus_timetable.needs_rebuild(good, [OUR_STOP], at(6, 0, day=tomorrow))


def test_load_builds_once_then_uses_the_cache(gtfs_zip, tmp_path, monkeypatch):
    downloads = []

    def fake_download(url, dest, timeout=60):
        downloads.append(url)
        shutil.copy(gtfs_zip, dest)

    monkeypatch.setattr(bus_timetable, "download", fake_download)
    cache = tmp_path / "cache"
    first = bus_timetable.load(SETTINGS, cache, at(10, 0))
    again = bus_timetable.load(SETTINGS, cache, at(10, 1))
    assert downloads == ["https://data.bus-data.dft.gov.uk/timetable/download/gtfs-file/yorkshire/"]
    assert set(by_id(again)) == set(by_id(first)) == {"T1", "T2", "T6", "T7"}
    assert [p.name for p in cache.iterdir()] == ["timetable.json"]  # temp zip cleaned up


def test_load_falls_back_to_cache_if_rebuild_fails(gtfs_zip, tmp_path, monkeypatch):
    cache = tmp_path / "cache"
    monkeypatch.setattr(
        bus_timetable, "download", lambda u, d, timeout=60: shutil.copy(gtfs_zip, d)
    )
    bus_timetable.load(SETTINGS, cache, at(10, 0))

    def offline(url, dest, timeout=60):
        raise urllib.error.URLError("no internet")

    monkeypatch.setattr(bus_timetable, "download", offline)
    next_morning = at(6, 0, day=TUESDAY + timedelta(days=1))
    assert bus_timetable.load(SETTINGS, cache, next_morning)["trips"]
    with pytest.raises(urllib.error.URLError):  # a week later the cache doesn't cover today
        bus_timetable.load(SETTINGS, cache, next_morning + timedelta(days=7))


def test_unknown_stop_is_an_error(gtfs_zip, tmp_path, monkeypatch):
    monkeypatch.setattr(
        bus_timetable, "download", lambda u, d, timeout=60: shutil.copy(gtfs_zip, d)
    )
    with pytest.raises(ValueError, match="no buses found"):
        bus_timetable.load({"stops": ["450999999"]}, tmp_path, at(10, 0))


# ---- Departures from the timetable alone ----


def show(timetable, now, vehicles=None, **settings):
    s = {**SETTINGS, **settings}
    return bus.departures(timetable, bus.upcoming(timetable, s, now), vehicles, s, now)


def test_scheduled_departures(timetable):
    data = show(timetable, at(10, 5))
    rows = data["departures"]
    assert [(r["route"], r["destination"], r["due"]) for r in rows] == [
        ("33", "Leeds Bus Stn", "5 min"),
        ("33", "Seacroft", "10:40"),  # over 30 minutes away: clock time
        ("X6", "Extra", "11:10"),
    ]
    assert not any(r["live"] for r in rows) and data["live_feed"] is False
    assert data["stop"] == "Our Stop"
    assert data["summary"] == "Next 33 to Leeds Bus Stn in 5 minutes (timetabled)"


def test_route_filter_walk_time_and_limit(timetable):
    assert [r["route"] for r in show(timetable, at(10, 5), routes=["x6"])["departures"]] == ["X6"]
    walk = show(timetable, at(10, 5), walk_minutes=10)["departures"]
    assert [r["scheduled_time"] for r in walk] == ["10:40", "11:10"]
    assert len(show(timetable, at(10, 5), max_departures=1)["departures"]) == 1


def test_bus_past_midnight_comes_from_the_previous_service_day(timetable):
    data = show(timetable, at(0, 15, day=TUESDAY + timedelta(days=1)))
    [night] = data["departures"]
    assert night["destination"] == "Night Bus" and night["due"] == "5 min"


def test_nothing_coming(timetable):
    data = show(timetable, at(15, 0), name="Home")
    assert data["departures"] == [] and data["stop"] == "Home"
    assert data["summary"] == "No buses in the next 90 minutes"


# ---- Live positions ----


def vehicle(trip="T1", lat=53.805, when=None, start_date="20261110"):
    ts = int((when or at(10, 7)).timestamp())
    return gtfs_rt.Vehicle(trip, start_date, "r1", lat, -1.55, ts, "BUS-1")


def first(data):
    return data["departures"][0]


def test_live_bus_running_late(timetable):
    # Halfway to our stop at 10:07; timetabled to be there at 10:05: 2 minutes late.
    data = show(timetable, at(10, 7, 30), [vehicle(lat=53.805, when=at(10, 7))])
    r = first(data)
    assert r["live"] and r["late_minutes"] == 2
    assert r["time"] == "10:12" and r["due"] == "4 min"
    assert data["summary"] == "Next 33 to Leeds Bus Stn in 4 minutes (live)"


def test_live_bus_waiting_at_the_start_is_not_early(timetable):
    r = first(show(timetable, at(9, 50), [vehicle(lat=53.80, when=at(9, 50))]))
    assert r["live"] and r["time"] == "10:10" and r["late_minutes"] == 0


def test_live_bus_that_has_passed_is_dropped(timetable):
    data = show(timetable, at(10, 11), [vehicle(lat=53.815, when=at(10, 11))])
    assert [r["destination"] for r in data["departures"]] == ["Seacroft", "Extra"]


def test_late_bus_still_shows_after_its_timetabled_time(timetable):
    # 10:12, a bus timetabled for 10:10 is still on its way: live keeps it on screen.
    r = first(show(timetable, at(10, 12), [vehicle(lat=53.808, when=at(10, 12))]))
    assert r["scheduled_time"] == "10:10" and r["live"] and r["late_minutes"] >= 3


def test_unusable_positions_fall_back_to_the_timetable(timetable):
    now = at(10, 7)
    for v in (
        vehicle(lat=53.90),  # nowhere near its route
        vehicle(when=now - timedelta(minutes=30)),  # position too old
        vehicle(start_date="20261109"),  # yesterday's run of the same trip
        vehicle(trip="SOMETHING-ELSE"),
    ):
        r = first(show(timetable, now, [v]))
        assert not r["live"] and r["time"] == "10:10", v


def test_bounding_box_covers_the_route_up_to_our_stop(timetable):
    candidates = bus.upcoming(timetable, SETTINGS, at(10, 5))
    min_lat, min_lon, max_lat, max_lon = bus.bounding_box(timetable, candidates, pad=0)
    assert (min_lat, max_lat) == (53.80, 53.81)  # not on to Seacroft (53.82)
    assert min_lon == max_lon == -1.55


# ---- fetch(): network stubbed out ----


@pytest.fixture
def offline_fetch(gtfs_zip, tmp_path, monkeypatch):
    monkeypatch.setattr(bus, "find_repo_root", lambda: tmp_path)
    monkeypatch.setattr(bus, "_now", lambda: at(10, 5))
    monkeypatch.delenv(bus.KEY_NAME, raising=False)
    monkeypatch.setattr(
        bus_timetable, "download", lambda u, d, timeout=60: shutil.copy(gtfs_zip, d)
    )
    calls = []

    def fake_urlopen(req, timeout=None):
        calls.append(req.full_url)
        raise urllib.error.URLError(f"failed to reach {req.full_url}")

    monkeypatch.setattr(bus.urllib.request, "urlopen", fake_urlopen)
    return tmp_path, calls


def test_fetch_without_a_key_is_timetable_only(offline_fetch):
    root, calls = offline_fetch
    data = bus.fetch(SETTINGS)
    assert calls == []  # no live request without a key
    assert data["live_feed"] is False and len(data["departures"]) == 3
    assert (root / "cache" / "bus" / "timetable.json").is_file()
    json.dumps(data)  # JSON-able for the display


def test_fetch_live_failure_falls_back_and_never_logs_the_key(offline_fetch, caplog):
    root, calls = offline_fetch
    (root / ".env").write_text("BODS_API_KEY=sekrit-key-123\n")
    with caplog.at_level(logging.WARNING):
        data = bus.fetch(SETTINGS)
    assert len(calls) == 1 and "sekrit-key-123" in calls[0]
    assert data["live_feed"] is False
    assert "live positions unavailable" in caplog.text
    assert "sekrit-key-123" not in caplog.text and "***" in caplog.text


# ---- GTFS-RT decoding ----


def _varint(n: int) -> bytes:
    out = bytearray()
    while True:
        b, n = n & 0x7F, n >> 7
        out.append(b | (0x80 if n else 0))
        if not n:
            return bytes(out)


def _field(number: int, value) -> bytes:
    if isinstance(value, float):
        return _varint(number << 3 | 5) + struct.pack("<f", value)
    if isinstance(value, int):
        return _varint(number << 3) + _varint(value)
    if isinstance(value, str):
        value = value.encode()
    return _varint(number << 3 | 2) + _varint(len(value)) + value


def test_gtfs_rt_vehicle_positions():
    trip = _field(1, "VJabc") + _field(2, "10:00:00") + _field(3, "20261110") + _field(5, "r1")
    position = _field(1, 53.805) + _field(2, -1.55) + _field(3, 90.0)
    vp = _field(1, trip) + _field(2, position) + _field(5, 1794308174) + _field(8, _field(1, "B1"))
    no_trip = _field(2, position) + _field(5, 1794308174)
    feed = (
        _field(1, _field(1, "2.0") + _field(3, 1794308180))  # header
        + _field(2, _field(1, "e1") + _field(4, vp))
        + _field(2, _field(1, "e2") + _field(4, no_trip))  # skipped: no trip
        + _varint(99 << 3 | 1)
        + b"\0" * 8  # an unknown fixed64 field is skipped
    )
    [v] = gtfs_rt.vehicles(feed)
    assert (v.trip_id, v.start_date, v.route_id, v.vehicle_id) == ("VJabc", "20261110", "r1", "B1")
    assert v.lat == pytest.approx(53.805) and v.lon == pytest.approx(-1.55)
    assert v.timestamp == 1794308174


def test_gtfs_rt_rejects_truncated_data():
    with pytest.raises(ValueError):
        gtfs_rt.vehicles(_field(2, b"\x22\x05ab"))


# ---- .env ----


def test_dotenv_and_environment(tmp_path, monkeypatch):
    (tmp_path / ".env").write_text(
        "# secrets\nexport BODS_API_KEY=\"abc123\"\nOTHER = 'x y'\nEMPTY=\nnot a line\n"
    )
    assert env.read_dotenv(tmp_path / ".env") == {
        "BODS_API_KEY": "abc123",
        "OTHER": "x y",
        "EMPTY": "",
    }
    monkeypatch.delenv("BODS_API_KEY", raising=False)
    assert env.get_secret("BODS_API_KEY", tmp_path) == "abc123"
    assert env.get_secret("EMPTY", tmp_path) is None
    assert env.get_secret("MISSING", None) is None
    monkeypatch.setenv("BODS_API_KEY", "from-env")
    assert env.get_secret("BODS_API_KEY", tmp_path) == "from-env"
