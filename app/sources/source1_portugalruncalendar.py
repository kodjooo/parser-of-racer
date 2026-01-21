import logging
import time
from urllib.parse import urljoin

from playwright.sync_api import BrowserContext, TimeoutError as PlaywrightTimeoutError

from app.integrations.geocode import (
    format_coordinates,
    parse_coordinates,
    reverse_geocode_portugal,
)
from app.integrations.url_normalize import normalize_url
from app.utils.retry import run_with_retries


def _extract_links_by_selector(page, selector: str) -> list[str]:
    locator = page.locator(selector)
    links: list[str] = []
    for idx in range(locator.count()):
        href = locator.nth(idx).get_attribute("href")
        if href:
            links.append(href)
    return links


def _extract_event_links(page, selector_primary: str) -> list[str]:
    selectors = [
        selector_primary,
        "div.space-y-6 a[href]",
        "div.space-y-6 a",
    ]
    for selector in selectors:
        links = _extract_links_by_selector(page, selector)
        if links:
            return links
    return []


def _to_relative_selector(selector: str) -> str:
    parts = selector.strip().split()
    return parts[-1] if parts else selector.strip()


def _get_first_event_marker(page, selector_primary: str) -> str:
    links = _extract_event_links(page, selector_primary)
    return links[0] if links else ""


def scrape_source1(
    context: BrowserContext,
    base_url: str,
    event_selector: str,
    next_button_selector: str,
    coords_selector: str,
    detail_links_selector: str,
    timeout_ms: int,
    max_pages: int,
    opencage_base_url: str,
    opencage_api_key: str,
    opencage_delay_sec: float,
    logger: logging.Logger,
) -> dict[str, tuple[str, str]]:
    page = context.new_page()
    page.set_default_timeout(timeout_ms)

    results: dict[str, tuple[str, str]] = {}
    detail_page = context.new_page()
    detail_page.set_default_timeout(timeout_ms)

    def _goto(url: str) -> None:
        page.goto(url, wait_until="networkidle")

    use_button_pagination = bool(next_button_selector.strip())

    def _collect_links() -> tuple[int, int]:
        listing_locator = page.locator(event_selector)
        listing_links: list[str] = []
        for idx in range(listing_locator.count()):
            href = listing_locator.nth(idx).get_attribute("href")
            if href:
                listing_links.append(href)
        if not listing_links:
            logger.warning("Не найдены ссылки событий на странице %s", page.url)
        detail_selector = _to_relative_selector(detail_links_selector)
        added = 0
        for idx, href in enumerate(listing_links):
            coords_absolute = urljoin(page.url, href)
            table_href = None
            detail_href = None
            if idx < listing_locator.count():
                detail_locator = listing_locator.nth(idx).locator(detail_selector)
                if detail_locator.count() > 0:
                    candidate = detail_locator.first.get_attribute("href")
                    if candidate:
                        detail_href = candidate
            if detail_href:
                table_href = detail_href
            else:
                table_href = href
            absolute = urljoin(page.url, table_href)
            normalized = normalize_url(absolute)
            if normalized not in results:
                def _open_detail() -> None:
                    detail_page.goto(coords_absolute, wait_until="networkidle")

                run_with_retries(_open_detail, logger=logger, action_name="загрузка карточки")

                coords_text = ""
                coords_locator = detail_page.locator(coords_selector)
                if coords_locator.count() > 0:
                    coords_text = coords_locator.first.inner_text().strip()

                coords = parse_coordinates(coords_text)
                if not coords:
                    logger.warning("Не найдены координаты для события %s", coords_absolute)
                    continue

                lat, lon = coords
                in_portugal = reverse_geocode_portugal(
                    lat,
                    lon,
                    opencage_base_url,
                    opencage_api_key,
                    opencage_delay_sec,
                    logger,
                )
                if not in_portugal:
                    logger.debug("Событие вне Португалии: %s", absolute)
                    continue

                coord_str = format_coordinates(lat, lon)
                results[normalized] = (absolute, coord_str)
                added += 1
            else:
                logger.debug("Дубликат после нормализации: %s", absolute)
        return len(listing_links), added

    if not use_button_pagination:
        logger.error("SOURCE1_NEXT_BUTTON_SELECTOR не задан, пагинация недоступна")
        page.close()
        detail_page.close()
        return results

    try:
        run_with_retries(lambda: _goto(base_url), logger=logger, action_name="загрузка страницы")
    except PlaywrightTimeoutError as exc:
        logger.error("Таймаут при загрузке %s: %s", base_url, exc)
        page.close()
        detail_page.close()
        return results

    last_marker = ""
    for page_index in range(1, max_pages + 1):
        marker_before = _get_first_event_marker(page, event_selector)
        if marker_before and marker_before == last_marker:
            logger.debug("Маркер списка не изменился, остановка пагинации")
            break
        last_marker = marker_before
        logger.debug("Страница %s, маркер списка до клика: %s", page_index, marker_before)
        raw_count, added_count = _collect_links()
        logger.debug(
            "Страница %s, ссылок в DOM: %s, добавлено уникальных: %s",
            page_index,
            raw_count,
            added_count,
        )

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
    detail_page.close()
    return results
