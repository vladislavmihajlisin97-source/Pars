"""Тести конфігурації (.env + змінні оточення) та CLI-аргументів."""

import pytest

from telegram_parser.cli import build_parser, parse_date, parse_media_types
from telegram_parser.config import _parse_env_file, load_config


def test_parse_env_file(tmp_path):
    env = tmp_path / ".env"
    env.write_text(
        "# коментар\n"
        "TELEGRAM_API_ID=123456\n"
        'TELEGRAM_API_HASH="abcdef0123456789"\n'
        "TELEGRAM_SESSION=my_session\n"
        "\n"
        "BROKEN_LINE_WITHOUT_EQ\n",
        encoding="utf-8",
    )
    values = _parse_env_file(env)
    assert values == {
        "TELEGRAM_API_ID": "123456",
        "TELEGRAM_API_HASH": "abcdef0123456789",
        "TELEGRAM_SESSION": "my_session",
    }


def test_load_config_from_env_file(tmp_path, monkeypatch):
    for key in ("TELEGRAM_API_ID", "TELEGRAM_API_HASH", "TELEGRAM_SESSION"):
        monkeypatch.delenv(key, raising=False)
    (tmp_path / ".env").write_text(
        "TELEGRAM_API_ID=111\nTELEGRAM_API_HASH=abc\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    config = load_config()
    assert config.api_id == 111
    assert config.api_hash == "abc"
    assert config.session == "pars"  # значення за замовчуванням


def test_load_config_env_vars_win(tmp_path, monkeypatch):
    monkeypatch.delenv("TELEGRAM_API_ID", raising=False)
    monkeypatch.delenv("TELEGRAM_API_HASH", raising=False)
    monkeypatch.setenv("TELEGRAM_API_ID", "222")
    monkeypatch.setenv("TELEGRAM_API_HASH", "def")
    (tmp_path / ".env").write_text(
        "TELEGRAM_API_ID=111\nTELEGRAM_API_HASH=abc\n", encoding="utf-8"
    )
    monkeypatch.chdir(tmp_path)
    config = load_config()
    assert config.api_id == 222
    assert config.api_hash == "def"


def test_parse_date():
    from datetime import timezone

    dt = parse_date("2024-05-14")
    assert (dt.year, dt.month, dt.day) == (2024, 5, 14)
    assert dt.tzinfo == timezone.utc

    dt_full = parse_date("2024-05-14T10:30:00")
    assert dt_full.hour == 10 and dt_full.minute == 30


def test_parse_date_invalid():
    with pytest.raises(SystemExit):
        # argparse помилки валидації -> SystemExit(2)
        parser = build_parser()
        parser.parse_args(["parse", "chan", "--since", "не-дата"])


def test_parse_media_types():
    assert parse_media_types("photo, video") == frozenset({"photo", "video"})
    with pytest.raises(SystemExit):
        build_parser().parse_args(["parse", "chan", "--media-types", "spam"])


def test_cli_parse_defaults():
    args = build_parser().parse_args(["parse", "durov"])
    assert args.command == "parse"
    assert args.channel == "durov"
    assert args.mode == "api"
    assert args.limit == 0
    assert args.format == "json"
    assert args.media is False


def test_cli_parse_full():
    args = build_parser().parse_args([
        "parse", "@durov", "--mode", "web", "-l", "100",
        "--since", "2024-01-01", "--until", "2024-06-30",
        "-f", "all", "--media", "--media-types", "photo,video",
        "--max-media-size", "50", "-o", "out_dir",
    ])
    assert args.mode == "web"
    assert args.limit == 100
    assert args.since.year == 2024
    assert args.until.month == 6
    assert args.format == "all"
    assert args.media is True
    assert args.media_types == frozenset({"photo", "video"})
    assert args.max_media_size == 50
    assert args.out == "out_dir"
