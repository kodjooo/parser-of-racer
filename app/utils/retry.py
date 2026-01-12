import logging
import time
from collections.abc import Callable
from typing import TypeVar

T = TypeVar("T")


def run_with_retries(
    action: Callable[[], T],
    *,
    retries: int = 3,
    delays: tuple[float, ...] = (2.0, 5.0, 10.0),
    logger: logging.Logger | None = None,
    action_name: str = "операция",
) -> T:
    last_exc: Exception | None = None
    for attempt in range(retries):
        try:
            return action()
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            if logger:
                logger.warning("Сбой при выполнении '%s': %s", action_name, exc)
            if attempt < retries - 1:
                time.sleep(delays[min(attempt, len(delays) - 1)])
    if last_exc:
        raise last_exc
    raise RuntimeError("Не удалось выполнить операцию")
