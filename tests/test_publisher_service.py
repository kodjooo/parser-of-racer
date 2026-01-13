"""Тесты сервиса публикаций."""

from unittest.mock import MagicMock

import pytest

pytest.importorskip("publisher", reason="Модуль publisher не используется в этом проекте")

from publisher.gs.sheets import RSSRow, SetkaRow, VKRow
from publisher.services.publisher import PublisherService
from publisher.tg.client import TelegramClient


@pytest.fixture()
def clients():
    sheets = MagicMock()
    telegraph = MagicMock()
    vk = MagicMock()
    telegram = MagicMock()
    service = PublisherService(sheets, telegraph, vk, telegram)
    return sheets, telegraph, vk, telegram, service


def test_process_rss_flow_success(clients):
    sheets, telegraph, vk, telegram, service = clients
    row = RSSRow(
        row_number=2,
        gpt_post_title="Заголовок статьи",
        gpt_post="Заголовок статьи\n\nОсновной текст",
        short_post="Короткая версия\n\nЧитать подробнее > https://example.com",
        average_post="",
        link="https://source.example",
        image_url="https://example.com/image.jpg",
        telegraph_link="",
        vk_post_link="",
        telegram_post_link="",
        status="Revised",
    )
    sheets.fetch_rss_ready_rows.return_value = [row]
    telegraph.create_page.return_value = "https://telegra.ph/page"
    vk.get_short_link.return_value = "vk.cc/short"
    vk.publish_post.return_value = "https://vk.com/wall-1_1"
    telegram.send_post.return_value = "https://t.me/channel/1"

    service.process_rss_flow()

    telegraph.create_page.assert_called_once_with(title="Заголовок статьи", gpt_post=row.gpt_post, image_url=row.image_url)
    vk.get_short_link.assert_called_once_with("https://telegra.ph/page")
    vk.publish_post.assert_called_once()
    vk_message = vk.publish_post.call_args[0][0]
    assert vk_message.startswith("#Обзор_Новостей")
    assert "Заголовок статьи" in vk_message.splitlines()[1]
    assert "Читать подробнее > vk.cc/short" in vk_message
    telegram.send_post.assert_called_once_with(
        "#Обзор_Новостей\nЗаголовок статьи\n\nКороткая версия",
        row.image_url,
        "https://telegra.ph/page",
        add_spacing=True,
        link_label="Читать подробнее >",
    )
    sheets.update_rss_row.assert_called_once_with(row, "https://telegra.ph/page", "https://vk.com/wall-1_1", "https://t.me/channel/1")
    sheets.write_rss_error.assert_not_called()


def test_process_rss_flow_uses_existing_telegraph_link(clients):
    sheets, telegraph, vk, telegram, service = clients
    row = RSSRow(
        row_number=3,
        gpt_post_title="",
        gpt_post="Существующий пост",
        short_post="Коротко\n\nЧитать подробнее > https://example.com",
        average_post="",
        link="",
        image_url="https://example.com/image.jpg",
        telegraph_link="https://telegra.ph/existing",
        vk_post_link="",
        telegram_post_link="",
        status="Revised",
    )
    sheets.fetch_rss_ready_rows.return_value = [row]
    vk.get_short_link.return_value = "vk.cc/existing"
    vk.publish_post.return_value = "https://vk.com/wall-1_2"
    telegram.send_post.return_value = "https://t.me/channel/2"

    service.process_rss_flow()

    telegraph.create_page.assert_not_called()
    sheets.update_rss_row.assert_called_once_with(row, "https://telegra.ph/existing", "https://vk.com/wall-1_2", "https://t.me/channel/2")
    vk.get_short_link.assert_called_once_with("https://telegra.ph/existing")
    telegram.send_post.assert_called_once_with(
        "#Обзор_Новостей\n\nКоротко",
        row.image_url,
        "https://telegra.ph/existing",
        add_spacing=True,
        link_label="Читать подробнее >",
    )
    vk_message = vk.publish_post.call_args[0][0]
    assert vk_message.startswith("#Обзор_Новостей")
    assert "Читать подробнее > vk.cc/existing" in vk_message


def test_process_rss_flow_average_post_mode(clients):
    sheets, telegraph, vk, telegram, _ = clients
    service = PublisherService(sheets, telegraph, vk, telegram, use_average_post=True)
    row = RSSRow(
        row_number=7,
        gpt_post_title="Средний заголовок",
        gpt_post="Полная версия текста",
        short_post="",
        average_post="Основной средний текст\n\nИсточник >",
        link="https://example.com/source",
        image_url="https://example.com/image.jpg",
        telegraph_link="",
        vk_post_link="",
        telegram_post_link="",
        status="Revised",
    )
    sheets.fetch_rss_ready_rows.return_value = [row]
    telegraph.create_page.return_value = "https://telegra.ph/page"
    vk.get_short_link.return_value = "vk.cc/source"
    vk.publish_post.return_value = "https://vk.com/wall-1_77"
    telegram.send_post.return_value = "https://t.me/channel/77"

    service.process_rss_flow()

    vk.get_short_link.assert_called_once_with("https://example.com/source")
    vk_message = vk.publish_post.call_args[0][0]
    assert "Источник > vk.cc/source" in vk_message
    telegram.send_post.assert_called_once_with(
        "#Обзор_Новостей\nСредний заголовок\n\nОсновной средний текст",
        row.image_url,
        "https://example.com/source",
        add_spacing=True,
        link_label="Источник >",
    )
    sheets.update_rss_row.assert_called_once()


