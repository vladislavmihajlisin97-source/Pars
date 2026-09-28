"""Завантаження медіа (фото, відео, документи...) з дедуплікацією та лімітом розміру."""

from __future__ import annotations

import asyncio
import mimetypes
import re
from pathlib import Path
from typing import Any, Iterable, Optional

from telethon import TelegramClient


DEFAULT_EXT = {
    "photo": "jpg",
    "video": "mp4",
    "gif": "mp4",
    "video_note": "mp4",
    "voice": "ogg",
    "audio": "mp3",
    "sticker": "webp",
}

_UNSAFE_CHARS = re.compile(r"[^\w\-. ]+", flags=re.UNICODE)
_SPACES = re.compile(r"\s+")


def sanitize_filename(name: str, max_length: int = 80) -> str:
    """Безпечне імʼя файлу: без шляхів, керуючих символів і надлишку пробілів."""
    name = _UNSAFE_CHARS.sub("_", (name or "").strip())
    name = _SPACES.sub(" ", name).strip(" ._")
    if len(name) > max_length:
        stem, dot, ext = name[:max_length].rpartition(".")
        if dot and len(ext) <= 5:
            name = f"{stem[: max_length - len(ext) - 1]}.{ext}"
        else:
            name = name[:max_length]
    return name or "file"


class MediaDownloader:
    """Завантажує медіа повідомлень у каталог виводу.

    * дедуплікація однакового контенту (форварди того ж файла не качаємо двічі);
    * пропуск уже завантажених файлів (можливість докачати після обриву);
    * фільтр за типом і максимальним розміром;
    * паралельне завантаження через ``workers``.
    """

    def __init__(
        self,
        client: TelegramClient,
        output_dir: Path,
        media_dir_name: str = "media",
        media_types: Iterable[str] = frozenset(),
        max_size: int = 0,
        workers: int = 4,
        progress: Any = None,
    ) -> None:
        self.client = client
        self.output_dir = Path(output_dir)
        self.media_dir = self.output_dir / media_dir_name
        self.media_types = set(media_types)
        self.max_size = max_size
        self.workers = max(1, workers)
        self.progress = progress  # callable(done, total) або None
        self._seen: dict[tuple, str] = {}
        self.downloaded = 0
        self.skipped_existing = 0
        self.duplicates = 0
        self.errors: list[str] = []

    # -- фільтри ------------------------------------------------------------

    def matches(self, media_dict: dict[str, Any]) -> bool:
        """Чи підходить медіа під фільтри типу/розміру."""
        if not media_dict:
            return False
        if self.media_types and media_dict.get("type") not in self.media_types:
            return False
        if self.max_size:
            size = media_dict.get("size")
            if isinstance(size, int) and size > self.max_size:
                return False
        return True

    # -- імена файлів ---------------------------------------------------------

    def _dedup_key(self, media_dict: dict[str, Any]) -> Optional[tuple]:
        media_id = media_dict.get("id")
        if media_id is None:
            return None
        return (media_dict.get("type"), media_id)

    def _target_path(self, message_id: int, media_dict: dict[str, Any]) -> Path:
        original = media_dict.get("file_name")
        ext: Optional[str] = None
        if original and "." in original:
            ext = original.rsplit(".", 1)[1].lower() or None
        if not ext:
            mime = media_dict.get("mime_type")
            guessed = mimetypes.guess_extension(mime) if mime else None
            if guessed:
                ext = guessed.lstrip(".")
                if ext == "jpe":
                    ext = "jpg"
        if not ext:
            ext = DEFAULT_EXT.get(media_dict.get("type", ""), "bin")

        if original:
            safe = sanitize_filename(original)
            name = f"{message_id}_{safe}"
        else:
            name = f"{message_id}.{ext}"
        return self.media_dir / name

    # -- завантаження ---------------------------------------------------------

    async def _download_one(self, message: Any, media_dict: dict[str, Any]) -> None:
        key = self._dedup_key(media_dict)
        if key and key in self._seen:
            media_dict["file"] = self._seen[key]
            media_dict["duplicate"] = True
            self.duplicates += 1
            return

        path = self._target_path(getattr(message, "id", 0), media_dict)
        if path.exists() and path.stat().st_size > 0:
            relative = path.relative_to(self.output_dir).as_posix()
            media_dict["file"] = relative
            if key:
                self._seen[key] = relative
            self.skipped_existing += 1
            return

        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            result = await message.download_media(file=str(path))
        except Exception as exc:  # FloodWait, мережа, файли-сироти тощо
            media_dict["error"] = f"{type(exc).__name__}: {exc}"
            self.errors.append(f"повідомлення {getattr(message, 'id', '?')}: {exc}")
            return

        if result:
            final = Path(str(result))
            try:
                relative = final.relative_to(self.output_dir).as_posix()
            except ValueError:
                relative = final.name
            media_dict["file"] = relative
            if key:
                self._seen[key] = relative
            self.downloaded += 1
        else:
            media_dict["error"] = "не вдалося завантажити"

    async def run(self, tasks: list[tuple[Any, dict[str, Any]]]) -> None:
        """Завантажити всі (повідомлення, media_dict) пари."""
        if not tasks:
            return
        self.media_dir.mkdir(parents=True, exist_ok=True)
        total = len(tasks)
        done = 0
        semaphore = asyncio.Semaphore(self.workers)

        async def worker(message: Any, media_dict: dict[str, Any]) -> None:
            nonlocal done
            async with semaphore:
                await self._download_one(message, media_dict)
            done += 1
            if self.progress and (done % 10 == 0 or done == total):
                try:
                    self.progress(done, total)
                except Exception:
                    pass

        await asyncio.gather(*(worker(m, d) for m, d in tasks))
