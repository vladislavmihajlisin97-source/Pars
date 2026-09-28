"""Конфігурація: api_id / api_hash з .env або змінних оточення."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


class ConfigError(RuntimeError):
    """Помилка конфігурації (немає ключів, кривий .env тощо)."""


@dataclass
class Config:
    api_id: Optional[int] = None
    api_hash: Optional[str] = None
    session: str = "pars"
    proxy: Optional[str] = None


def _parse_env_file(path: Path) -> dict[str, str]:
    """Простий парсер .env без зовнішніх залежностей."""
    values: dict[str, str] = {}
    if not path.is_file():
        return values
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            values[key] = value
    return values


def _find_env_file() -> Optional[Path]:
    """Шукаємо .env у поточному каталозі та біля точки входу."""
    candidates = [
        Path.cwd() / ".env",
        Path(__file__).resolve().parent.parent / ".env",
    ]
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return None


def load_config() -> Config:
    """Пріоритет: змінні оточення > файл .env."""
    file_values = _parse_env_file(_find_env_file() or Path(".env"))

    def get(name: str, default: Optional[str] = None) -> Optional[str]:
        return os.environ.get(name) or file_values.get(name) or default

    api_id_raw = get("TELEGRAM_API_ID")
    api_hash = get("TELEGRAM_API_HASH")

    api_id: Optional[int] = None
    if api_id_raw:
        try:
            api_id = int(api_id_raw)
        except ValueError as exc:
            raise ConfigError(
                f"TELEGRAM_API_ID має бути числом, отримано: {api_id_raw!r}"
            ) from exc

    return Config(
        api_id=api_id,
        api_hash=api_hash,
        session=get("TELEGRAM_SESSION", "pars") or "pars",
        proxy=get("TELEGRAM_PROXY"),
    )


def require_api_credentials(config: Config) -> tuple[int, str]:
    """Перевірити наявність ключів або зрозуміло пояснити, як їх отримати."""
    if not config.api_id or not config.api_hash:
        raise ConfigError(
            "Для режиму 'api' потрібні ключі Telegram API.\n"
            "  1. Зайдіть на https://my.telegram.org -> API development tools\n"
            "  2. Створіть застосунок і скопіюйте api_id та api_hash\n"
            "  3. Заповніть .env (зразок — .env.example):\n"
            "       TELEGRAM_API_ID=...\n"
            "       TELEGRAM_API_HASH=...\n"
            "Або скористайтесь режимом без ключів: --mode web "
            "(працює лише для публічних каналів)."
        )
    return config.api_id, config.api_hash
