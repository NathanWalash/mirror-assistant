import json
import logging
import urllib.error
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from mirror_voice.hub import calendar
from mirror_voice.hub.calendar import Source, build

FIXTURES = Path(__file__).parent / "fixtures"
LONDON = ZoneInfo("Europe/London")
SECRET_A = "https://calendar.google.com/calendar/ical/abc123%40group/private-5ecre7t0ken/basic.ics"
SECRET_B = "webcal://outlook.office365.com/owa/calendar/1111aaaa/2222bbbbsecret/calendar.ics"
FILES = {SECRET_A: "calendar_google.ics", SECRET_B: "calendar_outlook.ics"}
SETTINGS = {
    "calendars": [
        {"name": "Alex", "url": SECRET_A, "colour": "#123456"},
        {"name": "Sam", "url": SECRET_B},
    ],
    "days": 4,
    "max_events": 30,
}
# Tuesday 10 November 2026, 8am: GMT (the clocks went back on 25 October).
NOW = datetime(2026, 11, 10, 8, 0, tzinfo=LONDON)


def ics(name):
    return (FIXTURES / name).read_text()


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    """Serve fixture files instead of the internet; clear the last-good cache."""
    monkeypatch.setattr(calendar, "_cache", {})
    monkeypatch.setattr(calendar, "download", lambda url: ics(FILES[url]))


def titles(day):
    return [(e["time"], e["title"]) for e in day["events"]]


def test_merges_both_calendars_by_day():
    data = calendar.fetch(SETTINGS, now=NOW)
    labels = [d["label"] for d in data["days"]]
    assert labels == ["Today", "Tomorrow", "Thursday", "Friday"]
    today, tomorrow, thursday, friday = data["days"]
    assert today["date"] == "2026-11-10"
    assert titles(today) == [
        ("until 09:00", "Late shift"),  # started last night, still going
        ("09:30", "Standup"),
        ("14:30", "Dentist"),
        ("18:00", "Gym"),
        ("19:00", "Five-a-side"),  # Outlook's "GMT Standard Time" zone
    ]
    assert data["notes"] == []
    assert data["more"] == 0
    json.dumps(data)  # must be JSON-able for the display


def test_finished_and_cancelled_events_are_hidden():
    today = calendar.fetch(SETTINGS, now=NOW)["days"][0]
    shown = {e["title"] for e in today["events"]}
    assert "Early run" not in shown  # 06:30-07:15, already over at 8am
    assert "Cancelled plans" not in shown


def test_recurrence_exdate_and_moved_occurrence():
    days = calendar.fetch(SETTINGS, now=NOW)["days"]
    tomorrow, thursday = days[1], days[2]
    # Standup is moved to 11:00 and renamed on Wednesday only.
    assert ("11:00", "Standup (moved)") in titles(tomorrow)
    assert ("09:30", "Standup") not in titles(tomorrow)
    assert ("09:30", "Standup") in titles(thursday)
    # Gym is every Tue/Thu, but Thursday 12th is excluded (EXDATE).
    assert ("18:00", "Gym") in titles(days[0])
    assert all(e["title"] != "Gym" for e in thursday["events"])


def test_all_day_events_come_first_and_span_days():
    days = calendar.fetch(SETTINGS, now=NOW)["days"]
    tomorrow, thursday = days[1], days[2]
    assert titles(tomorrow)[0] == ("All day", "Bin day")  # weekly all-day series
    trip = thursday["events"][0]
    assert trip["title"] == "Trip to Manchester"
    assert trip["all_day"] and (trip["until"], trip["until_short"]) == ("Saturday", "Sat")
    assert trip["who"] == ["Sam"]
    # Listed once, on its first day, not repeated on Friday.
    assert all(e["title"] != "Trip to Manchester" for e in days[3]["events"])


def test_same_event_on_both_calendars_shows_once_with_both_names():
    tomorrow = calendar.fetch(SETTINGS, now=NOW)["days"][1]
    [dinner] = [e for e in tomorrow["events"] if e["title"] == "Flat dinner"]
    assert dinner["who"] == ["Alex", "Sam"]
    assert dinner["colours"] == ["#123456", calendar.PALETTE[1]]  # set colour, then default
    assert (dinner["start"], dinner["end"]) == ("19:00", "21:00")


def test_utc_event_shown_in_local_time():
    friday = calendar.fetch(SETTINGS, now=NOW)["days"][3]
    assert ("20:00", "Call with family") in titles(friday)  # 20:00Z is 20:00 GMT


def test_times_across_the_clocks_going_back():
    src = Source("Test", "#fff", "https://example.com/x", ics=ics("calendar_dst.ics"))
    saturday = datetime(2026, 10, 24, 6, 0, tzinfo=LONDON)  # BST; clocks go back Sunday 2am
    days = build([src], {"days": 3, "max_events": 30}, saturday)["days"]
    sat, sun, mon = (titles(d) for d in days)
    # Booked in London time: stays at 09:00 either side of the change.
    assert ("09:00", "Morning walk") in sat and ("09:00", "Morning walk") in mon
    # Booked in UTC: 12:00Z is 13:00 in BST, then 12:00 in GMT.
    assert ("13:00", "UTC sync") in sat
    assert ("12:00", "UTC sync") in sun
    # Floating time (no zone) means local time.
    assert ("13:00", "Floating lunch") in sun
    # New York is still on summer time that Monday: 09:00 EDT = 13:00 GMT.
    assert ("13:00", "New York call") in mon


def test_max_events_cuts_later_events_and_counts_them():
    data = calendar.fetch({**SETTINGS, "max_events": 3}, now=NOW)
    shown = [e for d in data["days"] for e in d["events"]]
    assert len(shown) == 3 and data["more"] > 0
    assert [d["label"] for d in data["days"]] == ["Today"]
    assert data["summary"][-1] == f"Plus {data['more']} more not shown."


