import logging
from collections.abc import Iterable

import requests

from app.utils.retry import run_with_retries


def chunk_lines(lines: Iterable[str], max_chars: int) -> list[str]:
    chunks: list[str] = []
    current: list[str] = []
    current_len = 0

    for line in lines:
        line_len = len(line)
        projected = current_len + line_len + (1 if current else 0)
        if projected > max_chars and current:
            chunks.append("\n".join(current))
            current = [line]
            current_len = line_len
            continue
        if line_len > max_chars and not current:
            chunks.append(line)
            current = []
            current_len = 0
            continue
        current.append(line)
        current_len = projected

    if current:
        chunks.append("\n".join(current))
    return chunks


def send_message(
    token: str,
    chat_id: str,
    text: str,
    logger: logging.Logger,
) -> None:
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {"chat_id": chat_id, "text": text, "disable_web_page_preview": True}

    def _action() -> None:
        response = requests.post(url, data=payload, timeout=30)
        if response.status_code == 429:
            raise RuntimeError("Превышен лимит Telegram")
        if not response.ok:
            raise RuntimeError(f"Ошибка Telegram: {response.status_code} {response.text}")
        logger.info("Telegram ответ: %s", response.text)

    run_with_retries(_action, logger=logger, action_name="отправка Telegram")
