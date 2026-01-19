import logging
import sys

from playwright.sync_api import sync_playwright

from app.config import load_config
from app.integrations.sheets import fetch_known_urls, fetch_worksheet_gid, write_missing_races
from app.integrations.state import add_notified, get_notified_set, load_state, prune_known, save_state
from app.integrations.telegram import chunk_lines, send_message
from app.logging_setup import setup_logging
from app.sources.source1_portugalruncalendar import scrape_source1
from app.sources.source2_portugalrunning import scrape_source2


def _log_config(logger: logging.Logger, config) -> None:
    logger.info(
        "Запуск с параметрами: sheet_id=%s worksheet=%s url_column=%s",
        config.sheet_id,
        config.worksheet_name,
        config.url_column,
    )
    logger.info("Источники: source1=%s source2=%s", config.source1_enabled, config.source2_enabled)
    logger.info("DRY_RUN=%s RUN_HEADLESS=%s", config.dry_run, config.run_headless)


def main() -> int:
    config = load_config()
    setup_logging(config.log_level)
    logger = logging.getLogger("race_monitor")
    _log_config(logger, config)

    known_urls = fetch_known_urls(
        config.sheet_id,
        config.worksheet_name,
        config.url_column,
        config.google_credentials_path,
        logger,
    )
    logger.info("Загружено известных URL: %s", len(known_urls))

    state = load_state(config.state_path)
    notified_set = get_notified_set(state)

    source_errors: list[str] = []
    source_results: dict[str, dict[str, str]] = {}

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=config.run_headless)
        context = browser.new_context(user_agent=config.user_agent)

        if config.source1_enabled:
            try:
                source_results["portugalruncalendar.com"] = scrape_source1(
                    context,
                    config.source1_url,
                    config.source1_event_links,
                    config.source1_next_button_selector,
                    config.timeout_ms,
                    config.max_pagination_pages,
                    logger,
                )
            except Exception as exc:  # noqa: BLE001
                logger.exception("Ошибка источника portugalruncalendar.com: %s", exc)
                source_errors.append("portugalruncalendar.com")

        if config.source2_enabled:
            try:
                source_results["portugalrunning.com"] = scrape_source2(
                    context,
                    config.source2_url,
                    config.source2_next_button,
                    config.source2_month_list_links,
                    config.source2_event_list,
                    config.source2_event_links,
                    config.timeout_ms,
                    logger,
                )
            except Exception as exc:  # noqa: BLE001
                logger.exception("Ошибка источника portugalrunning.com: %s", exc)
                source_errors.append("portugalrunning.com")

        context.close()
        browser.close()

    if not source_results:
        logger.error("Не удалось получить данные ни с одного источника")
        return 1

    to_notify_map: dict[str, set[str]] = {}
    missing_rows: list[tuple[str, str]] = []

    for source_name, url_map in source_results.items():
        scraped_set = set(url_map.keys())
        new_candidates = scraped_set - known_urls
        to_notify = new_candidates - notified_set
        to_notify_map[source_name] = to_notify

        logger.info(
            "Источник %s: всего=%s новых=%s к отправке=%s",
            source_name,
            len(scraped_set),
            len(new_candidates),
            len(to_notify),
        )

        if to_notify:
            for normalized in sorted(to_notify):
                missing_rows.append((source_name, url_map[normalized]))

    if all(not urls for urls in to_notify_map.values()):
        logger.info("Новых ссылок нет, уведомления не отправляются")
        if not config.dry_run:
            prune_known(state, known_urls)
            save_state(config.state_path, state)
        return 1 if source_errors else 0

    if not config.dry_run:
        missing_gid = write_missing_races(
            config.sheet_id,
            config.missing_worksheet_name,
            missing_rows,
            config.google_credentials_path,
            logger,
        )
    else:
        missing_gid = fetch_worksheet_gid(
            config.sheet_id,
            config.missing_worksheet_name,
            config.google_credentials_path,
            logger,
        )

    total_missing = len(missing_rows)
    sheet_link = (
        f"https://docs.google.com/spreadsheets/d/{config.sheet_id}"
        f"/edit#gid={missing_gid}"
    )
    message_lines = [
        f"{total_missing} races were found that aren't in our table.",
        "",
        f"View the full list: {sheet_link}",
    ]
    chunks = chunk_lines(message_lines, config.max_telegram_chars)
    if config.dry_run:
        logger.info("DRY_RUN включен, сообщения не отправляются")
        for chunk in chunks:
            logger.info("Сообщение:\n%s", chunk)
        return 1 if source_errors else 0

    for chunk in chunks:
        send_message(
            config.telegram_api_id,
            config.telegram_api_hash,
            config.telegram_session_path,
            config.telegram_target,
            chunk,
            logger,
        )

    for source_name, to_notify in to_notify_map.items():
        if to_notify:
            add_notified(state, to_notify, source_name)

    prune_known(state, known_urls)
    save_state(config.state_path, state)

    return 1 if source_errors else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:  # noqa: BLE001
        logging.getLogger("race_monitor").exception("Критическая ошибка: %s", exc)
        sys.exit(1)
