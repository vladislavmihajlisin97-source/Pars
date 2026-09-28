"""Дрібні спільні допоміжні функції."""

from __future__ import annotations

import re
from typing import Tuple
from urllib.parse import urlparse

_UNSAFE_DIR = re.compile(r"[^\w\-]+", flags=re.UNICODE)


def parse_channel_ref(ref: str) -> Tuple[str, int]:
    """Нормалізувати посилання на канал.

    Підтримує: ``@username``, ``username``, ``https://t.me/username``,
    ``https://t.me/username/123`` (123 -> підказка max_id),
    приватні ідентифікатори (``-100...``) і ``joinchat``-хеші.

    Повертає ``(назва_каналу, підказка_max_id)``.
    """
    value = (ref or "").strip()
    if not value:
        raise ValueError("Не задано канал.")

    if value.startswith(("http://", "https://")):
        path = urlparse(value).path.strip("/")
        parts = [p for p in path.split("/") if p]
        if not parts:
            raise ValueError(f"Не вдалося розібрати посилання: {ref!r}")
        name = parts[0]
        message_id = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 0
        return name, message_id
    if value.startswith("@"):
        return value[1:], 0
    if value.startswith("t.me/"):
        return parse_channel_ref("https://" + value)
    return value, 0


def safe_dir_name(name: str, fallback: str = "channel") -> str:
    """Безпечна назва каталогу для результатів (кирилиця дозволена)."""
    cleaned = _UNSAFE_DIR.sub("_", (name or "").strip()).strip("_")
    return cleaned[:64] or fallback
