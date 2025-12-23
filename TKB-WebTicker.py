#!/usr/bin/env python3
"""
TKB-WebTicker.py
----------------
Aktualisiert die WebTicker-History (JSON) mit neuen state.log-Daten
und rendert daraus das HTML-Dashboard inkl. Git/FTP Hooks.
"""
from __future__ import annotations

import argparse
import json
import logging
from datetime import datetime, timedelta, timezone
from html import escape as html_escape
from pathlib import Path
from typing import Any, Dict, List, Tuple

from webticker_lib import (
    HISTORY_VERSION,
    isoformat,
    load_state_entries,
    normalize_snapshot,
    normalize_trade,
    parse_iso_datetime,
    serialize_snapshot,
    serialize_trade,
)

LOGGER = logging.getLogger("tkb_webticker")
DEFAULT_CONFIG = Path(__file__).resolve().parent.parent / "TKB-config.json"

WINDOWS = {
    "7d": (7, "Letzte 7 Tage"),
    "30d": (30, "Letzte 30 Tage"),
    "365d": (365, "Letzte 365 Tage"),
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Aktualisiert den Sharrow Live-Ticker")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG), help="Pfad zur TKB-config.json")
    parser.add_argument("--state-log", dest="state_log", help="Pfad zur lokalen state.log")
    parser.add_argument("--output", dest="output_path", help="Override JSON-Ausgabe")
    parser.add_argument("--html-output", dest="html_output", help="Override HTML-Ausgabe")
    parser.add_argument("--marker-output", dest="marker_output", help="Override Welldone-File")
    parser.add_argument("--force-upload", action="store_true", help="FTP Upload erzwingen")
    parser.add_argument("--pretty", action="store_true", help="JSON hübsch formatieren")
    return parser.parse_args()


def load_config(path: Path) -> Dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"Config file {path} fehlt")
    return json.loads(path.read_text(encoding="utf-8"))


def detect_paths(config: Dict[str, Any], args: argparse.Namespace) -> Tuple[Path, Path, Path, Path]:
    web_cfg = config.get("web_ticker", {})
    base_dir = Path(__file__).resolve().parent
    json_name = web_cfg.get("output_json", "TKB-WebTicker.json")
    html_name = web_cfg.get("output_html", "TKB-WebTicker.html")
    welldone_name = web_cfg.get("welldone_file", "TKB-WebTicker-welldone.txt")
    state_name = web_cfg.get("state_log", "Goldjunge-state.log")

    state_log = Path(args.state_log) if args.state_log else base_dir / state_name
    output_json = Path(args.output_path) if args.output_path else base_dir / json_name
    output_html = Path(args.html_output) if args.html_output else base_dir / html_name
    marker_path = Path(args.marker_output) if args.marker_output else base_dir / welldone_name
    return state_log, output_json, output_html, marker_path


