import logging
from urllib.parse import urljoin

from playwright.sync_api import BrowserContext

from app.integrations.url_normalize import normalize_url
from app.utils.retry import run_with_retries


def _extract_month_links(page, list_selector: str, link_selector: str) -> list[str]:
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


def scrape_source2(
    context: BrowserContext,
    base_url: str,
    next_button_selector: str,
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
        links = _extract_month_links(page, list_selector, link_selector)
        if not links:
            logger.warning("Не найдены события в месяце %s", index + 1)
        for href in links:
            absolute = urljoin(page.url, href)
            normalized = normalize_url(absolute)
            results.setdefault(normalized, absolute)

        if index == 12:
            break

        marker_before = _get_month_marker(page)
        links_before = set(_extract_month_links(page, list_selector, link_selector))

        def _click_next() -> None:
            page.click(next_button_selector)

        run_with_retries(_click_next, logger=logger, action_name="переход на следующий месяц")

        def _wait_for_change() -> None:
            try:
                page.wait_for_function(
                    "(selector, previous) => {"
                    "const el = document.querySelector(selector);"
                    "if (!el) { return false; }"
                    "const text = (el.textContent || '').trim();"
                    "return text && text !== previous;"
                    "}",
                    arg=["#evcal_cur", marker_before],
                    timeout=timeout_ms,
                )
                return
            except Exception:
                pass

            page.wait_for_timeout(800)
            links_after = set(_extract_month_links(page, list_selector, link_selector))
            if links_after == links_before:
                raise RuntimeError("Не удалось дождаться смены месяца")

        try:
            run_with_retries(_wait_for_change, logger=logger, action_name="ожидание смены месяца")
        except Exception:
            logger.warning("Переход месяца может быть неочевиден, продолжаем")

    page.close()
    return results
