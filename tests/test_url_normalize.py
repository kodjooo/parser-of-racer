from app.integrations.url_normalize import normalize_url


def test_url_normalize() -> None:
    raw = "HTTPS://Example.COM//events/123/?utm_source=ad&fbclid=zzz#section"
    normalized = normalize_url(raw)
    assert normalized == "//example.com/events/123"


def test_url_normalize_query_kept() -> None:
    raw = "https://example.com/events/123/?q=run&utm_medium=ad"
    normalized = normalize_url(raw)
    assert normalized == "//example.com/events/123?q=run"


def test_url_normalize_removes_www() -> None:
    raw = "https://www.example.com/events/123/"
    normalized = normalize_url(raw)
    assert normalized == "//example.com/events/123"
