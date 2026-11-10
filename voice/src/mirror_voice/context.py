"""What the assistant can see on the board, boiled down for one question.

The model never calls tools: on the Pi a 3B model picks tools unreliably and a second
model pass is slow. Instead, cheap keyword routing looks at what was said and adds a few
lines of the board's live data ("Live info") to that one question:

    always                         the time and date (one line)
    weather words                  the weather          ("do I need a coat?")
    bus words / route numbers      the next few buses   ("when's the next 24?")
    day / calendar words, names    today and tomorrow   ("what's Sam up to tomorrow?")
    briefing phrases               all of the above, compact ("give me a rundown")

Prompt reading is slow on the Pi (tens of tokens a second), so each block is a line or
two. Only data the hub actually fetched goes in: a widget that's failing says when it
last updated, or "unavailable", never a guess.

Pure: give it the utterance, `Hub.board()` and the time; no network, no clock.
To teach it a new phrase, add it to one of the keyword lists below.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

# Keyword lists: lower case, whole words or phrases. Apostrophes are ignored when
# matching, so "whats" and "what's" are the same; other punctuation is ignored too.
WEATHER_WORDS = [
    "weather", "forecast", "temperature", "degrees", "outside",
    "rain", "raining", "rainy", "wet", "dry", "drizzle", "shower", "showers",
    "umbrella", "brolly", "coat", "jacket", "jumper", "layers", "hat", "gloves", "scarf",
    "cold", "chilly", "freezing", "warm", "hot", "sunny", "sun", "cloudy",
    "wind", "windy", "snow", "snowing", "ice", "icy", "fog", "foggy",
]  # fmt: skip
# Asking for a bus into town: only buses whose destination is in widgets.bus.town.
TOWN_WORDS = ["into town", "in town", "to town", "town", "city centre", "into the city"]
BUS_WORDS = [
    "bus", "buses", "next one",
    "late for", "catch", "bus stop", "timetable",
]  # fmt: skip
# Clearly about plans: always bring in the calendar.
CALENDAR_WORDS = [
    "calendar", "diary", "schedule", "agenda", "plans", "planned", "my day",
    "meeting", "meetings", "appointment", "appointments", "event", "events",
    "busy", "free", "working", "whats on", "anything on",
]  # fmt: skip
# Only about plans when nothing else matched: "a coat today?" is a weather question.
WHEN_WORDS = [
    "today", "tonight", "tomorrow", "this morning", "this afternoon", "this evening",
    "later",
]  # fmt: skip
BRIEFING_WORDS = [
    "whats going on", "whats happening", "rundown", "run down", "brief me", "briefing",
    "morning brief", "catch me up", "fill me in", "whats the plan", "what do i need to know",
]  # fmt: skip

# A route number asked for: "next X84", "number 1", "when's the 24", "the 24 into town"
# (not "the next 6 hours" or "the 3 best films"). Runs on normalise()d text.
_ROUTE = r"([a-z]?\d{1,3}[a-z]?)"
ROUTE_ASKED = re.compile(
    rf"\b(?:next|number)\s+{_ROUTE}\b"
    r"(?!\s+(?:hours?|minutes?|mins?|days?|weeks?|degrees|oclock|am|pm|percent)\b)"
    rf"|\bthe\s+{_ROUTE}(?=\s+(?:bus|due|comes?|coming|leaves?|goes|go|gets?|to|into|from)\b|$)"
)

# Words in bus destinations that say nothing about which bus ("Leeds Bus Station").
_PLACE_NOISE = {"bus", "station", "stn", "city", "centre", "center", "road", "campus", "the"}

MAX_EVENTS_PER_DAY = 4
TITLE_CHARS = 40
BUSES = 4
BUSES_IN_BRIEFING = 3


@dataclass(frozen=True)
class Route:
    """Which parts of the board an utterance is about."""

    weather: bool = False
    bus: bool = False
    calendar: bool = False
    briefing: bool = False
    people: tuple[str, ...] = ()  # names mentioned ("Sam"); empty = everyone
    buses: tuple[str, ...] = ()  # routes or destinations mentioned ("24"); empty = any
    town: bool = False  # "into town": only buses marked into_town (widgets.bus.town)


def normalise(text: str) -> str:
    """Lower case, apostrophes dropped, other punctuation to spaces, single spaces."""
    text = re.sub(r"['’`]", "", text.lower())
    return " ".join(re.sub(r"[^\w]+", " ", text).split())


def mentions(text: str, phrases: Iterable[str]) -> bool:
    """Whether normalised `text` contains any phrase as whole words."""
    for phrase in phrases:
        p = normalise(phrase)
        if p and re.search(rf"(?<!\w){re.escape(p)}(?!\w)", text):
            return True
    return False


def route(
    utterance: str, board: Mapping[str, Any] | None = None, people: Iterable[str] = ()
) -> Route:
    """Decide what to look up. The board adds its own words (route numbers, destinations,
    calendar names); `people` adds the flatmates' names (assistant.people)."""
    text = normalise(utterance)
    data = {name: (entry or {}).get("data") or {} for name, entry in (board or {}).items()}

    if mentions(text, BRIEFING_WORDS):
        return Route(weather=True, bus=True, calendar=True, briefing=True)

    names = [str(p.get("name", "")) for p in data.get("calendar", {}).get("people", [])]
    named = tuple(dict.fromkeys(n for n in [*names, *people] if n and mentions(text, [n])))
    found = {w for w in bus_words(data.get("bus", {})) if mentions(text, [w])}
    found.update(a or b for a, b in ROUTE_ASKED.findall(text))  # even if none is coming
    buses = tuple(sorted(found))

    weather = mentions(text, WEATHER_WORDS)
    town = mentions(text, TOWN_WORDS)
    bus = bool(buses) or town or mentions(text, BUS_WORDS)
    calendar = bool(named) or mentions(text, CALENDAR_WORDS)
    if not (weather or bus or calendar):
        calendar = mentions(text, WHEN_WORDS)
    return Route(weather=weather, bus=bus, calendar=calendar, people=named, buses=buses, town=town)


