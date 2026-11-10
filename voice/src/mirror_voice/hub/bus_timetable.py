"""The bus timetable for your stop(s), cut down once a day from the BODS regional GTFS.

The Bus Open Data Service publishes every English bus timetable as GTFS, one zip per
region (Yorkshire is ~150 MB zipped, ~1 GB unzipped, almost all of it stop_times.txt and
shapes.txt). We never unzip it: the zip is streamed to a temp file, read row by row
straight out of the archive, and boiled down to just the trips that call at the
configured stops in the next few days. That small JSON (tens of KB) is cached and used
for every refresh until the next day's rebuild.

https://data.bus-data.dft.gov.uk/timetable/download/  (GTFS downloads need no API key)
"""

from __future__ import annotations

import csv
import io
import json
import logging
import os
import tempfile
import time
import urllib.request
import zipfile
from collections.abc import Iterator
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

GTFS_URL = "https://data.bus-data.dft.gov.uk/timetable/download/gtfs-file/{region}/"
CACHE_VERSION = 1
DAYS = 3  # cache this many days ahead (plus yesterday, for trips running past midnight)
REBUILD_HOUR = 5  # BODS regenerates the files overnight (~04:30); rebuild after this


def _reader(zf: zipfile.ZipFile, name: str) -> tuple[dict[str, int], Iterator[list[str]]]:
    """(column index by name, row iterator) for one file in the zip, streamed."""
    if name not in zf.namelist():
        return {}, iter(())
    text = io.TextIOWrapper(zf.open(name), encoding="utf-8-sig", newline="")
    rows = csv.reader(text)
    header = next(rows, [])
    return {col.strip(): i for i, col in enumerate(header)}, rows


def gtfs_seconds(hhmmss: str) -> int:
    """GTFS time ("25:10:00" is 01:10 the next morning) -> seconds after midnight."""
    h, m, s = hhmmss.strip().split(":")
    return int(h) * 3600 + int(m) * 60 + int(s)


def service_dates(
    zf: zipfile.ZipFile, service_ids: set[str], dates: list[date]
) -> dict[str, list[str]]:
    """Which of `dates` each service runs on (calendar.txt + calendar_dates.txt)."""
    days = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
    running: dict[str, set[date]] = {sid: set() for sid in service_ids}
    col, rows = _reader(zf, "calendar.txt")
    for row in rows:
        sid = row[col["service_id"]]
        if sid not in running:
            continue
        start = datetime.strptime(row[col["start_date"]], "%Y%m%d").date()
        end = datetime.strptime(row[col["end_date"]], "%Y%m%d").date()
        for d in dates:
            if start <= d <= end and row[col[days[d.weekday()]]] == "1":
                running[sid].add(d)
    col, rows = _reader(zf, "calendar_dates.txt")
    wanted = {d.strftime("%Y%m%d"): d for d in dates}
    for row in rows:
        sid, day = row[col["service_id"]], row[col["date"]]
        if sid in running and day in wanted:
            if row[col["exception_type"]] == "1":
                running[sid].add(wanted[day])
            else:
                running[sid].discard(wanted[day])
    return {sid: sorted(d.isoformat() for d in ds) for sid, ds in running.items()}


