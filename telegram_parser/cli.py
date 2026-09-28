"""Командний інтерфейс Pars.

Виклик:
    python pars.py parse <канал> [опції]
    python pars.py info <канал>
    python pars.py login
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Sequence

from . import __version__
from .api_client import create_client, start_client
from .config import ConfigError, load_config, require_api_credentials
from .exporters import SUPPORTED_FORMATS, export_result
from .models import ParseOptions
from .parsing import ChannelParser
from .serialize import MEDIA_TYPES
from .web_scraper import WebParseError, WebScraper

EPILOG = """приклади:
  # весь вміст каналу у JSON (потрібні api_id/api_hash у .env)
  python pars.py parse durov

  # усе разом із медіа, у трьох форматах
  python pars.py parse @durov --media --format all

  # лише останні 500 повідомлень
  python pars.py parse https://t.me/durov -l 500 --media --media-types photo,video

  # повідомлення за періодом
  python pars.py parse durov --since 2024-01-01 --until 2024-06-30

  # без API-ключів (публічна веб-превʼюшка t.me/s)
  python pars.py parse durov --mode web
"""


def parse_date(value: str) -> datetime:
    """Дата у форматі YYYY-MM-DD або повний ISO (за замовчуванням UTC)."""
    for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M"):
        try:
            return datetime.strptime(value, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    try:
        parsed = datetime.fromisoformat(value)
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except ValueError:
        raise argparse.ArgumentTypeError(
            f"неправильна дата {value!r} (очікується YYYY-MM-DD чи ISO 8601)"
        ) from None


def parse_media_types(value: str) -> frozenset[str]:
    """Розібрати 'photo,video' -> frozenset({'photo','video'})."""
    types = {t.strip().lower() for t in value.split(",") if t.strip()}
    unknown = types - set(MEDIA_TYPES)
    if unknown:
        raise argparse.ArgumentTypeError(
            f"невідомі типи медіа: {', '.join(sorted(unknown))}. "
            f"Доступні: {', '.join(MEDIA_TYPES)}"
        )
    return frozenset(types)


def human_size(num_bytes: int) -> str:
    value = float(num_bytes)
    for unit in ("Б", "КБ", "МБ", "ГБ"):
        if value < 1024 or unit == "ГБ":
            return f"{value:.1f} {unit}" if unit != "Б" else f"{int(value)} {unit}"
        value /= 1024
    return f"{num_bytes} Б"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pars",
        description="Pars — парсер телеграм-каналів: повний вміст каналу "
        "(повідомлення, медіа, реакції, перегляди) у JSON/JSONL/CSV.",
        epilog=EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--version", action="version", version=f"Pars {__version__}"
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # --- parse ---------------------------------------------------------------
    p_parse = sub.add_parser(
        "parse",
        help="спарсувати канал (головна команда)",
        epilog=EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p_parse.add_argument(
        "channel",
        help="канал: @username, username, https://t.me/username, "
        "https://t.me/username/123 або числовий id",
    )
    p_parse.add_argument(
        "-m", "--mode", choices=("api", "web"), default="api",
        help="api — повний парсинг через Telegram API (потрібні ключі у .env); "
        "web — публічна превʼюшка t.me/s без ключів (лише публічні канали) "
        "[типово: api]",
    )
    p_parse.add_argument(
        "-l", "--limit", type=int, default=0, metavar="N",
        help="максимум N останніх повідомлень (0 = усі)",
    )
    p_parse.add_argument(
        "--min-id", type=int, default=0, metavar="ID",
        help="парсити повідомлення з id > ID",
    )
    p_parse.add_argument(
        "--max-id", type=int, default=0, metavar="ID",
        help="парсити повідомлення з id <= ID",
    )
    p_parse.add_argument(
        "--since", type=parse_date, metavar="DATE",
        help="лише повідомлення від дати (YYYY-MM-DD або ISO 8601)",
    )
    p_parse.add_argument(
        "--until", type=parse_date, metavar="DATE",
        help="лише повідомлення до дати",
    )
    p_parse.add_argument(
        "--reverse", action="store_true",
        help="від старих до нових (типово: від нових до старих)",
    )
    p_parse.add_argument(
        "-o", "--out", default="output", metavar="DIR",
        help="кореневий каталог результатів [типово: output]",
    )
    p_parse.add_argument(
        "-f", "--format", choices=(*SUPPORTED_FORMATS, "all"), default="json",
        help="формат виводу [типово: json]",
    )
    p_parse.add_argument(
        "--media", action="store_true",
        help="завантажити медіа (у режимі web — лише превʼю)",
    )
    p_parse.add_argument(
        "--media-types", type=parse_media_types, default=frozenset(),
        metavar="LIST",
        help="фільтр типів медіа через кому: "
        "photo / video / voice / audio / document / sticker / gif / video_note",
    )
    p_parse.add_argument(
        "--max-media-size", type=float, default=0, metavar="MB",
        help="максимальний розмір файлу медіа, МБ (0 = без обмеження)",
    )
    p_parse.add_argument(
        "--media-workers", type=int, default=4, metavar="N",
        help="паралельні завантаження медіа [типово: 4]",
    )
    p_parse.add_argument(
        "--session", default=None, metavar="NAME",
        help="назва файлу сесії Telegram (типово з .env або 'pars')",
    )

    # --- info ----------------------------------------------------------------
    p_info = sub.add_parser(
        "info", help="показати інформацію про канал (режим api)"
    )
    p_info.add_argument("channel", help="канал: @username, посилання або id")
    p_info.add_argument(
        "--session", default=None, metavar="NAME", help="назва файлу сесії"
    )

    # --- login ---------------------------------------------------------------
    sub.add_parser(
        "login",
        help="увійти в Telegram і зберегти сесію (один раз, далі парсинг без логіна)",
    )
    return parser


# ---------------------------------------------------------------------------
# api-режим (Telethon)
# ---------------------------------------------------------------------------

def _api_client(args: argparse.Namespace):
    config = load_config()
    require_api_credentials(config)
    if getattr(args, "session", None):
        config.session = args.session
    return create_client(config)


async def _run_parse_api(args: argparse.Namespace, options: ParseOptions):
    client = _api_client(args)
    await start_client(client)
    try:
        parser = ChannelParser(client, options)
        result = await parser.parse(args.channel)
    finally:
        await client.disconnect()
    return result


def _run_parse_web(args: argparse.Namespace, options: ParseOptions):
    scraper = WebScraper()
    result = scraper.parse(
        args.channel,
        limit=options.limit,
        min_id=options.min_id,
        output_root=options.output_root,
    )
    if args.media:
        scraper.download_media(result)
    return result


# ---------------------------------------------------------------------------
# Команди
# ---------------------------------------------------------------------------

def cmd_parse(args: argparse.Namespace) -> int:
    formats = (
        list(SUPPORTED_FORMATS) if args.format == "all" else [args.format]
    )
    options = ParseOptions(
        limit=args.limit,
        min_id=args.min_id,
        max_id=args.max_id,
        since=args.since,
        until=args.until,
        reverse=args.reverse,
        output_root=Path(args.out),
        download_media=args.media,
        media_types=args.media_types,
        max_media_size=int(args.max_media_size * 1024 * 1024),
        media_workers=args.media_workers,
    )

    if args.mode == "web":
        result = _run_parse_web(args, options)
    else:
        result = asyncio.run(_run_parse_api(args, options))

    if result.output_dir is None:  # теоретично недосяжно, але захистимося
        result.output_dir = Path(args.out)

    written = export_result(result, result.output_dir, formats=formats)
    print("\nЗбережено:")
    for path in written:
        size = human_size(path.stat().st_size) if path.is_file() else "—"
        print(f"  {path}  ({size})")
    return 0


def cmd_info(args: argparse.Namespace) -> int:
    import json

    async def runner() -> None:
        client = _api_client(args)
        await start_client(client)
        try:
            parser = ChannelParser(client, ParseOptions())
            info = await parser.channel_info(args.channel)
            print(json.dumps(info, ensure_ascii=False, indent=2))
        finally:
            await client.disconnect()

    asyncio.run(runner())
    return 0


def cmd_login(_args: argparse.Namespace) -> int:
    async def runner() -> None:
        client = _api_client(argparse.Namespace())
        await start_client(client)
        me = await client.get_me()
        name = getattr(me, "first_name", None) or me
        print(f"Успішно! Ви: {name}")
        print(
            "Сесію збережено — тепер pars.py може парсити канали без повторного входу."
        )
        await client.disconnect()

    asyncio.run(runner())
    return 0


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "parse":
            return cmd_parse(args)
        if args.command == "info":
            return cmd_info(args)
        if args.command == "login":
            return cmd_login(args)
        parser.error(f"невідома команда: {args.command}")
    except (ConfigError, WebParseError, ValueError) as exc:
        print(f"Помилка: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("\nПерервано користувачем.", file=sys.stderr)
        return 130
    return 1


if __name__ == "__main__":
    sys.exit(main())
