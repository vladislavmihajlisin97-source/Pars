"""Створення та запуск Telethon-клієнта."""

from __future__ import annotations

from typing import Any, Optional, Tuple

from telethon import TelegramClient

from .config import Config


def parse_proxy(proxy_url: Optional[str]) -> Optional[Tuple[str, str, int]]:
    """'socks5://host:port' -> кортеж для Telethon ('socks5', host, port)."""
    if not proxy_url:
        return None
    url = proxy_url.strip()
    scheme, sep, rest = url.partition("://")
    if not sep:
        raise ValueError(
            f"Неправильний формат проксі: {proxy_url!r}. "
            "Очікується scheme://host:port, наприклад socks5://127.0.0.1:9050"
        )
    scheme = scheme.lower()
    if scheme not in ("socks4", "socks5", "http"):
        raise ValueError(f"Непідтримуваний тип проксі: {scheme} (socks4/socks5/http)")
    host, _, port = rest.rpartition(":")
    if not host or not port.isdigit():
        raise ValueError(f"Неправильний формат проксі: {proxy_url!r}")
    return (scheme, host, int(port))


def create_client(config: Config) -> TelegramClient:
    """TelegramClient за конфігурацією (сесія, ключі, проксі)."""
    proxy: Any = parse_proxy(config.proxy)
    return TelegramClient(
        config.session,
        config.api_id,  # type: ignore[arg-type]
        config.api_hash,  # type: ignore[arg-type]
        proxy=proxy,
    )


async def start_client(client: TelegramClient) -> TelegramClient:
    """Запуск клієнта. При першому вході Telethon інтерактивно запитає
    телефон, код підтвердження та (за потреби) пароль 2FA — сесія
    збережеться у файл ``<session>.session`` і надалі логін не потрібен.
    """
    await client.start()  # type: ignore[func-returns-value]
    return client
