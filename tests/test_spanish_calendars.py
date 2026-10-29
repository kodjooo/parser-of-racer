import datetime as dt
import json
import logging
from pathlib import Path
import pytest
from app.sources.spanish_calendars import APPROVED_SOURCES, running_life, rockthesport, rock_event


class Response:
    status_code = 200
    def __init__(self, body):
        self.text = body if isinstance(body, str) else json.dumps(body)
        self.content = self.text.encode()
    def raise_for_status(self): pass
    def json(self): return json.loads(self.text)


def listing(next_link=""):
    event = {"@type":"SportsEvent", "name":"Carrera", "startDate":"2099-01-02",
             "url":"/es/carrera/test", "location":{"address":{"addressCountry":"ES"}}}
    return '<script type="application/ld+json">'+json.dumps(event)+'</script>'+next_link


def test_running_lists_only_calendar_and_refuses_incomplete(monkeypatch):
    monkeypatch.setattr("app.sources.spanish_calendars.time.sleep", lambda _: None)
    calls = []
    class Session:
        def get(self, url, **kwargs):
            calls.append(url)
            assert kwargs["allow_redirects"] is False
            return Response(listing('<a rel="next" href="?page=2">next</a>') if len(calls)==1 else listing())
    assert len(running_life(APPROVED_SOURCES[0], logging.getLogger(), session=Session())) == 2
    assert calls == [APPROVED_SOURCES[0]["url"], APPROVED_SOURCES[0]["url"]+"?page=2"]
    calls.clear()
    with pytest.raises(ValueError, match="лимит"):
        running_life(APPROVED_SOURCES[0], logging.getLogger(), max_pages=1, session=Session())


def test_running_refuses_foreign_pagination():
    class Session:
        def get(self, *args, **kwargs):
            return Response(listing('<a rel="next" href="https://other.test/">next</a>'))
    with pytest.raises(ValueError, match="границы"):
        running_life(APPROVED_SOURCES[0], logging.getLogger(), session=Session())


def race(**changes):
    return {"id":"1", "countryId":65, "sport":"running", "slug":"carrera", "title":"Carrera",
            "startedDateIso":"2099-01-02T10:00:00", "latitude":41, "longitude":2} | changes


@pytest.mark.parametrize("changes", [{"countryId":1},{"sport":"cycling"},{"title":"Prueba cancelada"},
                                      {"startedDateIso":"2020-01-01"}])
def test_rock_rejects_non_races_wrong_country_cancelled_and_past(changes):
    assert rock_event(race(**changes), dt.date(2026,10,29)) is None


def test_rock_counts_all_sports_before_filtering_and_refuses_partial():
    class Session:
        def __init__(self, total): self.total=total
        def post(self, url, **kwargs):
            assert kwargs["json"]["kind"] == "country:65"
            assert kwargs["allow_redirects"] is False
            return Response({"data":{"items":[race(),race(id="2",sport="cycling")],
                "pagination":{"currentPage":1,"totalPages":1,"totalItems":self.total}}})
    assert len(rockthesport(APPROVED_SOURCES[1], logging.getLogger(), session=Session(2))) == 1
    with pytest.raises(ValueError, match="неполный"):
        rockthesport(APPROVED_SOURCES[1], logging.getLogger(), session=Session(3))


def test_no_sources_publish_when_second_source_fails(monkeypatch):
    from types import SimpleNamespace
    from app import spain
    monkeypatch.setenv("ES_SOURCES_JSON", json.dumps(APPROVED_SOURCES))
    monkeypatch.setattr(spain.Credentials,"from_service_account_file",lambda *a,**k: None)
    monkeypatch.setattr(spain.gspread,"authorize",lambda _: SimpleNamespace(open_by_key=lambda _: object()))
    monkeypatch.setattr(spain,"fetch_country_records",lambda *a,**k: [])
    def scrape(source,*a,**k):
        if source["adapter"] == "rockthesport": raise ValueError("source failed")
        return []
    monkeypatch.setattr(spain,"scrape_source",scrape)
    monkeypatch.setattr(spain,"_get_or_create_worksheet",lambda *a: pytest.fail("Premature sheet write"))
    config=SimpleNamespace(worksheet_name="RACES",missing_worksheet_name="Missing races PT",
        google_credentials_path="unused",dry_run=False,sheet_id="unused",url_column="WEBSITE",max_pagination_pages=120)
    with pytest.raises(ValueError,match="source failed"): spain.run_spain(config)
