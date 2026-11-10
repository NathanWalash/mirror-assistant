"""Next buses from your stop, from the Bus Open Data Service (BODS).

BODS has no "departures at stop X" call, so this combines two of its feeds:

1. **Timetable** (bus_timetable.py): the regional GTFS, cut down once a day to the
   trips that pick up at your stop(s). No API key needed.
2. **Live positions** (gtfs_rt.py): GTFS-Realtime vehicle positions in a box around the
   routes, every refresh. BODS has already matched each bus to its GTFS trip_id, so we
   know exactly which timetabled journey each bus is running. Needs BODS_API_KEY in the
   environment or the repo's .env (free: https://data.bus-data.dft.gov.uk/account/signup/).

A bus is "live" when its position tells us how late it is: we find where it is along
its route, compare that with when it was timetabled to be there, and carry the delay
forward to your stop. Without a key, or if the live feed fails, the times shown are the
timetable and are marked as such.

Settings (under `widgets.bus` in config.yaml):
    stops            ATCO codes of your stop(s), e.g. ["450010687"] (find yours on bustimes.org)
    routes           only show these route numbers, e.g. ["33", "33A"] (default: all)
    max_departures   how many to show (default 5)
    walk_minutes     hide buses leaving sooner than this (default 0)
    horizon_minutes  how far ahead to look (default 90)
    name             label for the stop (default: its name in the timetable)
    region           BODS GTFS region file (default "yorkshire")
    live             use live positions when a key is set (default true)
    groups           optional: split the stops by direction, each with its own heading,
                     e.g. [{label: "Town", stops: [...]}, {label: "Out", stops: [...]}].
                     When set, the groups' stops replace `stops`.
    max_per_group    buses shown per group (default 3; a group can set its own
                     `max_departures`)
"""

from __future__ import annotations

import logging
import math
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from mirror_voice.config import find_repo_root
from mirror_voice.env import get_secret
from mirror_voice.hub import bus_timetable, gtfs_rt

log = logging.getLogger(__name__)

DEFAULT_REFRESH_MINUTES = 1.0

TZ = ZoneInfo("Europe/London")
LIVE_URL = "https://data.bus-data.dft.gov.uk/api/v1/gtfsrtdatafeed/"
KEY_NAME = "BODS_API_KEY"

LATE_GRACE = 30 * 60  # still look for live buses this long after their timetabled time
POSITION_MAX_AGE = 10 * 60  # ignore positions older than this
ON_ROUTE_METRES = 300  # how close to the line between two stops a bus must be
AT_STOP_METRES = 80  # within this of our stop still counts as "not gone yet"
MAX_EARLY = 5 * 60  # don't believe a bus is running more than this early
MINUTES_UNTIL_CLOCK = 30  # beyond this the display shows "14:05" not "34 min"
GONE = -1.0  # estimate(): the bus has already passed the stop


def fetch(settings: dict[str, Any]) -> dict[str, Any]:
    settings = with_group_stops(settings)
    root = find_repo_root()
    now = _now()
    cache_dir = Path(settings.get("cache_dir") or root / "cache" / "bus")
    timetable = bus_timetable.load(settings, cache_dir, now)
    candidates = upcoming(timetable, settings, now)

    vehicles: list[gtfs_rt.Vehicle] | None = None
    key = get_secret(KEY_NAME, root)
    if key and settings.get("live", True) and candidates:
        try:
            vehicles = fetch_vehicles(key, bounding_box(timetable, candidates))
        except Exception as e:  # live is a bonus: fall back to the timetable
            log.warning("bus: live positions unavailable: %s", redact(str(e), key))
    return departures(timetable, candidates, vehicles, settings, now)


def _now() -> datetime:
    return datetime.now(TZ)


def redact(text: str, secret: str) -> str:
    return text.replace(secret, "***") if secret else text


def fetch_vehicles(key: str, bbox: tuple[float, float, float, float]) -> list[gtfs_rt.Vehicle]:
    min_lat, min_lon, max_lat, max_lon = bbox
    query = urllib.parse.urlencode(
        {"boundingBox": f"{min_lon:.4f},{min_lat:.4f},{max_lon:.4f},{max_lat:.4f}", "api_key": key}
    )
    req = urllib.request.Request(f"{LIVE_URL}?{query}", headers={"User-Agent": "mirror-assistant"})
    with urllib.request.urlopen(req, timeout=20) as resp:
        return gtfs_rt.vehicles(resp.read())


# ---- Pure from here down: no network, testable with fixtures ----


