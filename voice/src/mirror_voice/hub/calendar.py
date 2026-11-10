"""Both flatmates' calendars, from their private iCal (ICS) links.

Settings (under `widgets.calendar` in config.yaml):
    calendars    list of {name, url, colour?, email?}: whose calendar, its secret ICS link,
                 an optional dot colour ("#7fb8ff" or a CSS colour name), and optionally
                 the owner's email (to find their RSVP; Google feeds usually say it anyway)
    days         how many days to show, starting today (default 4)
    max_events   most events on screen at once (default 7)
    timezone     the mirror's timezone (default Europe/London)
    show_declined   show events the owner said no to (default false)
    show_cancelled  show cancelled events, struck through (default false)

The links are secrets: anyone with one can read that calendar. They never leave this
module: not in the data sent to the page, not in errors, not in the logs. Owners' email
addresses don't either: only the RSVP state worked out from them goes out.

RSVP ("response"), per person per event: accepted | tentative | needs_action | declined |
cancelled. It comes from the ATTENDEE line matching the owner's email (PARTSTAT); events
they organised or with no guest list have none, so it falls back to STATUS:TENTATIVE or
Outlook's X-MICROSOFT-CDO-BUSYSTATUS:TENTATIVE, and otherwise counts as accepted.

Recurring events (RRULE, EXDATE, moved occurrences), all-day events and time zones are
handled by `icalendar` + `recurring-ical-events`. One calendar failing still shows the
others, with a note saying whose is missing.
"""

from __future__ import annotations

import logging
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import icalendar
import recurring_ical_events

log = logging.getLogger(__name__)

DEFAULT_REFRESH_MINUTES = 10.0
DEFAULT_DAYS = 4
DEFAULT_MAX_EVENTS = 7
DEFAULT_TIMEZONE = "Europe/London"

# Dot colours for calendars that don't set one, in config order.
PALETTE = ["#6fb6ff", "#ffa66b", "#8fe39a", "#e3a0ff", "#ffd966", "#ff8a9a"]
COLOUR_RE = re.compile(r"^(#[0-9a-fA-F]{3,8}|[a-zA-Z]{3,20})$")

MAX_ICS_BYTES = 20_000_000  # a busy, years-old Google calendar is a few MB
LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}  # plain http only allowed for these (testing)
REDACTED = "<calendar link>"


# ---------------------------------------------------------------- secrets ----


def secret_parts(url: str) -> set[str]:
    """The link, its path, and any token-like piece of it (anything with a digit in)."""
    parts = urllib.parse.urlsplit(https_url(url))
    path = parts.path + ("?" + parts.query if parts.query else "")
    found = {url, https_url(url), path}
    found.update(
        p
        for p in re.split(r"[/?&=]", path)
        if len(p) >= 20 or (len(p) >= 6 and any(c.isdigit() for c in p))
    )
    found |= {urllib.parse.unquote(s) for s in found}
    return {s for s in found if len(s) > 1}


def redact(text: str, *urls: str) -> str:
    """Remove calendar links, or any recognisable piece of them, from `text`."""
    secrets = set().union(*(secret_parts(u) for u in urls if u))
    if secrets:  # one pass, longest first, so a replacement is never re-matched
        pattern = "|".join(re.escape(s) for s in sorted(secrets, key=len, reverse=True))
        text = re.sub(pattern, REDACTED, text)
    # Belt and braces: no link of any kind goes out in an error message.
    return re.sub(r"\b(?:https?|webcal)://\S+", REDACTED, text)


def describe_error(e: BaseException, *urls: str) -> str:
    """A short, link-free reason for a failed download, e.g. "HTTP 404"."""
    if isinstance(e, urllib.error.HTTPError):
        reason = f"HTTP {e.code}"
    elif isinstance(e, urllib.error.URLError):
        reason = str(e.reason)
    elif isinstance(e, TimeoutError):
        reason = "timed out"
    else:
        reason = f"{type(e).__name__}: {e}"
    return redact(reason, *urls)[:120]


def https_url(url: str) -> str:
    """Calendar apps hand out webcal:// links; they're plain https underneath."""
    if url.lower().startswith("webcal://"):
        return "https://" + url[len("webcal://") :]
    return url


# --------------------------------------------------------------- download ----


