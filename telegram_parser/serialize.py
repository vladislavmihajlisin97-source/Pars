"""Серіалізація обʼєктів Telethon (повідомлення, медіа, канали) у словники.

Усі функції написані «захисно» (через ``getattr`` та ``isinstance``),
щоб працювати з різними версіями TL-схеми та з сирими TL-обʼєктами,
і з custom-обʼєктами Telethon, які повертає ``iter_messages``.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from telethon import utils
from telethon.tl.types import (
    DocumentAttributeAnimated,
    DocumentAttributeAudio,
    DocumentAttributeFilename,
    DocumentAttributeSticker,
    DocumentAttributeVideo,
    MessageFwdHeader,
    MessageMediaContact,
    MessageMediaDice,
    MessageMediaDocument,
    MessageMediaGame,
    MessageMediaGeo,
    MessageMediaInvoice,
    MessageMediaPhoto,
    MessageMediaPoll,
    MessageMediaWebPage,
    MessageReplyHeader,
    MessageReplyStoryHeader,
    PhotoSize,
    PhotoSizeProgressive,
    ReactionEmoji,
)

try:  # newer TL layers only
    from telethon.tl.types import MessageMediaPaidMedia
except ImportError:  # pragma: no cover
    MessageMediaPaidMedia = None  # type: ignore[assignment]


# ---------------------------------------------------------------------------
# Допоміжне
# ---------------------------------------------------------------------------

def to_iso(dt: Optional[datetime]) -> Optional[str]:
    """datetime -> ISO-8601 у UTC (наївні дати вважаємо UTC)."""
    if dt is None:
        return None
    if isinstance(dt, datetime):
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc).isoformat(timespec="seconds")
    return str(dt)


def _text_of(message: Any) -> str:
    """Текст повідомлення: працює і з custom Message, і з сирим TL-обʼєктом."""
    for attr in ("raw_text", "message"):
        value = getattr(message, attr, None)
        if isinstance(value, str):
            return value
    return ""


def message_link(entity: Any, message_id: int) -> Optional[str]:
    """Пряме посилання на повідомлення (публічний або приватний канал)."""
    if entity is None:
        return None
    username = getattr(entity, "username", None)
    if username:
        return f"https://t.me/{username}/{message_id}"
    raw_id = getattr(entity, "id", None)
    if raw_id:
        return f"https://t.me/c/{raw_id}/{message_id}"
    return None


# ---------------------------------------------------------------------------
# Класифікація та серіалізація медіа
# ---------------------------------------------------------------------------

MEDIA_TYPES = (
    "photo", "video", "gif", "voice", "audio", "video_note",
    "sticker", "document", "link", "geo", "contact", "poll",
    "dice", "game", "invoice", "paid_media",
)


def classify_media(media: Any) -> str:
    """Коротка назва типу медіа."""
    if isinstance(media, MessageMediaPhoto):
        return "photo"
    if isinstance(media, MessageMediaDocument):
        doc = getattr(media, "document", None)
        if doc is not None:
            mime = getattr(doc, "mime_type", "") or ""
            for attr in getattr(doc, "attributes", None) or []:
                if isinstance(attr, DocumentAttributeSticker):
                    return "sticker"
                if isinstance(attr, DocumentAttributeAudio):
                    return "voice" if attr.voice else "audio"
                if isinstance(attr, DocumentAttributeVideo):
                    if getattr(attr, "round_message", False):
                        return "video_note"
                    if mime == "image/gif" or isinstance(attr, DocumentAttributeAnimated):
                        return "gif"
                    return "video"
            if mime.startswith("image/"):
                return "document"  # зображення-файл (не фото Telegram)
        return "document"
    if isinstance(media, MessageMediaWebPage):
        return "link"
    if isinstance(media, MessageMediaGeo):
        return "geo"
    if isinstance(media, MessageMediaContact):
        return "contact"
    if isinstance(media, MessageMediaPoll):
        return "poll"
    if isinstance(media, MessageMediaDice):
        return "dice"
    if isinstance(media, MessageMediaGame):
        return "game"
    if isinstance(media, MessageMediaInvoice):
        return "invoice"
    if MessageMediaPaidMedia and isinstance(media, MessageMediaPaidMedia):
        return "paid_media"
    return "media"


def _photo_dimensions(photo: Any) -> tuple[Optional[int], Optional[int], Optional[int]]:
    """(ширина, висота, розмір_у_байтах) найбільшого розміру фото."""
    best: tuple[int, int, Optional[int]] | None = None
    for size in getattr(photo, "sizes", None) or []:
        w = getattr(size, "w", None)
        h = getattr(size, "h", None)
        if not w or not h:
            continue  # PhotoStrippedSize / PhotoPathSize тощо
        if isinstance(size, PhotoSizeProgressive):
            byte_size = max(getattr(size, "sizes", None) or [0]) or None
        elif isinstance(size, PhotoSize):
            byte_size = getattr(size, "size", None)
        else:
            byte_size = None
        if best is None or w * h > best[0] * best[1]:
            best = (w, h, byte_size)
    if best is None:
        return None, None, None
    return best


def _document_info(doc: Any) -> dict[str, Any]:
    """Витягнути filename / тривалість / розміри з атрибутів документа."""
    info: dict[str, Any] = {
        "id": getattr(doc, "id", None),
        "mime_type": getattr(doc, "mime_type", None),
        "size": getattr(doc, "size", None),
    }
    file_name = None
    for attr in getattr(doc, "attributes", None) or []:
        if isinstance(attr, DocumentAttributeFilename):
            file_name = attr.file_name
        elif isinstance(attr, DocumentAttributeVideo):
            info.setdefault("duration", getattr(attr, "duration", None))
            info.setdefault("width", getattr(attr, "w", None))
            info.setdefault("height", getattr(attr, "h", None))
        elif isinstance(attr, DocumentAttributeAudio):
            info.setdefault("duration", getattr(attr, "duration", None))
            performer = getattr(attr, "performer", None)
            title = getattr(attr, "title", None)
            if performer:
                info.setdefault("performer", performer)
            if title:
                info.setdefault("title", title)
    if file_name:
        info["file_name"] = file_name
    return info


def serialize_media(media: Any) -> dict[str, Any]:
    """Медіа-обʼєкт Telegram -> словник."""
    mtype = classify_media(media)

    if mtype == "photo":
        photo = getattr(media, "photo", None)
        width, height, size = _photo_dimensions(photo)
        data: dict[str, Any] = {"type": "photo", "width": width, "height": height, "size": size}
        photo_id = getattr(photo, "id", None)
        if photo_id is not None:
            data["id"] = photo_id
    elif mtype == "link":
        webpage = getattr(media, "webpage", None)
        data = {"type": "link"}
        for src, dst in (
            ("url", "url"), ("title", "title"),
            ("description", "description"),
            ("site_name", "site_name"), ("type", "web_type"),
            ("author", "author"), ("duration", "duration"),
        ):
            value = getattr(webpage, src, None)
            if value:
                data[dst] = value
    elif mtype == "geo":
        geo = getattr(media, "geo", None)
        data = {
            "type": "geo",
            "latitude": getattr(geo, "lat", None),
            "longitude": getattr(geo, "long", None),
        }
    elif mtype == "contact":
        data = {
            "type": "contact",
            "phone": getattr(media, "phone_number", None),
            "first_name": getattr(media, "first_name", None),
            "last_name": getattr(media, "last_name", None),
            "user_id": getattr(media, "user_id", None),
        }
    elif mtype == "poll":
        poll = getattr(media, "poll", None)
        question = getattr(poll, "question", None)
        if not isinstance(question, str):
            question = None
        answers = []
        for answer in getattr(poll, "answers", None) or []:
            answers.append({
                "text": getattr(answer, "text", None),
                "voters": getattr(answer, "voters", None),
                "chosen": bool(getattr(answer, "chosen", False)),
            })
        data = {
            "type": "poll",
            "question": question,
            "closed": bool(getattr(poll, "closed", False)),
            "answers": answers,
        }
    elif mtype == "dice":
        data = {
            "type": "dice",
            "emoji": getattr(media, "emoji", None),
            "value": getattr(media, "value", None),
        }
    elif mtype == "paid_media":
        data = {"type": "paid_media"}
        payload = getattr(media, "extended_media", None) or []
        items = []
        for item in payload:
            item_type = classify_media(item)
            if item_type not in ("photo", "document"):
                continue
            serialized = serialize_media(item)
            serialized.pop("type", None)
            serialized["kind"] = item_type
            items.append(serialized)
        data["items"] = items
    else:
        # photo / document / video / audio / voice / sticker / gif / video_note...
        doc = getattr(media, "document", None)
        if doc is not None:
            data = {"type": mtype, **_document_info(doc)}
        else:
            data = {"type": mtype}

    if getattr(media, "spoiler", False):
        data["spoiler"] = True
    return data


# ---------------------------------------------------------------------------
# Реакції, відповіді, форварди
# ---------------------------------------------------------------------------

def _serialize_reactions(reactions: Any) -> Optional[list[dict[str, Any]]]:
    if not reactions:
        return None
    out: list[dict[str, Any]] = []
    for rc in getattr(reactions, "results", None) or []:
        reaction = getattr(rc, "reaction", None)
        if isinstance(reaction, str):
            emoji: Optional[str] = reaction
        elif isinstance(reaction, ReactionEmoji):
            emoji = reaction.emoticon
        elif reaction is not None:
            emoji = f"custom:{getattr(reaction, 'document_id', '')}"
        else:
            emoji = None
        out.append({"emoji": emoji, "count": getattr(rc, "count", 0)})
    return out or None


def _serialize_reply(reply: Any) -> Optional[dict[str, Any]]:
    if reply is None:
        return None
    if isinstance(reply, MessageReplyStoryHeader):
        return {
            "story": True,
            "story_id": getattr(reply, "story_id", None),
        }
    if not isinstance(reply, MessageReplyHeader):
        # невідомий різновид заголовка — повертаємо як є, строково
        return {"raw": type(reply).__name__}
    data: dict[str, Any] = {}
    if getattr(reply, "reply_to_msg_id", None):
        data["message_id"] = reply.reply_to_msg_id
    if getattr(reply, "reply_to_top_id", None):
        data["top_message_id"] = reply.reply_to_top_id
    if getattr(reply, "reply_to_peer_id", None) is not None:
        try:
            data["peer_id"] = utils.get_peer_id(reply.reply_to_peer_id)
        except (TypeError, ValueError):
            pass
    if getattr(reply, "quote_text", None):
        data["quote"] = reply.quote_text
    return data or None


def _serialize_forward(fwd: Optional[MessageFwdHeader]) -> Optional[dict[str, Any]]:
    if fwd is None:
        return None
    data: dict[str, Any] = {"date": to_iso(getattr(fwd, "date", None))}
    if getattr(fwd, "from_name", None):
        data["from_name"] = fwd.from_name
    if getattr(fwd, "from_id", None) is not None:
        try:
            data["from_id"] = utils.get_peer_id(fwd.from_id)
        except (TypeError, ValueError):
            pass
    if getattr(fwd, "channel_post", None):
        data["channel_post"] = fwd.channel_post
    if getattr(fwd, "post_author", None):
        data["post_author"] = fwd.post_author
    if getattr(fwd, "psa_type", None):
        data["psa_type"] = fwd.psa_type
    return data


# ---------------------------------------------------------------------------
# Повідомлення та канал
# ---------------------------------------------------------------------------

def serialize_message(message: Any, entity: Any = None) -> dict[str, Any]:
    """Повідомлення -> словник, готовий до експорту."""
    media = getattr(message, "media", None)
    action = getattr(message, "action", None)
    is_service = action is not None

    if is_service:
        mtype = "service"
    elif media is not None:
        mtype = classify_media(media)
    else:
        mtype = "text"

    data: dict[str, Any] = {
        "id": getattr(message, "id", None),
        "date": to_iso(getattr(message, "date", None)),
        "edited": to_iso(getattr(message, "edit_date", None)),
        "type": mtype,
        "text": _text_of(message),
        "has_media": media is not None,
    }

    if is_service:
        data["action"] = type(action).__name__
    elif media is not None:
        data["media"] = serialize_media(media)

    for src in ("views", "forwards", "post_author", "grouped_id", "via_bot_id"):
        value = getattr(message, src, None)
        if value is not None:
            data["author" if src == "post_author" else src] = value

    reactions = _serialize_reactions(getattr(message, "reactions", None))
    if reactions:
        data["reactions"] = reactions

    forward = _serialize_forward(getattr(message, "fwd_from", None))
    if forward:
        data["forward"] = forward

    reply = _serialize_reply(getattr(message, "reply_to", None))
    if reply:
        data["reply_to"] = reply

    link = message_link(entity, getattr(message, "id", 0) or 0)
    if link:
        data["link"] = link

    return data


def serialize_channel(entity: Any, full: Any = None) -> dict[str, Any]:
    """Канал (Channel + ChannelFull) -> словник."""
    data: dict[str, Any] = {
        "id": getattr(entity, "id", None),
        "title": getattr(entity, "title", None),
        "username": getattr(entity, "username", None),
        "kind": type(entity).__name__.lower(),
    }
    if full is not None:
        about = getattr(full, "about", None)
        if about:
            data["description"] = about
        participants = getattr(full, "participants_count", None)
        if participants is not None:
            data["participants_count"] = participants
        invite = getattr(full, "exported_invite", None)
        invite_link = getattr(invite, "link", None)
        if invite_link:
            data["invite_link"] = invite_link
    return data
