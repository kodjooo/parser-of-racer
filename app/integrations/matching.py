"""Сопоставление трасс и фильтрация служебных страниц.

Заменяет прежнее сравнение «точное совпадение нормализованного URL» на
многоуровневое:

- уровень 0 (exact): нормализованный URL уже есть в RACES;
- уровень A (parent/child + языковой префикс): тот же host, и пути «вложены»
  друг в друга (один является префиксом другого), либо отличаются только
  ведущим языковым сегментом (/pt, /en, ...).

- уровень B (кросс-платформенно): одно событие на разных сайтах/поддоменах,
  опознаётся по совпадению slug события (последний значимый сегмент пути,
  с годом). Применяется осторожно: slug должен быть достаточно длинным,
  содержать буквы и не входить в стоп-лист общих слов; каждое совпадение
  логируется для аудита. Включается флагом cross_platform_match.

Категория C (новая редакция года — это новая трасса) соблюдается автоматически:
год нигде не вырезается, поэтому `race-2025` и `race-2026` различаются и в пути
(A), и в slug (B), и НЕ схлопываются.
"""

import re
import unicodedata
from dataclasses import dataclass, field
from urllib.parse import urlsplit

from app.integrations.url_normalize import normalize_url


_YEAR_RE = re.compile(r"20\d{2}")


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
# Категория B: «мусорные» последние сегменты, по которым НЕЛЬЗЯ сопоставлять
# события между сайтами (слишком общие → ложные совпадения).
DEFAULT_SLUG_STOPLIST = (
    "info",
    "viewform",
    "inscritos",
    "inscricao",
    "inscricoes",
    "resultados",
    "classificacao",
    "classificacoes",
    "index",
    "index.php",
)
# Минимальная длина slug для кросс-платформенного совпадения.
DEFAULT_CROSS_PLATFORM_MIN_SLUG_LEN = 6

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
    cross_platform_match: bool = True
    cross_platform_min_slug_len: int = DEFAULT_CROSS_PLATFORM_MIN_SLUG_LEN
    slug_stoplist: tuple[str, ...] = DEFAULT_SLUG_STOPLIST
    name_match: bool = True


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


def _event_slug(url: str) -> str | None:
    """Последний значимый сегмент пути как сигнатура события (с годом).

    Год НЕ вырезается, поэтому `race-2025` и `race-2026` дают разные slug —
    категория C соблюдается.
    """
    _, segments, _ = _split(url)
    if not segments:
        return None
    return segments[-1].lower().replace("_", "-")


def _slug_is_usable(slug: str, config: MatchConfig) -> bool:
    if len(slug) < config.cross_platform_min_slug_len:
        return False
    if slug in config.slug_stoplist:
        return False
    # должна быть хотя бы одна буква (исключаем чисто числовые id типа "425")
    return any(ch.isalpha() for ch in slug)


def normalize_event_name(name: str) -> str:
    """Нормализация названия события для сравнения.

    Убирает диакритику (Mâmoa→mamoa), приводит к нижнему регистру, схлопывает
    пунктуацию/пробелы. Год (цифры) СОХРАНЯЕТСЯ — категория C: «Trail X 2025» и
    «Trail X 2026» остаются разными.
    """
    folded = unicodedata.normalize("NFKD", name)
    folded = folded.encode("ascii", "ignore").decode("ascii")
    folded = folded.lower()
    folded = re.sub(r"[^a-z0-9]+", " ", folded)
    return folded.strip()


def _name_has_year(normalized_name: str) -> bool:
    return bool(_YEAR_RE.search(normalized_name))


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
    names: list[str] = field(default_factory=list)
    exact: set[str] = field(init=False, default_factory=set)
    by_host: dict[str, list[list[str]]] = field(init=False, default_factory=dict)
    by_slug: dict[str, str] = field(init=False, default_factory=dict)
    by_name: dict[str, str] = field(init=False, default_factory=dict)

    def __post_init__(self) -> None:
        for raw in self.websites:
            if not raw or not raw.strip():
                continue
            self.exact.add(normalize_url(raw))
            host, segments, _ = _split(raw)
            segments = _strip_lang(segments, self.config.lang_prefixes)
            self.by_host.setdefault(host, []).append(segments)

            if self.config.cross_platform_match:
                slug = _event_slug(raw)
                if slug and _slug_is_usable(slug, self.config):
                    # первый встретившийся известный URL для этого slug
                    self.by_slug.setdefault(slug, raw)

        # Индекс названий (RACE NAME + RACE NAME (PT)). Только названия с годом —
        # это обеспечивает «имя + год строго» и исключает общие названия без года.
        if self.config.name_match:
            for name in self.names:
                if not name or not name.strip():
                    continue
                norm = normalize_event_name(name)
                if norm and _name_has_year(norm):
                    self.by_name.setdefault(norm, name.strip())

    def match(self, url: str, name: str | None = None) -> tuple[str, str] | None:
        """Возвращает (категория, с_чем_совпало) или None, если трасса новая.

        Если передано name — дополнительно проверяется совпадение по названию
        (имя + год строго), уровень N.
        """
        norm = normalize_url(url)
        if norm in self.exact:
            return ("exact", norm)

        host, segments, _ = _split(url)
        segments = _strip_lang(segments, self.config.lang_prefixes)

        for known_segments in self.by_host.get(host, []):
            if self._is_parent_child(segments, known_segments):
                return ("A", host + "/" + "/".join(known_segments))

        # Уровень B: кросс-платформенно по slug события (с годом).
        if self.config.cross_platform_match:
            slug = _event_slug(url)
            if slug and _slug_is_usable(slug, self.config):
                known_url = self.by_slug.get(slug)
                if known_url is not None:
                    return ("B", known_url)

        # Уровень N: совпадение по названию + год (кросс-платформенно).
        if name is not None:
            name_match = self.match_name(name)
            if name_match is not None:
                return ("N", name_match)

        return None

    def match_name(self, name: str) -> str | None:
        """Совпадение по нормализованному названию (имя + год строго)."""
        if not self.config.name_match or not name:
            return None
        norm = normalize_event_name(name)
        if not norm or not _name_has_year(norm):
            return None
        return self.by_name.get(norm)

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
            # Защита категории C: не схлопывать «безгодовый» родитель с годовым
            # ребёнком — иначе можно спрятать новую годовую редакцию. Матч
            # допускается только если год ребёнка уже присутствует у родителя
            # (или года нет вовсе).
            child_years = set(_YEAR_RE.findall(extra[0]))
            parent_years = set(_YEAR_RE.findall(shorter[-1]))
            if child_years and not child_years <= parent_years:
                return False
            overlap = _tokens(shorter[-1]) & _tokens(extra[0])
            if len(overlap) >= _MIN_TOKEN_OVERLAP:
                return True

        return False
