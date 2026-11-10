from datetime import datetime
from zoneinfo import ZoneInfo

import pytest
from mirror_voice import context
from mirror_voice.context import Route, live_info, route

TZ = ZoneInfo("Europe/London")
NOW = datetime(2026, 11, 10, 8, 0, tzinfo=TZ)  # a Tuesday morning


def weather_data():
    return {
        "place": "Leeds",
        "temp": 7,
        "feels_like": 4,
        "condition": "Light rain",
        "icon": "rain",
        "wind_mph": 12,
        "high": 9,
        "low": 3,
        "sunrise": "07:20",
        "sunset": "16:18",
        "rain": {"max_chance": 70, "hours": [], "summary": "Rain likely from 10:00"},
    }


def bus_data(now=NOW):
    def dep(route, dest, minutes, live=True):
        at = now.timestamp() + minutes * 60
        return {
            "route": route,
            "destination": dest,
            "expected": round(at),
            "time": datetime.fromtimestamp(at, TZ).strftime("%H:%M"),
            "minutes": minutes,
            "live": live,
        }

    return {
        "stop": "Corner Shop",
        "departures": [
            dep("24", "Holt Park", -3),  # left since the last fetch
            dep("24", "Holt Park", 4),
            dep("X9", "Leeds City Bus Stn", 6),
            dep("51", "Moortown", 11, live=False),
            dep("24", "Holt Park", 19),
            dep("X9", "Leeds City Bus Stn", 45),
        ],
        "horizon_minutes": 90,
        "summary": "Next 24 to Holt Park in 4 minutes (live)",
    }


def event(title, start, end, who, all_day=False):
    return {
        "title": title,
        "time": "All day" if all_day else start,
        "start": "" if all_day else start,
        "end": "" if all_day else end,
        "all_day": all_day,
        "until": "",
        "until_short": "",
        "who": who,
        "colours": [],
    }


def calendar_data():
    return {
        "days": [
            {
                "label": "Today",
                "date": "2026-11-10",
                "events": [
                    event("Early swim", "06:30", "07:30", ["Sam"]),  # already over
                    event("Standup", "09:30", "09:45", ["Alex"]),
                    event("Dentist", "14:00", "14:30", ["Sam"]),
                ],
            },
            {
                "label": "Tomorrow",
                "date": "2026-11-11",
                "events": [
                    event("Bins out", "", "", ["Alex", "Sam"], all_day=True),
                    event("Five-a-side", "19:00", "20:00", ["Sam"]),
                ],
            },
            {
                "label": "Thursday",
                "date": "2026-11-12",
                "events": [event("SECRET THURSDAY THING", "10:00", "11:00", ["Alex"])],
            },
        ],
        "more": 0,
        "people": [{"name": "Alex", "colour": "#fff"}, {"name": "Sam", "colour": "#000"}],
        "notes": [],
        "summary": [],
    }


def ok(data, updated=None):
    return {"status": "ok", "data": data, "updated": updated or NOW.timestamp() - 60}


def board(**overrides):
    b = {
        "weather": ok(weather_data()),
        "bus": ok(bus_data()),
        "calendar": ok(calendar_data()),
    }
    b.update(overrides)
    return b


def tokens(text: str) -> int:
    """Rough token count: Llama tokenisers average ~4 characters a token in English."""
    return len(text) // 4 + 1


# ---------------------------------------------------------------- routing ----


@pytest.mark.parametrize(
    "said",
    [
        "Do I need a coat?",
        "Is it going to RAIN later",
        "should i take an umbrella",
        "Is it cold outside, Robin?",
        "what's the weather like",
    ],
)
def test_weather_words(said):
    assert route(said, board()) == Route(weather=True)


@pytest.mark.parametrize(
    "said",
    [
        "When's the next bus into town?",
        "what time's the next 24",
        "Am I going to be late for the X9?",
        "next one to holt park?",
    ],
)
def test_bus_words_including_routes_and_destinations_from_the_data(said):
    assert route(said, board()).bus


