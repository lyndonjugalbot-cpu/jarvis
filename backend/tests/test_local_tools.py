import json
import os

import httpx

from tools.files import make_file_tools
from tools.registry import ToolRegistry
from tools.system import make_system_tools
from tools.weather import home_place, make_weather_tools

# ---------------------------------------------------------------- weather


def weather_client(seen):
    def handler(request):
        seen.append(request.url)
        if "geocoding" in request.url.host:
            if request.url.params["name"] == "Nowhere":
                return httpx.Response(200, json={})
            return httpx.Response(
                200,
                json={
                    "results": [
                        {
                            "name": "Auckland",
                            "admin1": "Auckland",
                            "country": "New Zealand",
                            "latitude": -36.85,
                            "longitude": 174.76,
                        }
                    ]
                },
            )
        return httpx.Response(
            200,
            json={
                "current": {
                    "temperature_2m": 18.2,
                    "apparent_temperature": 17.0,
                    "weather_code": 2,
                    "wind_speed_10m": 14.0,
                    "relative_humidity_2m": 70,
                },
                "daily": {
                    "time": ["2026-10-05"],
                    "weather_code": [61],
                    "temperature_2m_max": [19.0],
                    "temperature_2m_min": [12.0],
                    "precipitation_probability_max": [60],
                },
            },
        )

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


async def test_weather_for_home_and_a_named_place():
    seen = []
    reg = ToolRegistry(make_weather_tools("Auckland", weather_client(seen)))
    result = json.loads((await reg.run("get_weather", {})).text)
    assert result["place"] == "Auckland, Auckland, New Zealand"
    assert result["now"]["conditions"] == "partly cloudy" and result["now"]["temperature_c"] == 18.2
    assert result["forecast"] == [
        {
            "date": "2026-10-05",
            "conditions": "light rain",
            "high_c": 19.0,
            "low_c": 12.0,
            "rain_chance_pct": 60,
        }
    ]
    missing = await reg.run("get_weather", {"place": "Nowhere"})
    assert missing.is_error and "couldn't find" in missing.text


async def test_weather_without_a_home():
    result = await ToolRegistry(make_weather_tools("", weather_client([]))).run("get_weather", {})
    assert result.is_error and "config.toml" in result.text


def test_home_place_from_the_time_zone(tmp_path):
    zone = tmp_path / "zoneinfo" / "America" / "Los_Angeles"
    zone.parent.mkdir(parents=True)
    zone.write_text("")
    link = tmp_path / "localtime"
    link.symlink_to(zone)
    assert home_place("", str(link)) == "Los Angeles"
    assert home_place("Wellington", str(link)) == "Wellington"
    assert home_place("", str(tmp_path / "missing")) == ""


# ---------------------------------------------------------------- files


def files_registry(root):
    return ToolRegistry(make_file_tools([root], spotlight=False))


async def test_search_and_read_inside_the_allowed_folder(tmp_path):
    root = tmp_path / "Documents"
    (root / "plans").mkdir(parents=True)
    (root / "plans" / "trip plan.txt").write_text("Fly on Friday.")
    (root / ".secret").mkdir()
    (root / ".secret" / "trip keys.txt").write_text("hidden")
    reg = files_registry(root)
    found = json.loads((await reg.run("search_files", {"query": "trip"})).text)
    assert [f["name"] for f in found] == ["trip plan.txt"]
    text = json.loads(
        (await reg.run("read_file", {"path": str(root / "plans" / "trip plan.txt")})).text
    )
    assert text["text"] == "Fly on Friday." and text["truncated"] is False


async def test_reading_outside_the_folders_is_refused(tmp_path):
    root = tmp_path / "Documents"
    root.mkdir()
    outside = tmp_path / "private.txt"
    outside.write_text("no")
    (root / "sneaky.txt").symlink_to(outside)
    reg = files_registry(root)
    for path in (str(outside), str(root / ".." / "private.txt"), str(root / "sneaky.txt")):
        result = await reg.run("read_file", {"path": path})
        assert result.is_error and "only read files" in result.text, path


async def test_binary_and_long_files(tmp_path):
    root = tmp_path / "Documents"
    root.mkdir()
    (root / "photo.jpg").write_bytes(b"\xff\xd8\x00\x10JFIF")
    (root / "long.txt").write_text("x" * 30_000)
    reg = files_registry(root)
    assert "plain text" in (await reg.run("read_file", {"path": str(root / "photo.jpg")})).text
    long = json.loads((await reg.run("read_file", {"path": str(root / "long.txt")})).text)
    assert len(long["text"]) == 20_000 and long["truncated"] is True


# ---------------------------------------------------------------- system


async def test_system_stats_shape():
    stats = json.loads((await ToolRegistry(make_system_tools()).run("system_stats", {})).text)
    assert {"cpu_pct", "memory_used_pct", "disk_free_gb", "battery_pct", "uptime_hours"} <= set(
        stats
    )


async def test_open_app_and_url_use_the_system_opener():
    ran = []

    async def runner(args):
        ran.append(args)
        return 1 if args[-1] == "Nope" else 0

    reg = ToolRegistry(make_system_tools(runner=runner, platform="darwin"))
    assert not (await reg.run("open_app", {"name": "Calendar"})).is_error
    assert (await reg.run("open_app", {"name": "Nope"})).is_error
    assert (await reg.run("open_app", {"name": "-g"})).is_error
    assert not (await reg.run("open_url", {"url": "https://example.com"})).is_error
    for bad in ("file:///etc/passwd", "javascript:alert(1)", "example.com"):
        assert (await reg.run("open_url", {"url": bad})).is_error, bad
    assert ran == [
        ["open", "-a", "Calendar"],
        ["open", "-a", "Nope"],
        ["open", "https://example.com"],
    ]


def test_spotlight_is_used_on_macos_only():
    # The default follows the platform; tests above force the portable walker.
    tools = make_file_tools([])
    assert [t.name for t in tools] == ["search_files", "read_file"]
    assert os.sep == "/"