def download(url: str) -> str:
    url = https_url(url.strip())
    parts = urllib.parse.urlsplit(url)
    if parts.scheme != "https" and not (parts.scheme == "http" and parts.hostname in LOCAL_HOSTS):
        raise ValueError("link must start with https:// or webcal://")
    req = urllib.request.Request(url, headers={"User-Agent": "mirror-assistant"})
    with urllib.request.urlopen(req, timeout=20) as resp:
        body = resp.read(MAX_ICS_BYTES + 1)
    if len(body) > MAX_ICS_BYTES:
        raise ValueError("calendar is too big")
    return body.decode("utf-8", errors="replace")


@dataclass
class Source:
    """One configured calendar, plus what we last managed to download from it."""

    name: str
    colour: str
    url: str = field(repr=False)  # secret
    ics: str | None = None  # last good download
    fetched: float | None = None
    error: str | None = None  # why the latest download failed, link-free
    email: str = field(default="", repr=False)  # owner, from config; private


# Last good download per link, so a blip on one calendar keeps showing its events.
_cache: dict[str, tuple[str, float]] = {}
_cache_lock = threading.Lock()


def calendars(settings: dict[str, Any]) -> list[Source]:
    sources = []
    for i, cal in enumerate(settings.get("calendars") or []):
        if not isinstance(cal, dict) or not cal.get("url"):
            continue  # a half-filled entry in config.yaml: ignore it rather than crash
        colour = str(cal.get("colour") or cal.get("color") or "")
        if not COLOUR_RE.match(colour):
            colour = PALETTE[i % len(PALETTE)]
        name = str(cal.get("name") or f"Calendar {i + 1}")
        email = str(cal.get("email") or "").strip()
        sources.append(Source(name, colour, str(cal["url"]), email=email))
    return sources


def fetch(settings: dict[str, Any], now: datetime | None = None) -> dict[str, Any]:
    """Download every calendar and boil them down to the next few days."""
    sources = calendars(settings)
    all_urls = [s.url for s in sources]
    for src in sources:
        try:
            src.ics = download(src.url)
            src.fetched = time.time()
            icalendar.Calendar.from_ical(src.ics)  # don't cache something we can't read
            with _cache_lock:
                _cache[src.url] = (src.ics, src.fetched)
        except Exception as e:
            src.error = describe_error(e, *all_urls)
            log.warning("calendar: couldn't load %s's calendar: %s", src.name, src.error)
            with _cache_lock:
                src.ics, src.fetched = _cache.get(src.url, (None, None))

    if sources and all(src.ics is None for src in sources):
        reasons = "; ".join(f"{s.name}: {s.error}" for s in sources)
        raise RuntimeError(f"no calendars could be loaded ({reasons})")
    return build(sources, settings, now)


# ------------------------------------------------------------------ parse ----


ACCEPTED, TENTATIVE, NEEDS_ACTION, DECLINED, CANCELLED = (
    "accepted",
    "tentative",
    "needs_action",
    "declined",
    "cancelled",
)
PARTSTAT = {
    "ACCEPTED": ACCEPTED,
    "TENTATIVE": TENTATIVE,
    "NEEDS-ACTION": NEEDS_ACTION,
    "DECLINED": DECLINED,
    "DELEGATED": DECLINED,  # passed it to someone else: they're not going
}
# For a merged event's title: the keenest person sets the tone.
KEENNESS = [ACCEPTED, TENTATIVE, NEEDS_ACTION, DECLINED, CANCELLED]
# How the summary lines say each (accepted says nothing).
SAY = {
    TENTATIVE: "maybe",
    NEEDS_ACTION: "not replied",
    DECLINED: "declined",
    CANCELLED: "cancelled",
}
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


@dataclass
class Event:
    title: str
    start: datetime | date
    end: datetime | date
    who: list[Source]
    responses: list[str] = field(default_factory=list)  # one per `who`

    @property
    def all_day(self) -> bool:
        return not isinstance(self.start, datetime)


def owner_email(cal: icalendar.Calendar, configured: str = "") -> str:
    """Whose calendar this is: the `email:` setting, else Google's X-WR-CALNAME."""
    if configured:
        return configured.casefold()
    name = str(cal.get("X-WR-CALNAME") or "").strip()
    return name.casefold() if EMAIL_RE.match(name) else ""


