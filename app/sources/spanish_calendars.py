"""Подтверждённые испанские календари: списки событий, без сбора цен и вариантов."""
import datetime as dt
import os
import re
import time
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit

import requests
from app.sources.spanish_structured import extract_events

APPROVED_SOURCES = [
    {"name": "Running.life", "url": "https://running.life/calendario-carreras/espana",
     "event_path_regex": r"^/es/carrera/", "adapter": "running_life"},
    {"name": "RockTheSport", "url": "https://web.rockthesport.com/es",
     "event_path_regex": r"^/es/event/", "adapter": "rockthesport"},
]
# Публичный идентификатор клиентского приложения, опубликован самим источником.
PUBLIC_WEB_KEY = "rts_public_web_2024_a8f3d9e1c4b7"


class CalendarPage(HTMLParser):
    def __init__(self):
        super().__init__()
        self.next_links = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "a" and "next" in attrs.get("rel", "").split():
            self.next_links.append(attrs.get("href", ""))


def source_client(session=None):
    if session is not None:
        return session
    client = requests.Session()
    # Источник видит настоящее имя сервиса; под браузер не маскируемся.
    client.headers['User-Agent'] = os.getenv('ES_HTTP_USER_AGENT') or 'RaceFinderMonitor/1.0 (+https://racefinder.es)'
    return client


def checked_response(response):
    response.raise_for_status()
    if response.status_code != 200:
        raise ValueError("Неожиданный статус источника: " + str(response.status_code))
    if len(response.content) > 4_000_000:
        raise ValueError("Слишком большой ответ источника")
    return response


def running_life(source, logger, max_pages=120, session=None):
    client = source_client(session)
    url = source["url"]
    origin = urlsplit(url)
    seen, events = set(), []
    while url:
        if url in seen:
            raise ValueError("Цикл пагинации Running.life; список не записывается")
        if len(seen) >= max_pages:
            raise ValueError("Достигнут лимит обхода; неполный список не записывается")
        seen.add(url)
        text = checked_response(client.get(url, timeout=30, allow_redirects=False)).text
        batch = [e for e in extract_events(text, url)
                 if urlsplit(e["url"]).hostname == origin.hostname
                 and re.search(source["event_path_regex"], urlsplit(e["url"]).path)]
        # Пустая страница может означать изменение разметки: не затираем прошлый список.
        if not batch:
            raise ValueError("Running.life: не найдены будущие испанские события JSON-LD")
        events.extend(batch)
        page = CalendarPage()
        page.feed(text)
        targets = set(urljoin(url, link) for link in page.next_links)
        if len(targets) > 1:
            raise ValueError("Running.life: неоднозначная пагинация")
        url = next(iter(targets), None)
        if url:
            target = urlsplit(url)
            if target.scheme != "https" or target.hostname != origin.hostname or target.path != origin.path:
                raise ValueError("Running.life: ссылка пагинации вышла за границы календаря")
            time.sleep(0.2)
    logger.info("Running.life: страниц=%s событий=%s", len(seen), len(events))
    return events


def rock_event(item, today):
    if item.get("countryId") != 65 or str(item.get("sport", "")).casefold() not in (
            "running", "running/atletismo", "running/athletics", "athletics", "trail", "obstacles"):
        return None
    name = str(item.get("title") or "").strip()
    slug = str(item.get("slug") or "")
    if not name or re.search(r"cancelad[ao]|cancelled|canceled", name, re.I):
        return None
    if not re.fullmatch(r"[a-zA-Z0-9_-]+", slug):
        raise ValueError("RockTheSport: неверный slug события")
    try:
        date = dt.date.fromisoformat(str(item.get("startedDateIso", ""))[:10])
    except ValueError as error:
        raise ValueError("RockTheSport: нет корректной даты события") from error
    if date < today:
        return None
    coords = ""
    try:
        lat, lon = float(item["latitude"]), float(item["longitude"])
        if -90 <= lat <= 90 and -180 <= lon <= 180:
            coords = f"{lat:.6f}, {lon:.6f}"
    except (KeyError, TypeError, ValueError):
        pass
    return {"name": name, "url": "https://web.rockthesport.com/es/event/" + slug,
            "date": date.isoformat(), "country": "Spain", "coords": coords,
            "region": "", "city": ""}


def rockthesport(source, logger, max_pages=120, session=None):
    client = source_client(session)
    today = dt.datetime.now(dt.timezone.utc).date()
    start = int(dt.datetime.combine(today, dt.time(), dt.timezone.utc).timestamp() * 1000)
    headers = {"X-API-Key": (os.getenv("ROCKTHESPORT_PUBLIC_API_KEY") or PUBLIC_WEB_KEY),
               "X-Requested-With": "XMLHttpRequest"}
    filters = {"kind": "country:65", "(a) orderBy": "data.dates.startedDateTimestamp",
               "(ge) data.dates.startedDateTimestamp": start}
    events, ids, expected = [], set(), None
    for number in range(1, max_pages + 1):
        response = checked_response(client.post(
            "https://publicservice.rockthesport.com/api/event/list",
            params={"pageNumber": number, "pageSize": 99}, json=filters,
            headers=headers, timeout=30, allow_redirects=False))
        payload = response.json()
        data = payload.get("data", {})
        items, pagination = data.get("items"), data.get("pagination", {})
        if not isinstance(items, list) or pagination.get("currentPage") != number:
            raise ValueError("RockTheSport: изменился формат календаря")
        total = pagination.get("totalItems")
        pages = pagination.get("totalPages")
        if not isinstance(total, int) or total < 0 or not isinstance(pages, int) or pages < 0:
            raise ValueError("RockTheSport: нет счётчика полноты")
        if expected is None:
            expected = total
        if total != expected or pages > max_pages:
            raise ValueError("RockTheSport: список изменился или превышен лимит обхода")
        for item in items:
            identity = str(item.get("id") or "")
            if not identity or identity in ids:
                raise ValueError("RockTheSport: повтор страницы или события; список не записывается")
            ids.add(identity)
            event = rock_event(item, today)
            if event:
                events.append(event)
        if number >= pages:
            if len(ids) != expected:
                raise ValueError("RockTheSport: получен неполный список")
            logger.info("RockTheSport: страниц=%s всего=%s беговых=%s", number, len(ids), len(events))
            return events
        time.sleep(0.2)
    raise ValueError("Достигнут лимит обхода; неполный список не записывается")
