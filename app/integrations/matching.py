"""Сопоставление трасс и фильтрация служебных страниц.

Заменяет прежнее сравнение «точное совпадение нормализованного URL» на
многоуровневое:

- уровень 0 (exact): нормализованный URL уже есть в RACES;
- уровень A (parent/child + языковой префикс): тот же host, и пути «вложены»
  друг в друга (один является префиксом другого), либо отличаются только
  ведущим языковым сегментом (/pt, /en, ...).

Категория C (новая редакция года — это новая трасса) соблюдается автоматически:
год нигде не вырезается, поэтому `race-2025` и `race-2026` различаются в сегменте
пути и НЕ схлопываются.

Категория B (кросс-платформенное совпадение по slug) добавляется отдельным
этапом и здесь пока не реализована.
"""

from dataclasses import dataclass, field
from urllib.parse import urlsplit

from app.integrations.url_normalize import normalize_url


DEFAULT_LANG_PREFIXES = ("pt", "en", "es", "fr", "pt-pt", "en-us")
DEFAULT_SUBPAGE_SEGMENTS = (
    "inscritos",
    "inscricao",
    "inscricoes",
    "resultados",
    "classificacao",
    "classificacoes",
    "info",
)
DEFAULT_CONTAINER_SEGMENTS = ("eventos", "evento", "event", "events")
DEFAULT_SERVICE_BLOCKLIST = ("organizadores-provas", "organizadores")

# Минимальное число общих значимых токенов, чтобы считать дочерний сегмент
# тем же событием, что и родительский slug.
_MIN_TOKEN_OVERLAP = 2
# Токены короче этого порога считаем шумом ("s", "de", "do" ...).
_MIN_TOKEN_LEN = 2


@dataclass(frozen=True)
class MatchConfig:
    lang_prefixes: tuple[str, ...] = DEFAULT_LANG_PREFIXES
    subpage_segments: tuple[str, ...] = DEFAULT_SUBPAGE_SEGMENTS
    container_segments: tuple[str, ...] = DEFAULT_CONTAINER_SEGMENTS
    service_blocklist: tuple[str, ...] = DEFAULT_SERVICE_BLOCKLIST
    block_homepage: bool = True
    block_generic_forms: bool = True


def _split(url: str) -> tuple[str, list[str], str]:
    """Возвращает (host, [сегменты пути], query) из нормализованного URL."""
    norm = normalize_url(url)  # "//host/path?query"
    parts = urlsplit("https:" + norm)
    segments = [seg for seg in parts.path.split("/") if seg]
    return parts.netloc, segments, parts.query


def _strip_lang(segments: list[str], lang_prefixes: tuple[str, ...]) -> list[str]:
    if segments and segments[0].lower() in lang_prefixes:
        return segments[1:]
    return segments


def _tokens(segment: str) -> set[str]:
    raw = segment.lower().replace("_", "-").split("-")
    return {tok for tok in raw if len(tok) >= _MIN_TOKEN_LEN}


def is_service_page(url: str, config: MatchConfig) -> bool:
    """Категория D: служебные/индексные страницы, не относящиеся к гонкам."""
    host, segments, query = _split(url)

    # Домашняя страница: нет пути и нет query (timerspeed.com/?tribe_events=...
    # сюда НЕ попадает, т.к. содержит query — это реальное событие).
    if config.block_homepage and not segments and not query:
        return True

    # Generic Google Forms.
    if config.block_generic_forms and host == "docs.google.com" and segments[:1] == ["forms"]:
        return True

    # Служебные страницы по списку подстрок пути.
    path_lower = "/".join(segments).lower()
    for token in config.service_blocklist:
        if token and token in path_lower:
            return True

    return False


@dataclass
class KnownIndex:
    """Индекс известных трасс из колонки WEBSITE листа RACES."""

    websites: list[str]
    config: MatchConfig = field(default_factory=MatchConfig)
    exact: set[str] = field(init=False, default_factory=set)
    by_host: dict[str, list[list[str]]] = field(init=False, default_factory=dict)

    def __post_init__(self) -> None:
        for raw in self.websites:
            if not raw or not raw.strip():
                continue
            self.exact.add(normalize_url(raw))
            host, segments, _ = _split(raw)
            segments = _strip_lang(segments, self.config.lang_prefixes)
            self.by_host.setdefault(host, []).append(segments)

    def match(self, url: str) -> tuple[str, str] | None:
        """Возвращает (категория, с_чем_совпало) или None, если трасса новая."""
        norm = normalize_url(url)
        if norm in self.exact:
            return ("exact", norm)

        host, segments, _ = _split(url)
        segments = _strip_lang(segments, self.config.lang_prefixes)

        for known_segments in self.by_host.get(host, []):
            if self._is_parent_child(segments, known_segments):
                return ("A", host + "/" + "/".join(known_segments))

        return None

    def _is_parent_child(self, a: list[str], b: list[str]) -> bool:
        # Совпадение после срезания языкового префикса (/pt/ ≡ без префикса).
        if a == b:
            return bool(a)

        shorter, longer = (a, b) if len(a) < len(b) else (b, a)
        if not shorter:
            return False  # уровень домашней страницы — слишком широко

        # Короткий путь должен быть префиксом длинного.
        if longer[: len(shorter)] != shorter:
            return False

        # Защита: короткий путь не должен заканчиваться «контейнерным» сегментом
        # (eventos/event/...), иначе листинг схлопнет все вложенные события.
        if shorter[-1].lower() in self.config.container_segments:
            return False

        extra = longer[len(shorter):]

        # Случай 1: лишний хвост — это суб-страница (/inscritos, /resultados, ...).
        if all(seg.lower() in self.config.subpage_segments for seg in extra):
            return True

        # Случай 2: один лишний сегмент, разделяющий значимые токены с родителем
        # (corrida-s-joao ≡ corrida-s-joao/corrida-de-s-joao-2026).
        if len(extra) == 1:
            overlap = _tokens(shorter[-1]) & _tokens(extra[0])
            if len(overlap) >= _MIN_TOKEN_OVERLAP:
                return True

        return False
