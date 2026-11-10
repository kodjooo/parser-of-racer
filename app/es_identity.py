"""Подтверждение одинаковых испанских событий прямой ссылкой на регистрацию."""
import collections
import datetime as dt
from html.parser import HTMLParser
import re
import time
from urllib.parse import urljoin, urlsplit, parse_qs

from app.integrations.matching import normalize_event_name
from app.integrations.url_normalize import normalize_url
from app.sources.spanish_structured import extract_events, Page, walk_json
import json


class RegistrationLinks(HTMLParser):
    def __init__(self):
        super().__init__()
        self.current = None
        self.links = []

    def handle_starttag(self, tag, attrs):
        if tag == 'a':
            self.current = [dict(attrs).get('href', ''), '']

    def handle_data(self, text):
        if self.current is not None:
            self.current[1] += text

    def handle_endtag(self, tag):
        if tag == 'a' and self.current is not None:
            self.links.append(self.current)
            self.current = None


def rock_identity(url):
    parts = urlsplit(url)
    if parts.scheme != 'https' or parts.hostname != 'web.rockthesport.com' or parts.username or parts.password:
        return None
    match = re.fullmatch(r'/(?:es|en|pt|pt-PT|ca|eu|fr|it)/event/([a-zA-Z0-9_-]+)(?:/[^?#]*)?/?', parts.path)
    return 'https://web.rockthesport.com/es/event/' + match[1] if match else None


def life_page(url):
    parts = urlsplit(url)
    return (parts.scheme == 'https' and parts.hostname == 'running.life'
            and not parts.username and not parts.password
            and bool(re.fullmatch(r'/es/carrera/[a-zA-Z0-9_-]+/?', parts.path)))


def title_date(event):
    date = event.get('date', '')
    title = re.sub(r'\b' + re.escape(date[:4]) + r'\b', '', event.get('name', '')) if date else ''
    return normalize_event_name(title), date


def page_evidence(text, url):
    own = [e for e in extract_events(text, url, today=dt.date.min)
           if normalize_url(e['url']) == normalize_url(url)]
    parser = RegistrationLinks()
    parser.feed(text)
    labels = {'sitio web', 'inscripcion', 'website', 'registration'}
    links = {urljoin(url, href) for href, label in parser.links
             if normalize_event_name(label).strip() in labels}
    targets = {rock_identity(link) for link in links}
    return {'dates': sorted({e['date'] for e in own}), 'targets': sorted(targets - {None}),
            'branded_urls': sorted(link for link in links if mychip_slug(link))}


def mychip_slug(url):
    parts = urlsplit(url)
    if parts.scheme != 'https' or parts.hostname != 'inscripciones.mychip.es' or parts.username or parts.password:
        return None
    match = re.fullmatch(r'/es/evento/([a-zA-Z0-9_-]+)/?', parts.path)
    return match[1] if match else None


class BrandedPage(HTMLParser):
    def __init__(self):
        super().__init__()
        self.frames = []

    def handle_starttag(self, tag, attrs):
        if tag == 'iframe':
            self.frames.append(dict(attrs).get('src', ''))


def branded_event_id(brand_text, rock_text, brand_url, rock_url, date):
    # Брендированная MyChip и RockTheSport должны указывать один ID платформы.
    canonical = rock_identity(rock_url)
    if not canonical or mychip_slug(brand_url) != canonical.rsplit('/', 1)[-1]:
        return None
    page = Page()
    page.feed(rock_text)
    own_date = False
    for block in page.blocks:
        try:
            own_date |= any(rock_identity(e.get('url', '')) == canonical and str(e.get('startDate', ''))[:10] == date
                            for e in walk_json(json.loads(block)))
        except (ValueError, TypeError):
            continue
    if not own_date:
        return None
    ids = set(re.findall(r'"eventId"\s*:\s*"?(\d+)', rock_text.replace('\\"', '"')))
    if len(ids) != 1:
        return None
    parser = BrandedPage()
    parser.feed(brand_text)
    for frame in parser.frames:
        parts = urlsplit(frame)
        if parts.scheme != 'https' or parts.hostname not in ('www.stay22.com', 'stay22.com'):
            continue
        query = parse_qs(parts.query)
        campaign = query.get('campaign', [''])[0]
        match = re.fullmatch(r'portada_(\d+)', campaign)
        if match and match[1] in ids and query.get('checkin') == [date]:
            return match[1]
    return None