def build(zip_path: Path, stop_ids: list[str], today: date, days: int = DAYS) -> dict[str, Any]:
    """Cut a GTFS zip down to the trips that pick up at `stop_ids` from yesterday to
    `today + days - 1`, with every call on those trips (for placing live buses)."""
    wanted = set(stop_ids)
    dates = [today + timedelta(days=n) for n in range(-1, days)]
    with zipfile.ZipFile(zip_path) as zf:
        # 1. Which trips call at our stops at all (any day)?
        col, rows = _reader(zf, "stop_times.txt")
        t, s = col["trip_id"], col["stop_id"]
        trip_ids = {row[t] for row in rows if row[s] in wanted}

        # 2. Their route, service and headsign.
        col, rows = _reader(zf, "trips.txt")
        trips: dict[str, dict[str, str]] = {}
        for row in rows:
            if row[col["trip_id"]] in trip_ids:
                trips[row[col["trip_id"]]] = {
                    "route_id": row[col["route_id"]],
                    "service_id": row[col["service_id"]],
                    "headsign": row[col["trip_headsign"]] if "trip_headsign" in col else "",
                }

        # 3. Keep only the ones that run in our date window.
        runs = service_dates(zf, {tr["service_id"] for tr in trips.values()}, dates)
        trips = {tid: tr for tid, tr in trips.items() if runs.get(tr["service_id"])}

        # 4. Every call of the trips we kept, in order.
        calls: dict[str, list[tuple[int, str, int, bool]]] = {tid: [] for tid in trips}
        col, rows = _reader(zf, "stop_times.txt")
        t, s, seq = col["trip_id"], col["stop_id"], col["stop_sequence"]
        dep, arr = col["departure_time"], col["arrival_time"]
        pickup = col.get("pickup_type")
        for row in rows:
            trip_calls = calls.get(row[t])
            if trip_calls is None:
                continue
            when = row[dep] or row[arr]
            if not when:
                continue  # untimed stop: no use to us
            no_pickup = pickup is not None and row[pickup] == "1"
            trip_calls.append((int(row[seq]), row[s], gtfs_seconds(when), no_pickup))

        # 5. Stop names/positions and route numbers for what's left.
        needed = {stop for tc in calls.values() for _, stop, _, _ in tc}
        col, rows = _reader(zf, "stops.txt")
        stops = {
            row[col["stop_id"]]: {
                "name": row[col["stop_name"]],
                "lat": round(float(row[col["stop_lat"]]), 6),
                "lon": round(float(row[col["stop_lon"]]), 6),
            }
            for row in rows
            if row[col["stop_id"]] in needed and row[col["stop_lat"]]
        }
        col, rows = _reader(zf, "routes.txt")
        routes = {
            row[col["route_id"]]: row[col["route_short_name"]] or row[col["route_long_name"]]
            for row in rows
        }
        col, rows = _reader(zf, "feed_info.txt")
        feed_version = next((row[col["feed_version"]] for row in rows), "")

    out_trips = []
    for tid, tr in trips.items():
        ordered = sorted(calls[tid])
        # Where on this trip you can get on at one of our stops (not the last stop).
        at = [
            i
            for i, (_, stop, _, no_pickup) in enumerate(ordered)
            if stop in wanted and not no_pickup and i < len(ordered) - 1
        ]
        if not at:
            continue
        last_stop = ordered[-1][1]
        out_trips.append(
            {
                "id": tid,
                "route": routes.get(tr["route_id"], tr["route_id"]),
                "headsign": tr["headsign"] or stops.get(last_stop, {}).get("name", ""),
                "dates": runs[tr["service_id"]],
                "calls": [[stop, secs] for _, stop, secs, _ in ordered],
                "at": at,
            }
        )
    out_trips.sort(key=lambda tr: tr["calls"][tr["at"][0]][1])
    return {
        "version": CACHE_VERSION,
        "stop_ids": sorted(wanted),
        "dates": [d.isoformat() for d in dates],
        "feed_version": feed_version,
        "stops": stops,
        "trips": out_trips,
    }


def download(url: str, dest: Path, timeout: float = 60) -> None:
    """Stream a (big) download to `dest` without holding it in memory."""
    req = urllib.request.Request(url, headers={"User-Agent": "mirror-assistant"})
    with urllib.request.urlopen(req, timeout=timeout) as resp, dest.open("wb") as f:
        while chunk := resp.read(1 << 20):
            f.write(chunk)


def needs_rebuild(cached: dict[str, Any] | None, stop_ids: list[str], now: datetime) -> bool:
    if not cached or cached.get("version") != CACHE_VERSION:
        return True
    if cached.get("stop_ids") != sorted(set(stop_ids)):
        return True
    today = now.date().isoformat()
    if today not in cached.get("dates", []):
        return True
    built = cached.get("built", "")[:10]
    return built < today and now.hour >= REBUILD_HOUR


def load(settings: dict[str, Any], cache_dir: Path, now: datetime) -> dict[str, Any]:
    """The cut-down timetable for the configured stops, rebuilt once a day.

    If a rebuild fails (no internet first thing, BODS down) the previous cache keeps
    being used for as long as it covers today; otherwise the error propagates."""
    stop_ids = [str(s) for s in settings["stops"]]
    path = cache_dir / "timetable.json"
    cached = _read(path)
    if not needs_rebuild(cached, stop_ids, now):
        return cached  # type: ignore[return-value]
    url = settings.get("gtfs_url") or GTFS_URL.format(region=settings.get("region", "yorkshire"))
    try:
        fresh = rebuild(url, stop_ids, cache_dir, now)
    except Exception as e:
        if cached and cached.get("stop_ids") == sorted(set(stop_ids)):
            if now.date().isoformat() in cached.get("dates", []):
                log.warning("bus: timetable rebuild failed (%s); using yesterday's", e)
                return cached
        raise
    return fresh


def rebuild(url: str, stop_ids: list[str], cache_dir: Path, now: datetime) -> dict[str, Any]:
    cache_dir.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    fd, tmp = tempfile.mkstemp(suffix=".zip", dir=cache_dir)
    os.close(fd)
    try:
        download(url, Path(tmp))
        downloaded = time.monotonic()
        data = build(Path(tmp), stop_ids, now.date())
    finally:
        Path(tmp).unlink(missing_ok=True)
    data["built"] = now.isoformat(timespec="seconds")
    data["source"] = url
    if not data["trips"]:
        raise ValueError(f"no buses found for stops {', '.join(stop_ids)}: check the codes")
    path = cache_dir / "timetable.json"
    part = path.with_suffix(".part")
    part.write_text(json.dumps(data, separators=(",", ":")))
    part.replace(path)
    log.info(
        "bus: timetable rebuilt: %d trips (download %.0fs, filter %.0fs)",
        len(data["trips"]),
        downloaded - started,
        time.monotonic() - downloaded,
    )
    return data


def _read(path: Path) -> dict[str, Any] | None:
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return None