def load_history(json_path: Path) -> Dict[str, Any]:
    if not json_path.exists():
        return {"version": HISTORY_VERSION, "trades": [], "snapshots": []}
    try:
        payload = json.loads(json_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        LOGGER.warning("JSON korrupt – starte frische History")
        return {"version": HISTORY_VERSION, "trades": [], "snapshots": []}
    history = payload.get("history")
    if not history:
        LOGGER.info("Bestehende Datei ohne history-Block – initialisiere neu")
        return {"version": HISTORY_VERSION, "trades": [], "snapshots": []}
    return {
        "version": history.get("version", HISTORY_VERSION),
        "trades": list(history.get("trades", [])),
        "snapshots": list(history.get("snapshots", [])),
    }


def merge_history(
    history: Dict[str, Any], trades: List[Dict[str, Any]], snapshots: List[Dict[str, Any]]
) -> None:
    existing_tickets = {entry.get("ticket") for entry in history["trades"]}
    appended = False
    for trade in trades:
        ticket = str(trade.get("ticket"))
        if not ticket or ticket in existing_tickets:
            continue
        history["trades"].append(serialize_trade(trade))
        existing_tickets.add(ticket)
        appended = True
    if appended:
        history["trades"].sort(key=lambda item: item.get("closed_at", ""))

    existing_snaps = {entry.get("timestamp") for entry in history["snapshots"]}
    appended = False
    for snap in snapshots:
        serialized = serialize_snapshot(snap)
        stamp = serialized.get("timestamp")
        if not stamp or stamp in existing_snaps:
            continue
        history["snapshots"].append(serialized)
        existing_snaps.add(stamp)
        appended = True
    if appended:
        history["snapshots"].sort(key=lambda item: item.get("timestamp", ""))

    history["version"] = HISTORY_VERSION


def _materialize_trades(history: Dict[str, Any]) -> List[Dict[str, Any]]:
    trades: List[Dict[str, Any]] = []
    for entry in history.get("trades", []):
        closed_at = parse_iso_datetime(entry.get("closed_at"))
        opened_at = parse_iso_datetime(entry.get("opened_at"))
        if not closed_at:
            continue
        trades.append(
            {
                "ticket": entry.get("ticket"),
                "symbol": entry.get("symbol"),
                "volume": float(entry.get("volume", 0.0)),
                "profit": float(entry.get("profit", 0.0)),
                "order_type": entry.get("order_type"),
                "comment": entry.get("comment"),
                "opened_at": opened_at,
                "closed_at": closed_at,
                "tp_label": entry.get("tp_label"),
                "sl_label": entry.get("sl_label"),
                "exit_reason": entry.get("exit_reason"),
            }
        )
    trades.sort(key=lambda trade: trade["closed_at"])
    return trades


def _materialize_snapshots(history: Dict[str, Any]) -> List[Dict[str, Any]]:
    result: List[Dict[str, Any]] = []
    for entry in history.get("snapshots", []):
        timestamp = parse_iso_datetime(entry.get("timestamp"))
        if not timestamp:
            continue
        result.append(
            {
                "timestamp": timestamp,
                "balance": float(entry.get("balance", 0.0)),
                "equity": float(entry.get("equity", 0.0)),
                "floating": float(entry.get("floating", 0.0)),
            }
        )
    result.sort(key=lambda snap: snap["timestamp"])
    return result


def summarize_trades(trades: List[Dict[str, Any]]) -> Dict[str, Any]:
    if not trades:
        return {"profit": 0.0, "trades": 0, "wins": 0, "losses": 0, "win_rate": 0.0}
    profit = sum(trade["profit"] for trade in trades)
    wins = sum(1 for trade in trades if trade["profit"] > 0)
    losses = sum(1 for trade in trades if trade["profit"] < 0)
    total = len(trades)
    return {
        "profit": round(profit, 2),
        "trades": total,
        "wins": wins,
        "losses": losses,
        "win_rate": round(wins / total * 100, 2) if total else 0.0,
    }


def _canonical_side(order_type: str | None) -> str:
    if not order_type:
        return ""
    side = str(order_type).upper()
    if "BUY" in side:
        return "BUY"
    if "SELL" in side:
        return "SELL"
    return side


EXIT_LABELS = {
    "tp": "Exit: TP",
    "sl": "Exit: SL",
    "manual": "Exit Manual",
}
_DEFAULT_EXIT_TYPE = "manual"
_TP_REASON_HINTS = ("deal_reason_tp", "tp_hit", "takeprofit", "take profit", "target_tp")
_SL_REASON_HINTS = ("deal_reason_sl", "sl_hit", "stoploss", "stop loss", "target_sl")
_TP_COMMENT_HINTS = ("[tp", " tp", "tp ", "tp:", "tp-", "tp hit", "take profit")
_SL_COMMENT_HINTS = ("[sl", " sl", "sl ", "sl:", "sl-", "sl hit", "stop loss")


def _normalize_text(value: Any) -> str:
    return str(value).strip().lower()


def _contains_hint(value: Any, hints: Tuple[str, ...]) -> bool:
    if not value:
        return False
    text = _normalize_text(value)
    return any(hint in text for hint in hints)


def determine_exit_type(trade: Dict[str, Any] | None) -> str:
    if not trade:
        return _DEFAULT_EXIT_TYPE
    if trade.get("tp_label"):
        return "tp"
    if _contains_hint(trade.get("exit_reason"), _TP_REASON_HINTS):
        return "tp"
    if _contains_hint(trade.get("comment"), _TP_COMMENT_HINTS):
        return "tp"
    if trade.get("sl_label"):
        return "sl"
    if _contains_hint(trade.get("exit_reason"), _SL_REASON_HINTS):
        return "sl"
    if _contains_hint(trade.get("comment"), _SL_COMMENT_HINTS):
        return "sl"
    return _DEFAULT_EXIT_TYPE


def _build_exit_label(exit_type: str) -> str:
    return EXIT_LABELS.get(exit_type, EXIT_LABELS[_DEFAULT_EXIT_TYPE])


def summarize_single_trade(trade: Dict[str, Any] | None, *, include_comment: bool = False) -> Dict[str, Any] | None:
    if not trade:
        return None
    exit_type = determine_exit_type(trade)
    summary = {
        "ticket": trade.get("ticket"),
        "symbol": trade.get("symbol"),
        "profit": round(trade.get("profit", 0.0), 2),
        "volume": round(trade.get("volume", 0.0), 2),
        "order_type": _canonical_side(trade.get("order_type")),
        "closed_at": isoformat(trade.get("closed_at")) if trade.get("closed_at") else None,
        "exit": _build_exit_label(exit_type),
        "exit_type": exit_type,
        "comment": trade.get("comment"),
    }
    if not include_comment:
        summary.pop("comment", None)
    return summary


def build_windows(trades: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    now = datetime.now(timezone.utc)
    windows: Dict[str, Dict[str, Any]] = {}
    for key, (days, _) in WINDOWS.items():
        cutoff = now - timedelta(days=days)
        window_trades = [trade for trade in trades if trade["closed_at"] >= cutoff]
        summary = summarize_trades(window_trades)
        best_trade = max(window_trades, key=lambda t: t["profit"], default=None)
        worst_trade = min(window_trades, key=lambda t: t["profit"], default=None)
        summary["best_trade"] = summarize_single_trade(best_trade)
        summary["worst_trade"] = summarize_single_trade(worst_trade)
        windows[key] = summary
    return windows


def build_symbol_lists(trades: List[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    stats: Dict[str, Dict[str, Any]] = {}
    for trade in trades:
        symbol = trade.get("symbol", "UNKWN")
        bucket = stats.setdefault(
            symbol, {"symbol": symbol, "profit": 0.0, "trades": 0, "wins": 0, "losses": 0}
        )
        bucket["profit"] += trade["profit"]
        bucket["trades"] += 1
        if trade["profit"] > 0:
            bucket["wins"] += 1
        elif trade["profit"] < 0:
            bucket["losses"] += 1
    ordered = sorted(stats.values(), key=lambda item: item["profit"], reverse=True)
    for idx, entry in enumerate(ordered, 1):
        entry["rank"] = idx
    top = ordered[:5]
    bottom_slice = ordered[-5:]
    bottom = sorted(bottom_slice, key=lambda item: item["rank"])
    return top, bottom


def build_recent_trades(trades: List[Dict[str, Any]], limit: int = 10) -> List[Dict[str, Any]]:
    recent = trades[-limit:][::-1]
    result: List[Dict[str, Any]] = []
    for trade in recent:
        summary = summarize_single_trade(trade, include_comment=True)
        if summary:
            result.append(summary)
    return result


def build_daily_breakdown(trades: List[Dict[str, Any]], days: int = 7) -> List[Dict[str, Any]]:
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    buckets: Dict[str, Dict[str, Any]] = {}
    for trade in trades:
        if trade["closed_at"] < cutoff:
            continue
        key = trade["closed_at"].date().isoformat()
        bucket = buckets.setdefault(key, {"date": key, "profit": 0.0, "trades": 0})
        bucket["profit"] += trade["profit"]
        bucket["trades"] += 1
    return sorted(buckets.values(), key=lambda item: item["date"])


def build_payload(
    history: Dict[str, Any],
    trades: List[Dict[str, Any]],
    snapshots: List[Dict[str, Any]],
    config: Dict[str, Any],
    trade_active: bool,
    pause_message: str | None,
) -> Dict[str, Any]:
    project_name = config.get("project", {}).get("name", "Sharrow")
    now = datetime.now(timezone.utc)
    latest_snapshot = snapshots[-1] if snapshots else None
    account = {
        "balance": round(latest_snapshot.get("balance", 0.0), 2) if latest_snapshot else 0.0,
        "equity": round(latest_snapshot.get("equity", 0.0), 2) if latest_snapshot else 0.0,
        "floating": round(latest_snapshot.get("floating", 0.0), 2) if latest_snapshot else 0.0,
        "snapshot_at": isoformat(latest_snapshot["timestamp"]) if latest_snapshot else None,
    }

    overall = summarize_trades(trades)
    windows = build_windows(trades)
    top_symbols, bottom_symbols = build_symbol_lists(trades)
    recent_trades = build_recent_trades(trades)
    daily_breakdown = build_daily_breakdown(trades)

    meta = {
        "bot": project_name,
        "generated_at": isoformat(now),
        "snapshot_at": account.get("snapshot_at"),
        "trade_active": trade_active,
    }
    if not trade_active:
        meta["status"] = "paused"
        meta["pause_message"] = pause_message or "Handel aktuell ausgesetzt."
        meta["pause_since"] = isoformat(now)

    payload = {
        "meta": meta,
        "account": account,
        "overall": overall,
        "windows": windows,
        "top_symbols": top_symbols,
        "bottom_symbols": bottom_symbols,
        "recent_trades": recent_trades,
        "daily_breakdown": daily_breakdown,
        "history": history,
    }
    return payload


def render_html(payload: Dict[str, Any]) -> str:
    meta = payload.get("meta", {})
    account = payload.get("account", {})
    windows = payload.get("windows", {})
    overall = payload.get("overall", {})
    top_symbols = payload.get("top_symbols", [])
    bottom_symbols = payload.get("bottom_symbols", [])
    recent = payload.get("recent_trades", [])
    pause_message = meta.get("pause_message") if meta.get("status") == "paused" else None

    def fmt_money(value: float) -> str:
        return f"{value:,.2f}".replace(",", " ").replace(" ", "\u00a0")

    def fmt_pct(value: float) -> str:
        return f"{value:.2f}%"

    def render_symbol_table(items: List[Dict[str, Any]]) -> str:
        if not items:
            return "<p class='muted'>Keine Daten</p>"
        rows = []
        for fallback_idx, stat in enumerate(items, 1):
            rank = stat.get("rank", fallback_idx)
            rows.append(
                "<tr>"
                f"<td>{rank}.</td>"
                f"<td>{html_escape(stat.get('symbol',''))}</td>"
                f"<td class='num'>{fmt_money(stat.get('profit',0.0))}</td>"
                f"<td class='num'>{stat.get('trades',0)}</td>"
                "</tr>"
            )
        return (
            "<table><thead><tr><th>#</th><th>Symbol</th><th class='num'>Profit</th>"
            "<th class='num'>Trades</th></tr></thead><tbody>"
            + "".join(rows)
            + "</tbody></table>"
        )

    def chunked(items: List[str], size: int) -> List[List[str]]:
        return [items[idx : idx + size] for idx in range(0, len(items), size)]

    recent_cards: List[str] = []
    for trade in recent:
        profit_cls = "pos" if trade.get("profit", 0.0) >= 0 else "neg"
        side = trade.get("order_type") or ""
        side_cls = "buy" if side == "BUY" else "sell" if side == "SELL" else ""
        volume = trade.get("volume", 0.0)
        exit_label = trade.get("exit") or EXIT_LABELS[_DEFAULT_EXIT_TYPE]
        exit_type = trade.get("exit_type") or _DEFAULT_EXIT_TYPE
        side_markup = ""
        if side:
            side_markup = f" · <span class=\"side {side_cls}\">{html_escape(side)}</span>"
        recent_cards.append(
            "<div class='trade-card'>"
            f"<div class='trade-top'>{html_escape(trade.get('symbol',''))}"
            f"{side_markup} · {volume:.2f} Lot</div>"
            f"<div class='trade-profit {profit_cls}'>{fmt_money(trade.get('profit',0.0))}</div>"
            f"<div class='trade-meta exit {exit_type}'>{html_escape(exit_label)}</div>"
            f"<div class='trade-meta'>{html_escape(trade.get('closed_at',''))}</div>"
            "</div>"
        )
    if recent_cards:
        recent_rows = [
            "<div class='trade-row'>" + "".join(row_cards) + "</div>"
            for row_cards in chunked(recent_cards, 5)
        ]
        recent_markup = "".join(recent_rows)
    else:
        recent_markup = "<p class='muted'>Keine Trades verfügbar.</p>"

    def render_trade_hint(trade: Dict[str, Any] | None, label: str) -> str:
        if not trade:
            return f"<div class='sub-line muted'>{label}: –</div>"
        profit = trade.get("profit", 0.0)
        profit_cls = "pos" if profit >= 0 else "neg"
        symbol = trade.get("symbol") or "-"
        side = trade.get("order_type") or ""
        side_cls = "buy" if side == "BUY" else "sell" if side == "SELL" else ""
        volume = trade.get("volume", 0.0)
        pieces: List[str] = [html_escape(symbol)]
        if side:
            pieces.append(f"<span class='side {side_cls}'>{side}</span>")
        pieces.append(f"{volume:.2f} Lot")
        pieces.append(fmt_money(profit))
        exit_label = trade.get("exit")
        if exit_label:
            pieces.append(html_escape(exit_label))
        closed_at = trade.get("closed_at") or ""
        if closed_at:
            pieces.append(html_escape(closed_at))
        meta = " · ".join(pieces)
        return f"<div class='sub-line {profit_cls}'>{label}: {meta}</div>"

    window_cards = []
    for key, (_, label) in WINDOWS.items():
        stats = windows.get(key, {})
        window_cards.append(
            "<div class='stat-card'>"
            f"<div class='label'>{label}</div>"
            f"<div class='value'>{fmt_money(stats.get('profit',0.0))}</div>"
            f"<div class='meta-line'>{stats.get('trades',0)} Trades · {fmt_pct(stats.get('win_rate',0.0))}</div>"
            f"{render_trade_hint(stats.get('best_trade'), 'Best')}"
            f"{render_trade_hint(stats.get('worst_trade'), 'Worst')}"
            "</div>"
        )

    html = f"""<!DOCTYPE html>
<html lang="de">
<head>
  <meta charset="utf-8" />
  <title>{html_escape(meta.get('bot','Sharrow'))} Live-Ticker</title>
  <style>
    body {{ font-family: 'Inter', Arial, sans-serif; margin: 0; padding: 24px; background: #070c16; color: #f5f6fb; }}
    h1 {{ margin: 0 0 12px; font-size: 1.8rem; }}
    h2 {{ margin: 0 0 12px; font-size: 1.4rem; }}
    .meta {{ color: #9aa3c1; margin-bottom: 20px; }}
    .banner {{ padding: 14px 18px; border-radius: 10px; margin-bottom: 20px; font-weight: 600; }}
    .banner.paused {{ background: #402726; border: 1px solid #f87171; color: #fcd9d7; }}
    .cards {{ display: grid; grid-template-columns: repeat(auto-fit,minmax(160px,1fr)); gap: 16px; margin-bottom: 30px; }}
    .card {{ background: #11162a; border-radius: 12px; padding: 16px; box-shadow: 0 12px 32px rgba(0,0,0,0.45); }}
    .card .label {{ color: #9aa3c1; font-size: 0.85rem; margin-bottom: 6px; }}
    .card .value {{ font-size: 1.4rem; font-weight: 600; }}
    .stat-grid {{ display: grid; grid-template-columns: repeat(auto-fit,minmax(200px,1fr)); gap: 14px; }}
    .stat-card {{ background: #11162a; border-radius: 12px; padding: 16px; }}
    .stat-card .label {{ color: #9aa3c1; font-size: 0.85rem; margin-bottom: 6px; }}
    .stat-card .value {{ font-size: 1.2rem; font-weight: 600; margin-bottom: 6px; }}
    .stat-card .meta-line {{ color: #8b93b3; font-size: 0.85rem; }}
    .stat-card .sub-line {{ font-size: 0.8rem; margin-top: 6px; color: #8d95b6; }}
    .stat-card .sub-line.pos {{ color: #4ade80; }}
    .stat-card .sub-line.neg {{ color: #f87171; }}
    .section {{ margin-bottom: 36px; }}
    table {{ width: 100%; border-collapse: collapse; background: #11162a; border-radius: 12px; overflow: hidden; }}
    th,td {{ padding: 10px 12px; text-align: left; }}
    th {{ background: #1b2340; font-weight: 500; }}
    tr:nth-child(even) td {{ background: #151c32; }}
    .num {{ text-align: right; font-variant-numeric: tabular-nums; }}
    .trade-list {{ display: flex; flex-direction: column; gap: 14px; }}
    .trade-row {{ display: grid; grid-template-columns: repeat(5,minmax(0,1fr)); gap: 12px; }}
    @media (max-width: 1500px) {{
      .trade-row {{ grid-template-columns: repeat(auto-fit,minmax(220px,1fr)); }}
    }}
    .trade-card {{ background: #11162a; border-radius: 12px; padding: 14px; }}
    .trade-top {{ font-weight: 600; margin-bottom: 4px; }}
    .side {{ font-weight: 600; }}
    .side.buy {{ color: #60a5fa; }}
    .side.sell {{ color: #f87171; }}
    .trade-profit.pos {{ color: #4ade80; }}
    .trade-profit.neg {{ color: #f87171; }}
    .trade-meta {{ font-size: 0.8rem; color: #8d95b6; }}
    .trade-meta.exit {{ font-weight: 600; }}
    .trade-meta.exit.tp {{ color: #4ade80; }}
    .trade-meta.exit.sl {{ color: #f87171; }}
    .trade-meta.exit.manual {{ color: #8d95b6; }}
    .muted {{ color: #8d95b6; font-size: 0.9rem; }}
  </style>
</head>
<body>
  <h1>{html_escape(meta.get('bot','Sharrow'))} Live-Ticker</h1>
  <div class="meta">Snapshot: {html_escape(account.get('snapshot_at') or '–')} · Generiert: {html_escape(meta.get('generated_at',''))}</div>
  {('<div class="banner paused">' + html_escape(pause_message) + '</div>') if pause_message else ''}
  <div class="cards">
    <div class="card"><div class="label">Balance</div><div class="value">{fmt_money(account.get('balance',0.0))}</div></div>
    <div class="card"><div class="label">Equity</div><div class="value">{fmt_money(account.get('equity',0.0))}</div></div>
    <div class="card"><div class="label">Win-Rate gesamt</div><div class="value">{fmt_pct(overall.get('win_rate',0.0))}</div></div>
    <div class="card"><div class="label">Trades gesamt</div><div class="value">{overall.get('trades',0)}</div></div>
  </div>
  <div class="section">
    <h2>Performance-Fenster</h2>
    <div class="stat-grid">{''.join(window_cards)}</div>
  </div>
    <div class="section">
      <h2>Letzte Trades</h2>
      <div class="trade-list">{recent_markup}</div>
    </div>
  <div class="section">
    <h2>Top Performer</h2>
    {render_symbol_table(top_symbols)}
  </div>
  <div class="section">
    <h2>Tough Performer</h2>
    {render_symbol_table(bottom_symbols)}
  </div>
</body>
</html>
"""
    return html


def write_payload(payload: Dict[str, Any], path: Path, pretty: bool) -> None:
    history = payload.pop("history")
    to_write = dict(payload)
    to_write["history"] = history
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        if pretty:
            json.dump(to_write, handle, indent=2, ensure_ascii=False)
        else:
            json.dump(to_write, handle, separators=(",", ":"), ensure_ascii=False)
        handle.write("\n")
    payload["history"] = history


def write_html(content: str, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def write_marker(payload: Dict[str, Any], path: Path) -> None:
    windows = payload.get("windows", {})
    week = windows.get("7d", {})
    timestamp = isoformat(datetime.now(timezone.utc))
    content = (
        f"{timestamp}\nprofit_7d={week.get('profit',0.0)}\ntrades_7d={week.get('trades',0)}\n"
    )
    path.write_text(content, encoding="utf-8")


def maybe_upload(files: List[Tuple[str, Path]], upload_cfg: Dict[str, Any]) -> None:
    if not upload_cfg or not upload_cfg.get("enabled"):
        return
    protocol = upload_cfg.get("protocol", "ftp").lower()
    if protocol != "ftp":
        raise RuntimeError(f"Unsupported upload protocol: {protocol}")
    host = upload_cfg.get("host")
    username = upload_cfg.get("username")
    password = upload_cfg.get("password")
    port = int(upload_cfg.get("port", 21))
    remote_json = upload_cfg.get("json_remote_path")
    remote_html = upload_cfg.get("html_remote_path")
    if not all([host, username, password]) or not any([remote_json, remote_html]):
        raise RuntimeError("FTP Upload aktiviert, aber Credentials/Pfade fehlen")
    with ftplib.FTP() as ftp:
        ftp.connect(host, port)
        ftp.login(username, password)
        for label, local_path in files:
            target = remote_json if label == "json" else remote_html
            if not target or not local_path.exists():
                continue
            with local_path.open("rb") as handle:
                ftp.storbinary(f"STOR {target}", handle)
    LOGGER.info("FTP Upload abgeschlossen")


def main() -> int:
    args = parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    config = load_config(Path(args.config).expanduser())
    state_log, output_json, output_html, marker_path = detect_paths(config, args)

    history = load_history(output_json)
    entries = load_state_entries(state_log) if state_log and state_log.exists() else []
    trades_from_log = [normalize_trade(entry) for entry in entries if entry.get("type") == "trade"]
    snapshots_from_log = [
        normalize_snapshot(entry) for entry in entries if entry.get("type") == "snapshot"
    ]
    merge_history(history, trades_from_log, snapshots_from_log)

    trades = _materialize_trades(history)
    snapshots = _materialize_snapshots(history)
    trade_active = bool(config.get("trade_active", True))
    pause_message = config.get("trade_pause_message")
    payload = build_payload(history, trades, snapshots, config, trade_active, pause_message)

    write_payload(payload, output_json, args.pretty)
    html_content = render_html(payload)
    write_html(html_content, output_html)
    write_marker(payload, marker_path)

    upload_cfg = dict(config.get("web_ticker", {}).get("upload", {}))
    if args.force_upload:
        upload_cfg["enabled"] = True
    maybe_upload([("json", output_json), ("html", output_html)], upload_cfg)
    LOGGER.info("WebTicker aktualisiert (Trades=%s)", len(trades))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