def test_process_rss_flow_handles_errors(clients):
    sheets, telegraph, vk, telegram, service = clients
    row = RSSRow(
        row_number=4,
        gpt_post_title="",
        gpt_post="Текст",
        short_post="Коротко",
        average_post="",
        link="",
        image_url="https://example.com/image.jpg",
        telegraph_link="",
        vk_post_link="",
        telegram_post_link="",
        status="Revised",
    )
    sheets.fetch_rss_ready_rows.return_value = [row]
    telegraph.create_page.return_value = "https://telegra.ph/page"
    vk.publish_post.side_effect = RuntimeError("Ошибка VK")

    service.process_rss_flow()

    sheets.write_rss_error.assert_called_once()
    sheets.update_rss_row.assert_not_called()


def test_process_vk_flow_success(clients):
    sheets, _, vk, _, service = clients
    row = VKRow(
        row_number=5,
        title="Заголовок",
        content="Содержимое",
        image_url="https://example.com/image.jpg",
        post_link="",
        status="Revised",
    )
    sheets.fetch_vk_rows.return_value = [row]
    vk.publish_post.return_value = "https://vk.com/wall-1_3"

    service.process_vk_flow()

    vk.publish_post.assert_called_once()
    sheets.mark_vk_published.assert_called_once_with(row, "https://vk.com/wall-1_3")


def test_process_rss_flow_processes_only_first_row(clients):
    sheets, telegraph, vk, telegram, service = clients
    row1 = RSSRow(
        row_number=10,
        gpt_post_title="",
        gpt_post="Пост 1",
        short_post="Пост 1 коротко",
        average_post="",
        link="",
        image_url="https://example.com/img1.jpg",
        telegraph_link="",
        vk_post_link="",
        telegram_post_link="",
        status="Revised",
    )
    row2 = RSSRow(
        row_number=11,
        gpt_post_title="",
        gpt_post="Пост 2",
        short_post="Пост 2 коротко",
        average_post="",
        link="",
        image_url="https://example.com/img2.jpg",
        telegraph_link="",
        vk_post_link="",
        telegram_post_link="",
        status="Revised",
    )
    sheets.fetch_rss_ready_rows.return_value = [row1, row2]
    telegraph.create_page.return_value = "https://telegra.ph/post1"
    vk.get_short_link.return_value = "vk.cc/one"
    vk.publish_post.return_value = "https://vk.com/wall-1_10"
    telegram.send_post.return_value = "https://t.me/channel/10"

    service.process_rss_flow()

    sheets.update_rss_row.assert_called_once_with(row1, "https://telegra.ph/post1", "https://vk.com/wall-1_10", "https://t.me/channel/10")
    vk.publish_post.assert_called_once()
    telegraph.create_page.assert_called_once()
    telegram.send_post.assert_called_once()


def test_process_setka_flow_success(clients):
    sheets, _, _, telegram, service = clients
    row = SetkaRow(
        row_number=6,
        title="Заголовок",
        content="Содержимое",
        image_url="https://example.com/image.jpg",
        post_link="",
        status="Revised",
    )
    sheets.fetch_setka_rows.return_value = [row]
    telegram.send_post.return_value = "https://t.me/channel/3"

    service.process_setka_flow()

    telegram.send_post.assert_called_once_with("Содержимое", row.image_url, add_spacing=True)
    sheets.mark_setka_published.assert_called_once_with(row, "https://t.me/channel/3")


def test_process_setka_flow_long_message_without_photo(clients):
    sheets, _, _, telegram, service = clients
    long_content = "A" * (TelegramClient.CAPTION_LIMIT + 10)
    row = SetkaRow(
        row_number=8,
        title="Заголовок",
        content=long_content,
        image_url="https://example.com/image.jpg",
        post_link="",
        status="Revised",
    )
    sheets.fetch_setka_rows.return_value = [row]
    telegram.send_post.return_value = "https://t.me/channel/8"

    service.process_setka_flow()

    telegram.send_post.assert_called_once_with(long_content, None, add_spacing=False)
    sheets.mark_setka_published.assert_called_once_with(row, "https://t.me/channel/8")
