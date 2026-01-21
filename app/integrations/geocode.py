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


def _is_portugal(country_code: str | None) -> bool:
    return (country_code or "").lower() == "pt"


def reverse_geocode_portugal(
    lat: float,
    lon: float,
    base_url: str,
    api_key: str,
    delay_sec: float,
    logger: logging.Logger,
) -> bool:
    _respect_delay(delay_sec)
    url = f"{base_url.rstrip('/')}/json"
    params = {
        "q": f"{lat},{lon}",
        "key": api_key,
        "no_annotations": 1,
        "limit": 1,
    }
    response = requests.get(url, params=params, timeout=30)
    response.raise_for_status()
    data = response.json()
    results = data.get("results", []) if isinstance(data, dict) else []
    if not results:
        logger.debug("Reverse geocode: no results for %s,%s", lat, lon)
        return False
    components = results[0].get("components", {})
    country_code = components.get("country_code")
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
    api_key: str,
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
    url = f"{base_url.rstrip('/')}/json"
    params = {
        "q": location,
        "key": api_key,
        "no_annotations": 1,
        "limit": 1,
        "countrycode": "pt",
    }
    response = requests.get(url, params=params, timeout=30)
    response.raise_for_status()
    data: dict[str, Any] = response.json()
    results = data.get("results", []) if isinstance(data, dict) else []
    if not results:
        logger.debug("Geocode: no results for '%s'", location)
        _CACHE[cache_key] = (0.0, 0.0, False)
        return None

    first = results[0]
    geometry = first.get("geometry", {})
    lat = float(geometry["lat"])
    lon = float(geometry["lng"])
    components = first.get("components", {}) if isinstance(first, dict) else {}
    country_code = components.get("country_code")
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
