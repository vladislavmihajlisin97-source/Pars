"""Тести веб-скрейпера t.me/s — офлайн, на фікстурах (без мережі)."""

from pathlib import Path

import pytest

from telegram_parser.web_scraper import WebParseError, WebScraper, _parse_views

FIXTURES = Path(__file__).parent / "fixtures"
PAGE_1_URL = "https://t.me/s/testchannel"
PAGE_2_URL = "https://t.me/s/testchannel?before=100"


class FakeResponse:
    def __init__(self, text: str, status_code: int = 200) -> None:
        self.text = text
        self.status_code = status_code


class FakeSession:
    """Підмінює requests.Session: віддає заздалегідь підготовлені сторінки.

    Значення — рядок HTML або кортеж ``(html, status_code)``.
    """

    def __init__(self, pages: dict[str, object]) -> None:
        self.pages = pages
        self.requested_urls: list[str] = []

    def get(self, url, timeout=None, headers=None):
        self.requested_urls.append(url)
        if url not in self.pages:
            raise AssertionError(f"неочікуваний запит: {url}")
        value = self.pages[url]
        if isinstance(value, tuple):
            return FakeResponse(*value)
        return FakeResponse(str(value))


def make_scraper(pages: dict[str, str]) -> tuple[WebScraper, FakeSession]:
    session = FakeSession(pages)
    scraper = WebScraper(session=session, delay=0, log=lambda *_: None)
    return scraper, session


def load(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def make_pages() -> dict[str, str]:
    return {
        PAGE_1_URL: load("web_page_1.html"),
        PAGE_2_URL: load("web_page_2.html"),
    }


# ---------------------------------------------------------------- views

@pytest.mark.parametrize("raw,expected", [
    ("1.4K", 1400),
    ("15.2K", 15200),
    ("2M", 2_000_000),
    ("999", 999),
    ("", None),
    ("abc", None),
])
def test_parse_views(raw, expected):
    assert _parse_views(raw) == expected


# ---------------------------------------------------------------- parse

def test_full_parse():
    scraper, session = make_scraper(make_pages())
    result = scraper.parse("testchannel", output_root=None)

    assert [m["id"] for m in result.messages] == [103, 102, 101, 100, 99]
    # службових повідомлень (без тексту і медіа) фільтруємо
    assert 104 not in {m["id"] for m in result.messages}

    # пагінація: рівно два запити
    assert session.requested_urls == [PAGE_1_URL, PAGE_2_URL]

    # інформація про канал
    assert result.channel["title"] == "Test Channel"
    assert result.channel["username"] == "testchannel"
    assert result.channel["description"] == "Канал для тестів"

    # статистика
    assert result.stats["total_messages"] == 5
    assert result.stats["by_type"]["photo"] == 1
    assert result.stats["by_type"]["video"] == 1


def test_message_fields():
    scraper, _ = make_scraper(make_pages())
    result = scraper.parse("testchannel")

    by_id = {m["id"]: m for m in result.messages}
    photo = by_id[103]
    assert photo["type"] == "photo"
    assert photo["views"] == 1400
    assert photo["media"]["preview_url"].startswith("https://cdn")
    assert photo["link"] == "https://t.me/testchannel/103"
    assert photo["date"] == "2024-05-14T12:08:49+00:00"

    # <br> перетворюється на перенос рядка, теги прибираються
    assert "Рядок перший\nРядок другий з жирним" == by_id[102]["text"]
    assert by_id[102]["views"] == 999

    forwarded = by_id[100]
    assert forwarded["forward"]["from_name"].startswith("Forwarded from")
    assert forwarded["forward"]["link"] == "https://t.me/source_channel"


def test_limit():
    scraper, session = make_scraper(make_pages())
    result = scraper.parse("testchannel", limit=2)
    assert len(result.messages) == 2
    # друга сторінка не потрібна
    assert session.requested_urls == [PAGE_1_URL]


def test_min_id():
    scraper, session = make_scraper(make_pages())
    result = scraper.parse("testchannel", min_id=100)
    assert [m["id"] for m in result.messages] == [103, 102, 101]
    # before=100 <= min_id=100 -> не ходимо на другу сторінку
    assert session.requested_urls == [PAGE_1_URL]


def test_min_id_fetches_second_page_when_needed():
    scraper, session = make_scraper(make_pages())
    result = scraper.parse("testchannel", min_id=99)
    assert [m["id"] for m in result.messages] == [103, 102, 101, 100]
    assert session.requested_urls == [PAGE_1_URL, PAGE_2_URL]


def test_channel_ref_variants():
    scraper, session = make_scraper({
        PAGE_1_URL: load("web_page_1.html"),
        PAGE_2_URL: load("web_page_2.html"),
    })
    for ref in ("@testchannel", "https://t.me/testchannel", "testchannel"):
        session.requested_urls.clear()
        result = scraper.parse(ref, limit=1)
        assert result.stats["total_messages"] == 1
        assert session.requested_urls == [PAGE_1_URL]


def test_no_web_preview_raises():
    scraper, _ = make_scraper({
        PAGE_1_URL: (
            "<html><body><div class='tgme_page_action'>"
            "If you have Telegram, you can view channel</div></body></html>"
        )
    })
    with pytest.raises(WebParseError, match="превʼюшка"):
        scraper.parse("testchannel")


def test_not_found_404():
    scraper, _ = make_scraper({PAGE_1_URL: ("", 404)})
    with pytest.raises(WebParseError, match="404"):
        scraper.parse("testchannel")


def test_invite_link_rejected():
    scraper, _ = make_scraper({})
    with pytest.raises(WebParseError, match="запрошення"):
        scraper.parse("https://t.me/+AbCdEf123")


def test_output_dir_created(tmp_path):
    scraper, _ = make_scraper(make_pages())
    result = scraper.parse("testchannel", output_root=tmp_path)
    assert result.output_dir == tmp_path / "testchannel"
    assert result.output_dir.is_dir()