def groups(settings: dict[str, Any]) -> list[dict[str, Any]]:
    """The configured direction groups, checked, or [] if there are none."""
    out = []
    for i, g in enumerate(settings.get("groups") or []):
        if not isinstance(g, dict) or not g.get("stops"):
            raise ValueError(f"bus group {i + 1} needs a list of stops")
        out.append(
            {
                "label": str(g.get("label") or f"Group {i + 1}"),
                "stops": [str(s) for s in g["stops"]],
                "max": int(g.get("max_departures", settings.get("max_per_group", 3))),
            }
        )
    return out


def with_group_stops(settings: dict[str, Any]) -> dict[str, Any]:
    """Settings whose `stops` are every grouped stop, when groups are configured."""
    gs = groups(settings)
    if not gs:
        return settings
    return {**settings, "stops": list(dict.fromkeys(s for g in gs for s in g["stops"]))}


def _midnight(day: str) -> datetime:
    return datetime.combine(date.fromisoformat(day), datetime.min.time(), TZ)


def upcoming(timetable: dict[str, Any], settings: dict[str, Any], now: datetime) -> list[dict]:
    """Timetabled calls at our stop(s) from a little in the past (late buses) to the horizon."""
    routes = {str(r).upper() for r in settings.get("routes") or []}
    horizon = now + timedelta(minutes=float(settings.get("horizon_minutes", 90)))
    earliest = now - timedelta(seconds=LATE_GRACE)
    out = []
    for trip in timetable["trips"]:
        if routes and str(trip["route"]).upper() not in routes:
            continue
        for day in trip["dates"]:
            base = _midnight(day)
            for at in trip["at"]:
                when = base + timedelta(seconds=trip["calls"][at][1])
                if earliest <= when <= horizon:
                    out.append({"trip": trip, "day": day, "at": at, "scheduled": when})
    return out


def bounding_box(
    timetable: dict[str, Any], candidates: list[dict], pad: float = 0.005
) -> tuple[float, float, float, float]:
    """(min_lat, min_lon, max_lat, max_lon) around the route up to our stop."""
    stops = timetable["stops"]
    points = [
        (stops[stop]["lat"], stops[stop]["lon"])
        for c in candidates
        for stop, _ in c["trip"]["calls"][: c["at"] + 1]
        if stop in stops
    ]
    lats, lons = [p[0] for p in points], [p[1] for p in points]
    return min(lats) - pad, min(lons) - pad, max(lats) + pad, max(lons) + pad


def _metres(a: tuple[float, float], b: tuple[float, float]) -> tuple[float, float]:
    """(x, y) metres from a to b; flat-earth is fine over a few km."""
    lat0 = math.radians((a[0] + b[0]) / 2)
    return (b[1] - a[1]) * 111_320 * math.cos(lat0), (b[0] - a[0]) * 110_574


def locate(
    calls: list[tuple[tuple[float, float] | None, int]], pos: tuple[float, float], at_secs: int
) -> tuple[float, float] | None:
    """Where a bus is along its trip: (position as a fractional call index, timetabled
    seconds-after-midnight for that spot). Of the stretches between stops the bus is
    close to, picks the one it should be on around `at_secs` (handles loops that pass
    the same street twice). None if it isn't near its route at all."""
    best: tuple[float, float, float] | None = None  # (score, index, secs)
    for i in range(len(calls) - 1):
        (a, ta), (b, tb) = calls[i], calls[i + 1]
        if a is None or b is None:
            continue
        bx, by = _metres(a, b)
        px, py = _metres(a, pos)
        seg = bx * bx + by * by
        f = 0.0 if seg == 0 else max(0.0, min(1.0, (px * bx + py * by) / seg))
        dist = math.hypot(px - f * bx, py - f * by)
        if dist > ON_ROUTE_METRES:
            continue
        secs = ta + f * (tb - ta)
        score = abs(secs - at_secs) + dist  # seconds off timetable + metres off route
        if best is None or score < best[0]:
            best = (score, i + f, secs)
    return None if best is None else (best[1], best[2])


def estimate(candidate: dict, vehicle: gtfs_rt.Vehicle, stops: dict) -> float | None:
    """Expected departure (Unix time) of a live bus at our stop, or None if it can't be
    placed. Returns GONE if it has already passed."""
    trip, at = candidate["trip"], candidate["at"]
    base = _midnight(candidate["day"]).timestamp()
    calls = [
        ((stops[s]["lat"], stops[s]["lon"]) if s in stops else None, secs)
        for s, secs in trip["calls"]
    ]
    seen = vehicle.timestamp - base  # when the position was recorded, in trip seconds
    where = locate(calls, (vehicle.lat, vehicle.lon), int(seen))
    if where is None:
        return None
    index, timetabled = where
    if index > at:
        ours = calls[at][0]
        if ours is None or math.hypot(*_metres(ours, (vehicle.lat, vehicle.lon))) > AT_STOP_METRES:
            return GONE
    if index < 0.05:  # still at the start, waiting to set off: it won't leave early
        delay = max(0.0, seen - calls[0][1])
    else:
        delay = max(float(-MAX_EARLY), seen - timetabled)
    return base + trip["calls"][at][1] + delay