def bus_words(bus: Mapping[str, Any]) -> list[str]:
    """Route numbers ("24", "X84") and destination names ("Holt Park") in the bus data."""
    words: set[str] = set()
    for dep in bus.get("departures") or []:
        words.add(str(dep.get("route", "")))
        place = normalise(str(dep.get("destination", ""))).split()
        while place and place[-1] in _PLACE_NOISE:
            place.pop()
        if place and place != ["leeds"]:  # the city name alone is too broad
            words.add(" ".join(place))
    return [w for w in words if w]


# ------------------------------------------------------------------ lines ----


def live_info(
    utterance: str, board: Mapping[str, Any] | None, now: datetime, people: Iterable[str] = ()
) -> str:
    """The "Live info" block for one question: a time line, plus what it's about.

    `board` is `Hub.board()`, or None if the hub isn't running (then: just the time).
    A widget that's switched off is left out; one that's on but has no data yet says
    "unavailable", so the model knows it doesn't know. `people` is assistant.people.
    """
    lines = [time_line(now)]
    if not board:
        return lines[0]
    r = route(utterance, board, people)
    if r.weather and "weather" in board:
        lines.append(weather_line(board["weather"], now))
    if r.calendar and "calendar" in board:
        lines.extend(calendar_lines(board["calendar"], now, r.people))
    if r.bus and "bus" in board:
        count = BUSES_IN_BRIEFING if r.briefing else BUSES
        lines.append(bus_line(board["bus"], now, count, r.buses, r.town))
    return "\n".join(line for line in lines if line)


def time_line(now: datetime) -> str:
    return f"Now: {now:%A} {now.day} {now:%B}, {now:%H:%M}."


def _stale(entry: Mapping[str, Any], now: datetime) -> str:
    """' (not updated since 14:05)' if the hub's last fetch of this widget failed."""
    if entry.get("status") == "ok" or not entry.get("updated"):
        return ""
    when = datetime.fromtimestamp(entry["updated"], now.tzinfo)
    stamp = f"{when:%H:%M}" if when.date() == now.date() else f"{when:%a} {when:%H:%M}"
    return f" (not updated since {stamp})"


def _usable(entry: Mapping[str, Any] | None) -> Mapping[str, Any] | None:
    """The widget's data, or None if the hub has never fetched it."""
    if not entry or not entry.get("data") or entry.get("status") == "error":
        return None
    return entry["data"]


def weather_line(entry: Mapping[str, Any] | None, now: datetime) -> str:
    w = _usable(entry)
    if w is None:
        return "Weather: unavailable."
    where = f" in {w['place']}" if w.get("place") else ""
    parts = [f"{w['temp']}C (feels {w['feels_like']})", str(w["condition"]).lower()]
    if w.get("wind_mph") is not None:
        parts.append(f"wind {w['wind_mph']} mph")
    parts.append(f"today {w['low']}-{w['high']}C")
    rain = (w.get("rain") or {}).get("summary")
    if rain:
        parts.append(rain[0].lower() + rain[1:])
    return f"Weather{where}: {', '.join(parts)}.{_stale(entry, now)}"


