"""Парсинг публічних каналів через веб-превʼю t.me/s/<канал> — без API-ключів.

Обмеження веб-режиму: лише публічні канали з увімкненою превʼюшкою;
доступні текст, дата, перегляди, превʼю медіа, форварди, реакції (загальною
сумою). Для повного вмісту (усі повідомлення, реакції по окремих емодзі,
завантаження медіа у найкращій якості) використовуйте режим ``api``.
"""

from __future__ import annotations

import re
import time
from pathlib import Path
from typing import Any, Callable, Optional
from urllib.parse import urljoin, urlparse, parse_qs

import requests
from bs4 import BeautifulSoup

from .models import ParseResult
from .utils import parse_channel_ref, safe_dir_name

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)

_NO_PREVIEW_MARKERS = (
    "tgme_page_action",       # сторінка з кнопкою «View in Telegram»
    "If you have Telegram, you can",
)


class WebParseError(RuntimeError):
    """Помилка веб-парсингу (канал недоступний, превʼюшка вимкнена тощо)."""


def _parse_views(raw: Optional[str]) -> Optional[int]:
    """'1.4M' / '15.2K' / '999' -> число."""
    if not raw:
        return None
    text = raw.strip().upper().replace(",", ".")
    multipliers = {"K": 1_000, "M": 1_000_000, "B": 1_000_000_000}
    match = re.match(r"^([\d.]+)\s*([KMB]?)$", text)
    if not match:
        return None
    number = float(match.group(1))
    suffix = match.group(2)
    if suffix:
        number *= multipliers[suffix]
    return int(number)


def _style_image_url(style: Optional[str]) -> Optional[str]:
    """Витягти URL з 'background-image:url(...)' у атрибуті style."""
    if not style:
        return None
    match = re.search(r"url\(['\"]?(.*?)['\"]?\)", style)
    return match.group(1) if match else None


