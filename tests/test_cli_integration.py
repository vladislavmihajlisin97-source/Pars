"""Наскрізний тест CLI: команда parse у режимі web (t.me/s підмінено фікс­турами)."""

import json
from pathlib import Path

import pytest

from telegram_parser.cli import main

FIXTURES = Path(__file__).parent / "fixtures"
PAGE_1_URL = "https://t.me/s/testchannel"
PAGE_2_URL = "https://t.me/s/testchannel?before=100"


@pytest.fixture()
def fake_tme(monkeypatch):
    """Підмінюємо WebScraper._fetch на локальні сторінки."""
    from telegram_parser import web_scraper

    pages = {
        PAGE_1_URL: (FIXTURES / "web_page_1.html").read_text(encoding="utf-8"),
        PAGE_2_URL: (FIXTURES / "web_page_2.html").read_text(encoding="utf-8"),
    }

    def fake_fetch(self, url: str) -> str:
        if url not in pages:
            raise web_scraper.WebParseError(f"неочікуваний URL: {url}")
        return pages[url]

    monkeypatch.setattr(web_scraper.WebScraper, "_fetch", fake_fetch)
    return pages


def test_cli_web_parse_all_formats(tmp_path, fake_tme, capsys):
    exit_code = main([
        "parse", "testchannel", "--mode", "web",
        "--format", "all", "--out", str(tmp_path),
    ])
    assert exit_code == 0

    out_dir = tmp_path / "testchannel"
    for name in ("channel_info.json", "messages.json", "messages.jsonl", "messages.csv"):
        assert (out_dir / name).is_file(), name

    payload = json.loads((out_dir / "messages.json").read_text(encoding="utf-8"))
    assert payload["mode"] == "web"
    assert payload["stats"]["total_messages"] == 5

    # підсумок зі списком файлів — у виводі
    captured = capsys.readouterr().out
    assert "Збережено" in captured
    assert "messages.json" in captured


def test_cli_web_parse_limit(tmp_path, fake_tme):
    exit_code = main([
        "parse", "@testchannel", "--mode", "web", "--limit", "2",
        "--format", "jsonl", "--out", str(tmp_path),
    ])
    assert exit_code == 0
    lines = (tmp_path / "testchannel" / "messages.jsonl").read_text("utf-8").splitlines()
    assert len(lines) == 2


def test_cli_missing_channel_argument():
    with pytest.raises(SystemExit):
        main(["parse"])


def test_cli_no_credentials_api_mode(tmp_path, monkeypatch):
    # без api_id/api_hash режим api має пояснити, що робити
    for key in ("TELEGRAM_API_ID", "TELEGRAM_API_HASH"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.chdir(tmp_path)  # без .env поруч

    exit_code = main(["parse", "durov", "--out", str(tmp_path / "out")])
    assert exit_code == 2
