"""Weather from Open-Meteo: free, no API key, no account."""

import os
from typing import Annotated

import httpx
from pydantic import Field

from tools.registry import ToolError, ToolSpec, tool

GEOCODE = "https://geocoding-api.open-meteo.com/v1/search"
CURRENT = "temperature_2m,apparent_temperature,weather_code,wind_speed_10m,relative_humidity_2m"
DAILY = "weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max"
FORECAST = "https://api.open-meteo.com/v1/forecast"

# WMO weather codes as Open-Meteo reports them
CONDITIONS = {
    0: "clear", 1: "mostly clear", 2: "partly cloudy", 3: "overcast", 45: "fog",
    48: "freezing fog", 51: "light drizzle", 53: "drizzle", 55: "heavy drizzle",
    56: "freezing drizzle", 57: "freezing drizzle", 61: "light rain", 63: "rain",
    65: "heavy rain", 66: "freezing rain", 67: "freezing rain", 71: "light snow", 73: "snow",
    75: "heavy snow", 77: "snow grains", 80: "light showers", 81: "showers",
    82: "heavy showers", 85: "snow showers", 86: "heavy snow showers", 95: "thunderstorm",
    96: "thunderstorm with hail", 99: "thunderstorm with heavy hail",
}  # fmt: skip


def home_place(configured: str, localtime: str = "/etc/localtime") -> str:
    """The configured home, else the city in this computer's time zone (e.g. Pacific/Auckland)."""
    if configured:
        return configured
    try:
        zone = os.readlink(localtime).split("zoneinfo/", 1)[1]
    except (OSError, IndexError):
        return ""
    return zone.rsplit("/", 1)[-1].replace("_", " ") if "/" in zone else ""


def make_weather_tools(home: str, http: httpx.AsyncClient | None = None) -> list[ToolSpec]:
    client = http or httpx.AsyncClient(timeout=15)
    places: dict[str, dict] = {}

    async def fetch(url: str, params: dict) -> dict:
        try:
            response = await client.get(url, params=params)
            response.raise_for_status()
            return response.json()
        except httpx.HTTPError as e:
            raise ToolError(f"Couldn't reach the weather service: {e}") from e

    async def locate(name: str) -> dict:
        key = name.lower()
        if key not in places:
            found = await fetch(
                GEOCODE, {"name": name, "count": 1, "language": "en", "format": "json"}
            )
            if not found.get("results"):
                raise ToolError(f'I couldn\'t find a place called "{name}".')
            places[key] = found["results"][0]
        return places[key]

    @tool()
    async def get_weather(
        place: Annotated[str, Field(description="City or town; leave empty for home")] = "",
        days: Annotated[int, Field(ge=1, le=7, description="Days of forecast")] = 1,
    ) -> dict:
        """Current weather and the forecast for a place (home when no place is given)."""
        name = place.strip() or home
        if not name:
            raise ToolError(
                "I don't know where home is: name a place, or set [user] location in config.toml."
            )
        loc = await locate(name)
        data = await fetch(
            FORECAST,
            {
                "latitude": loc["latitude"],
                "longitude": loc["longitude"],
                "current": CURRENT,
                "daily": DAILY,
                "timezone": "auto",
                "forecast_days": days,
            },
        )
        now, daily = data["current"], data["daily"]
        return {
            "place": ", ".join(
                p for p in (loc["name"], loc.get("admin1"), loc.get("country")) if p
            ),
            "now": {
                "conditions": CONDITIONS.get(now["weather_code"], "unknown"),
                "temperature_c": now["temperature_2m"],
                "feels_like_c": now["apparent_temperature"],
                "wind_kmh": now["wind_speed_10m"],
                "humidity_pct": now["relative_humidity_2m"],
            },
            "forecast": [
                {
                    "date": day,
                    "conditions": CONDITIONS.get(code, "unknown"),
                    "high_c": high,
                    "low_c": low,
                    "rain_chance_pct": rain,
                }
                for day, code, high, low, rain in zip(
                    daily["time"],
                    daily["weather_code"],
                    daily["temperature_2m_max"],
                    daily["temperature_2m_min"],
                    daily["precipitation_probability_max"],
                    strict=False,
                )
            ],
        }

    return [get_weather]
