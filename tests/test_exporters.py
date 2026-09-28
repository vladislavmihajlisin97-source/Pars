"""Тести експорту результатів у JSON / JSONL / CSV."""

import csv
import json

from telegram_parser.exporters import export_result
from telegram_parser.models import ParseResult


def make_result() -> ParseResult:
    return ParseResult(
        channel={"id": 1, "title": "Канал", "username": "testchannel"},
        messages=[
            {
                "id": 2,
                "date": "2024-05-14T12:00:00+00:00",
                "type": "photo",
                "text": "Опис фото",
                "has_media": True,
                "media": {
                    "type": "photo", "width": 800, "height": 600,
                    "size": 50_000, "file": "media/2.jpg",
                },
                "views": 100,
                "reactions": [{"emoji": "🔥", "count": 3}],
            },
            {
                "id": 1,
                "date": "2024-05-13T10:00:00+00:00",
                "type": "text",
                "text": "Привіт, канале",
                "has_media": False,
                "link": "https://t.me/testchannel/1",
            },
        ],
        stats={"total_messages": 2, "by_type": {"photo": 1, "text": 1}},
        mode="api",
    )


def test_export_json(tmp_path):
    result = make_result()
    written = export_result(result, tmp_path, formats=("json",))
    messages_path = tmp_path / "messages.json"
    assert messages_path in written

    payload = json.loads(messages_path.read_text(encoding="utf-8"))
    assert payload["channel"]["username"] == "testchannel"
    assert payload["stats"]["total_messages"] == 2
    assert len(payload["messages"]) == 2
    assert payload["messages"][0]["media"]["file"] == "media/2.jpg"
    # кирилиця має зберігатися як є (ensure_ascii=False)
    assert "Канал" in messages_path.read_text(encoding="utf-8")

    info = json.loads((tmp_path / "channel_info.json").read_text(encoding="utf-8"))
    assert info["channel"]["title"] == "Канал"
    assert info["mode"] == "api"


def test_export_jsonl(tmp_path):
    result = make_result()
    export_result(result, tmp_path, formats=("jsonl",))
    lines = (tmp_path / "messages.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    first = json.loads(lines[0])
    assert first["id"] == 2
    assert first["media"]["type"] == "photo"


def test_export_csv(tmp_path):
    result = make_result()
    export_result(result, tmp_path, formats=("csv",))
    with (tmp_path / "messages.csv").open(encoding="utf-8-sig", newline="") as fh:
        rows = list(csv.DictReader(fh))
    assert len(rows) == 2
    assert rows[0]["id"] == "2"
    assert rows[0]["media_type"] == "photo"
    assert rows[0]["media_file"] == "media/2.jpg"
    assert rows[0]["reactions"] == "🔥×3"
    assert rows[1]["text"] == "Привіт, канале"
    assert rows[1]["media_file"] == ""


def test_export_all_formats(tmp_path):
    written = export_result(make_result(), tmp_path, formats=("json", "jsonl", "csv"))
    names = {p.name for p in written}
    assert names == {
        "channel_info.json", "messages.json", "messages.jsonl", "messages.csv",
    }
