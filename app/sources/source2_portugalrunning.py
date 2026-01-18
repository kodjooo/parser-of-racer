import logging
import time
from urllib.parse import urljoin

from playwright.sync_api import BrowserContext

from app.integrations.url_normalize import normalize_url
from app.utils.retry import run_with_retries


def _extract_month_listing_links(page, list_selector: str) -> list[str]:
    locator = page.locator(list_selector)
    links: list[str] = []
    for idx in range(locator.count()):
        href = locator.nth(idx).get_attribute("href")
        if href:
            links.append(href)
    return links


def _extract_detail_links(page, list_selector: str, link_selector: str) -> list[str]:
    links: list[str] = []
    list_locator = page.locator(list_selector)
    for idx in range(list_locator.count()):
        event_locator = list_locator.nth(idx).locator(link_selector)
        for jdx in range(event_locator.count()):
            href = event_locator.nth(jdx).get_attribute("href")
            if href:
                links.append(href)
    return links


def _get_month_marker(page) -> str:
    selectors = [
        "#evcal_cur",
        ".eventon_fullcal .evo_month_title",
        ".eventon_fullcal .evcal_month_line",
        "#evcal_head",
    ]
    for selector in selectors:
        locator = page.locator(selector)
        if locator.count() > 0:
            text = locator.first.inner_text().strip()
            if text:
                return text
    first_link_locator = page.locator("a.evcal_evdata_row")
    if first_link_locator.count() > 0:
        href = first_link_locator.first.get_attribute("href")
        if href:
            return href
    return ""


def _get_all_month_markers(page) -> list[str]:
    locator = page.locator("#evcal_cur")
    markers: list[str] = []
    for idx in range(locator.count()):
        text = locator.nth(idx).inner_text().strip()
        if text:
            markers.append(text)
    return markers


def scrape_source2(
    context: BrowserContext,
    base_url: str,
    next_button_selector: str,
    month_list_links_selector: str,
    list_selector: str,
    link_selector: str,
    timeout_ms: int,
    logger: logging.Logger,
) -> dict[str, str]:
    page = context.new_page()
    page.set_default_timeout(timeout_ms)

    run_with_retries(lambda: page.goto(base_url, wait_until="networkidle"), logger=logger, action_name="загрузка календаря")
    page.wait_for_selector(next_button_selector)

    results: dict[str, str] = {}
    for index in range(13):
        listing_links = _extract_month_listing_links(page, month_list_links_selector)
        if not listing_links:
            logger.warning("Не найдены ссылки карточек в месяце %s", index + 1)

        for href in listing_links:
            absolute = urljoin(page.url, href)
            detail_page = context.new_page()
            detail_page.set_default_timeout(timeout_ms)

            def _open_detail() -> None:
                detail_page.goto(absolute, wait_until="networkidle")

            run_with_retries(_open_detail, logger=logger, action_name="загрузка карточки")
            detail_links = _extract_detail_links(detail_page, list_selector, link_selector)
            if not detail_links:
                logger.warning("Не найдены ссылки событий в карточке %s", absolute)
            for detail_href in detail_links:
                detail_absolute = urljoin(detail_page.url, detail_href)
                normalized = normalize_url(detail_absolute)
                if normalized not in results:
                    logger.debug("Итоговая ссылка события: %s", detail_absolute)
                    results[normalized] = detail_absolute
            detail_page.close()

        if index == 12:
            break

        marker_before = _get_month_marker(page)
        links_before = set(_extract_month_listing_links(page, month_list_links_selector))
        logger.debug("Маркер месяца до клика: %s", marker_before)

        def _click_next() -> None:
            page.click(next_button_selector)

        run_with_retries(_click_next, logger=logger, action_name="переход на следующий месяц")

        def _wait_for_change() -> None:
            deadline = time.monotonic() + 10
            while time.monotonic() < deadline:
                marker_after = _get_month_marker(page)
                if marker_after and marker_after != marker_before:
                    logger.debug("Маркер месяца после клика: %s", marker_after)
                    return
                page.wait_for_timeout(500)

            markers = _get_all_month_markers(page)
            logger.debug("Маркер месяца не изменился, текущие значения: %s", markers)

            page.wait_for_timeout(800)
            links_after = set(_extract_month_listing_links(page, month_list_links_selector))
            if links_after == links_before:
                raise RuntimeError("Не удалось дождаться смены месяца")

        try:
            run_with_retries(
                _wait_for_change,
                logger=logger,
                action_name="ожидание смены месяца",
                delays=(10.0, 10.0, 10.0),
            )
        except Exception:
            logger.warning("Переход месяца может быть неочевиден, продолжаем")

    page.close()
    return results
