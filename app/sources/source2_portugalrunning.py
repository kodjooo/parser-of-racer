"""Источник 2 — portugalrunning.com (через WordPress REST API + per-event iCal).

История: помесячный обход DOM сломался (сайт убрал навигацию), затем перестал
работать и bulk-фид iCal (`/export-events/all/` → 500, ключ убрали со страницы).
Устойчивый способ сейчас — два машинных эндпоинта WordPress/EventON:

1) WP REST `/wp-json/wp/v2/ajde_events` — перечисление ВСЕХ событий
   (id, название с годом, ссылка). Постранично, стабильно.
2) Per-event iCal `/export-events/<id>_0/?key=<KEY>` — дата, локация, название
   по конкретному событию. Ключ (стабильный) есть в сыром HTML страницы события.

Логика (дёшево → дорого):
- Собрать все события через REST.
- Пред-фильтр без тяжёлых запросов: год в названии (текущий/следующий) +
  дедуп по имени против RACES (known_index) — отсекаем прошлое и известное.
- Для оставшихся кандидатов: per-event iCal → дата (будущее), локация
  (геокодинг, Португалия), затем запись.

Ссылка в таблицу — каноническая страница события portugalrunning.com (внешняя
регистрационная ссылка грузится на странице через JS и в сыром HTML отсутствует).
"""

import datetime
import html
import logging
import re

import requests

from app.integrations.geocode import format_coordinates, geocode_location_portugal
from app.integrations.url_normalize import normalize_url


_KEY_RE = re.compile(r"export-events/\d+_0/\?key=([a-f0-9]+)")
_YEAR_RE = re.compile(r"20\d{2}")
_ICS_FIELD = lambda name, text: (  # noqa: E731
    re.search(rf"^{name}[^:\r\n]*:(.+)$", text, re.MULTILINE)
)


def _clean_name(raw: str) -> str:
    name = html.unescape(raw or "")
    name = name.replace("–", "-").replace("—", "-")
    return re.sub(r"\s+", " ", name).strip()


def _clean_location(location: str) -> str:
    loc = location.replace("\\,", ",").replace("\\;", ";").strip()
    half = len(loc) // 2
    first, second = loc[:half].strip().strip(","), loc[half:].strip().strip(",")
    if first and first == second:
        return first
    return loc


def _fetch_all_events(rest_url: str, timeout_ms: int, logger: logging.Logger) -> list[dict]:
    events: list[dict] = []
    page = 1
    per_page = 100
    timeout = max(30, timeout_ms // 1000)
    while True:
        resp = requests.get(
            rest_url,
            params={"per_page": per_page, "page": page, "orderby": "date", "order": "desc"},
            timeout=timeout,
        )
        if resp.status_code == 400:
            # WP отдаёт 400, когда page > totalpages — нормальный конец пагинации
            break
        resp.raise_for_status()
        batch = resp.json()
        if not isinstance(batch, list) or not batch:
            break
        events.extend(batch)
        total_pages = int(resp.headers.get("X-WP-TotalPages", "0") or 0)
        if total_pages and page >= total_pages:
            break
        page += 1
    logger.info("source2 REST: получено событий=%s", len(events))
    return events


class _KeyCache:
    def __init__(self, fallback: str) -> None:
        self.key = fallback.strip() if fallback else ""

    def get(self, event_url: str, timeout: int, logger: logging.Logger) -> str:
        if self.key:
            return self.key
        try:
            html_text = requests.get(event_url, params={"nocache": "1"}, timeout=timeout).text
            match = _KEY_RE.search(html_text)
            if match:
                self.key = match.group(1)
                logger.info("source2: ключ iCal получен со страницы события")
        except requests.RequestException as exc:
            logger.warning("source2: не удалось получить ключ iCal: %s", exc)
        return self.key


def scrape_source2(
    rest_url: str,
    export_base: str,
    ical_key: str,
    timeout_ms: int,
    opencage_base_url: str,
    opencage_api_key: str,
    opencage_delay_sec: float,
    known_index,
    logger: logging.Logger,
) -> dict[str, tuple[str, str, str]]:
    results: dict[str, tuple[str, str, str]] = {}
    timeout = max(30, timeout_ms // 1000)

    today = datetime.date.today()
    allowed_years = {str(today.year), str(today.year + 1)}

    events = _fetch_all_events(rest_url, timeout_ms, logger)

    key_cache = _KeyCache(ical_key)
    skipped_year = skipped_known = skipped_past = skipped_pt = 0
    candidates = 0

    for event in events:
        name = _clean_name((event.get("title") or {}).get("rendered", ""))
        page_url = (event.get("link") or "").strip()
        event_id = event.get("id")
        if not name or not page_url or event_id is None:
            continue

        # Пред-фильтр по году в названии: отсекаем явно прошлогодние редакции.
        years = set(_YEAR_RE.findall(name))
        if years and not (years & allowed_years):
            skipped_year += 1
            continue

        # Дедуп по имени (имя + год) против RACES — без тяжёлых запросов.
        if known_index is not None and known_index.match_name(name):
            skipped_known += 1
            continue

        candidates += 1

        key = key_cache.get(page_url, timeout, logger)
        if not key:
            continue
        ics_url = f"{export_base.rstrip('/')}/{event_id}_0/"
        try:
            ics = requests.get(ics_url, params={"key": key}, timeout=timeout)
            ics.raise_for_status()
            ics_text = ics.text
        except requests.RequestException as exc:
            logger.warning("source2: per-event iCal не получен (%s): %s", event_id, exc)
            continue

        dt = _ICS_FIELD("DTSTART", ics_text)
        if not dt:
            continue
        digits = re.sub(r"\D", "", dt.group(1))[:8]
        try:
            event_date = datetime.date(int(digits[:4]), int(digits[4:6]), int(digits[6:8]))
        except (ValueError, IndexError):
            continue
        if event_date < today:
            skipped_past += 1
            continue

        loc_field = _ICS_FIELD("LOCATION", ics_text)
        location = _clean_location(loc_field.group(1)) if loc_field else ""
        if not location:
            logger.warning("source2: нет локации для %s", name)
            continue

        coords = geocode_location_portugal(
            location, opencage_base_url, opencage_api_key, opencage_delay_sec, logger
        )
        if not coords:
            skipped_pt += 1
            continue

        lat, lon = coords
        normalized = normalize_url(page_url)
        if normalized not in results:
            results[normalized] = (page_url, format_coordinates(lat, lon), name)

    logger.info(
        "source2: событий=%s пропущено(год=%s известных=%s прошлых=%s не_PT=%s) к_проверке=%s",
        len(events),
        skipped_year,
        skipped_known,
        skipped_past,
        skipped_pt,
        len(results),
    )
    return results