def identity_urls(event):
    # Подтверждение относится к конкретной дате, не ко всем редакциям одной ссылки.
    if event.get('_identity_date') != event.get('date'):
        return []
    return [url for url in event.get('_identity_urls', []) if life_page(url) or rock_identity(url)]


def same_identity(left, right):
    if not left.get('date') or left['date'] != right.get('date'):
        return False
    a = {normalize_url(url) for url in [left['url']] + identity_urls(left)}
    b = {normalize_url(url) for url in [right['url']] + identity_urls(right)}
    return bool(a & b)


def enrich_identities(events, cache, logger, session=None, now=None, max_lookups=50):
    from app.sources.spanish_calendars import source_client, checked_response
    from app.spain import same_edition_location
    now = time.time() if now is None else now
    out = [dict(event) for event in events]
    groups = collections.defaultdict(list)
    for event in out:
        # Старое подтверждение нельзя использовать после изменения даты или страницы.
        event.pop('_identity_urls', None)
        event.pop('_identity_date', None)
        if event.get('country') == 'Spain' and all(title_date(event)):
            groups[title_date(event)].append(event)
    report = {'lookups': 0, 'confirmed_pairs': 0, 'unresolved_pairs': 0, 'pairs': []}
    client = None
    for (_, date), group in groups.items():
        lives = [e for e in group if life_page(e['url'])]
        rocks = [e for e in group if rock_identity(e['url'])]
        if not lives or not rocks:
            continue
        for life in lives:
            candidates = [rock for rock in rocks if not same_edition_location(life, rock)]
            if not candidates:
                continue
            key = life['url'] + '|' + date
            evidence = cache.get(key)
            expected = sorted({rock_identity(rock['url']) for rock in candidates})
            ttl = 7 * 86400 if evidence and date in evidence.get('dates', []) and evidence.get('targets') else 86400
            fresh = evidence and evidence.get('candidate_targets') == expected and 0 <= now - evidence.get('checked_at', 0) < ttl
            if not fresh:
                if report['lookups'] >= max_lookups:
                    evidence = {'dates': [], 'targets': [], 'reason': 'lookup_limit'}
                else:
                    report['lookups'] += 1
                    try:
                        client = client or source_client(session)
                        response = checked_response(client.get(life['url'], timeout=20, allow_redirects=False))
                        evidence = dict(page_evidence(response.text, life['url']), checked_at=now)
                        if date in evidence['dates']:
                            for brand in evidence['branded_urls']:
                                for rock in candidates:
                                    target = rock_identity(rock['url'])
                                    if target in evidence['targets'] or mychip_slug(brand) != target.rsplit('/', 1)[-1]:
                                        continue
                                    if report['lookups'] + 2 > max_lookups:
                                        continue
                                    report['lookups'] += 2
                                    brand_response = checked_response(client.get(brand, timeout=20, allow_redirects=False))
                                    rock_response = checked_response(client.get(rock['url'], timeout=20, allow_redirects=False))
                                    platform_id = branded_event_id(brand_response.text, rock_response.text, brand, rock['url'], date)
                                    if platform_id:
                                        evidence['targets'].append(target)
                                        evidence.setdefault('branded_confirmations', []).append({'url': brand, 'target': target, 'event_id': platform_id})
                    except Exception as exc:
                        logger.warning('Не удалось проверить регистрацию %s: %s', life['url'], exc)
                        evidence = {'dates': [], 'targets': [], 'checked_at': now, 'reason': 'fetch_error'}
                    evidence['candidate_targets'] = expected
                    cache[key] = evidence
            for rock in candidates:
                matched = date in evidence['dates'] and rock_identity(rock['url']) in evidence['targets']
                reason = ('confirmed_registration' if matched else evidence.get('reason') or
                          ('date_mismatch' if date not in evidence['dates'] else 'no_matching_registration'))
                report['pairs'].append({'life': life['url'], 'rock': rock['url'], 'date': date, 'reason': reason})
                report['confirmed_pairs' if matched else 'unresolved_pairs'] += 1
                if matched:
                    for event in (life, rock):
                        event['_identity_date'] = date
                        event['_identity_urls'] = sorted(set(event.get('_identity_urls', []) + [life['url'], rock['url']]))
    logger.info('Сопоставление ES: запросов=%s подтверждено=%s не подтверждено=%s',
                report['lookups'], report['confirmed_pairs'], report['unresolved_pairs'])
    return out, report