class WebScraper:
    """Ітеративне зчитування сторінок https://t.me/s/<канал>.

    Пагінація працює через параметр ``?before=<id>`` — Telegram сам віддає
    посилання «Show more» на наступну (старішу) порцію повідомлень.
    """

    BASE_URL = "https://t.me/s/{channel}"

    def __init__(
        self,
        timeout: float = 20.0,
        delay: float = 0.4,
        session: Optional[requests.Session] = None,
        log: Callable[[str], None] = print,
    ) -> None:
        self.timeout = timeout
        self.delay = delay          # пауза між запитами, щоб не дратувати t.me
        self.session = session or requests.Session()
        self.log = log

    # -- мережа -----------------------------------------------------------------

    def _fetch(self, url: str) -> str:
        try:
            response = self.session.get(
                url, timeout=self.timeout, headers={"User-Agent": USER_AGENT}
            )
        except requests.RequestException as exc:
            raise WebParseError(f"Не вдалося завантажити {url}: {exc}") from exc
        if response.status_code == 404:
            raise WebParseError(
                f"Канал не знайдено (404): {url}. Перевірте назву каналу."
            )
        if response.status_code != 200:
            raise WebParseError(
                f"Неочікувана відповідь {response.status_code} від {url}"
            )
        return response.text

    # -- розбір сторінки ----------------------------------------------------------

    def _channel_info(self, soup: BeautifulSoup) -> dict[str, Any]:
        info: dict[str, Any] = {}
        header_title = soup.select_one(
            ".tgme_channel_info_header_title"
        ) or soup.select_one(".tgme_title")
        if header_title:
            info["title"] = header_title.get_text(strip=True)
        else:
            og_title = soup.find("meta", property="og:title")
            if og_title and og_title.get("content"):
                info["title"] = og_title["content"]
        description = soup.select_one(".tgme_channel_info_description")
        if description:
            info["description"] = description.get_text(" ", strip=True)
        return info

    def _parse_message(self, node: Any) -> dict[str, Any]:
        post_ref = node.get("data-post") or ""
        message_id = int(post_ref.split("/")[-1]) if "/" in post_ref else 0

        text_node = node.select_one(".tgme_widget_message_text")
        if text_node is not None:
            for br in text_node.find_all("br"):
                br.replace_with("\n")
            text = text_node.get_text()
        else:
            text = ""

        views: Optional[int] = None
        views_node = node.select_one(".tgme_widget_message_views")
        if views_node is not None:
            views = _parse_views(views_node.get_text(strip=True))
            if views is None:
                # data-view атрибут, який Telegram ставить на самому div
                views = _parse_views(node.get("data-view"))

        date: Optional[str] = None
        time_node = node.select_one("time")
        if time_node is not None and time_node.get("datetime"):
            date = time_node["datetime"]

        media: Optional[dict[str, Any]] = None
        photo = node.select_one("a.tgme_widget_message_photo_wrap")
        if photo is not None:
            url = _style_image_url(photo.get("style"))
            media = {"type": "photo", "preview_url": url}
        if media is None:
            video = node.select_one("video")
            if video is not None:
                media = {
                    "type": "video",
                    "url": video.get("src"),
                    "preview_url": _style_image_url(
                        (node.select_one(".tgme_widget_message_video_thumb") or {}).get("style")  # type: ignore[union-attr]
                    ),
                }
        if media is None:
            thumb = node.select_one(
                ".tgme_widget_message_video_thumb, .tgme_widget_message_roundvideo"
            )
            if thumb is not None:
                media = {
                    "type": "video",
                    "preview_url": _style_image_url(thumb.get("style")),
                }

        data: dict[str, Any] = {
            "id": message_id,
            "date": date,
            "type": media["type"] if media else ("text" if text else "service"),
            "text": text.strip(),
            "has_media": media is not None,
        }
        if media:
            data["media"] = media
        if views is not None:
            data["views"] = views

        forwarded = node.select_one(".tgme_widget_message_forwarded")
        if forwarded is not None:
            name = forwarded.select_one("a")
            data["forward"] = {
                "from_name": forwarded.get_text(" ", strip=True),
                "link": name.get("href") if name else None,
            }

        date_link = node.select_one("a.tgme_widget_message_date")
        href = date_link.get("href") if date_link else None
        if href:
            data["link"] = href
        elif message_id:
            data["link"] = f"https://t.me/{post_ref.rsplit('/', 1)[0]}/{message_id}"

        # позначки «закріплено», «отредаговано» тощо — корисні прапорці
        if node.get("data-pinned") == "1":
            data["pinned"] = True
        return data

    def _parse_page(self, html: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        soup = BeautifulSoup(html, "html.parser")
        messages = [
            self._parse_message(node)
            for node in soup.select("div.tgme_widget_message")
        ]
        return messages, self._channel_info(soup)

    def _next_page_url(self, html: str, channel: str) -> Optional[str]:
        """Посилання «Show more» (старіші повідомлення) або None."""
        soup = BeautifulSoup(html, "html.parser")
        more = soup.select_one(
            "a.tme_messages_show_more_button, a.tgme_widget_message_load_more"
        )
        if more is not None and more.get("href"):
            return urljoin("https://t.me/", more["href"])
        # запасний варіант: шукаємо ?before= у будь-яких посиланнях сторінки
        for link in soup.find_all("a", href=True):
            parsed = urlparse(link["href"])
            query = parse_qs(parsed.query)
            if "before" in query and query["before"][0].isdigit():
                return urljoin("https://t.me/", link["href"])
        return None

    # -- публічний API ------------------------------------------------------------

    def parse(
        self,
        channel_ref: str,
        limit: int = 0,
        min_id: int = 0,
        output_root: Optional[Path] = None,
    ) -> ParseResult:
        """Спарсити канал (весь, або до ``limit`` повідомлень / id > min_id)."""
        channel, _ = parse_channel_ref(channel_ref)
        out_dir: Optional[Path] = None
        if output_root is not None:
            out_dir = Path(output_root) / safe_dir_name(channel)
            out_dir.mkdir(parents=True, exist_ok=True)
        if channel.startswith("+"):
            raise WebParseError(
                "Для приватних каналів за посиланням-запрошенням веб-режим "
                "не працює — використайте режим api (після приєднання)."
            )

        url = self.BASE_URL.format(channel=channel)
        html = self._fetch(url)
        if "tgme_widget_message" not in html and any(
            marker in html for marker in _NO_PREVIEW_MARKERS
        ):
            raise WebParseError(
                f"У каналу {channel!r} недоступна веб-превʼюшка (t.me/s) або "
                "канал приватний. Спробуйте режим api."
            )

        collected: list[dict[str, Any]] = []
        seen_ids: set[int] = set()
        channel_info: dict[str, Any] = {}
        page = 0

        while True:
            page += 1
            page_messages, page_info = self._parse_page(html)
            # інформація про канал може бути лише на першій сторінці —
            # обʼєднуємо, не втрачаючи вже зібраного
            if page == 1:
                channel_info = dict(page_info)
            else:
                for key, value in page_info.items():
                    if value and not channel_info.get(key):
                        channel_info[key] = value

            added = 0
            for message in page_messages:
                mid = message.get("id") or 0
                if mid and mid in seen_ids:
                    continue
                if min_id and mid and mid <= min_id:
                    continue
                if not message.get("text") and not message.get("media"):
                    continue  # службові повідомлення веб-превʼюшки
                seen_ids.add(mid)
                collected.append(message)
                added += 1
                if limit and len(collected) >= limit:
                    break

            self.log(
                f"  сторінка {page}: всього {len(collected):,} повідомлень"
            )
            if limit and len(collected) >= limit:
                break
            if added == 0:
                # сторінка не дала нових повідомлень — сітка вичерпана
                break

            next_url = self._next_page_url(html, channel)
            if not next_url:
                break
            # не йдемо глибше, ніж просив користувач (min_id)
            parsed_next = urlparse(next_url)
            before = parse_qs(parsed_next.query).get("before", [None])[0]
            if min_id and before and int(before) <= min_id:
                break

            time.sleep(self.delay)
            html = self._fetch(next_url)

        channel_info["username"] = channel
        if not channel_info.get("title"):
            channel_info["title"] = channel
        channel_info["source"] = "web"

        dates = [m["date"] for m in collected if m.get("date")]
        by_type: dict[str, int] = {}
        for m in collected:
            by_type[m.get("type", "?")] = by_type.get(m.get("type", "?"), 0) + 1

        stats = {
            "total_messages": len(collected),
            "by_type": dict(sorted(by_type.items(), key=lambda kv: -kv[1])),
            "with_media": sum(1 for m in collected if m.get("has_media")),
            "earliest_date": min(dates) if dates else None,
            "latest_date": max(dates) if dates else None,
        }
        return ParseResult(
            channel=channel_info,
            messages=collected,
            stats=stats,
            mode="web",
            output_dir=out_dir,
        )

    def download_media(self, result: ParseResult) -> None:
        """Завантажити те, що доступне з веб-превʼюшки (зображення/відео).

        Увага: t.me/s віддає лише превʼю (стиснені фото/відео ~320px).
        Повноцінні файли в оригінальній якості доступні лише в режимі api.
        """
        if not result.output_dir:
            raise WebParseError(
                "Каталог виводу не створено (output_root не передано в parse)."
            )
        media_dir = result.output_dir / "media"
        media_dir.mkdir(parents=True, exist_ok=True)
        downloaded = 0
        for message in result.messages:
            media = message.get("media") or {}
            url = media.get("url") or media.get("preview_url")
            if not url:
                continue
            ext = "mp4" if media.get("url") else "jpg"
            path = media_dir / f"{message.get('id')}.{ext}"
            if path.exists() and path.stat().st_size > 0:
                media["file"] = path.relative_to(result.output_dir).as_posix()
                continue
            try:
                response = self.session.get(
                    url, timeout=self.timeout, headers={"User-Agent": USER_AGENT}
                )
                response.raise_for_status()
                path.write_bytes(response.content)
                media["file"] = path.relative_to(result.output_dir).as_posix()
                downloaded += 1
                time.sleep(self.delay)
            except requests.RequestException as exc:
                media["error"] = str(exc)
        self.log(f"  завантажено медіа-превʼю: {downloaded}")
