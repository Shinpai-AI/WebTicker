#!/usr/bin/env python3
"""
Initial import script for the Sharrow WebTicker.
Reads an MT5 Konto-Report (+ optional state.log) and creates the persistent history JSON.
"""
from __future__ import annotations

import argparse
import json
import logging
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

from bs4 import BeautifulSoup

from webticker_lib import (
    HISTORY_VERSION,
    isoformat,
    load_state_entries,
    normalize_snapshot,
    normalize_trade,
    serialize_snapshot,
    serialize_trade,
)

LOGGER = logging.getLogger("tkb_webticker_initial")
DEFAULT_CONFIG = Path(__file__).resolve().parent.parent / "TKB-config.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Initialisiert die WebTicker-History aus Konto-Reports")
    parser.add_argument("--config", help="Pfad zur TKB-config.json (Default: eine Ebene über dem Skript)")
    parser.add_argument("--statement", help="Pfad zum MT5 Konto-Report (Default aus Config)")
    parser.add_argument("--state-log", help="Optional: vorhandene Goldjunge-state.log (Default aus Config)")
    parser.add_argument("--output", help="Override Ziel-JSON (ansonsten aus Config)")
    parser.add_argument("--skip-render", action="store_true", help="TKB-WebTicker.py danach nicht starten")
    return parser.parse_args()


def load_config(path: Path) -> Dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"Config file {path} fehlt")
    return json.loads(path.read_text(encoding="utf-8"))


def detect_output_path(config: Dict[str, Any], args: argparse.Namespace) -> Path:
    if args.output:
        return Path(args.output).expanduser().resolve()
    json_name = config.get("web_ticker", {}).get("output_json", "TKB-WebTicker.json")
    return (Path(__file__).resolve().parent / json_name).resolve()


def detect_statement_path(config: Dict[str, Any], args: argparse.Namespace) -> Path:
    if args.statement:
        cand = Path(args.statement).expanduser()
    else:
        stmt_name = config.get("web_ticker", {}).get("initial_statement")
        if not stmt_name:
            raise ValueError(
                "Kein Konto-Report angegeben. Entweder --statement nutzen oder "
                "'web_ticker.initial_statement' in der TKB-config.json setzen."
            )
        cand = Path(stmt_name)
        if not cand.is_absolute():
            cand = Path(__file__).resolve().parent / cand
    cand = cand.resolve()
    if not cand.exists():
        raise FileNotFoundError(f"Konto-Report {cand} nicht gefunden")
    return cand


def detect_state_log_path(config: Dict[str, Any], args: argparse.Namespace) -> Path | None:
    candidate: Path | None = None
    if args.state_log:
        candidate = Path(args.state_log).expanduser()
    else:
        web_cfg = config.get("web_ticker", {})
        paths_cfg = config.get("paths", {})
        state_name = web_cfg.get("state_log", "Goldjunge-state.log")
        local = Path(__file__).resolve().parent / state_name
        if local.exists():
            candidate = local
        else:
            mt5_path = Path(paths_cfg.get("mt5_path", ""))
            files_sub = paths_cfg.get("mt5_files_subpath", "MQL5/Files")
            remote = (mt5_path / files_sub / state_name).resolve()
            if remote.exists():
                candidate = remote
    if candidate:
        candidate = candidate.resolve()
    return candidate


def parse_statement_html(path: Path) -> List[Dict[str, Any]]:
    text = path.read_text(encoding="utf-16")
    soup = BeautifulSoup(text, "html.parser")
    table = soup.find("table")
    if table is None:
        raise ValueError("Konnte keine Tabelle im Konto-Report finden")
    rows = table.find_all("tr")
    column_row_idx = None
    for idx, row in enumerate(rows):
        cells = [cell.get_text(strip=True) for cell in row.find_all(["td", "th"])]
        if len(cells) >= 7 and cells[0].lower().startswith("zeit"):
            column_row_idx = idx
            break
    if column_row_idx is None:
        raise ValueError("Spaltenkopf 'Zeit' im Report nicht gefunden")

    trades: List[Dict[str, Any]] = []
    for row in rows[column_row_idx + 1 :]:
        cells = [cell.get_text(strip=True) for cell in row.find_all(["td", "th"])]
        if not cells:
            break
        if cells[0].startswith("Ergebnisse") or cells[0].startswith("Balanceoperationen"):
            break
        if len(cells) < 14:
            continue
        open_time = cells[0]
        ticket = cells[1]
        symbol = cells[2]
        order_type = cells[3]
        comment = cells[4]
        volume = _parse_float(cells[5])
        close_time = cells[9]
        profit = _parse_float(cells[-1])
        try:
            opened_at = datetime.strptime(open_time, "%Y.%m.%d %H:%M:%S").replace(tzinfo=timezone.utc)
            closed_at = datetime.strptime(close_time, "%Y.%m.%d %H:%M:%S").replace(tzinfo=timezone.utc)
        except ValueError:
            continue
        trades.append(
            {
                "ticket": ticket,
                "symbol": symbol,
                "volume": volume,
                "profit": profit,
                "order_type": order_type,
                "comment": comment,
                "opened_at": opened_at,
                "closed_at": closed_at,
            }
        )
    return trades