@pytest.mark.parametrize(
    "said",
    ["What's my day like?", "am I busy", "any meetings?", "What's on my calendar", "plans?"],
)
def test_calendar_words(said):
    r = route(said, board())
    assert r.calendar and not r.weather and not r.bus and r.people == ()


def test_when_words_alone_mean_the_calendar():
    assert route("what about tomorrow", board()) == Route(calendar=True)
    assert route("anything tonight?", board()) == Route(calendar=True)


def test_when_words_dont_drag_the_calendar_into_other_questions():
    assert route("do I need a coat today", board()) == Route(weather=True)


def test_a_calendar_name_scopes_to_that_person():
    r = route("What's Sam up to tomorrow?", board())
    assert r.calendar and r.people == ("Sam",)
    assert route("is alex free, and SAM?", board()).people == ("Alex", "Sam")


@pytest.mark.parametrize(
    "said",
    [
        "Give me a rundown",
        "morning briefing please",
        "Morning brief!",
        "brief me",
        "Catch me up, Robin",
        "whats going on",
        "What’s happening today?",  # curly apostrophe
    ],
)
def test_briefing_phrases_get_everything(said):
    r = route(said, board())
    assert r.briefing and r.weather and r.bus and r.calendar


@pytest.mark.parametrize(
    "said",
    ["Tell me a joke", "how do I look?", "what should I have for tea", "stop it", "", "!!!"],
)
def test_anything_else_is_just_the_time(said):
    assert route(said, board()) == Route()
    assert live_info(said, board(), NOW) == "Now: Tuesday 10 November, 08:00."


def test_word_boundaries():
    assert route("I'm training for a race", board()) == Route()  # not "rain"
    assert route("what's the hotel called", board()) == Route()  # not "hot"
    assert route("the 245 is a funny number", board()) == Route()  # not route 24


def test_keyword_lists_are_easy_to_extend(monkeypatch):
    monkeypatch.setattr(context, "WEATHER_WORDS", [*context.WEATHER_WORDS, "parky"])
    assert route("it's a bit parky", board()).weather


# ----------------------------------------------------------------- blocks ----


def test_time_line_is_always_first():
    info = live_info("do I need a coat", board(), NOW)
    assert info.splitlines()[0] == "Now: Tuesday 10 November, 08:00."


def test_weather_block():
    info = live_info("do I need a coat", board(), NOW)
    assert info.splitlines()[1] == (
        "Weather in Leeds: 7C (feels 4), light rain, wind 12 mph, today 3-9C, "
        "rain likely from 10:00."
    )
    assert "Bus" not in info and "Calendar" not in info


def test_bus_block_counts_down_from_now_and_skips_buses_already_gone():
    info = live_info("next bus?", board(), NOW)
    assert info.splitlines()[1] == (
        "Buses from Corner Shop: 24 to Holt Park 4 min; X9 to Leeds City Bus Stn 6 min; "
        "51 to Moortown 11 min (timetable); 24 to Holt Park 19 min."
    )


def test_bus_times_follow_the_clock_between_fetches():
    later = datetime(2026, 11, 10, 8, 5, tzinfo=TZ)
    line = context.bus_line(ok(bus_data()), later, count=2)
    # The 24 was due a minute ago but is tracked live, so it may still be coming.
    assert (
        line == "Buses from Corner Shop: 24 to Holt Park due now; X9 to Leeds City Bus Stn 1 min."
    )
    much_later = datetime(2026, 11, 10, 8, 11, 30, tzinfo=TZ)
    line = context.bus_line(ok(bus_data()), much_later, count=2)
    # The timetabled 51 (no live position) is dropped once its time has passed.
    assert line == "Buses from Corner Shop: 24 to Holt Park 7 min; X9 to Leeds City Bus Stn 08:45."


