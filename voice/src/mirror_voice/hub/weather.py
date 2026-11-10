"""Weather from Open-Meteo (https://open-meteo.com): free, no API key.

Settings (under `widgets.weather` in config.yaml):
    latitude, longitude   where to forecast for
    place                 label shown on the mirror (optional)
    rain_hours            how many hours ahead the rain outlook covers (default 6)
"""

from __future__ import annotations

import json
import urllib.parse
import urllib.request
from typing import Any

DEFAULT_REFRESH_MINUTES = 15.0

API_URL = "https://api.open-meteo.com/v1/forecast"

# WMO weather codes -> (description, icon name the display knows how to draw).
# https://open-meteo.com/en/docs (scroll to "WMO Weather interpretation codes")
CONDITIONS: dict[int, tuple[str, str]] = {
    0: ("Clear", "clear"),
    1: ("Mostly clear", "clear"),
    2: ("Partly cloudy", "partly-cloudy"),
    3: ("Overcast", "cloud"),
    45: ("Fog", "fog"),
    48: ("Freezing fog", "fog"),
    51: ("Light drizzle", "drizzle"),
    53: ("Drizzle", "drizzle"),
    55: ("Heavy drizzle", "drizzle"),
    56: ("Freezing drizzle", "drizzle"),
    57: ("Freezing drizzle", "drizzle"),
    61: ("Light rain", "rain"),
    63: ("Rain", "rain"),
    65: ("Heavy rain", "rain"),
    66: ("Freezing rain", "rain"),
    67: ("Freezing rain", "rain"),
    71: ("Light snow", "snow"),
    73: ("Snow", "snow"),
    75: ("Heavy snow", "snow"),
    77: ("Snow grains", "snow"),
    80: ("Light showers", "rain"),
    81: ("Showers", "rain"),
    82: ("Heavy showers", "rain"),
    85: ("Snow showers", "snow"),
    86: ("Heavy snow showers", "snow"),
    95: ("Thunderstorm", "thunder"),
    96: ("Thunderstorm with hail", "thunder"),
    99: ("Thunderstorm with hail", "thunder"),
}

RAIN_LIKELY = 50  # % chance at which we say rain is likely
RAIN_POSSIBLE = 20


def build_url(settings: dict[str, Any]) -> str:
    params = {
        "latitude": float(settings["latitude"]),
        "longitude": float(settings["longitude"]),
        "current": "temperature_2m,apparent_temperature,weather_code,is_day,wind_speed_10m",
        "hourly": "temperature_2m,precipitation_probability,weather_code",
        "daily": "weather_code,temperature_2m_max,temperature_2m_min,"
        "precipitation_probability_max,sunrise,sunset",
        "timezone": "auto",  # times come back in the location's local time
        "forecast_days": 2,  # so the rain outlook works late in the evening
        "wind_speed_unit": "mph",
    }
    return f"{API_URL}?{urllib.parse.urlencode(params)}"


def fetch(settings: dict[str, Any]) -> dict[str, Any]:
    """Download the forecast and boil it down to what the mirror shows."""
    req = urllib.request.Request(build_url(settings), headers={"User-Agent": "mirror-assistant"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        payload = json.load(resp)
    return parse(payload, settings)


def condition(code: int) -> tuple[str, str]:
    return CONDITIONS.get(code, ("Unknown", "cloud"))


def parse(payload: dict[str, Any], settings: dict[str, Any]) -> dict[str, Any]:
    """Turn an Open-Meteo response into the widget's data. Pure: no network."""
    current, hourly, daily = payload["current"], payload["hourly"], payload["daily"]
    rain_hours = int(settings.get("rain_hours", 6))

    text, icon = condition(int(current["weather_code"]))
    if icon == "clear" and not current.get("is_day", 1):
        icon = "clear-night"

    # Hourly times look like "2026-11-10T14:00"; current time like "2026-11-10T14:15".
    this_hour = current["time"][:13]
    start = next(
        (i for i, t in enumerate(hourly["time"]) if t[:13] >= this_hour),
        len(hourly["time"]),
    )
    hours = [
        {"time": t[11:16], "chance": int(chance or 0)}
        for t, chance in zip(
            hourly["time"][start : start + rain_hours],
            hourly["precipitation_probability"][start : start + rain_hours],
            strict=True,
        )
    ]

    today = current["time"][:10]
    day = daily["time"].index(today) if today in daily["time"] else 0

    return {
        "place": str(settings.get("place", "")),
        "temp": round(current["temperature_2m"]),
        "feels_like": round(current["apparent_temperature"]),
        "condition": text,
        "icon": icon,
        "wind_mph": round(current["wind_speed_10m"]),
        "high": round(daily["temperature_2m_max"][day]),
        "low": round(daily["temperature_2m_min"][day]),
        "sunrise": daily["sunrise"][day][11:16],
        "sunset": daily["sunset"][day][11:16],
        "rain": {
            "max_chance": max((h["chance"] for h in hours), default=0),
            "hours": hours,
            "summary": rain_summary(hours),
        },
    }


def rain_summary(hours: list[dict[str, Any]]) -> str:
    """One short line, e.g. "Rain likely from 14:00" or "Dry for the next 6 hours"."""
    if not hours:
        return ""
    for threshold, phrase in ((RAIN_LIKELY, "Rain likely"), (RAIN_POSSIBLE, "Chance of rain")):
        first = next((h for h in hours if h["chance"] >= threshold), None)
        if first:
            when = "now" if first is hours[0] else f"from {first['time']}"
            return f"{phrase} {when}"
    return f"Dry for the next {len(hours)} hours"
