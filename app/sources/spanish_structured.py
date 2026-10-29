"""Ограниченный обход согласованных источников с Event JSON-LD; без обхода защит."""
import datetime as dt
from html.parser import HTMLParser
import json
import re
from urllib.parse import urljoin, urlsplit
from xml.etree import ElementTree as ET
import requests


class Page(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links = []
        self.blocks = []
        self.current = None

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'a' and attrs.get('href'):
            self.links.append(attrs['href'])
        if tag == 'script' and attrs.get('type', '').lower() == 'application/ld+json':
            self.current = []

    def handle_data(self, data):
        if self.current is not None:
            self.current.append(data)

    def handle_endtag(self, tag):
        if tag == 'script' and self.current is not None:
            self.blocks.append(''.join(self.current))
            self.current = None


def walk_json(value):
    if isinstance(value, list):
        for item in value:
            yield from walk_json(item)
    elif isinstance(value, dict):
        types = value.get('@type', [])
        if isinstance(types, str):
            types = [types]
        if any(t in ('Event', 'SportsEvent') for t in types):
            yield value
        for item in value.values():
            if isinstance(item, (dict, list)):
                yield from walk_json(item)


def extract_events(html, page_url, today=None):
    today = today or dt.datetime.now(dt.timezone.utc).date()
    page = Page()
    page.feed(html)
    events = []
    for block in page.blocks:
        try:
            data = json.loads(block)
        except (ValueError, TypeError):
            continue
        for item in walk_json(data):
            try:
                date = dt.date.fromisoformat(str(item.get('startDate', ''))[:10])
            except ValueError:
                continue
            if date < today or str(item.get('eventStatus', '')).endswith('EventCancelled'):
                continue
            location = item.get('location') or {}
            if isinstance(location, list):
                location = location[0] if location else {}
            if not isinstance(location, dict):
                continue
            address = location.get('address') or {}
            if not isinstance(address, dict):
                continue
            country = address.get('addressCountry') or ''
            if isinstance(country, dict):
                country = country.get('name') or country.get('identifier', '')
            # Недостаточно домена .es: страну должен подтверждать сам источник.
            if str(country).strip().casefold() not in ('es', 'esp', 'spain', 'españa', 'espana'):
                continue
            url = urljoin(page_url, str(item.get('url') or page_url))
            if urlsplit(url).scheme not in ('http', 'https'):
                continue
            name = str(item.get('name') or '').strip()
            if not name:
                continue
            coords = ''
            geo = location.get('geo') or {}
            try:
                lat, lon = float(geo['latitude']), float(geo['longitude'])
                if -90 <= lat <= 90 and -180 <= lon <= 180:
                    coords = f'{lat:.6f}, {lon:.6f}'
            except (KeyError, TypeError, ValueError):
                pass
            events.append({'url': url, 'name': name, 'date': date.isoformat(),
                           'coords': coords, 'country': 'Spain',
                           'region': str(address.get('addressRegion') or ''),
                           'city': str(address.get('addressLocality') or '')})
    return events


def validate_source(source):
    if not isinstance(source, dict) or not source.get('name') or not source.get('url') or not source.get('event_path_regex'):
        raise ValueError('Для источника нужны name, url и event_path_regex')
    url = urlsplit(source['url'])
    if url.scheme != 'https' or not url.hostname or url.username or url.password:
        raise ValueError('Источник должен иметь публичный HTTPS URL без пароля')
    re.compile(source['event_path_regex'])


def scrape_source(source, logger, max_pages=50, session=None):
    validate_source(source)
    adapter = source.get('adapter')
    if adapter:
        from app.sources.spanish_calendars import APPROVED_SOURCES, running_life, rockthesport
        approved = next((s for s in APPROVED_SOURCES if s['adapter'] == adapter), None)
        if not approved or source['url'] != approved['url']:
            raise ValueError('Адаптер разрешён только для подтверждённого источника')
        return {'running_life': running_life, 'rockthesport': rockthesport}[adapter](
            source, logger, max_pages=max_pages, session=session)
    client = session or requests.Session()
    root = source['url']
    host = urlsplit(root).hostname
    queue = [root]
    seen = set()
    events = []
    pattern = re.compile(source['event_path_regex'])
    while queue and len(seen) < max_pages:
        url = queue.pop(0)
        if url in seen or urlsplit(url).hostname != host:
            continue
        seen.add(url)
        response = client.get(url, timeout=25, allow_redirects=False)
        # Редиректы, 403/429 и CAPTCHA не обходятся автоматически.
        if response.status_code != 200:
            response.raise_for_status()
            raise ValueError(f'Источник вернул редирект/неожиданный статус: {response.status_code}')
        if len(response.content) > 4_000_000:
            raise ValueError('Слишком большая страница источника')
        text = response.text
        if text.lstrip().startswith('<?xml') or '<urlset' in text or '<sitemapindex' in text:
            tree = ET.fromstring(text)
            sitemap_index = tree.tag.endswith('sitemapindex')
            links = [node.text for node in tree.iter() if node.tag.endswith('}loc') or node.tag == 'loc']
        else:
            page = Page()
            page.feed(text)
            links = page.links
            sitemap_index = False
            events.extend(e for e in extract_events(text, url)
                          if pattern.search(urlsplit(e['url']).path))
        for raw in links:
            if not raw:
                continue
            link = urljoin(url, raw).split('#', 1)[0]
            parts = urlsplit(link)
            if parts.scheme == 'https' and parts.hostname == host and (sitemap_index or pattern.search(parts.path)):
                if link not in seen and link not in queue and len(queue) < max_pages * 5:
                    queue.append(link)
    if queue:
        raise ValueError('Достигнут лимит обхода; неполный список не записывается')
    if not events:
        raise ValueError('В источнике не найдены будущие испанские Event JSON-LD; нужна проверка адаптера')
    logger.info('Источник %s: страниц=%s событий=%s', source['name'], len(seen), len(events))
    return events
