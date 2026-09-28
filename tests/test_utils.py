"""Тести допоміжних функцій: посилання на канал, імена файлів, фільтри медіа."""


import pytest

from telegram_parser.media import MediaDownloader, sanitize_filename
from telegram_parser.utils import parse_channel_ref, safe_dir_name


@pytest.mark.parametrize("ref,expected", [
    ("durov", ("durov", 0)),
    ("@durov", ("durov", 0)),
    ("https://t.me/durov", ("durov", 0)),
    ("https://t.me/durov/123", ("durov", 123)),
    ("http://t.me/durov/456/", ("durov", 456)),
    ("t.me/durov", ("durov", 0)),
    ("-1001234567890", ("-1001234567890", 0)),
])
def test_parse_channel_ref(ref, expected):
    assert parse_channel_ref(ref) == expected


def test_parse_channel_ref_empty():
    with pytest.raises(ValueError):
        parse_channel_ref("")
    with pytest.raises(ValueError):
        parse_channel_ref("https://t.me/")


@pytest.mark.parametrize("name,expected", [
    ("durov", "durov"),
    ("Канал новин!", "Канал_новин"),
    ("  spaces  ", "spaces"),
    ("", "channel"),
    (None, "channel"),
])
def test_safe_dir_name(name, expected):
    assert safe_dir_name(name) == expected


def test_sanitize_filename():
    assert sanitize_filename("../../../etc/passwd") == "etc_passwd"
    assert sanitize_filename("звіт 2024.pdf") == "звіт 2024.pdf"
    assert sanitize_filename("") == "file"
    long = "a" * 300 + ".pdf"
    assert len(sanitize_filename(long)) <= 80


def make_downloader(tmp_path, **kwargs):
    return MediaDownloader(
        client=None, output_dir=tmp_path, media_dir_name="media", **kwargs
    )


def test_media_filter_by_type(tmp_path):
    downloader = make_downloader(tmp_path, media_types={"photo", "video"})
    assert downloader.matches({"type": "photo"})
    assert downloader.matches({"type": "video"})
    assert not downloader.matches({"type": "document"})
    assert not downloader.matches({})


def test_media_filter_all_types_when_empty(tmp_path):
    downloader = make_downloader(tmp_path)
    assert downloader.matches({"type": "document"})


def test_media_filter_by_size(tmp_path):
    downloader = make_downloader(tmp_path, max_size=1024)
    assert downloader.matches({"type": "document", "size": 512})
    assert not downloader.matches({"type": "document", "size": 2048})
    # невідомий розмір (фото без метрик) не відсікаємо
    assert downloader.matches({"type": "photo", "size": None})


def test_media_target_path(tmp_path):
    downloader = make_downloader(tmp_path)
    # документ з іменем файлу
    path = downloader._target_path(
        42, {"type": "document", "file_name": "Звіт (фінальний).pdf"}
    )
    assert path.name.startswith("42_")
    assert path.suffix == ".pdf"
    assert path.parent == tmp_path / "media"

    # фото без імені
    path = downloader._target_path(7, {"type": "photo"})
    assert path.name == "7.jpg"

    # документ із mime, але без імені
    path = downloader._target_path(9, {"type": "document", "mime_type": "application/pdf"})
    assert path.suffix == ".pdf"