def test_days_setting_limits_the_window():
    data = calendar.fetch({**SETTINGS, "days": 1}, now=NOW)
    assert [d["label"] for d in data["days"]] == ["Today"]


def test_empty_today_still_shown():
    data = calendar.fetch(SETTINGS, now=datetime(2026, 11, 16, 23, 0, tzinfo=LONDON))
    assert data["days"][0]["label"] == "Today"
    assert data["days"][0]["events"] == [] or data["days"][0]["events"][0]["all_day"]


def test_summary_lines_for_mirror():
    summary = calendar.fetch(SETTINGS, now=NOW)["summary"]
    assert summary[0].startswith("Today: Sam: Late shift (until 09:00); Alex: Standup")
    assert "Alex & Sam: Flat dinner (19:00-21:00)" in summary[1]
    assert "Sam: Trip to Manchester (all day until Saturday)" in summary[2]


def test_no_calendars_configured_is_not_an_error():
    data = calendar.fetch({"calendars": []}, now=NOW)
    assert data["days"] == [{"label": "Today", "date": "2026-11-10", "events": []}]
    assert "config.yaml" in data["notes"][0]


def test_one_calendar_failing_still_shows_the_other(monkeypatch):
    def flaky(url):
        if url == SECRET_B:
            raise urllib.error.URLError(f"could not reach {calendar.https_url(url)}")
        return ics(FILES[url])

    monkeypatch.setattr(calendar, "download", flaky)
    data = calendar.fetch(SETTINGS, now=NOW)
    assert data["notes"] == ["Couldn't load Sam's calendar"]
    assert ("14:30", "Dentist") in titles(data["days"][0])
    assert all(e["who"] == ["Alex"] for d in data["days"] for e in d["events"])


def test_failing_calendar_falls_back_to_its_last_good_copy(monkeypatch):
    calendar.fetch(SETTINGS, now=NOW)  # both fine: cached

    def gabe_down(url):
        if url == SECRET_B:
            raise TimeoutError("timed out")
        return ics(FILES[url])

    monkeypatch.setattr(calendar, "download", gabe_down)
    data = calendar.fetch(SETTINGS, now=NOW)
    assert data["notes"][0].startswith("Sam's calendar not updated since ")
    assert ("19:00", "Five-a-side") in titles(data["days"][0])


def test_all_calendars_failing_raises_without_the_links(monkeypatch):
    def down(url):
        raise urllib.error.HTTPError(url, 404, "Not Found", {}, None)

    monkeypatch.setattr(calendar, "download", down)
    with pytest.raises(RuntimeError) as err:
        calendar.fetch(SETTINGS, now=NOW)
    assert str(err.value) == "no calendars could be loaded (Alex: HTTP 404; Sam: HTTP 404)"


# ---- the links are secrets ----

SECRET_BITS = ["5ecre7t0ken", "abc123", "2222bbbbsecret", "1111aaaa", "calendar.google.com"]


def assert_no_secrets(text):
    for bit in SECRET_BITS:
        assert bit not in text, f"{bit!r} leaked into {text!r}"


@pytest.mark.parametrize(
    "error",
    [
        urllib.error.URLError(f"<urlopen error [Errno 8] nodename nor servname: {SECRET_A}>"),
        ValueError(f"unknown url type: {SECRET_B!r}"),
        OSError("bad path /calendar/ical/abc123%40group/private-5ecre7t0ken/basic.ics"),
        OSError("bad path /calendar/ical/abc123@group/private-5ecre7t0ken/basic.ics"),
        OSError("token private-5ecre7t0ken rejected"),
    ],
)
def test_errors_and_logs_never_contain_the_link(monkeypatch, caplog, error):
    def broken(url):
        raise error

    monkeypatch.setattr(calendar, "download", broken)
    caplog.set_level(logging.DEBUG)
    with pytest.raises(RuntimeError) as err:
        calendar.fetch(SETTINGS, now=NOW)
    assert_no_secrets(str(err.value))
    assert_no_secrets(caplog.text)


REAL_DOWNLOAD = calendar.download  # before the autouse fixture swaps it out


def test_real_urllib_errors_are_redacted():
    # A space in the link makes urllib refuse it before touching the network, and its
    # error message quotes the secret path back.
    url = "http://127.0.0.1:9/private-5ecre7t0ken/has space/basic.ics"
    with pytest.raises(Exception) as raw:
        REAL_DOWNLOAD(url)
    assert "5ecre7t0ken" in str(raw.value)  # urllib leaks it...
    assert_no_secrets(calendar.describe_error(raw.value, url))  # ...we don't


def test_data_sent_to_the_page_has_no_links():
    data = calendar.fetch(SETTINGS, now=NOW)
    assert_no_secrets(json.dumps(data))
    assert "url" not in json.dumps(data["people"])


def test_plain_http_refused_except_on_this_machine():
    with pytest.raises(ValueError, match="https"):
        REAL_DOWNLOAD("http://example.com/private.ics")


def test_webcal_links_become_https():
    assert calendar.https_url("webcal://example.com/a.ics") == "https://example.com/a.ics"
    assert calendar.https_url("https://example.com/a.ics") == "https://example.com/a.ics"


def test_bad_colours_and_half_filled_entries_are_ignored():
    sources = calendar.calendars(
        {
            "calendars": [
                {"name": "A", "url": "https://e.com/a", "colour": "red; background: url(x)"},
                {"name": "B"},  # no link yet
                "nonsense",
            ]
        }
    )
    assert [(s.name, s.colour) for s in sources] == [("A", calendar.PALETTE[0])]
