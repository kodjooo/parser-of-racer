import asyncio
import logging
import os
from collections.abc import Iterable

from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.tl.types import PeerChannel, PeerChat

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
    api_id: int,
    api_hash: str,
    session_path: str,
    session_string: str | None,
    target: str,
    text: str,
    logger: logging.Logger,
) -> None:
    def _resolve_target() -> PeerChat | PeerChannel | str:
        if not target:
            return target
        if target.startswith("@"):
            return target
        if target.lstrip("-").isdigit():
            chat_id = int(target)
            if str(chat_id).startswith("-100"):
                return PeerChannel(abs(chat_id))
            return PeerChat(abs(chat_id))
        return target

    async def _send() -> None:
        if session_string:
            client = TelegramClient(StringSession(session_string), api_id, api_hash)
        else:
            client = TelegramClient(session_path, api_id, api_hash)

        async with client:
            if not await client.is_user_authorized():
                raise RuntimeError(
                    "Сессия Telegram не авторизована. Сначала выполните локальный вход и перенесите файл/строку сессии."
                )
            await client.send_message(
                _resolve_target(),
                text,
                link_preview=False,
                parse_mode="html",
            )

    def _action() -> None:
        asyncio.run(_send())
        logger.info("Сообщение отправлено через Telethon")

    run_with_retries(_action, logger=logger, action_name="отправка Telegram")
