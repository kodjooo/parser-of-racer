import json
import os
from datetime import datetime, timezone
from typing import Any


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_state(path: str) -> dict[str, Any]:
    if not os.path.exists(path):
        return {"notified": {}}
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def save_state(path: str, state: dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(state, handle, ensure_ascii=False, indent=2)


def get_notified_set(state: dict[str, Any]) -> set[str]:
    return set(state.get("notified", {}).keys())


def add_notified(
    state: dict[str, Any],
    normalized_urls: set[str],
    source: str,
) -> None:
    now = _now_iso()
    notified = state.setdefault("notified", {})
    for url in normalized_urls:
        notified[url] = {
            "first_seen_at": notified.get(url, {}).get("first_seen_at", now),
            "last_notified_at": now,
            "source": source,
        }


def prune_known(state: dict[str, Any], known_urls: set[str]) -> None:
    notified = state.get("notified", {})
    for url in list(notified.keys()):
        if url in known_urls:
            notified.pop(url, None)
