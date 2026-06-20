"""Источник 2 — portugalrunning.com (через iCal-фид EventON).

Старый помесячный обход DOM сломался: сайт переделали (нет #evcal_next/#evcal_cur),
а список на странице показывает только текущий месяц. Полный календарь доступен
через экспорт-фид EventON:

    https://www.portugalrunning.com/export-events/all/?key=<KEY>

Фид (text/calendar) содержит ВСЕ события с названием (SUMMARY, с годом),
локацией (LOCATION), датой (DTSTART) и канонической ссылкой (URL).

Логика:
1) Получить key (из .env или со страницы календаря).
2) Скачать iCal, распарсить, отобрать будущие события.
3) Дедуп по названию (имя + год) через known_index — чтобы НЕ открывать
   страницы уже известных трасс.
4) Для новых: открыть карточку события, взять внешнюю регистрационную ссылку
   (как делал прежний скрипт), геокодировать локацию (OpenCage, Португалия).
"""

import datetime
import logging
import re

import requests
from playwright.sync_api import BrowserContext

from app.integrations.geocode import format_coordinates, geocode_location_portugal
from app.integrations.url_normalize import normalize_url
from app.utils.retry import run_with_retries


_KEY_RE = re.compile(r"export-events/[^\"']*?key=([a-f0-9]+)")


def _resolve_key(context: BrowserContext, page_url: str, timeout_ms: int, logger) -> str | None:
    page = context.new_page()
    page.set_default_timeout(timeout_ms)
    try:
        run_with_retries(
            lambda: page.goto(page_url, wait_until="domcontentloaded"),
            logger=logger,
            action_name="загрузка страницы для ключа iCal",
        )
        html = page.content()
    finally:
        page.close()
    match = _KEY_RE.search(html)
    return match.group(1) if match else None


def _parse_ical(text: str) -> list[dict[str, str]]:
    # Развёртка свёрнутых строк (RFC 5545: продолжение начинается с пробела/таба).
    lines: list[str] = []
    for raw in text.split("\n"):
        if raw[:1] in (" ", "\t") and lines:
            lines[-1] += raw[1:]
        else:
            lines.append(raw.rstrip("\r"))

    events: list[dict[str, str]] = []
    current: dict[str, str] | None = None
    for line in lines:
        if line == "BEGIN:VEVENT":
            current = {}
        elif line == "END:VEVENT":
            if current is not None:
                events.append(current)
            current = None
        elif current is not None and ":" in line:
            key, value = line.split(":", 1)
            key = key.split(";")[0]
            current[key] = value.replace("\\,", ",").replace("\\;", ";").strip()
    return events


def _event_date(event: dict[str, str]) -> datetime.date | None:
    value = event.get("DTSTART", "")[:8]
    try:
        return datetime.date(int(value[:4]), int(value[4:6]), int(value[6:8]))
    except (ValueError, IndexError):
        return None


def _clean_location(location: str) -> str:
    loc = location.strip()
    # EventON дублирует строку локации ("X, Y X, Y") — берём первую половину.
    half = len(loc) // 2
    first, second = loc[:half].strip().strip(","), loc[half:].strip().strip(",")
    if first and first == second:
        return first
    return loc


def scrape_source2(
    context: BrowserContext,
    ical_url: str,
    ical_key: str,
    page_url: str,
    months_ahead: int,
    reg_link_selector: str,
    timeout_ms: int,
    opencage_base_url: str,
    opencage_api_key: str,
    opencage_delay_sec: float,
    known_index,
    logger: logging.Logger,
) -> dict[str, tuple[str, str, str]]:
    results: dict[str, tuple[str, str, str]] = {}

    key = ical_key.strip() if ical_key else ""
    if not key:
        key = _resolve_key(context, page_url, timeout_ms, logger) or ""
        if not key:
            logger.error("Не удалось получить ключ iCal со страницы %s", page_url)
            return results
        logger.info("Ключ iCal получен со страницы")

    response = requests.get(ical_url, params={"key": key}, timeout=60)
    response.raise_for_status()
    events = _parse_ical(response.text)
    logger.info("iCal: всего событий в фиде=%s", len(events))

    today = datetime.date.today()
    cutoff = today + datetime.timedelta(days=months_ahead * 31) if months_ahead > 0 else None

    detail_page = context.new_page()
    detail_page.set_default_timeout(timeout_ms)
    try:
        future = 0
        skipped_known = 0
        for event in events:
            event_date = _event_date(event)
            if not event_date or event_date < today:
                continue
            if cutoff and event_date > cutoff:
                continue
            future += 1

            name = event.get("SUMMARY", "").strip()
            canon_url = event.get("URL", "").strip()
            location = _clean_location(event.get("LOCATION", ""))

            # Дедуп по названию (имя + год) — не открываем страницы известных трасс.
            if name and known_index is not None and known_index.match_name(name):
                skipped_known += 1
                continue

            if not location:
                logger.warning("Нет локации для события %s", name or canon_url)
                continue

            coords = geocode_location_portugal(
                location,
                opencage_base_url,
                opencage_api_key,
                opencage_delay_sec,
                logger,
            )
            if not coords:
                logger.debug("Событие вне Португалии: %s (%s)", name, location)
                continue

            # Внешняя регистрационная ссылка со страницы события (как раньше).
            table_url = canon_url
            if canon_url:
                try:
                    run_with_retries(
                        lambda: detail_page.goto(canon_url, wait_until="domcontentloaded"),
                        logger=logger,
                        action_name="загрузка карточки события",
                    )
                    link = detail_page.locator(reg_link_selector)
                    if link.count() > 0:
                        href = link.first.get_attribute("href")
                        if href:
                            table_url = href
                except Exception as exc:  # noqa: BLE001
                    logger.warning("Не удалось открыть карточку %s: %s", canon_url, exc)

            lat, lon = coords
            normalized = normalize_url(table_url)
            if normalized not in results:
                results[normalized] = (table_url, format_coordinates(lat, lon), name)

        logger.info(
            "iCal: будущих=%s пропущено_известных_по_имени=%s к проверке=%s",
            future,
            skipped_known,
            len(results),
        )
    finally:
        detail_page.close()

    return results
