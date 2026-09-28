"""Тести серіалізації обʼєктів Telethon у словники (офлайн, без мережі)."""

from datetime import datetime, timezone
from types import SimpleNamespace

from telethon.tl.types import (
    Document,
    DocumentAttributeAudio,
    DocumentAttributeFilename,
    DocumentAttributeVideo,
    Message,
    MessageFwdHeader,
    MessageMediaDocument,
    MessageMediaPhoto,
    MessageReplyHeader,
    MessageReactions,
    MessageService,
    MessageActionChatEditTitle,
    Photo,
    PhotoSize,
    ReactionCount,
    ReactionEmoji,
)

from telegram_parser.serialize import (
    classify_media,
    serialize_message,
    to_iso,
)

DT = datetime(2024, 5, 14, 12, 0, 0, tzinfo=timezone.utc)
ENTITY = SimpleNamespace(id=123456, title="Тестовий канал", username="testchannel")


def make_photo_message() -> Message:
    photo = Photo(
        id=10,
        access_hash=1,
        file_reference=b"",
        date=DT,
        sizes=[
            PhotoSize(type="m", w=320, h=240, size=12_000),
            PhotoSize(type="x", w=800, h=600, size=50_000),
        ],
        dc_id=2,
    )
    return Message(
        id=1, peer_id=None, date=DT, message="Фото",
        media=MessageMediaPhoto(photo=photo),
    )


def make_video_message() -> Message:
    document = Document(
        id=20, access_hash=1, file_reference=b"", date=DT,
        mime_type="video/mp4", size=10_000_000, dc_id=2,
        attributes=[
            DocumentAttributeVideo(duration=12, w=1280, h=720),
            DocumentAttributeFilename("clip.mp4"),
        ],
    )
    return Message(
        id=2, peer_id=None, date=DT, message="Відео",
        media=MessageMediaDocument(document=document),
    )


def make_voice_message() -> Message:
    document = Document(
        id=21, access_hash=1, file_reference=b"", date=DT,
        mime_type="audio/ogg", size=5_000, dc_id=2,
        attributes=[DocumentAttributeAudio(duration=3, voice=True)],
    )
    return Message(
        id=3, peer_id=None, date=DT, message="",
        media=MessageMediaDocument(document=document),
    )


def test_to_iso_naive_and_aware():
    assert to_iso(None) is None
    naive = datetime(2024, 1, 1, 10, 0, 0)
    assert to_iso(naive) == "2024-01-01T10:00:00+00:00"
    assert to_iso(DT) == "2024-05-14T12:00:00+00:00"


def test_text_message():
    message = Message(id=5, peer_id=None, date=DT, message="Привіт")
    data = serialize_message(message, ENTITY)
    assert data["id"] == 5
    assert data["type"] == "text"
    assert data["text"] == "Привіт"
    assert data["has_media"] is False
    assert data["date"] == "2024-05-14T12:00:00+00:00"
    assert data["link"] == "https://t.me/testchannel/5"
    assert "media" not in data


def test_photo_message():
    data = serialize_message(make_photo_message(), ENTITY)
    assert data["type"] == "photo"
    media = data["media"]
    assert media["width"] == 800 and media["height"] == 600
    assert media["size"] == 50_000
    assert media["id"] == 10
    assert data["link"] == "https://t.me/testchannel/1"


def test_video_message():
    data = serialize_message(make_video_message(), ENTITY)
    assert data["type"] == "video"
    media = data["media"]
    assert media["file_name"] == "clip.mp4"
    assert media["size"] == 10_000_000
    assert media["duration"] == 12
    assert media["width"] == 1280 and media["height"] == 720
    assert media["mime_type"] == "video/mp4"


def test_voice_message():
    data = serialize_message(make_voice_message(), ENTITY)
    assert data["type"] == "voice"
    assert data["media"]["duration"] == 3


def test_service_message():
    service = MessageService(
        id=7, peer_id=None,
        action=MessageActionChatEditTitle(title="Нова назва"),
    )
    data = serialize_message(service, ENTITY)
    assert data["type"] == "service"
    assert data["action"] == "MessageActionChatEditTitle"
    assert data["text"] == ""


def test_reactions():
    message = Message(
        id=8, peer_id=None, date=DT, message="з реакціями",
        reactions=MessageReactions(results=[
            ReactionCount(reaction=ReactionEmoji(emoticon="🔥"), count=7),
            ReactionCount(reaction=ReactionEmoji(emoticon="👍"), count=2),
        ]),
    )
    data = serialize_message(message, ENTITY)
    assert data["reactions"] == [
        {"emoji": "🔥", "count": 7},
        {"emoji": "👍", "count": 2},
    ]


def test_forward_and_reply():
    message = Message(
        id=9, peer_id=None, date=DT, message="переслане",
        fwd_from=MessageFwdHeader(date=DT, from_name="Джерело", channel_post=88),
        reply_to=MessageReplyHeader(reply_to_msg_id=42),
    )
    data = serialize_message(message, ENTITY)
    assert data["forward"]["from_name"] == "Джерело"
    assert data["forward"]["channel_post"] == 88
    assert data["reply_to"]["message_id"] == 42


def test_views_forwards_author_grouped():
    message = Message(
        id=10, peer_id=None, date=DT, message="метрики",
        views=1234, forwards=5, post_author="Редакція", grouped_id=777,
    )
    data = serialize_message(message, ENTITY)
    assert data["views"] == 1234
    assert data["forwards"] == 5
    assert data["author"] == "Редакція"
    assert data["grouped_id"] == 777


def test_private_channel_link():
    entity = SimpleNamespace(id=987654, title="Приватний", username=None)
    data = serialize_message(Message(id=3, peer_id=None, date=DT, message="x"), entity)
    assert data["link"] == "https://t.me/c/987654/3"


def test_classify_media_unknown():
    assert classify_media(None) == "media"
    assert classify_media("щось") == "media"
