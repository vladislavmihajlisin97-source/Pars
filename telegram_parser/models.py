"""Моделі даних парсера: опції запуску та результат парсингу."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional


@dataclass
class ParseOptions:
    """Опції одного запуску парсера.

    ``limit`` / ``min_id`` / ``max_id`` / ``since`` / ``until`` — фільтри
    діапазону повідомлень. Якщо нічого не задано — парситься *весь* канал.
    """

    limit: int = 0                 # 0 = без обмежень (усі повідомлення)
    min_id: int = 0                 # парсити повідомлення з id > min_id
    max_id: int = 0                 # парсити повідомлення з id <= max_id
    since: Optional[datetime] = None  # тільки повідомлення новіші за цю дату
    until: Optional[datetime] = None  # тільки повідомлення старіші за цю дату
    reverse: bool = False           # True = від старих до нових
    output_root: Optional[Path] = None  # кореневий каталог виводу (default: output)

    # Завантаження медіа
    download_media: bool = False
    media_dir_name: str = "media"   # підкаталог всередині каталогу виводу
    media_types: frozenset[str] = frozenset()  # порожньо = усі типи
    max_media_size: int = 0         # байти; 0 = без обмеження
    media_workers: int = 4          # паралельні завантаження

    def iter_kwargs(self) -> dict[str, Any]:
        """Аргументи для ``client.iter_messages``."""
        kwargs: dict[str, Any] = {}
        if self.limit:
            kwargs["limit"] = self.limit
        if self.min_id:
            kwargs["min_id"] = self.min_id
        if self.max_id:
            kwargs["max_id"] = self.max_id
        kwargs["reverse"] = self.reverse
        return kwargs


@dataclass
class ParseResult:
    """Результат парсингу каналу: інформація про канал + список повідомлень."""

    channel: dict[str, Any]
    messages: list[dict[str, Any]] = field(default_factory=list)
    stats: dict[str, Any] = field(default_factory=dict)
    mode: str = "api"               # "api" або "web"
    output_dir: Optional[Path] = None  # каталог, куди збережено результати

    @property
    def parsed_at(self) -> str:
        return datetime.now(timezone.utc).isoformat(timespec="seconds")
