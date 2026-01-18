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


def _discover_pagination_links(page, selectors: list[str]) -> list[str]:
    links: list[str] = []
    for selector in selectors:
        locator = page.locator(selector)
        for idx in range(locator.count()):
            href = locator.nth(idx).get_attribute("href")
            if href:
                links.append(href)
    return links


def scrape_source1(
    context: BrowserContext,
    base_url: str,
    event_selector: str,
    pagination_selectors: str,
    next_button_selector: str,
    timeout_ms: int,
    max_pages: int,
    logger: logging.Logger,
) -> dict[str, str]:
    page = context.new_page()
    page.set_default_timeout(timeout_ms)

    visited: set[str] = set()
    queue = [base_url]
    results: dict[str, str] = {}

    def _goto(url: str) -> None:
        page.goto(url, wait_until="networkidle")

    selectors = [value.strip() for value in pagination_selectors.split(",") if value.strip()]

    use_button_pagination = bool(next_button_selector.strip())

    def _collect_links() -> None:
        links = _extract_event_links(page, event_selector)
        if not links:
            logger.warning("Не найдены ссылки событий на странице %s", page.url)
        for href in links:
            absolute = urljoin(page.url, href)
            normalized = normalize_url(absolute)
            results.setdefault(normalized, absolute)

    if use_button_pagination:
        try:
            run_with_retries(lambda: _goto(base_url), logger=logger, action_name="загрузка страницы")
        except PlaywrightTimeoutError as exc:
            logger.error("Таймаут при загрузке %s: %s", base_url, exc)
            page.close()
            return results

        for _ in range(max_pages):
            current_url = normalize_url(page.url)
            if current_url in visited:
                break
            visited.add(current_url)
            marker_before = _get_first_event_marker(page, event_selector)
            _collect_links()

            next_button = page.locator(next_button_selector)
            if next_button.count() == 0:
                break

            def _click_next() -> None:
                next_button.first.click()

            run_with_retries(_click_next, logger=logger, action_name="клик Próxima")

            deadline = time.monotonic() + 10
            while time.monotonic() < deadline:
                marker_after = _get_first_event_marker(page, event_selector)
                if marker_after and marker_after != marker_before:
                    break
                page.wait_for_timeout(500)
            else:
                logger.warning("Не удалось дождаться смены списка после Próxima")
                break
    else:
        while queue and len(visited) < max_pages:
            current = queue.pop(0)
            normalized_page = normalize_url(current)
            if normalized_page in visited:
                continue

            try:
                run_with_retries(lambda: _goto(current), logger=logger, action_name="загрузка страницы")
            except PlaywrightTimeoutError as exc:
                logger.error("Таймаут при загрузке %s: %s", current, exc)
                visited.add(normalized_page)
                continue

            _collect_links()

            pagination_links = _discover_pagination_links(page, selectors)
            for href in pagination_links:
                absolute = urljoin(page.url, href)
                normalized = normalize_url(absolute)
                if normalized not in visited:
                    queue.append(absolute)

            visited.add(normalized_page)

    if len(visited) >= max_pages:
        logger.warning("Достигнут лимит страниц пагинации: %s", max_pages)

    page.close()
    return results