def departures(
    timetable: dict[str, Any],
    candidates: list[dict],
    vehicles: list[gtfs_rt.Vehicle] | None,
    settings: dict[str, Any],
    now: datetime,
) -> dict[str, Any]:
    """The widget's data: the next few buses, live where we can place them."""
    now_ts = now.timestamp()
    by_trip = {v.trip_id: v for v in vehicles or []}
    walk = float(settings.get("walk_minutes", 0)) * 60
    rows = []
    for c in candidates:
        scheduled = c["scheduled"].timestamp()
        expected, live = scheduled, False
        v = by_trip.get(c["trip"]["id"])
        if (
            v is not None
            and v.start_date in ("", c["day"].replace("-", ""))
            and now_ts - v.timestamp <= POSITION_MAX_AGE
        ):
            guess = estimate(c, v, timetable["stops"])
            if guess == GONE:
                continue  # already been
            if guess is not None:
                expected, live = guess, True
        if expected < now_ts - (60 if live else 0):
            continue  # timetabled time has passed and we've no sign of it
        if expected - now_ts < walk:
            continue  # can't make it
        rows.append((expected, scheduled, live, c))
    rows.sort(key=lambda r: r[0])

    def row(expected: float, scheduled: float, live: bool, c: dict) -> dict[str, Any]:
        minutes = max(0, int((expected - now_ts) // 60))
        return {
            "route": c["trip"]["route"],
            "destination": c["trip"]["headsign"],
            "expected": round(expected),
            "time": datetime.fromtimestamp(expected, TZ).strftime("%H:%M"),
            "scheduled_time": c["scheduled"].strftime("%H:%M"),
            "minutes": minutes,
            "due": when_text(minutes, expected),
            "live": live,
            "late_minutes": round((expected - scheduled) / 60) if live else None,
        }

    horizon = int(settings.get("horizon_minutes", 90))
    out = [row(*r) for r in rows[: int(settings.get("max_departures", 5))]]
    data: dict[str, Any] = {
        "stop": settings.get("name") or stop_name(timetable),
        "departures": out,
        "live_feed": vehicles is not None,
        "horizon_minutes": horizon,
        "summary": summary(out, horizon),
        "timetable": timetable.get("feed_version", ""),
    }

    gs = groups(settings)
    if gs:
        data["groups"] = []
        for g in gs:
            wanted, seen, picked = set(g["stops"]), set(), []
            for r in rows:
                c = r[3]
                key = (c["trip"]["id"], c["day"])  # one bus calling at two of the group's stops
                if c["trip"]["calls"][c["at"]][0] not in wanted or key in seen:
                    continue
                seen.add(key)
                picked.append(row(*r))
                if len(picked) >= g["max"]:
                    break
            data["groups"].append({"label": g["label"], "departures": picked})
        data["summary"] = "; ".join(
            f"{g['label']}: {group_summary(g['departures'], horizon)}" for g in data["groups"]
        )
    return data


def when_text(minutes: int, expected: float) -> str:
    if minutes <= 0:
        return "Due"
    if minutes > MINUTES_UNTIL_CLOCK:
        return datetime.fromtimestamp(expected, TZ).strftime("%H:%M")
    return f"{minutes} min"


def stop_name(timetable: dict[str, Any]) -> str:
    names = {timetable["stops"].get(s, {}).get("name", "") for s in timetable["stop_ids"]}
    return " / ".join(sorted(n for n in names if n))


def summary(rows: list[dict[str, Any]], horizon: int) -> str:
    """One line for Mirror to say, e.g. "Next 33 to Leeds in 4 minutes (live)"."""
    if not rows:
        return f"No buses in the next {horizon} minutes"
    r = rows[0]
    to = f" to {r['destination']}" if r["destination"] else ""
    source = "live" if r["live"] else "timetabled"
    return f"Next {r['route']}{to} {_spoken_when(r)} ({source})"


def group_summary(rows: list[dict[str, Any]], horizon: int) -> str:
    """The short form used per direction, e.g. "next 33 in 4 minutes"."""
    if not rows:
        return f"no buses in the next {horizon} minutes"
    return f"next {rows[0]['route']} {_spoken_when(rows[0])}"


def _spoken_when(r: dict[str, Any]) -> str:
    if r["minutes"] <= 0:
        return "due now"
    if r["minutes"] > MINUTES_UNTIL_CLOCK:
        return f"at {r['time']}"
    return f"in {r['minutes']} minute{'s' if r['minutes'] != 1 else ''}"
