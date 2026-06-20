from app.integrations.matching import KnownIndex, MatchConfig, is_service_page


CFG = MatchConfig()


# --- Категория D: служебные страницы ---

def test_service_homepage_blocked() -> None:
    assert is_service_page("https://dourorun.pt/", CFG)
    assert is_service_page("https://www.madeiramarathon.com/", CFG)
    assert is_service_page("https://corridaauchan.pt/", CFG)


def test_service_generic_google_form_blocked() -> None:
    assert is_service_page(
        "https://docs.google.com/forms/d/e/1FAIpQLSc/viewform", CFG
    )


def test_service_organizers_page_blocked() -> None:
    assert is_service_page("https://www.portugalrunning.com/organizadores-provas/", CFG)


def test_real_event_with_query_not_blocked() -> None:
    # timerspeed: query есть — это реальное событие, не домашняя страница
    assert not is_service_page(
        "https://timerspeed.com/?tribe_events=lpcnor-3a-corrida-de-sao-pedro", CFG
    )


def test_real_event_with_path_not_blocked() -> None:
    assert not is_service_page(
        "https://cyclonessports.com/index.php/365-correr-fontao-2026", CFG
    )


# --- Категория A: parent/child + языковой префикс ---

def test_exact_match() -> None:
    idx = KnownIndex(["https://acorrer.pt/eventos/cabrum-360"])
    assert idx.match("https://acorrer.pt/eventos/cabrum-360") == (
        "exact",
        "//acorrer.pt/eventos/cabrum-360",
    )


def test_language_prefix_treated_as_same() -> None:
    idx = KnownIndex(["https://runporto.com/pt/eventos/marginal-noite-esposende"])
    result = idx.match("https://runporto.com/eventos/marginal-noite-esposende")
    assert result is not None and result[0] == "A"


def test_child_subpage_inscritos() -> None:
    idx = KnownIndex(["https://www.portimer.pt/eventos/hygoes_2026/inscritos"])
    result = idx.match("https://www.portimer.pt/eventos/hygoes_2026")
    assert result is not None and result[0] == "A"


def test_child_deeper_path_shared_tokens() -> None:
    idx = KnownIndex(
        ["https://runporto.com/pt/eventos/corrida-s-joao/corrida-de-s-joao-2026/"]
    )
    result = idx.match("https://runporto.com/pt/eventos/corrida-s-joao/")
    assert result is not None and result[0] == "A"


# --- Категория C: новый год — это НОВАЯ трасса (не должно схлопываться) ---

def test_different_year_is_new() -> None:
    idx = KnownIndex(["https://lap2go.com/pt/event/mm-ovar-2025"])
    assert idx.match("https://lap2go.com/pt/event/mm-ovar-2026") is None


def test_similar_but_different_event_is_new() -> None:
    idx = KnownIndex(["https://lap2go.com/pt/event/trilhos-da-cola-2026"])
    assert idx.match("https://lap2go.com/pt/event/trilhos-do-inha-2026") is None


# --- Защита от ложных совпадений ---

def test_container_segment_does_not_collapse_events() -> None:
    # Известен только листинг /eventos — он не должен матчить конкретные события
    idx = KnownIndex(["https://acorrer.pt/eventos"])
    assert idx.match("https://acorrer.pt/eventos/cabrum-360") is None


# --- Категория B: кросс-платформенно по slug ---

def test_b_cross_platform_same_slug() -> None:
    idx = KnownIndex(["https://waitastart.com/corrida-das-fogueiras-2026"])
    result = idx.match("https://nativewarriors.pt/evento/corrida-das-fogueiras-2026")
    assert result is not None and result[0] == "B"


def test_b_cross_subdomain_with_id() -> None:
    idx = KnownIndex(
        ["https://ultramelidestroia.bol.pt/Comprar/Bilhetes/172727-corrida_atlantica_2026-troia_grandola/"]
    )
    result = idx.match(
        "https://www.bol.pt/Comprar/Bilhetes/172727-corrida_atlantica_2026-troia_grandola/"
    )
    assert result is not None and result[0] == "B"


def test_b_different_year_not_matched() -> None:
    # категория C важнее B: разный год — разные события
    idx = KnownIndex(["https://waitastart.com/corrida-das-fogueiras-2025"])
    assert idx.match("https://nativewarriors.pt/evento/corrida-das-fogueiras-2026") is None


def test_b_numeric_only_slug_not_matched() -> None:
    # чисто числовой id ("425") не должен матчить между сайтами
    idx = KnownIndex(["https://www.sinctime.com/evento/425"])
    assert idx.match("https://other-platform.pt/evento/425") is None


def test_b_generic_slug_info_not_matched() -> None:
    # "info" в стоп-листе — разные события acorrer не схлопываются
    idx = KnownIndex(["https://acorrer.pt/eventos/4119/info"])
    assert idx.match("https://acorrer.pt/eventos/4313/info") is None


def test_b_disabled_by_config() -> None:
    cfg = MatchConfig(cross_platform_match=False)
    idx = KnownIndex(["https://waitastart.com/corrida-das-fogueiras-2026"], cfg)
    assert idx.match("https://nativewarriors.pt/evento/corrida-das-fogueiras-2026") is None
