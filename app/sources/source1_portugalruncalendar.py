import logging
import time
from urllib.parse import urljoin

from playwright.sync_api import BrowserContext, TimeoutError as PlaywrightTimeoutError

from app.integrations.url_normalize import normalize_url
from app.utils.retry import run_with_retries


def _extract_event_links(page, selector_primary: str) -> list[str]:
    selectors = [
        selector_primary,
        "div.space-y-6 a[href]",
        "div.space-y-6 a",
    ]
    for selector in selectors:
        locator = page.locator(selector)
        if locator.count() == 0:
            continue
        links: list[str] = []
        for idx in range(locator.count()):
            href = locator.nth(idx).get_attribute("href")
            if href:
                links.append(href)
        if links:
            return links
    return []


def _get_first_event_marker(page, selector_primary: str) -> str:
    links = _extract_event_links(page, selector_primary)
    return links[0] if links else ""


def scrape_source1(
    context: BrowserContext,
    base_url: str,
    event_selector: str,
    next_button_selector: str,
    timeout_ms: int,
    max_pages: int,
    logger: logging.Logger,
) -> dict[str, str]:
    page = context.new_page()
    page.set_default_timeout(timeout_ms)

    results: dict[str, str] = {}

    def _goto(url: str) -> None:
        page.goto(url, wait_until="networkidle")

    use_button_pagination = bool(next_button_selector.strip())

    def _collect_links() -> None:
        links = _extract_event_links(page, event_selector)
        if not links:
            logger.warning("Не найдены ссылки событий на странице %s", page.url)
        for href in links:
            absolute = urljoin(page.url, href)
            normalized = normalize_url(absolute)
            results.setdefault(normalized, absolute)

    if not use_button_pagination:
        logger.error("SOURCE1_NEXT_BUTTON_SELECTOR не задан, пагинация недоступна")
        page.close()
        return results

    try:
        run_with_retries(lambda: _goto(base_url), logger=logger, action_name="загрузка страницы")
    except PlaywrightTimeoutError as exc:
        logger.error("Таймаут при загрузке %s: %s", base_url, exc)
        page.close()
        return results

    last_marker = ""
    for _ in range(max_pages):
        marker_before = _get_first_event_marker(page, event_selector)
        if marker_before and marker_before == last_marker:
            logger.debug("Маркер списка не изменился, остановка пагинации")
            break
        last_marker = marker_before
        logger.debug("Маркер списка до клика: %s", marker_before)
        _collect_links()

        next_button = page.locator(next_button_selector)
        count = next_button.count()
        if count == 0:
            logger.debug("Кнопка Próxima не найдена на странице: %s", page.url)
            break
        if next_button.first.is_disabled():
            logger.debug("Кнопка Próxima отключена на странице: %s", page.url)
            break

        def _click_next() -> None:
            next_button.first.click()

        run_with_retries(_click_next, logger=logger, action_name="клик Próxima")

        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            marker_after = _get_first_event_marker(page, event_selector)
            if marker_after and marker_after != marker_before:
                logger.debug("Маркер списка после клика: %s", marker_after)
                break
            page.wait_for_timeout(500)
        else:
            logger.warning("Не удалось дождаться смены списка после Próxima")
            break

    if max_pages <= 0:
        logger.warning("MAX_PAGINATION_PAGES задан неверно: %s", max_pages)

    page.close()
    return results
