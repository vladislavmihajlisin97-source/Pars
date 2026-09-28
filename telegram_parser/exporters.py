"""Експорт результатів парсингу у JSON / JSONL / CSV."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any, Iterable

from .models import ParseResult

SUPPORTED_FORMATS = ("json", "jsonl", "csv")

CSV_COLUMNS = (
    "id", "date", "type", "text", "views", "forwards", "author", "grouped_id",
    "edited", "link", "media_type", "media_file", "media_url", "media_size",
    "media_file_name", "reactions_total", "reactions", "forward_from",
    "reply_to", "service_action",
)


def _flatten(message: dict[str, Any]) -> dict[str, Any]:
    """Повідомлення -> плоский рядок для CSV."""
    media = message.get("media") or {}
    reactions = message.get("reactions") or []
    forward = message.get("forward") or {}
    reply = message.get("reply_to") or {}
    return {
        "id": message.get("id"),
        "date": message.get("date"),
        "type": message.get("type"),
        "text": message.get("text") or "",
        "views": message.get("views"),
        "forwards": message.get("forwards"),
        "author": message.get("author"),
        "grouped_id": message.get("grouped_id"),
        "edited": message.get("edited"),
        "link": message.get("link"),
        "media_type": media.get("type"),
        "media_file": media.get("file"),
        "media_url": media.get("url") or media.get("preview_url"),
        "media_size": media.get("size"),
        "media_file_name": media.get("file_name"),
        "reactions_total": sum(r.get("count", 0) for r in reactions),
        "reactions": "; ".join(
            f"{r.get('emoji')}×{r.get('count')}" for r in reactions
        ),
        "forward_from": forward.get("from_name") or forward.get("from_id"),
        "reply_to": reply.get("message_id"),
        "service_action": message.get("action"),
    }


def export_channel_info(result: ParseResult, out_dir: Path) -> Path:
    """Окремий файл з інформацією про канал та статистикою."""
    path = out_dir / "channel_info.json"
    payload = {
        "channel": result.channel,
        "stats": result.stats,
        "parsed_at": result.parsed_at,
        "mode": result.mode,
    }
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return path


def export_json(result: ParseResult, out_dir: Path) -> Path:
    """Повний самодостатній JSON: канал + статистика + всі повідомлення."""
    path = out_dir / "messages.json"
    payload = {
        "channel": result.channel,
        "stats": result.stats,
        "parsed_at": result.parsed_at,
        "mode": result.mode,
        "messages": result.messages,
    }
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return path


def export_jsonl(result: ParseResult, out_dir: Path) -> Path:
    """Одне повідомлення — один рядок (зручно для обробки потоками даних)."""
    path = out_dir / "messages.jsonl"
    with path.open("w", encoding="utf-8") as fh:
        for message in result.messages:
            fh.write(json.dumps(message, ensure_ascii=False) + "\n")
    return path


def export_csv(result: ParseResult, out_dir: Path) -> Path:
    """Плоска таблиця (utf-8-sig, щоб Excel одразу бачив кирилицю)."""
    path = out_dir / "messages.csv"
    with path.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(
            fh, fieldnames=CSV_COLUMNS, extrasaction="ignore"
        )
        writer.writeheader()
        for message in result.messages:
            row = _flatten(message)
            # None -> порожньо, щоб таблиця була чистою
            row = {k: ("" if v is None else v) for k, v in row.items()}
            writer.writerow(row)
    return path


_EXPORTERS = {
    "json": export_json,
    "jsonl": export_jsonl,
    "csv": export_csv,
}


def export_result(
    result: ParseResult,
    out_dir: Path,
    formats: Iterable[str] = ("json",),
) -> list[Path]:
    """Зберегти результат у всіх обраних форматах + channel_info.json."""
    out_dir.mkdir(parents=True, exist_ok=True)
    written = [export_channel_info(result, out_dir)]
    for fmt in formats:
        exporter = _EXPORTERS.get(fmt)
        if exporter is None:
            raise ValueError(
                f"Невідомий формат {fmt!r}. Доступні: {', '.join(SUPPORTED_FORMATS)}, all"
            )
        written.append(exporter(result, out_dir))
    return written