def test_calendar_is_today_and_tomorrow_only():
    info = live_info("what's my day like", board(), NOW)
    assert "SECRET THURSDAY THING" not in info
    assert "Early swim" not in info  # finished before now
    assert info.splitlines()[1:] == [
        "Calendar (Alex, Sam):",
        "Today: Alex: Standup (09:30-09:45); Sam: Dentist (14:00-14:30).",
        "Tomorrow: Alex & Sam: Bins out (all day); Sam: Five-a-side (19:00-20:00).",
    ]


def test_calendar_scoped_to_one_person():
    info = live_info("what's Alex up to tomorrow", board(), NOW)
    assert info.splitlines()[1:] == [
        "Calendar (Alex):",
        "Today: Standup (09:30-09:45).",
        "Tomorrow: Bins out (all day).",
    ]


def test_calendar_with_nothing_on():
    cal = calendar_data()
    cal["days"] = [{"label": "Today", "date": "2026-11-10", "events": []}]
    info = live_info("am I busy", board(calendar=ok(cal)), NOW)
    assert info.splitlines()[2:] == ["Today: nothing on.", "Tomorrow: nothing on."]


def test_calendar_caps_events_and_long_titles():
    cal = calendar_data()
    cal["days"][0]["events"] = [
        event(
            f"Meeting number {i} with a very long title indeed, really", "10:00", "11:00", ["Sam"]
        )
        for i in range(7)
    ]
    today = live_info("today's plans", board(calendar=ok(cal)), NOW).splitlines()[2]
    assert today.endswith("; +3 more.")
    assert today.count("…") == context.MAX_EVENTS_PER_DAY


def test_calendar_says_when_the_screen_cut_events_off():
    cal = calendar_data()
    cal["days"] = cal["days"][:2]
    cal["more"] = 2
    info = live_info("what about tomorrow", board(calendar=ok(cal)), NOW)
    assert info.endswith("Maybe more not listed.")


def test_calendar_notes_about_a_missing_person_are_passed_on():
    cal = calendar_data()
    cal["notes"] = ["Couldn't load Sam's calendar"]
    assert "(Couldn't load Sam's calendar)" in live_info("my day?", board(calendar=ok(cal)), NOW)
    assert "Couldn't load" not in live_info("is Alex free", board(calendar=ok(cal)), NOW)


def test_briefing_has_everything_and_is_compact():
    info = live_info("give me a rundown", board(), NOW)
    lines = info.splitlines()
    assert lines[0].startswith("Now:")
    assert lines[1].startswith("Weather")
    assert "Calendar" in info and "Tomorrow:" in info
    assert lines[-1].count(";") == context.BUSES_IN_BRIEFING - 1  # three buses
    assert tokens(info) < 150


def test_every_block_is_short():
    for said in ["coat?", "next bus", "my day", "what's Sam doing tomorrow", "tell me a joke"]:
        assert tokens(live_info(said, board(), NOW)) < 100, said


# ------------------------------------------------------------ stale data ----


def test_stale_widgets_say_when_they_last_updated():
    at = datetime(2026, 11, 10, 7, 15, tzinfo=TZ).timestamp()
    stale = {"status": "stale", "data": weather_data(), "updated": at}
    info = live_info("coat?", board(weather=stale), NOW)
    assert info.splitlines()[1].endswith("(not updated since 07:15)")

    stale_cal = {"status": "stale", "data": calendar_data(), "updated": at}
    assert "Calendar (Alex, Sam): (not updated since 07:15)" in live_info(
        "my day", board(calendar=stale_cal), NOW
    )


def test_stale_from_yesterday_names_the_day():
    at = datetime(2026, 11, 9, 22, 0, tzinfo=TZ).timestamp()
    stale = {"status": "stale", "data": weather_data(), "updated": at}
    assert "(not updated since Mon 22:00)" in live_info("coat?", board(weather=stale), NOW)


