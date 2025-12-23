#!/usr/bin/env python3
"""
Utility helpers shared between the WebTicker scripts.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

TIMESTAMP_FMT = "%Y.%m.%d %H:%M:%S"
WEB_TAG = "[WEB_TICKER]"
HISTORY_VERSION = 1


def isoformat(value: datetime) -> str:
    return value.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def parse_iso_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    cleaned = value.strip()
    if cleaned.endswith("Z"):
        cleaned = cleaned.replace("Z", "+00:00")
    return datetime.fromisoformat(cleaned).astimezone(timezone.utc)


def parse_log_timestamp(line: str) -> datetime:
    cleaned = line.lstrip("\ufeff")
    if not cleaned.startswith("["):
        raise ValueError(f"Ungültiges Logformat: {line[:40]}")
    end_idx = cleaned.find("]")
    if end_idx == -1:
        raise ValueError(f"Kein Timestamp in Zeile: {line[:80]}")
    stamp = cleaned[1:end_idx]
    return datetime.strptime(stamp, TIMESTAMP_FMT).replace(tzinfo=timezone.utc)


def load_state_entries(path: Path) -> List[Dict[str, Any]]:
    if not path or not path.exists():
        return []
    raw = path.read_bytes()
    text = None
    for encoding in ("utf-16-le", "utf-8-sig", "utf-8"):
        try:
            text = raw.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    if text is None:
        raise UnicodeError(f"Kann Datei {path} nicht dekodieren")
    entries: List[Dict[str, Any]] = []
    for idx, line in enumerate(text.splitlines(), 1):
        if WEB_TAG not in line:
            continue
        log_ts = parse_log_timestamp(line)
        json_start = line.find("{", line.find(WEB_TAG))
        if json_start == -1:
            raise ValueError(f"Keine JSON-Payload in Zeile {idx}")
        payload_text = line[json_start:].strip()
        payload = json.loads(payload_text)
        payload["_log_timestamp"] = log_ts
        entries.append(payload)
    return entries


def normalize_trade(entry: Dict[str, Any]) -> Dict[str, Any]:
    closed_at = parse_iso_datetime(entry.get("closed_at")) or entry["_log_timestamp"]
    opened_at = parse_iso_datetime(entry.get("opened_at"))
    comment = entry.get("comment") or entry.get("label")
    order_type = entry.get("order_type") or entry.get("direction") or entry.get("side")
    return {
        "ticket": str(entry.get("ticket")),
        "symbol": entry.get("symbol", "UNKNOWN"),
        "volume": float(entry.get("volume", 0.0)),
        "profit": float(entry.get("profit", 0.0)),
        "order_type": order_type,
        "comment": comment,
        "opened_at": opened_at,
        "closed_at": closed_at,
        "tp_label": entry.get("tp_label"),
        "sl_label": entry.get("sl_label"),
    }


def normalize_snapshot(entry: Dict[str, Any]) -> Dict[str, Any]:
    stamp = parse_iso_datetime(entry.get("timestamp")) or entry["_log_timestamp"]
    return {
        "timestamp": stamp,
        "balance": float(entry.get("balance", 0.0)),
        "equity": float(entry.get("equity", 0.0)),
        "floating": float(entry.get("floating", 0.0)),
    }


def serialize_trade(trade: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "ticket": trade["ticket"],
        "symbol": trade.get("symbol"),
        "volume": round(float(trade.get("volume", 0.0)), 5),
        "profit": round(float(trade.get("profit", 0.0)), 5),
        "order_type": trade.get("order_type"),
        "comment": trade.get("comment"),
        "opened_at": isoformat(trade["opened_at"]) if isinstance(trade.get("opened_at"), datetime) else trade.get("opened_at"),
        "closed_at": isoformat(trade["closed_at"]) if isinstance(trade.get("closed_at"), datetime) else trade.get("closed_at"),
        "tp_label": trade.get("tp_label"),
        "sl_label": trade.get("sl_label"),
    }


def serialize_snapshot(snapshot: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "timestamp": isoformat(snapshot["timestamp"]) if isinstance(snapshot["timestamp"], datetime) else snapshot["timestamp"],
        "balance": round(float(snapshot.get("balance", 0.0)), 2),
        "equity": round(float(snapshot.get("equity", 0.0)), 2),
        "floating": round(float(snapshot.get("floating", 0.0)), 2),
    }
