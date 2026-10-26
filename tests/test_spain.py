import datetime as dt
import json
import logging
import pytest
from app.sources.spanish_structured import extract_events, scrape_source, validate_source
from app.spain import select_new_events


def event(**overrides):
    return {'@type': 'SportsEvent', 'name': 'Carrera 2027', 'startDate': '2027-06-15',
            'url': 'https://example.test/race/2027', 'location': {
                'address': {'addressCountry': 'ES', 'addressRegion': 'Cataluña', 'addressLocality': 'Badalona'},
                'geo': {'latitude': 41.45, 'longitude': 2.25}}} | overrides


def html(value):
    return '<script type="application/ld+json">' + json.dumps(value) + '</script>'


def test_extract_graph_future_spain():
    result = extract_events(html({'@graph': [event()]}), 'https://example.test', dt.date(2026, 10, 26))
    assert result[0]['country'] == 'Spain'
    assert result[0]['coords'] == '41.450000, 2.250000'
    assert result[0]['city'] == 'Badalona'


@pytest.mark.parametrize('value', [event(startDate='2020-01-01'), event(startDate='invalid'),
    event(eventStatus='https://schema.org/EventCancelled'), event(location={'address': {'addressCountry': 'PT'}})])
def test_reject_wrong_country_past_cancelled_or_missing_date(value):
    assert extract_events(html(value), 'https://example.test', dt.date(2026, 10, 26)) == []


def test_country_not_inferred_from_domain():
    assert extract_events(html(event(location={})), 'https://example.es', dt.date(2026, 10, 26)) == []


def test_dedup_country_and_edition():
    candidate = extract_events(html(event()), 'https://example.test')[0]
    duplicate = dict(candidate, url='https://other.test/carrera-2027')
    assert len(select_new_events([candidate, duplicate], [])) == 1
    row = {'COUNTRY': 'Spain', 'WEBSITE': candidate['url'], 'EVENT START DATE': '15/06/2027'}
    assert select_new_events([candidate], [row]) == []
    assert len(select_new_events([candidate], [dict(row, COUNTRY='Portugal')])) == 1
    assert len(select_new_events([candidate], [dict(row, **{'EVENT START DATE': '15/06/2026'})])) == 1


def test_source_configuration_required():
    with pytest.raises(ValueError):
        validate_source({'name': 'pending', 'url': 'https://example.test'})


def test_source_without_structured_events_fails():
    class Response:
        status_code = 200
        content = b'<html>no event</html>'
        text = content.decode()
    class Session:
        def get(self, *args, **kwargs):
            return Response()
    with pytest.raises(ValueError, match='JSON-LD'):
        scrape_source({'name': 'test', 'url': 'https://example.test', 'event_path_regex': '/race/'},
                      logging.getLogger('test'), session=Session())


def test_sitemap_discovery_and_incomplete_run_are_bounded():
    class Response:
        status_code = 200
        def __init__(self, text):
            self.text = text
            self.content = text.encode()
    class Session:
        def __init__(self):
            self.calls = []
        def get(self, url, **kwargs):
            self.calls.append(url)
            assert kwargs["allow_redirects"] is False
            if url.endswith("sitemap.xml"):
                return Response('<urlset><url><loc>https://example.test/race/2027</loc></url></urlset>')
            return Response(html(event()))
    source = {"name": "fixture", "url": "https://example.test/sitemap.xml", "event_path_regex": "/race/"}
    session = Session()
    assert len(scrape_source(source, logging.getLogger("test"), session=session)) == 1
    assert len(session.calls) == 2
    with pytest.raises(ValueError, match="лимит"):
        scrape_source(source, logging.getLogger("test"), max_pages=1, session=Session())
