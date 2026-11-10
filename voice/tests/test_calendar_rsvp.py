"""The owner's RSVP per event: accepted / tentative / needs_action / declined / cancelled."""

import json
import logging
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from mirror_voice.hub import calendar

FIXTURES = Path(__file__).parent / "fixtures"
LONDON = ZoneInfo("Europe/London")
NOW = datetime(2026, 11, 10, 8, 0, tzinfo=LONDON)  # Tuesday 8am
WORK = "https://calendar.google.com/calendar/ical/work/private-w0rkt0ken/basic.ics"
FLAT = "https://outlook.office365.com/owa/calendar/1111aaaa/2222bbbb/calendar.ics"
FILES = {WORK: "calendar_rsvp.ics", FLAT: "calendar_outlook.ics"}
OWNER = "alex.example@example.com"  # the work feed's X-WR-CALNAME


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    monkeypatch.setattr(calendar, "_cache", {})
    monkeypatch.setattr(calendar, "download", lambda url: (FIXTURES / FILES[url]).read_text())


def fetch(*cals, **settings):
    return calendar.fetch({"calendars": list(cals), "max_events": 50, **settings}, now=NOW)


def events(data):
    """{title: event} across all days."""
    return {e["title"]: e for d in data["days"] for e in d["events"]}


def test_owner_attendee_in_each_state():
    shown = events(fetch({"name": "Alex", "url": WORK}))
    assert shown["Team lunch"]["responses"] == ["accepted"]  # MAILTO:Alex.Example@... any case
    assert shown["Running club"]["responses"] == ["tentative"]
    assert shown["Planning"]["responses"] == ["needs_action"]
    assert "Skipped meeting" not in shown  # declined: hidden by default
    assert "Called off" not in shown  # cancelled: hidden by default


def test_declined_and_cancelled_can_be_shown():
    shown = events(fetch({"name": "Alex", "url": WORK}, show_declined=True, show_cancelled=True))
    assert shown["Skipped meeting"]["response"] == "declined"
    assert shown["Called off"]["response"] == "cancelled"


def test_no_owner_attendee_falls_back_to_the_event():
    shown = events(fetch({"name": "Alex", "url": WORK}))
    assert shown["Focus time"]["responses"] == ["accepted"]  # organised it, no guest list
    assert shown["Pencilled in"]["responses"] == ["tentative"]  # STATUS:TENTATIVE


def test_outlook_busy_status_tentative():
    shown = events(fetch({"name": "Sam", "url": FLAT}))
    assert shown["Leaving drinks"]["responses"] == ["tentative"]  # X-MICROSOFT-CDO-BUSYSTATUS
    assert shown["Five-a-side"]["responses"] == ["accepted"]


def test_owner_from_x_wr_calname():
    from icalendar import Calendar

    cal = Calendar.from_ical((FIXTURES / "calendar_rsvp.ics").read_text())
    assert calendar.owner_email(cal) == OWNER
    other = Calendar.from_ical((FIXTURES / "calendar_outlook.ics").read_text())
    assert calendar.owner_email(other) == ""  # X-WR-CALNAME "Calendar": not an email


def test_email_setting_overrides_the_calendar_name():
    # Same feed, read as if it were other@example.com's: their RSVPs apply instead.
    shown = events(fetch({"name": "Other", "url": WORK, "email": "Other@Example.com"}))
    assert shown["Running club"]["responses"] == ["accepted"]
    assert shown["Team lunch"]["responses"] == ["tentative"]
    assert shown["Skipped meeting"]["responses"] == ["accepted"]
    assert "Planning" not in shown  # they declined it


def test_merged_event_keeps_each_persons_response():
    data = fetch({"name": "Alex", "url": WORK}, {"name": "Sam", "url": FLAT})
    dinner = events(data)["Flat dinner"]
    assert dinner["who"] == ["Alex", "Sam"]
    assert dinner["responses"] == ["tentative", "accepted"]
    assert dinner["response"] == "accepted"  # title shows the keenest person


def test_one_person_declining_a_shared_event_drops_only_them():
    # Read the same work feed as two people: Alex declined "Skipped meeting", Other didn't.
    data = fetch(
        {"name": "Alex", "url": WORK},
        {"name": "Other", "url": WORK, "email": "other@example.com"},
    )
    shown = events(data)
    assert shown["Skipped meeting"]["who"] == ["Other"]
    assert shown["Planning"]["who"] == ["Alex"]
    assert shown["Running club"]["responses"] == ["tentative", "accepted"]


def test_summary_says_maybe_and_not_replied():
    summary = " ".join(
        fetch({"name": "Alex", "url": WORK}, {"name": "Sam", "url": FLAT})["summary"]
    )
    assert "Alex: Running club (17:00-18:00, maybe)" in summary
    assert "Alex: Planning (10:00-11:00, not replied)" in summary
    assert "Alex: Team lunch (12:00-13:00)" in summary  # accepted: nothing added
    assert "Alex & Sam: Flat dinner (19:00-21:00; Alex maybe)" in summary
    assert "Sam: Leaving drinks (18:00-20:00, maybe)" in summary


def test_owner_emails_never_reach_the_page_or_logs(caplog):
    caplog.set_level(logging.DEBUG)
    data = fetch(
        {"name": "Alex", "url": WORK},
        {"name": "Other", "url": WORK, "email": "other@example.com"},
    )
    sent = json.dumps(data).casefold()
    assert "@" not in sent and "example.com" not in sent
    assert "@" not in caplog.text