def response_of(comp: icalendar.cal.Component, owner: str) -> str:
    """The owner's RSVP to one event (see the module docstring)."""
    if str(comp.get("STATUS", "")).upper() == "CANCELLED":
        return CANCELLED
    if owner:
        attendees = comp.get("ATTENDEE") or []
        if not isinstance(attendees, list):
            attendees = [attendees]
        for att in attendees:
            address = str(att).strip().casefold().removeprefix("mailto:")
            if address == owner:
                partstat = str(getattr(att, "params", {}).get("PARTSTAT", "NEEDS-ACTION"))
                return PARTSTAT.get(partstat.upper(), ACCEPTED)
    # No guest list, or they organised it: use the event's own status.
    busy = str(comp.get("X-MICROSOFT-CDO-BUSYSTATUS", "")).upper()
    if busy == "TENTATIVE" or str(comp.get("STATUS", "")).upper() == "TENTATIVE":
        return TENTATIVE
    return ACCEPTED


def to_local(value: datetime | date, tz: ZoneInfo) -> datetime | date:
    if not isinstance(value, datetime):
        return value  # all-day: a date, no time zone
    if value.tzinfo is None:  # "floating" time: means local time wherever you are
        return value.replace(tzinfo=tz)
    return value.astimezone(tz)


def events_between(
    ics: str, start: datetime, end: datetime, tz: ZoneInfo, email: str = ""
) -> list[Event]:
    """Every occurrence in [start, end) from one ICS file, each with the owner's RSVP as
    its single `responses` entry. Pure: no network."""
    cal = icalendar.Calendar.from_ical(ics)
    owner = owner_email(cal, email)
    found = []
    for comp in recurring_ical_events.of(cal, skip_bad_series=True).between(start, end):
        begin = to_local(comp.decoded("DTSTART"), tz)
        if "DTEND" in comp:
            finish = to_local(comp.decoded("DTEND"), tz)
        elif "DURATION" in comp:
            finish = begin + comp.decoded("DURATION")
        else:
            finish = begin + timedelta(days=1) if not isinstance(begin, datetime) else begin
        title = str(comp.get("SUMMARY") or "Busy").strip() or "Busy"
        found.append(Event(title, begin, finish, [], [response_of(comp, owner)]))
    return found


def first_day(event: Event, today: date) -> date:
    """The day an event is listed under: the day it starts, or today if it's under way."""
    day = event.start if event.all_day else event.start.date()
    return max(day, today)


def last_day(event: Event) -> date:
    """The last day an event covers (all-day DTEND is the day after, per the spec)."""
    if event.all_day:
        return max(event.start, event.end - timedelta(days=1))
    end = event.end
    return (end - timedelta(microseconds=1)).date() if end > event.start else end.date()


def day_label(day: date, today: date) -> str:
    offset = (day - today).days
    if offset == 0:
        return "Today"
    if offset == 1:
        return "Tomorrow"
    if offset < 7:
        return day.strftime("%A")
    return f"{day:%a} {day.day} {day:%b}"


