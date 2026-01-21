import os
from dataclasses import dataclass
from dotenv import load_dotenv


def _parse_bool(value: str | None, default: bool) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "y"}


def _parse_int(value: str | None, default: int) -> int:
    if value is None or value.strip() == "":
        return default
    return int(value)


@dataclass(frozen=True)
class Config:
    sheet_id: str
    worksheet_name: str
    url_column: str
    missing_worksheet_name: str
    google_credentials_path: str
    telegram_api_id: int
    telegram_api_hash: str
    telegram_target: str
    telegram_session_path: str
    telegram_session_string: str | None
    run_headless: bool
    timeout_ms: int
    user_agent: str | None
    state_path: str
    max_telegram_chars: int
    log_level: str
    dry_run: bool
    source1_enabled: bool
    source2_enabled: bool
    source1_url: str
    source1_event_links: str
    source1_next_button_selector: str
    source1_coords_selector: str
    source1_detail_links: str
    source2_url: str
    source2_next_button: str
    source2_month_list_links: str
    source2_event_list: str
    source2_event_links: str
    source2_location_selector: str
    max_pagination_pages: int
    opencage_base_url: str
    opencage_api_key: str
    opencage_delay_sec: float


REQUIRED_ENV = [
    "SHEET_ID",
    "WORKSHEET_NAME",
    "URL_COLUMN",
    "GOOGLE_CREDENTIALS_PATH",
    "TELEGRAM_API_ID",
    "TELEGRAM_API_HASH",
    "TELEGRAM_TARGET",
    "OPENCAGE_API_KEY",
]


def load_config() -> Config:
    load_dotenv()

    missing = [key for key in REQUIRED_ENV if not os.getenv(key)]
    if missing:
        missing_str = ", ".join(missing)
        raise ValueError(f"Отсутствуют обязательные переменные окружения: {missing_str}")

    return Config(
        sheet_id=os.environ["SHEET_ID"],
        worksheet_name=os.environ["WORKSHEET_NAME"],
        url_column=os.environ["URL_COLUMN"],
        missing_worksheet_name=os.getenv("MISSING_WORKSHEET_NAME", "Missing races"),
        google_credentials_path=os.environ["GOOGLE_CREDENTIALS_PATH"],
        telegram_api_id=int(os.environ["TELEGRAM_API_ID"]),
        telegram_api_hash=os.environ["TELEGRAM_API_HASH"],
        telegram_target=os.environ["TELEGRAM_TARGET"],
        telegram_session_path=os.getenv("TELEGRAM_SESSION_PATH", "./data/telegram.session"),
        telegram_session_string=os.getenv("TELEGRAM_SESSION_STRING") or None,
        run_headless=_parse_bool(os.getenv("RUN_HEADLESS"), True),
        timeout_ms=_parse_int(os.getenv("TIMEOUT_MS"), 30000),
        user_agent=os.getenv("USER_AGENT") or None,
        state_path=os.getenv("STATE_PATH", "./data/notified.json"),
        max_telegram_chars=_parse_int(os.getenv("MAX_TELEGRAM_CHARS"), 3800),
        log_level=os.getenv("LOG_LEVEL", "INFO"),
        dry_run=_parse_bool(os.getenv("DRY_RUN"), False),
        source1_enabled=_parse_bool(os.getenv("SOURCE1_ENABLED"), True),
        source2_enabled=_parse_bool(os.getenv("SOURCE2_ENABLED"), True),
        source1_url=os.getenv("SOURCE1_URL", "https://portugalruncalendar.com"),
        source1_event_links=os.getenv("SOURCE1_EVENT_LINKS", "div.space-y-6 a.block.h-full"),
        source1_next_button_selector=os.getenv(
            "SOURCE1_NEXT_BUTTON_SELECTOR",
            "button:has-text(\"Próxima\")",
        ),
        source1_coords_selector=os.getenv(
            "SOURCE1_COORDS_SELECTOR",
            "div.space-y-6 div.flex.items-start.gap-3 p.text-muted-foreground.mt-1",
        ),
        source1_detail_links=os.getenv(
            "SOURCE1_DETAIL_LINKS",
            "div.space-y-6 a.block.h-full a.w-full",
        ),
        source2_url=os.getenv(
            "SOURCE2_URL", "https://www.portugalrunning.com/calendario-de-corridas/"
        ),
        source2_next_button=os.getenv("SOURCE2_NEXT_BUTTON", "button#evcal_next"),
        source2_month_list_links=os.getenv(
            "SOURCE2_MONTH_LIST_LINKS",
            "div.evo_events_list_box div.eventon_list_event a",
        ),
        source2_event_list=os.getenv(
            "SOURCE2_EVENT_LIST", "div.eventon_events_list div.eventon_list_event"
        ),
        source2_event_links=os.getenv("SOURCE2_EVENT_LINKS", "a.evcal_evdata_row"),
        source2_location_selector=os.getenv(
            "SOURCE2_LOCATION_SELECTOR",
            "em.evcal_location em.event_location_name",
        ),
        max_pagination_pages=_parse_int(os.getenv("MAX_PAGINATION_PAGES"), 200),
        opencage_base_url=os.getenv(
            "OPENCAGE_BASE_URL", "https://api.opencagedata.com/geocode/v1"
        ),
        opencage_api_key=os.environ["OPENCAGE_API_KEY"],
        opencage_delay_sec=float(os.getenv("OPENCAGE_DELAY_SEC", "1.0")),
    )