def _parse_float(value: str) -> float:
    cleaned = re.sub(r"[^\d\-\.]", "", value.replace(",", "."))
    try:
        return float(cleaned)
    except ValueError:
        return 0.0


def merge_trades(*trade_lists: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    merged: Dict[str, Dict[str, Any]] = {}
    for trades in trade_lists:
        if not trades:
            continue
        for trade in trades:
            ticket = str(trade.get("ticket") or "")
            if not ticket:
                continue
            merged[ticket] = {
                "ticket": ticket,
                "symbol": trade.get("symbol"),
                "volume": float(trade.get("volume", 0.0)),
                "profit": float(trade.get("profit", 0.0)),
                "order_type": trade.get("order_type"),
                "comment": trade.get("comment"),
                "opened_at": trade.get("opened_at"),
                "closed_at": trade.get("closed_at"),
            }
    normalized = []
    for entry in merged.values():
        opened_at = entry.get("opened_at")
        closed_at = entry.get("closed_at")
        if isinstance(opened_at, str):
            opened_at = parse_iso_datetime(opened_at)
        if isinstance(closed_at, str):
            closed_at = parse_iso_datetime(closed_at)
        entry["opened_at"] = opened_at
        entry["closed_at"] = closed_at
        if closed_at:
            normalized.append(entry)
    normalized.sort(key=lambda trade: trade["closed_at"])
    return normalized


def build_history(
    trades: List[Dict[str, Any]], snapshots: List[Dict[str, Any]]
) -> Dict[str, Any]:
    history_trades = [serialize_trade(trade) for trade in trades]
    history_snaps = [serialize_snapshot(snap) for snap in snapshots]
    return {"version": HISTORY_VERSION, "trades": history_trades, "snapshots": history_snaps}


def write_history_file(history: Dict[str, Any], output_path: Path) -> None:
    payload = {"history": history}
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, ensure_ascii=False)
        handle.write("\n")


def run_webticker(config_path: Path, state_log: Path | None, python_bin: str | None) -> None:
    script_path = Path(__file__).resolve().parent / "TKB-WebTicker.py"
    python_cmd = python_bin or sys.executable
    args = [python_cmd, str(script_path), "--config", str(config_path), "--pretty"]
    if state_log:
        args.extend(["--state-log", str(state_log)])
    LOGGER.info("Starte %s", " ".join(args))
    result = subprocess.run(args, check=False)
    if result.returncode != 0:
        raise RuntimeError("TKB-WebTicker.py fehlgeschlagen")


def main() -> int:
    args = parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    config_path = Path(args.config).resolve() if args.config else DEFAULT_CONFIG
    config = load_config(config_path)
    output_path = detect_output_path(config, args)
    statement_path = detect_statement_path(config, args)
    state_log_path = detect_state_log_path(config, args)
    python_bin = config.get("paths", {}).get("python_bin")

    LOGGER.info("Lese Konto-Report %s", statement_path)
    trades_from_statement = parse_statement_html(statement_path)
    LOGGER.info("Report liefert %d Trades", len(trades_from_statement))

    trades_from_log: List[Dict[str, Any]] = []
    snapshots_from_log: List[Dict[str, Any]] = []
    if state_log_path and state_log_path.exists():
        LOGGER.info("Lese state.log %s", state_log_path)
        entries = load_state_entries(state_log_path)
        trades_from_log = [normalize_trade(entry) for entry in entries if entry.get("type") == "trade"]
        snapshots_from_log = [
            normalize_snapshot(entry) for entry in entries if entry.get("type") == "snapshot"
        ]
        LOGGER.info("state.log liefert %d Trades / %d Snapshots", len(trades_from_log), len(snapshots_from_log))

    merged_trades = merge_trades(trades_from_statement, trades_from_log)
    history = build_history(merged_trades, snapshots_from_log)
    write_history_file(history, output_path)
    LOGGER.info("History geschrieben nach %s (Trades=%d)", output_path, len(merged_trades))

    if not args.skip_render:
        run_webticker(config_path, state_log_path, python_bin)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