def test_failed_or_missing_widgets_are_unavailable_never_invented():
    broken = {"status": "error", "data": None, "updated": None}
    pending = {"status": "pending", "data": None, "updated": None}
    info = live_info("rundown", {"weather": broken, "bus": pending}, NOW)
    # No calendar widget configured at all: left out rather than "unavailable".
    assert info.splitlines()[1:] == ["Weather: unavailable.", "Buses: unavailable."]


def test_stale_buses_that_have_all_gone_are_unavailable():
    old = NOW.timestamp() - 3600
    stale = {"status": "stale", "data": bus_data(datetime.fromtimestamp(old, TZ)), "updated": old}
    assert live_info("next bus", board(bus=stale), NOW).splitlines()[1] == "Buses: unavailable."


def test_no_buses_in_fresh_data():
    data = {**bus_data(), "departures": []}
    line = live_info("next bus", board(bus=ok(data)), NOW).splitlines()[1]
    assert line == "Buses from Corner Shop: none in the next 90 min."


def test_no_hub_means_just_the_time():
    for said in ["give me a rundown", "do I need a coat", "tell me a joke"]:
        assert live_info(said, None, NOW) == "Now: Tuesday 10 November, 08:00."
        assert live_info(said, {}, NOW) == "Now: Tuesday 10 November, 08:00."


def test_a_named_route_or_destination_narrows_the_buses():
    assert route("when's the next 24?", board()).buses == ("24",)
    line = live_info("when's the next 24?", board(), NOW).splitlines()[1]
    assert line == "Buses from Corner Shop: 24 to Holt Park 4 min; 24 to Holt Park 19 min."
    line = live_info("bus to moortown?", board(), NOW).splitlines()[1]
    assert line == "Buses from Corner Shop: 51 to Moortown 11 min (timetable)."


def test_into_town_uses_the_buses_marked_as_going_there():
    data = bus_data()
    for dep in data["departures"]:
        dep["into_town"] = "Leeds" in dep["destination"]
    line = live_info("When's the next bus into town?", board(bus=ok(data)), NOW).splitlines()[1]
    assert line == (
        "Buses into town from Corner Shop: X9 to Leeds City Bus Stn 6 min; "
        "X9 to Leeds City Bus Stn 08:45."
    )
    # Without widgets.bus.town nothing is marked, so every bus is listed.
    line = live_info("next bus into town?", board(), NOW).splitlines()[1]
    assert line.startswith("Buses from Corner Shop: 24 to Holt Park 4 min;")


def test_into_town_when_none_are_coming():
    data = bus_data()
    for dep in data["departures"]:
        dep["into_town"] = dep["route"] == "24" and dep["minutes"] < 0  # only one, gone
    line = live_info("bus into town?", board(bus=ok(data)), NOW).splitlines()[1]
    assert line == "Buses into town from Corner Shop: none in the next few departures."


def test_a_route_that_isnt_coming_is_said_not_swapped():
    r = route("what time's the next 33", board())
    assert r.bus and r.buses == ("33",)
    line = live_info("what time's the next 33", board(), NOW).splitlines()[1]
    assert line.startswith("Buses from Corner Shop: no 33 listed; others: 24 to Holt Park 4 min;")


def test_numbers_that_arent_routes():
    assert route("is it dry for the next 6 hours", board()) == Route(weather=True)
    assert route("tell me the 3 best films", board()) == Route()


def test_someone_without_a_calendar_never_gets_someone_elses_plans():
    info = live_info("what's Jo up to tomorrow?", board(), NOW, people=["Alex", "Sam", "Jo"])
    assert info.splitlines()[1:] == ["No calendar for Jo: you can't see their plans."]
    both = live_info("are Jo and Sam free?", board(), NOW, people=["Jo"]).splitlines()[1:]
    assert both[0] == "No calendar for Jo: you can't see their plans."
    assert both[1] == "Calendar (Sam):"


def test_add_to_question_puts_the_note_after_the_question():
    assert context.add_to_question("coat?", "Now: x.") == "coat?\n\n[Live info]\nNow: x."
    assert context.add_to_question("coat?", "") == "coat?"
