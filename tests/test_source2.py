from app.sources.source2_portugalrunning import _clean_location, _clean_name, _KEY_RE


def test_clean_name_unescapes_and_normalizes() -> None:
    assert _clean_name("Tor des G&#233;ants (TOR330) 2026 &#8211; Vale") == \
        "Tor des Géants (TOR330) 2026 - Vale"


def test_clean_location_dedupes_doubled_string() -> None:
    # EventON дублирует локацию
    assert _clean_location("Santo Tirso,  Porto Santo Tirso,  Porto") == "Santo Tirso,  Porto"


def test_clean_location_single_kept() -> None:
    assert _clean_location("Lisboa") == "Lisboa"


def test_key_regex_extracts_per_event_key() -> None:
    html = 'href="https://www.portugalrunning.com/export-events/48030_0/?key=94c88e0378"'
    m = _KEY_RE.search(html)
    assert m and m.group(1) == "94c88e0378"
