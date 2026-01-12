import logging
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


def _discover_pagination_links(page) -> list[str]:
    selectors = [
        "nav[aria-label*='Pagination'] a[href]",
        "nav[aria-label*='pagination'] a[href]",
        "ul[role='navigation'] a[href]",
        "a[rel='next']",
        "a[rel='prev']",
        "a[aria-label*='Next']",
        "a[aria-label*='Previous']",
        "a[href*='page=']",
    ]
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

        links = _extract_event_links(page, event_selector)
        if not links:
            logger.warning("Не найдены ссылки событий на странице %s", current)
        for href in links:
            absolute = urljoin(page.url, href)
            normalized = normalize_url(absolute)
            results.setdefault(normalized, absolute)

        pagination_links = _discover_pagination_links(page)
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