def bus_line(
    entry: Mapping[str, Any] | None,
    now: datetime,
    count: int = BUSES,
    only: tuple[str, ...] = (),
    town: bool = False,
) -> str:
    """The next `count` buses: just the routes/destinations in `only` if any were named,
    just the ones into town if asked and the data says which those are."""
    b = _usable(entry)
    if b is None:
        return "Buses: unavailable."
    deps = b.get("departures") or []
    into_town = town and any(d.get("into_town") for d in deps)
    if into_town:
        deps = [d for d in deps if d.get("into_town")]
    stop = (" into town" if into_town else "") + (f" from {b['stop']}" if b.get("stop") else "")
    now_ts = now.timestamp()
    coming = []
    for dep in deps:
        expected = float(dep.get("expected", 0))
        if expected < now_ts - (60 if dep.get("live") else 0):
            continue  # left since the last fetch (a live one gets a minute's grace)
        minutes = max(0, int((expected - now_ts) // 60))
        when = "due now" if minutes == 0 else f"{minutes} min" if minutes <= 30 else dep["time"]
        to = f" to {dep['destination']}" if dep.get("destination") else ""
        tag = "" if dep.get("live") else " (timetable)"
        coming.append((dep, f"{dep['route']}{to} {when}{tag}"))
    stale = _stale(entry, now)
    if not coming:
        if stale:
            return "Buses: unavailable."
        if into_town:  # the data only holds the next few departures
            return f"Buses{stop}: none in the next few departures."
        return f"Buses{stop}: none in the next {b.get('horizon_minutes', 90)} min."
    wanted = [text for dep, text in coming if _is_one_of(dep, only)] if only else []
    if only and not wanted:  # say so, rather than let the model pick a different bus
        listed = [text for _, text in coming[:count]]
        lead = f"no {' or '.join(only)} listed; others: "
        return f"Buses{stop}: {lead}{'; '.join(listed)}.{stale}"
    listed = (wanted or [text for _, text in coming])[:count]
    return f"Buses{stop}: {'; '.join(listed)}.{stale}"


def _is_one_of(dep: Mapping[str, Any], wanted: tuple[str, ...]) -> bool:
    route_no = normalise(str(dep.get("route", "")))
    place = normalise(str(dep.get("destination", "")))
    return any(w == route_no or mentions(place, [w]) for w in wanted)


def calendar_lines(
    entry: Mapping[str, Any] | None, now: datetime, people: tuple[str, ...] = ()
) -> list[str]:
    """Today and tomorrow only, for everyone or just the people named."""
    c = _usable(entry)
    if c is None:
        return ["Calendar: unavailable."]
    names = [str(p.get("name", "")) for p in c.get("people") or []]
    missing = [p for p in people if p not in names]
    note = f"No calendar for {' or '.join(missing)}: you can't see their plans." if missing else ""
    people = tuple(p for p in people if p in names)
    if missing and not people:
        return [note]  # never someone else's plans in their place
    whose = list(people) or names
    head = "Calendar" if not whose else f"Calendar ({', '.join(whose)})"
    by_date = {d.get("date"): d.get("events") or [] for d in c.get("days") or []}
    shown_to = max(by_date, default="")  # last day the data covers
    show_who = len(names) > 1 and len(whose) != 1

    lines = [note] if note else []
    lines.append(f"{head}:{_stale(entry, now)}")
    today = now.date()
    for label, day in (("Today", today), ("Tomorrow", today + timedelta(days=1))):
        events = [e for e in by_date.get(day.isoformat(), []) if _for(e, people)]
        if day == today:
            events = [e for e in events if not _finished(e, now)]
        lines.append(f"{label}: {_day_text(events, show_who)}")
    if c.get("more") and shown_to <= (today + timedelta(days=1)).isoformat():
        lines[-1] += " Maybe more not listed."
    for note in c.get("notes") or []:
        if not people or any(p in note for p in people):
            lines.append(f"({note})")
    return lines


def _for(event: Mapping[str, Any], people: tuple[str, ...]) -> bool:
    return not people or any(p in (event.get("who") or []) for p in people)


def _finished(event: Mapping[str, Any], now: datetime) -> bool:
    """A timed event today that has already ended (the data is up to 10 min old)."""
    if event.get("all_day") or event.get("until") or not event.get("end"):
        return False
    start, end = event.get("start", ""), event["end"]
    return start <= end <= f"{now:%H:%M}"


def _day_text(events: list[Mapping[str, Any]], show_who: bool) -> str:
    if not events:
        return "nothing on."
    parts = []
    for e in events[:MAX_EVENTS_PER_DAY]:
        title = str(e.get("title", "Busy"))
        if len(title) > TITLE_CHARS:
            title = title[: TITLE_CHARS - 1].rstrip() + "…"
        if e.get("all_day"):
            when = "all day" + (f" until {e['until']}" if e.get("until") else "")
        elif str(e.get("time", "")).startswith("until"):
            when = e["time"]
        elif e.get("end") and e["end"] != e.get("start"):
            when = f"{e['start']}-{e['end']}"
        else:
            when = str(e.get("start") or e.get("time", ""))
        who = f"{' & '.join(e.get('who') or [])}: " if show_who and e.get("who") else ""
        parts.append(f"{who}{title} ({when})")
    extra = len(events) - MAX_EVENTS_PER_DAY
    return "; ".join(parts) + (f"; +{extra} more." if extra > 0 else ".")


def add_to_question(user_text: str, info: str) -> str:
    """The latest user turn as the model sees it: the question, then the live note."""
    return f"{user_text}\n\n[Live info]\n{info}" if info else user_text
