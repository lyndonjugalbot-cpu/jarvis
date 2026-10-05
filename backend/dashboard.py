"""Live data for the HUD dashboard: this computer's telemetry, which modules are ready, and where
home is (for the globe)."""

import asyncio
import logging
import socket
import time

import httpx
import psutil

from tools.weather import GEOCODE

log = logging.getLogger(__name__)


def telemetry(online: bool | None) -> dict:
    memory = psutil.virtual_memory()
    disk = psutil.disk_usage("/")
    battery = psutil.sensors_battery()
    return {
        "cpu": psutil.cpu_percent(interval=None),
        "memory": memory.percent,
        "disk": disk.percent,
        "battery": round(battery.percent) if battery else None,
        "charging": battery.power_plugged if battery else None,
        "network": online,
        "uptime_h": round((time.time() - psutil.boot_time()) / 3600, 1),
    }


async def internet_reachable() -> bool:
    def check() -> bool:
        try:
            socket.create_connection(("1.1.1.1", 53), timeout=1.5).close()
            return True
        except OSError:
            return False

    return await asyncio.to_thread(check)


async def module_rows(core, voice_state: str) -> list[dict]:
    rows = []
    cooling = core.router.status()["coolingDown"]
    for provider in core.providers:
        if provider.name in cooling:
            state = "cooling down"
        else:
            try:
                ready = await asyncio.wait_for(provider.available(), 10)
            except Exception:
                ready = False
            state = "online" if ready else "off"
            if ready and getattr(provider, "paid", False):
                state = "standby"
        rows.append({"name": provider.label, "state": state})
    rows.append({"name": "Context memory", "state": "active" if core.memory else "off"})
    google = core.google
    if google is not None:
        rows.append(
            {
                "name": "Google",
                "state": "connected"
                if google.connected
                else ("signed out" if google.configured else "not set up"),
            }
        )
    rows.append({"name": "Voice", "state": voice_state})
    return rows


async def locate_home(place: str) -> dict | None:
    if not place:
        return None
    try:
        async with httpx.AsyncClient(timeout=10) as http:
            response = await http.get(GEOCODE, params={"name": place, "count": 1, "format": "json"})
            hit = (response.json().get("results") or [None])[0]
    except (httpx.HTTPError, ValueError) as e:
        log.info("couldn't locate home for the globe: %s", e)
        return None
    if not hit:
        return None
    return {"name": hit["name"], "lat": hit["latitude"], "lon": hit["longitude"]}
