"""Головна логіка: повний парсинг телеграм-каналу через MTProto API."""

from __future__ import annotations

import asyncio
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Optional

from telethon import TelegramClient
from telethon.errors import FloodWaitError
from telethon.tl.functions.channels import GetFullChannelRequest

from .media import MediaDownloader
from .models import ParseOptions, ParseResult
from .serialize import serialize_channel, serialize_message
from .utils import parse_channel_ref, safe_dir_name

PROGRESS_EVERY = 200  # логувати прогрес кожні N повідомлень


class ChannelParser:
    """Повне витягування вмісту каналу: повідомлення + медіа + статистика."""

    def __init__(
        self,
        client: TelegramClient,
        options: ParseOptions,
        log: Callable[[str], None] = print,
    ) -> None:
        self.client = client
        self.options = options
        self.log = log

    # -- розвʼязання каналу ---------------------------------------------------

    async def resolve_channel(self, channel_ref: str) -> Any:
        """Перетворити посилання/@username/id в обʼєкт Entity."""
        name, _ = parse_channel_ref(channel_ref)

        # звичайні посилання-запрошення (+AbCdHash) API не розвʼязує напряму
        if name.startswith("+"):
            raise ValueError(
                f"Посилання-запрошення ({channel_ref!r}) неможливо розпарсити напряму.\n"
                "Спочатку приєднайтесь до каналу у застосунку Telegram, а потім "
                "вкажіть його @username або ідентифікатор."
            )

        try:
            entity = await self.client.get_entity(name)
        except ValueError as exc:
            raise ValueError(
                f"Не вдалося знайти канал {channel_ref!r}.\n"
                "Перевірте назву, або (для приватних каналів за числовим id) "
                " переконайтесь, що ця сесія раніше «бачила» канал — наприклад, "
                "ви його підписник."
            ) from exc
        return entity

    async def _channel_full(self, entity: Any) -> Optional[Any]:
        try:
            result = await self.client(GetFullChannelRequest(entity))
            return getattr(result, "full_chat", None)
        except Exception:
            return None

    async def channel_info(self, channel_ref: str) -> dict[str, Any]:
        """Інформація про канал: назва, username, опис, к-сть підписників."""
        entity = await self.resolve_channel(channel_ref)
        full = await self._channel_full(entity)
        return serialize_channel(entity, full)

    # -- парсинг ---------------------------------------------------------------

    def _date_filters_active(self) -> bool:
        return self.options.since is not None or self.options.until is not None

    def _date_ok(self, date: Optional[datetime]) -> Optional[bool]:
        """None = пропустити перевірку; True = підходить; False = відсіяти."""
        if date is None:
            return True
        since, until = self.options.since, self.options.until
        if since is not None and date < since:
            return False
        if until is not None and date > until:
            return False
        return True

    async def parse(self, channel_ref: str) -> ParseResult:
        started = time.monotonic()
        entity = await self.resolve_channel(channel_ref)
        # якщо в посиланні був id конкретного повідомлення — парсимо до нього
        name, message_hint = parse_channel_ref(channel_ref)
        max_id = self.options.max_id or message_hint or 0

        full = await self._channel_full(entity)
        channel_info = serialize_channel(entity, full)
        self.log(
            f"Канал: {channel_info.get('title') or name} "
            f"(id={channel_info.get('id')}, @{channel_info.get('username') or '—'})"
        )
        if full is not None and channel_info.get("participants_count") is not None:
            self.log(f"Підписників: {channel_info['participants_count']:,}")

        options = self.options
        output_root = Path(options.output_root or "output")
        out_dir = output_root / safe_dir_name(
            channel_info.get("username")
            or channel_info.get("title")
            or name
        )
        out_dir.mkdir(parents=True, exist_ok=True)

        downloader: Optional[MediaDownloader] = None
        if options.download_media:
            downloader = MediaDownloader(
                client=self.client,
                output_dir=out_dir,
                media_dir_name=options.media_dir_name,
                media_types=options.media_types,
                max_size=options.max_media_size,
                workers=options.media_workers,
                progress=lambda done, total: self.log(
                    f"  медіа: {done}/{total}"
                ),
            )

        messages: list[dict[str, Any]] = []
        media_tasks: list[tuple[Any, dict[str, Any]]] = []

        iter_kwargs = options.iter_kwargs()
        if max_id and "max_id" not in iter_kwargs:
            iter_kwargs["max_id"] = max_id

        date_stop_hint = (
            " з фільтром за датою" if self._date_filters_active() else ""
        )
        self.log(
            f"Збираю повідомлення{' (усі)' if not options.limit else f' (ліміт {options.limit})'}"
            f"{' від старих до нових' if options.reverse else ' (від нових до старих)'}"
            f"{date_stop_hint}..."
        )

        async for message in self.client.iter_messages(entity, **iter_kwargs):
            date = getattr(message, "date", None)
            date_ok = self._date_ok(date)
            if not date_ok:
                # ітеруємо від нових до старих: досягли нижньої межі дати — стоп
                if not options.reverse and options.since is not None:
                    break
                continue

            data = serialize_message(message, entity)
            messages.append(data)

            if downloader is not None:
                media_dict = data.get("media")
                if media_dict and downloader.matches(media_dict):
                    media_tasks.append((message, media_dict))

            if len(messages) % PROGRESS_EVERY == 0:
                oldest = data.get("date") or "?"
                self.log(f"  зібрано {len(messages):,} (дійшов до {oldest})")

            if options.limit and len(messages) >= options.limit:
                break

        # завантаження медіа окремим етапом (паралельно)
        if downloader is not None and media_tasks:
            self.log(f"Завантажую медіа: {len(media_tasks)} файлів...")
            try:
                await downloader.run(media_tasks)
            except FloodWaitError as exc:  # на випадок тривалих flood-wait
                wait = min(getattr(exc, "seconds", 60), 300)
                self.log(f"  Telegram просить зачекати {wait} c — чекаю...")
                await asyncio.sleep(wait)
                await downloader.run(media_tasks)

        stats = self._build_stats(
            messages, downloader, time.monotonic() - started
        )
        result = ParseResult(
            channel=channel_info,
            messages=messages,
            stats=stats,
            mode="api",
            output_dir=out_dir,
        )
        self.log(self._summary(result))
        return result

    # -- вивід ------------------------------------------------------------------

    @staticmethod
    def _build_stats(
        messages: list[dict[str, Any]],
        downloader: Optional[MediaDownloader],
        elapsed: float,
    ) -> dict[str, Any]:
        by_type: dict[str, int] = {}
        with_media = 0
        text_chars = 0
        dates = [m["date"] for m in messages if m.get("date")]

        for m in messages:
            by_type[m.get("type", "?")] = by_type.get(m.get("type", "?"), 0) + 1
            if m.get("has_media"):
                with_media += 1
            text_chars += len(m.get("text") or "")

        stats: dict[str, Any] = {
            "total_messages": len(messages),
            "by_type": dict(sorted(by_type.items(), key=lambda kv: -kv[1])),
            "with_media": with_media,
            "text_characters": text_chars,
            "earliest_date": min(dates) if dates else None,
            "latest_date": max(dates) if dates else None,
            "elapsed_seconds": round(elapsed, 1),
        }
        if downloader is not None:
            stats["media"] = {
                "downloaded": downloader.downloaded,
                "skipped_existing": downloader.skipped_existing,
                "duplicates": downloader.duplicates,
                "errors": len(downloader.errors),
            }
            if downloader.errors:
                stats["media"]["error_details"] = downloader.errors[:50]
        return stats

    def _summary(self, result: ParseResult) -> str:
        stats = result.stats
        lines = [
            f"Готово: {stats['total_messages']:,} повідомлень "
            f"за {stats['elapsed_seconds']} c",
        ]
        type_parts = [f"{k}: {v:,}" for k, v in stats["by_type"].items()]
        if type_parts:
            lines.append("  типи: " + ", ".join(type_parts))
        if stats.get("media"):
            media = stats["media"]
            lines.append(
                f"  медіа: завантажено {media['downloaded']}, "
                f"пропущено (вже є) {media['skipped_existing']}, "
                f"дублікатів {media['duplicates']}, помилок {media['errors']}"
            )
        return "\n".join(lines)
