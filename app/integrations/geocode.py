import logging
import re
import time
from typing import Any

import requests


_COORDS_RE = re.compile(
    r"(-?\d+(?:\.\d+)?)\s*[,\s]\s*(-?\d+(?:\.\d+)?)"
)
_LAST_REQUEST_TS: float | None = None
_CACHE: dict[str, tuple[float, float, bool]] = {}


def parse_coordinates(text: str) -> tuple[float, float] | None:
    match = _COORDS_RE.search(text)
    if not match:
        return None
    lat = float(match.group(1))
    lon = float(match.group(2))
    return lat, lon


def format_coordinates(lat: float, lon: float) -> str:
    return f"{lat:.6f}, {lon:.6f}"


def _respect_delay(delay_sec: float) -> None:
    global _LAST_REQUEST_TS
    if _LAST_REQUEST_TS is None:
        _LAST_REQUEST_TS = time.monotonic()
        return
    elapsed = time.monotonic() - _LAST_REQUEST_TS
    if elapsed < delay_sec:
        time.sleep(delay_sec - elapsed)
    _LAST_REQUEST_TS = time.monotonic()


def _build_headers(user_agent: str, email: str | None) -> dict[str, str]:
    ua = user_agent
    if email:
        ua = f"{user_agent} ({email})"
    return {"User-Agent": ua}


def _is_portugal(country_code: str | None) -> bool:
    return (country_code or "").lower() == "pt"


def reverse_geocode_portugal(
    lat: float,
    lon: float,
    base_url: str,
    user_agent: str,
    email: str | None,
    delay_sec: float,
    logger: logging.Logger,
) -> bool:
    _respect_delay(delay_sec)
    url = f"{base_url.rstrip('/')}/reverse"
    params = {
        "format": "json",
        "lat": f"{lat}",
        "lon": f"{lon}",
        "zoom": 10,
        "addressdetails": 1,
    }
    headers = _build_headers(user_agent, email)
    response = requests.get(url, params=params, headers=headers, timeout=30)
    response.raise_for_status()
    data = response.json()
    address = data.get("address", {}) if isinstance(data, dict) else {}
    country_code = address.get("country_code")
    is_pt = _is_portugal(country_code)
    logger.debug(
        "Reverse geocode %s,%s -> country=%s in_pt=%s",
        lat,
        lon,
        country_code,
        is_pt,
    )
    return is_pt


def geocode_location_portugal(
    location: str,
    base_url: str,
    user_agent: str,
    email: str | None,
    delay_sec: float,
    logger: logging.Logger,
) -> tuple[float, float] | None:
    cache_key = location.strip().lower()
    if not cache_key:
        return None
    cached = _CACHE.get(cache_key)
    if cached:
        lat, lon, in_pt = cached
        return (lat, lon) if in_pt else None

    _respect_delay(delay_sec)
    url = f"{base_url.rstrip('/')}/search"
    params = {
        "q": f"{location}, Portugal",
        "format": "json",
        "limit": 1,
        "addressdetails": 1,
    }
    headers = _build_headers(user_agent, email)
    response = requests.get(url, params=params, headers=headers, timeout=30)
    response.raise_for_status()
    data: list[dict[str, Any]] = response.json()
    if not data:
        logger.debug("Geocode: no results for '%s'", location)
        _CACHE[cache_key] = (0.0, 0.0, False)
        return None

    first = data[0]
    lat = float(first["lat"])
    lon = float(first["lon"])
    address = first.get("address", {}) if isinstance(first, dict) else {}
    country_code = address.get("country_code")
    in_pt = _is_portugal(country_code)
    logger.debug(
        "Geocode '%s' -> %s,%s country=%s in_pt=%s",
        location,
        lat,
        lon,
        country_code,
        in_pt,
    )
    _CACHE[cache_key] = (lat, lon, in_pt)
    return (lat, lon) if in_pt else None
