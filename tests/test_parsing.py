"""Інтеграційні тести ChannelParser — повний цикл парсингу з фейковим клієнтом.

Перевіряється головна функція: збір повідомлень, серіалізація, фільтри,
завантаження медіа, статистика та збереження результатів.
"""

import asyncio
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

from telethon.tl.types import (
    Message,
    MessageMediaPhoto,
    Photo,
    PhotoSize,
)

from telegram_parser.exporters import export_result
from telegram_parser.models import ParseOptions
from telegram_parser.parsing import ChannelParser

NOW = datetime(2024, 5, 14, 12, 0, 0, tzinfo=timezone.utc)
FAKE_CHANNEL = SimpleNamespace(
    id=42, title="Тестовий канал", username="testch"
)
FAKE_FULL = SimpleNamespace(
    about="Про канал",
    participants_count=1234,
    exported_invite=SimpleNamespace(link="https://t.me/+invite"),
)


class FakeMessage:
    """Проксі над сирим TL-повідомленням із методом завантаження медіа."""

    def __init__(self, tl_message) -> None:
        self._tl = tl_message

    def __getattr__(self, name):
        return getattr(self._tl, name)

    async def download_media(self, file=None):
        assert file is not None
        Path(file).write_bytes(b"jpeg-bytes")
        return file


def make_photo_message(msg_id: int, date: datetime, text: str) -> FakeMessage:
    photo = Photo(
        id=msg_id * 10, access_hash=1, file_reference=b"", date=date,
        sizes=[PhotoSize(type="x", w=800, h=600, size=50_000)], dc_id=2,
    )
    tl = Message(
        id=msg_id, peer_id=None, date=date, message=text,
        media=MessageMediaPhoto(photo=photo),
    )
    return FakeMessage(tl)


def make_text_message(msg_id: int, date: datetime, text: str) -> FakeMessage:
    return FakeMessage(
        Message(id=msg_id, peer_id=None, date=date, message=text)
    )


class FakeClient:
    def __init__(self, messages) -> None:
        self.messages = messages  # від нових до старих
        self.iter_kwargs: dict | None = None
        self.iter_entity = None

    async def get_entity(self, ref):
        return FAKE_CHANNEL

    async def __call__(self, request):  # GetFullChannelRequest
        return SimpleNamespace(full_chat=FAKE_FULL)

    def iter_messages(self, entity, **kwargs):
        self.iter_kwargs = kwargs
        self.iter_entity = entity

        async def generator():
            for message in self.messages:
                yield message

        return generator()


def run(coro):
    return asyncio.run(coro)


def make_messages():
    return [
        make_photo_message(3, NOW, "нове фото"),
        make_text_message(2, NOW - timedelta(days=1), "пост №2"),
        make_text_message(1, NOW - timedelta(days=2), "пост №1"),
    ]


def test_full_parse_with_media_and_export(tmp_path):
    client = FakeClient(make_messages())
    options = ParseOptions(
        download_media=True,
        output_root=tmp_path,
        media_workers=2,
    )
    result = run(ChannelParser(client, options, log=lambda *_: None).parse("testch"))

    # каталог виводу названо за username каналу
    assert result.output_dir == tmp_path / "testch"
    assert result.output_dir.is_dir()

    # інформація про канал з GetFullChannelRequest
    assert result.channel["title"] == "Тестовий канал"
    assert result.channel["participants_count"] == 1234
    assert result.channel["invite_link"] == "https://t.me/+invite"

    # повідомлення: від нових до старих
    assert [m["id"] for m in result.messages] == [3, 2, 1]
    assert result.messages[0]["type"] == "photo"

    # медіа завантажено і шлях записано у медіа-словник
    media = result.messages[0]["media"]
    assert media["file"] == "media/3.jpg"
    assert (tmp_path / "testch" / "media" / "3.jpg").read_bytes() == b"jpeg-bytes"

    # статистика
    assert result.stats["total_messages"] == 3
    assert result.stats["with_media"] == 1
    assert result.stats["media"]["downloaded"] == 1
    assert result.stats["by_type"] == {"photo": 1, "text": 2}

    # експорт у всі формати
    written = export_result(result, result.output_dir, formats=("json", "jsonl", "csv"))
    assert len(written) == 4
    payload = json.loads((tmp_path / "testch" / "messages.json").read_text("utf-8"))
    assert payload["channel"]["username"] == "testch"
    assert payload["messages"][0]["media"]["file"] == "media/3.jpg"


def test_iter_kwargs_passthrough(tmp_path):
    client = FakeClient(make_messages())
    options = ParseOptions(limit=2, min_id=1, reverse=True, output_root=tmp_path)
    run(ChannelParser(client, options, log=lambda *_: None).parse("testch"))
    kwargs = client.iter_kwargs
    assert kwargs["limit"] == 2
    assert kwargs["min_id"] == 1
    assert kwargs["reverse"] is True


def test_url_with_message_id_sets_max_id(tmp_path):
    client = FakeClient(make_messages())
    options = ParseOptions(output_root=tmp_path)
    run(ChannelParser(client, options, log=lambda *_: None).parse("https://t.me/testch/2"))
    assert client.iter_kwargs["max_id"] == 2


def test_date_filter_since(tmp_path):
    client = FakeClient(make_messages())
    cutoff = NOW - timedelta(hours=12)  # лишає лише повідомлення новіші за 12 год
    options = ParseOptions(since=cutoff, output_root=tmp_path)
    result = run(ChannelParser(client, options, log=lambda *_: None).parse("testch"))
    assert [m["id"] for m in result.messages] == [3]


def test_date_filter_until(tmp_path):
    client = FakeClient(make_messages())
    cutoff = NOW - timedelta(hours=12)  # id=2 і id=1 старіші за відсічку
    options = ParseOptions(until=cutoff, output_root=tmp_path)
    result = run(ChannelParser(client, options, log=lambda *_: None).parse("testch"))
    assert [m["id"] for m in result.messages] == [2, 1]


def test_media_type_filter(tmp_path):
    client = FakeClient(make_messages())
    options = ParseOptions(
        download_media=True, output_root=tmp_path,
        media_types=frozenset({"video"}),  # фото не проходимить фільтр
    )
    result = run(ChannelParser(client, options, log=lambda *_: None).parse("testch"))
    assert "file" not in result.messages[0]["media"]
    assert not (tmp_path / "testch" / "media").exists() or \
        not list((tmp_path / "testch" / "media").iterdir())


def test_existing_media_not_redownloaded(tmp_path):
    client = FakeClient(make_messages())
    options = ParseOptions(download_media=True, output_root=tmp_path)
    # файл уже існує — завантаження має пропуститися
    media_dir = tmp_path / "testch" / "media"
    media_dir.mkdir(parents=True)
    existing = media_dir / "3.jpg"
    existing.write_bytes(b"old")

    result = run(ChannelParser(client, options, log=lambda *_: None).parse("testch"))
    assert existing.read_bytes() == b"old"
    assert result.stats["media"]["skipped_existing"] == 1
