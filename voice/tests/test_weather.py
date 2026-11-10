import json
import urllib.parse
from pathlib import Path

import pytest
from mirror_voice.hub import weather

FIXTURE = Path(__file__).parent / "fixtures" / "open_meteo_leeds.json"
SETTINGS = {"latitude": 53.7997, "longitude": -1.5492, "place": "Leeds", "rain_hours": 6}


@pytest.fixture
def payload():
    return json.loads(FIXTURE.read_text())


def test_parse_current_and_today(payload):
    w = weather.parse(payload, SETTINGS)
    assert w["place"] == "Leeds"
    assert w["temp"] == 6 and w["feels_like"] == 4
    assert (w["condition"], w["icon"]) == ("Light rain", "rain")
    assert (w["high"], w["low"]) == (8, 4)
    assert (w["sunrise"], w["sunset"]) == ("07:23", "16:16")
    json.dumps(w)  # must be JSON-able for the display


def test_rain_outlook_starts_at_current_hour(payload):
    rain = weather.parse(payload, SETTINGS)["rain"]  # fixture "now" is 10:45
    assert [h["time"] for h in rain["hours"]] == [
        "10:00",
        "11:00",
        "12:00",
        "13:00",
        "14:00",
        "15:00",
    ]
    assert [h["chance"] for h in rain["hours"]] == [15, 25, 40, 65, 80, 55]
    assert rain["max_chance"] == 80
    assert rain["summary"] == "Rain likely from 13:00"


def test_rain_outlook_runs_past_midnight(payload):
    payload["current"]["time"] = "2026-11-10T22:30"
    hours = weather.parse(payload, SETTINGS)["rain"]["hours"]
    assert [h["time"] for h in hours] == ["22:00", "23:00", "00:00", "01:00", "02:00", "03:00"]


def test_clear_at_night_uses_moon(payload):
    payload["current"].update(weather_code=0, is_day=0)
    assert weather.parse(payload, SETTINGS)["icon"] == "clear-night"


def test_unknown_code_does_not_crash(payload):
    payload["current"]["weather_code"] = 42
    assert weather.parse(payload, SETTINGS)["condition"] == "Unknown"


@pytest.mark.parametrize(
    ("chances", "summary"),
    [
        ([0, 5, 10], "Dry for the next 3 hours"),
        ([60, 70, 10], "Rain likely now"),
        ([10, 30, 40], "Chance of rain from 11:00"),
        ([10, 30, 55], "Rain likely from 12:00"),
        ([], ""),
    ],
)
def test_rain_summary(chances, summary):
    hours = [{"time": f"{10 + i}:00", "chance": c} for i, c in enumerate(chances)]
    assert weather.rain_summary(hours) == summary


def test_url_asks_for_the_configured_place():
    query = urllib.parse.parse_qs(urllib.parse.urlparse(weather.build_url(SETTINGS)).query)
    assert query["latitude"] == ["53.7997"] and query["longitude"] == ["-1.5492"]
    assert "precipitation_probability" in query["hourly"][0]