def build(sources: list[Source], settings: dict[str, Any], now: datetime | None = None) -> dict:
    """Merge every calendar into the widget's data. Pure apart from `now`."""
    tz = ZoneInfo(str(settings.get("timezone") or DEFAULT_TIMEZONE))
    now = (now or datetime.now(tz)).astimezone(tz)
    days = max(1, int(settings.get("days", DEFAULT_DAYS)))
    max_events = max(1, int(settings.get("max_events", DEFAULT_MAX_EVENTS)))
    hidden = set()
    if not settings.get("show_declined", False):
        hidden.add(DECLINED)
    if not settings.get("show_cancelled", False):
        hidden.add(CANCELLED)
    today = now.date()
    window_start = datetime.combine(today, datetime.min.time(), tz)
    window_end = datetime.combine(today + timedelta(days=days), datetime.min.time(), tz)

    notes = []
    merged: dict[tuple, Event] = {}  # the same event on both calendars shows once
    for src in sources:
        if src.error:
            if src.fetched:
                when = datetime.fromtimestamp(src.fetched, tz).strftime("%H:%M")
                notes.append(f"{src.name}'s calendar not updated since {when}")
            else:
                notes.append(f"Couldn't load {src.name}'s calendar")
        if src.ics is None:
            continue
        try:
            events = events_between(src.ics, window_start, window_end, tz, src.email)
        except Exception as e:  # a calendar we can download but not read
            reason = redact(str(e), *(s.url for s in sources))
            log.warning("calendar: couldn't read %s's calendar: %s", src.name, reason)
            notes.append(f"Couldn't read {src.name}'s calendar")
            continue
        for ev in events:
            if not ev.all_day and ev.end <= now and ev.end > ev.start:
                continue  # already finished today
            [response] = ev.responses
            if response in hidden:
                continue  # they said no (or it's off): not on their list
            key = (ev.title.casefold(), ev.start, ev.end)
            if key not in merged:
                merged[key] = Event(ev.title, ev.start, ev.end, [])
            if src not in merged[key].who:  # each person keeps their own RSVP
                merged[key].who.append(src)
                merged[key].responses.append(response)

    def sort_key(ev: Event):
        day = first_day(ev, today)
        timed = not ev.all_day
        start = ev.start if timed else datetime.combine(day, datetime.min.time(), tz)
        return (day, timed, start, ev.title.casefold())

    shown = sorted(merged.values(), key=sort_key)
    more = max(0, len(shown) - max_events)
    shown = shown[:max_events]

    by_day: dict[date, list[dict[str, Any]]] = {today: []}
    for ev in shown:
        by_day.setdefault(first_day(ev, today), []).append(event_data(ev, today))

    out_days = [
        {"label": day_label(day, today), "date": day.isoformat(), "events": events}
        for day, events in sorted(by_day.items())
    ]
    return {
        "days": out_days,
        "more": more,
        "people": [{"name": s.name, "colour": s.colour} for s in sources],
        "notes": notes if sources else ["No calendars yet: add your ICS links to config.yaml"],
        "summary": summary_lines(out_days, more),
    }


def hhmm(value: datetime) -> str:
    return value.strftime("%H:%M")


def event_data(ev: Event, today: date) -> dict[str, Any]:
    day = first_day(ev, today)
    end_day = last_day(ev)
    if ev.all_day:
        time_label = "All day"
    elif ev.start.date() < day:  # started on an earlier day, still going
        time_label = f"until {hhmm(ev.end)}"
    else:
        time_label = hhmm(ev.start)
    until = until_short = ""
    if end_day > day:  # runs over several days, e.g. a holiday
        until = day_label(end_day, today)  # "Saturday"
        soon = (end_day - today).days < 7
        until_short = f"{end_day:%a}" if soon else f"{end_day.day} {end_day:%b}"
    return {
        "title": ev.title,
        "time": time_label,
        "start": hhmm(ev.start) if not ev.all_day else "",
        "end": hhmm(ev.end) if not ev.all_day else "",
        "all_day": ev.all_day,
        "until": until,
        "until_short": until_short,  # "Sat", or "21 Nov" if it's further off
        "who": [s.name for s in ev.who],
        "colours": [s.colour for s in ev.who],
        "responses": list(ev.responses),  # one per person in `who`
        "response": min(ev.responses, key=KEENNESS.index),  # the keenest, for the title
    }


def summary_lines(days: list[dict[str, Any]], more: int) -> list[str]:
    """Plain-English lines for Mirror to read from, e.g. when asked "what's my day like?"."""
    lines = []
    for day in days:
        if not day["events"]:
            lines.append(f"{day['label']}: nothing on.")
            continue
        parts = []
        for e in day["events"]:
            if e["all_day"]:
                when = "all day" + (f" until {e['until']}" if e["until"] else "")
            elif e["time"].startswith("until"):
                when = e["time"]
            else:
                when = f"{e['start']}-{e['end']}" if e["end"] != e["start"] else e["start"]
            parts.append(f"{' & '.join(e['who'])}: {e['title']} ({when}{rsvp_words(e)})")
        lines.append(f"{day['label']}: " + "; ".join(parts) + ".")
    if more:
        lines.append(f"Plus {more} more not shown.")
    return lines


def rsvp_words(e: dict[str, Any]) -> str:
    """ ", maybe" if everyone's the same; "; Sam maybe" if people differ; "" if all going."""
    responses = e["responses"]
    if len(set(responses)) == 1:
        return f", {SAY[responses[0]]}" if responses[0] in SAY else ""
    return "".join(
        f"; {who} {SAY[r]}" for who, r in zip(e["who"], responses, strict=True) if r in SAY
    )
