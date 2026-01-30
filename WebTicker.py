#!/usr/bin/env python3
"""
WebTicker.py - Alles in einer Datei!
------------------------------------
Generiert das Trading-Dashboard aus ReportHistory und/oder Goldjunge-state.log

Logik:
1. ReportHistory-*.html verfügbar? → 100% als Basis
   - state.log hat NEUERE Daten? → Nachtragen
   - state.log hat GLEICHE/ÄLTERE? → Ignorieren
2. ReportHistory NICHT verfügbar? → state.log als Basis
3. NICHTS verfügbar? → Fehler "Keine Daten anliegend!"
"""

import glob
import json
import logging
import re
import sys
from datetime import datetime, timedelta, timezone
from html import escape as html_escape
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

try:
    from bs4 import BeautifulSoup
except ImportError:
    print("FEHLER: beautifulsoup4 nicht installiert!")
    print("Bitte ausführen: pip install -r requirements.txt")
    sys.exit(1)

# =============================================================================
# CONFIGURATION
# =============================================================================

SCRIPT_DIR = Path(__file__).resolve().parent
BOT_NAME = "Goldjunge (Ray)"

# Input files (im Arbeitsverzeichnis)
REPORT_PATTERN = "ReportHistory-*.html"
STATE_LOG_NAME = "Goldjunge-state.log"

# Output files
OUTPUT_JSON = SCRIPT_DIR / "WebTicker.json"
OUTPUT_HTML = SCRIPT_DIR / "WebTicker.html"
OUTPUT_LOG = SCRIPT_DIR / "WebTicker.log"
OUTPUT_WELLDONE = SCRIPT_DIR / "welldone"

# Logging setup
logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.FileHandler(OUTPUT_LOG, encoding="utf-8"),
        logging.StreamHandler(sys.stdout)
    ]
)
LOG = logging.getLogger("WebTicker")

# =============================================================================
# UTILITY FUNCTIONS
# =============================================================================

def isoformat(dt: datetime) -> str:
    """Datetime zu ISO-String (UTC, ohne Mikrosekunden)."""
    return dt.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def parse_iso(value: Optional[str]) -> Optional[datetime]:
    """ISO-String zu datetime."""
    if not value:
        return None
    cleaned = value.strip().replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(cleaned).astimezone(timezone.utc)
    except ValueError:
        return None


def parse_mt5_timestamp(value: str) -> Optional[datetime]:
    """MT5 Timestamp (YYYY.MM.DD HH:MM:SS) zu datetime."""
    try:
        return datetime.strptime(value.strip(), "%Y.%m.%d %H:%M:%S").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def parse_float(value: str) -> float:
    """String zu float (mit Komma/Punkt-Handling)."""
    cleaned = re.sub(r"[^\d\-\.]", "", value.replace(",", "."))
    try:
        return float(cleaned)
    except ValueError:
        return 0.0


def canonical_side(order_type: Optional[str]) -> str:
    """Normalisiert BUY/SELL."""
    if not order_type:
        return ""
    upper = str(order_type).upper()
    if "BUY" in upper:
        return "BUY"
    if "SELL" in upper:
        return "SELL"
    return upper


# =============================================================================
# DATA LOADING - ReportHistory (HTML)
# =============================================================================

def find_report_file() -> Optional[Path]:
    """Sucht ReportHistory-*.html im Arbeitsverzeichnis."""
    pattern = str(SCRIPT_DIR / REPORT_PATTERN)
    files = glob.glob(pattern)
    if not files:
        return None
    # Neueste Datei nehmen (falls mehrere)
    return Path(sorted(files, key=lambda f: Path(f).stat().st_mtime, reverse=True)[0])


def load_report_html(path: Path) -> List[Dict[str, Any]]:
    """Parst ReportHistory HTML und extrahiert Trades."""
    LOG.info(f"Lade ReportHistory: {path.name}")

    # Versuche verschiedene Encodings
    text = None
    for encoding in ("utf-16", "utf-16-le", "utf-8-sig", "utf-8", "latin-1"):
        try:
            text = path.read_text(encoding=encoding)
            break
        except (UnicodeDecodeError, UnicodeError):
            continue

    if text is None:
        LOG.error(f"Kann {path} nicht dekodieren!")
        return []

    soup = BeautifulSoup(text, "html.parser")
    table = soup.find("table")
    if not table:
        LOG.error("Keine Tabelle im Report gefunden!")
        return []

    rows = table.find_all("tr")

    # Finde Spaltenheader
    header_idx = None
    for idx, row in enumerate(rows):
        cells = [c.get_text(strip=True) for c in row.find_all(["td", "th"])]
        if len(cells) >= 7 and cells[0].lower().startswith("zeit"):
            header_idx = idx
            break

    if header_idx is None:
        LOG.error("Spaltenheader 'Zeit' nicht gefunden!")
        return []

    trades = []
    for row in rows[header_idx + 1:]:
        cells = [c.get_text(strip=True) for c in row.find_all(["td", "th"])]
        if not cells:
            break
        if cells[0].startswith("Ergebnisse") or cells[0].startswith("Balanceoperationen"):
            break
        if len(cells) < 14:
            continue

        opened_at = parse_mt5_timestamp(cells[0])
        closed_at = parse_mt5_timestamp(cells[9])

        if not opened_at or not closed_at:
            continue

        trade = {
            "ticket": cells[1],
            "symbol": cells[2],
            "order_type": cells[3],
            "comment": cells[4],
            "volume": parse_float(cells[5]),
            "profit": parse_float(cells[-1]),
            "opened_at": opened_at,
            "closed_at": closed_at,
            "source": "report"
        }

        # Exit-Erkennung (TP/SL)
        close_price = parse_float(cells[10])
        tp_price = parse_float(cells[8])
        sl_price = parse_float(cells[7])

        if tp_price and abs(close_price - tp_price) < 0.0001:
            trade["exit_type"] = "tp"
        elif sl_price and abs(close_price - sl_price) < 0.0001:
            trade["exit_type"] = "sl"
        else:
            trade["exit_type"] = "manual"

        trades.append(trade)

    LOG.info(f"ReportHistory: {len(trades)} Trades geladen")
    return trades


# =============================================================================
# DATA LOADING - Goldjunge-state.log
# =============================================================================

def find_state_log() -> Optional[Path]:
    """Sucht Goldjunge-state.log im Arbeitsverzeichnis."""
    path = SCRIPT_DIR / STATE_LOG_NAME
    return path if path.exists() else None


def load_state_log(path: Path) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Parst state.log und extrahiert Trades + Snapshots."""
    LOG.info(f"Lade state.log: {path.name}")

    # Versuche verschiedene Encodings
    raw = path.read_bytes()
    text = None
    for encoding in ("utf-16-le", "utf-8-sig", "utf-8"):
        try:
            text = raw.decode(encoding)
            break
        except UnicodeDecodeError:
            continue

    if text is None:
        LOG.error(f"Kann {path} nicht dekodieren!")
        return [], []

    trades = []
    snapshots = []

    for line in text.splitlines():
        if "[WEB_TICKER]" not in line:
            continue

        # Timestamp aus Log-Zeile
        try:
            ts_end = line.find("]")
            ts_str = line[1:ts_end] if line.startswith("[") else None
            log_ts = parse_mt5_timestamp(ts_str) if ts_str else None
        except:
            log_ts = None

        # JSON-Payload extrahieren
        json_start = line.find("{", line.find("[WEB_TICKER]"))
        if json_start == -1:
            continue

        try:
            payload = json.loads(line[json_start:].strip())
        except json.JSONDecodeError:
            continue

        entry_type = payload.get("type")

        if entry_type == "trade":
            closed_at = parse_iso(payload.get("closed_at")) or log_ts
            opened_at = parse_iso(payload.get("opened_at"))

            if not closed_at:
                continue

            trade = {
                "ticket": str(payload.get("ticket")),
                "symbol": payload.get("symbol", "UNKNOWN"),
                "order_type": payload.get("order_type") or payload.get("direction"),
                "comment": payload.get("comment") or payload.get("label"),
                "volume": float(payload.get("volume", 0.0)),
                "profit": float(payload.get("profit", 0.0)),
                "opened_at": opened_at,
                "closed_at": closed_at,
                "exit_type": _detect_exit_type(payload),
                "source": "state_log"
            }
            trades.append(trade)

        elif entry_type == "snapshot":
            timestamp = parse_iso(payload.get("timestamp")) or log_ts
            if timestamp:
                snapshots.append({
                    "timestamp": timestamp,
                    "balance": float(payload.get("balance", 0.0)),
                    "equity": float(payload.get("equity", 0.0)),
                    "floating": float(payload.get("floating", 0.0)),
                })

    LOG.info(f"state.log: {len(trades)} Trades, {len(snapshots)} Snapshots")
    return trades, snapshots


def _detect_exit_type(payload: Dict[str, Any]) -> str:
    """Erkennt Exit-Typ aus Payload."""
    if payload.get("tp_label"):
        return "tp"
    if payload.get("sl_label"):
        return "sl"

    exit_reason = str(payload.get("exit_reason", "")).lower()
    comment = str(payload.get("comment", "")).lower()

    if any(hint in exit_reason or hint in comment for hint in ("tp", "takeprofit", "take profit")):
        return "tp"
    if any(hint in exit_reason or hint in comment for hint in ("sl", "stoploss", "stop loss")):
        return "sl"

    return "manual"


# =============================================================================
# DATA MERGING - Die Kern-Logik!
# =============================================================================

def merge_data(
    report_trades: List[Dict[str, Any]],
    log_trades: List[Dict[str, Any]],
    log_snapshots: List[Dict[str, Any]]
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """
    Merged Daten nach der heiligen Logik:
    - ReportHistory = 100% Basis
    - state.log = NUR neuere Daten nachtragen
    """

    # Alle Report-Trades als Basis (nach Ticket indiziert)
    merged: Dict[str, Dict[str, Any]] = {}
    latest_report_time: Optional[datetime] = None

    for trade in report_trades:
        ticket = str(trade.get("ticket"))
        if ticket:
            merged[ticket] = trade
            closed = trade.get("closed_at")
            if closed and (latest_report_time is None or closed > latest_report_time):
                latest_report_time = closed

    # state.log Trades: NUR wenn NEUER als Report
    added_from_log = 0
    for trade in log_trades:
        ticket = str(trade.get("ticket"))
        if not ticket:
            continue

        # Schon im Report? → Ignorieren
        if ticket in merged:
            continue

        # Neuer als Report? → Hinzufügen
        closed = trade.get("closed_at")
        if latest_report_time is None or (closed and closed > latest_report_time):
            merged[ticket] = trade
            added_from_log += 1

    if added_from_log > 0:
        LOG.info(f"Aus state.log nachgetragen: {added_from_log} neuere Trades")

    # Sortieren nach closed_at
    trades = sorted(merged.values(), key=lambda t: t.get("closed_at") or datetime.min.replace(tzinfo=timezone.utc))

    # Snapshots: nur die neuesten behalten (deduplizieren)
    snap_dict: Dict[str, Dict[str, Any]] = {}
    for snap in log_snapshots:
        ts = snap.get("timestamp")
        if ts:
            key = isoformat(ts)
            snap_dict[key] = snap

    snapshots = sorted(snap_dict.values(), key=lambda s: s.get("timestamp"))

    return trades, snapshots


# =============================================================================
# HISTORY MANAGEMENT
# =============================================================================

def load_history() -> Dict[str, Any]:
    """Lädt bestehende History aus JSON."""
    if not OUTPUT_JSON.exists():
        return {"version": 1, "trades": [], "snapshots": []}

    try:
        data = json.loads(OUTPUT_JSON.read_text(encoding="utf-8"))
        history = data.get("history", data)
        return {
            "version": history.get("version", 1),
            "trades": list(history.get("trades", [])),
            "snapshots": list(history.get("snapshots", []))
        }
    except (json.JSONDecodeError, KeyError):
        LOG.warning("JSON korrupt - starte frisch")
        return {"version": 1, "trades": [], "snapshots": []}


def save_history(trades: List[Dict[str, Any]], snapshots: List[Dict[str, Any]], payload: Dict[str, Any]) -> None:
    """Speichert History + Payload als JSON."""

    # Trades serialisieren
    history_trades = []
    for t in trades:
        history_trades.append({
            "ticket": t.get("ticket"),
            "symbol": t.get("symbol"),
            "volume": round(float(t.get("volume", 0)), 5),
            "profit": round(float(t.get("profit", 0)), 5),
            "order_type": canonical_side(t.get("order_type")),
            "comment": t.get("comment"),
            "opened_at": isoformat(t["opened_at"]) if t.get("opened_at") else None,
            "closed_at": isoformat(t["closed_at"]) if t.get("closed_at") else None,
            "exit_type": t.get("exit_type", "manual"),
        })

    # Snapshots serialisieren
    history_snaps = []
    for s in snapshots:
        history_snaps.append({
            "timestamp": isoformat(s["timestamp"]) if s.get("timestamp") else None,
            "balance": round(float(s.get("balance", 0)), 2),
            "equity": round(float(s.get("equity", 0)), 2),
            "floating": round(float(s.get("floating", 0)), 2),
        })

    payload["history"] = {
        "version": 1,
        "trades": history_trades,
        "snapshots": history_snaps
    }

    OUTPUT_JSON.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    LOG.info(f"JSON gespeichert: {OUTPUT_JSON.name}")


# =============================================================================
# STATISTICS & ANALYSIS
# =============================================================================

def calc_stats(trades: List[Dict[str, Any]], days: Optional[int] = None) -> Dict[str, Any]:
    """Berechnet Statistiken für Trades."""
    now = datetime.now(timezone.utc)

    if days:
        cutoff = now - timedelta(days=days)
        filtered = [t for t in trades if t.get("closed_at") and t["closed_at"] >= cutoff]
    else:
        filtered = trades

    if not filtered:
        return {"profit": 0.0, "trades": 0, "wins": 0, "losses": 0, "win_rate": 0.0}

    profit = sum(t.get("profit", 0) for t in filtered)
    wins = sum(1 for t in filtered if t.get("profit", 0) > 0)
    losses = sum(1 for t in filtered if t.get("profit", 0) < 0)
    total = len(filtered)

    return {
        "profit": round(profit, 2),
        "trades": total,
        "wins": wins,
        "losses": losses,
        "win_rate": round(wins / total * 100, 2) if total else 0.0
    }


def get_best_worst(trades: List[Dict[str, Any]], days: Optional[int] = None) -> Tuple[Optional[Dict], Optional[Dict]]:
    """Findet besten und schlechtesten Trade."""
    now = datetime.now(timezone.utc)

    if days:
        cutoff = now - timedelta(days=days)
        filtered = [t for t in trades if t.get("closed_at") and t["closed_at"] >= cutoff]
    else:
        filtered = trades

    if not filtered:
        return None, None

    best = max(filtered, key=lambda t: t.get("profit", 0))
    worst = min(filtered, key=lambda t: t.get("profit", 0))

    return best, worst


def get_recent_trades(trades: List[Dict[str, Any]], limit: int = 10) -> List[Dict[str, Any]]:
    """Holt die letzten N Trades."""
    return trades[-limit:][::-1]


# =============================================================================
# HTML GENERATION
# =============================================================================

EXIT_LABELS = {"tp": "Exit: TP", "sl": "Exit: SL", "manual": "Exit Manual"}


def generate_html(trades: List[Dict[str, Any]], snapshots: List[Dict[str, Any]]) -> str:
    """Generiert das HTML Dashboard."""

    now = datetime.now(timezone.utc)
    latest_snap = snapshots[-1] if snapshots else None

    # Stats berechnen
    stats_7d = calc_stats(trades, 7)
    stats_30d = calc_stats(trades, 30)
    stats_365d = calc_stats(trades, 365)
    stats_all = calc_stats(trades)

    best_7d, worst_7d = get_best_worst(trades, 7)
    best_30d, worst_30d = get_best_worst(trades, 30)
    best_365d, worst_365d = get_best_worst(trades, 365)

    recent = get_recent_trades(trades, 10)

    # Helper functions
    def fmt_money(val: float) -> str:
        return f"{val:,.2f}".replace(",", "\u00a0")

    def fmt_pct(val: float) -> str:
        return f"{val:.2f}%"

    def trade_card(t: Dict[str, Any]) -> str:
        profit = t.get("profit", 0)
        profit_cls = "pos" if profit >= 0 else "neg"
        side = canonical_side(t.get("order_type"))
        side_cls = "buy" if side == "BUY" else "sell" if side == "SELL" else ""
        volume = t.get("volume", 0)
        exit_type = t.get("exit_type", "manual")
        exit_label = EXIT_LABELS.get(exit_type, "Exit Manual")
        closed = isoformat(t["closed_at"]) if t.get("closed_at") else ""

        return f"""<div class='trade-card'>
            <div class='trade-top'>{html_escape(t.get('symbol', ''))}
                · <span class="side {side_cls}">{side}</span>
                · {volume:.2f} Lot</div>
            <div class='trade-profit {profit_cls}'>{fmt_money(profit)}</div>
            <div class='trade-meta exit {exit_type}'>{exit_label}</div>
            <div class='trade-meta'>{html_escape(closed)}</div>
        </div>"""

    def trade_hint(t: Optional[Dict[str, Any]], label: str) -> str:
        if not t:
            return f"<div class='sub-line muted'>{label}: –</div>"
        profit = t.get("profit", 0)
        profit_cls = "pos" if profit >= 0 else "neg"
        symbol = t.get("symbol", "-")
        side = canonical_side(t.get("order_type"))
        volume = t.get("volume", 0)
        return f"<div class='sub-line {profit_cls}'>{label}: {symbol} {side} {volume:.2f} Lot {fmt_money(profit)}</div>"

    def window_card(label: str, stats: Dict, best: Optional[Dict], worst: Optional[Dict]) -> str:
        return f"""<div class='stat-card'>
            <div class='label'>{label}</div>
            <div class='value'>{fmt_money(stats['profit'])}</div>
            <div class='meta-line'>{stats['trades']} Trades · {fmt_pct(stats['win_rate'])}</div>
            {trade_hint(best, 'Best')}
            {trade_hint(worst, 'Worst')}
        </div>"""

    # Recent trades HTML
    recent_html = "".join(trade_card(t) for t in recent) if recent else "<p class='muted'>Keine Trades</p>"

    # Balance/Equity
    balance = latest_snap.get("balance", 0) if latest_snap else 0
    equity = latest_snap.get("equity", 0) if latest_snap else 0
    snap_time = isoformat(latest_snap["timestamp"]) if latest_snap and latest_snap.get("timestamp") else "–"

    html = f"""<!DOCTYPE html>
<html lang="de">
<head>
    <meta charset="utf-8">
    <title>{BOT_NAME} Live-Ticker</title>
    <style>
        body {{ font-family: 'Inter', Arial, sans-serif; margin: 0; padding: 24px; background: #070c16; color: #f5f6fb; }}
        h1 {{ margin: 0 0 12px; font-size: 1.8rem; }}
        h2 {{ margin: 24px 0 12px; font-size: 1.4rem; }}
        .meta {{ color: #9aa3c1; margin-bottom: 20px; }}
        .cards {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr)); gap: 16px; margin-bottom: 30px; }}
        .card {{ background: #11162a; border-radius: 12px; padding: 16px; }}
        .card .label {{ color: #9aa3c1; font-size: 0.85rem; margin-bottom: 6px; }}
        .card .value {{ font-size: 1.4rem; font-weight: 600; }}
        .stat-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 14px; }}
        .stat-card {{ background: #11162a; border-radius: 12px; padding: 16px; }}
        .stat-card .label {{ color: #9aa3c1; font-size: 0.85rem; margin-bottom: 6px; }}
        .stat-card .value {{ font-size: 1.2rem; font-weight: 600; margin-bottom: 6px; }}
        .stat-card .meta-line {{ color: #8b93b3; font-size: 0.85rem; }}
        .stat-card .sub-line {{ font-size: 0.8rem; margin-top: 6px; color: #8d95b6; }}
        .sub-line.pos {{ color: #4ade80; }}
        .sub-line.neg {{ color: #f87171; }}
        .trade-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 12px; }}
        .trade-card {{ background: #11162a; border-radius: 12px; padding: 14px; }}
        .trade-top {{ font-weight: 600; margin-bottom: 4px; }}
        .side {{ font-weight: 600; }}
        .side.buy {{ color: #60a5fa; }}
        .side.sell {{ color: #f87171; }}
        .trade-profit.pos {{ color: #4ade80; font-size: 1.1rem; }}
        .trade-profit.neg {{ color: #f87171; font-size: 1.1rem; }}
        .trade-meta {{ font-size: 0.8rem; color: #8d95b6; }}
        .trade-meta.exit {{ font-weight: 600; }}
        .trade-meta.exit.tp {{ color: #4ade80; }}
        .trade-meta.exit.sl {{ color: #f87171; }}
        .muted {{ color: #8d95b6; }}
    </style>
</head>
<body>
    <h1>{BOT_NAME} Live-Ticker</h1>
    <div class="meta">Snapshot: {html_escape(snap_time)} · Generiert: {isoformat(now)}</div>

    <div class="cards">
        <div class="card"><div class="label">Balance</div><div class="value">{fmt_money(balance)}</div></div>
        <div class="card"><div class="label">Equity</div><div class="value">{fmt_money(equity)}</div></div>
        <div class="card"><div class="label">Win-Rate gesamt</div><div class="value">{fmt_pct(stats_all['win_rate'])}</div></div>
        <div class="card"><div class="label">Trades gesamt</div><div class="value">{stats_all['trades']}</div></div>
    </div>

    <h2>Performance-Fenster</h2>
    <div class="stat-grid">
        {window_card("Letzte 7 Tage", stats_7d, best_7d, worst_7d)}
        {window_card("Letzte 30 Tage", stats_30d, best_30d, worst_30d)}
        {window_card("Letzte 365 Tage", stats_365d, best_365d, worst_365d)}
    </div>

    <h2>Letzte Trades</h2>
    <div class="trade-grid">
        {recent_html}
    </div>
</body>
</html>"""

    return html


# =============================================================================
# MAIN
# =============================================================================

def main() -> int:
    LOG.info("=" * 50)
    LOG.info("WebTicker START")
    LOG.info("=" * 50)

    # 1. Datenquellen finden
    report_path = find_report_file()
    log_path = find_state_log()

    report_trades: List[Dict[str, Any]] = []
    log_trades: List[Dict[str, Any]] = []
    log_snapshots: List[Dict[str, Any]] = []

    # 2. Daten laden nach Logik
    if report_path:
        LOG.info(f"ReportHistory gefunden: {report_path.name}")
        report_trades = load_report_html(report_path)

        if log_path:
            LOG.info(f"state.log gefunden: {log_path.name}")
            log_trades, log_snapshots = load_state_log(log_path)
        else:
            LOG.info("state.log nicht gefunden - nur ReportHistory nutzen")

    elif log_path:
        LOG.info("Kein ReportHistory - nutze nur state.log")
        log_trades, log_snapshots = load_state_log(log_path)

    else:
        LOG.error("Keine Daten anliegend!")
        return 1

    # 3. Daten mergen
    trades, snapshots = merge_data(report_trades, log_trades, log_snapshots)
    LOG.info(f"Gesamt: {len(trades)} Trades, {len(snapshots)} Snapshots")

    if not trades:
        LOG.error("Keine Trades nach dem Merge!")
        return 1

    # 4. Payload bauen
    now = datetime.now(timezone.utc)
    stats = calc_stats(trades)
    latest_snap = snapshots[-1] if snapshots else None

    payload = {
        "meta": {
            "bot": BOT_NAME,
            "generated_at": isoformat(now),
            "snapshot_at": isoformat(latest_snap["timestamp"]) if latest_snap else None,
        },
        "account": {
            "balance": round(latest_snap.get("balance", 0), 2) if latest_snap else 0,
            "equity": round(latest_snap.get("equity", 0), 2) if latest_snap else 0,
            "floating": round(latest_snap.get("floating", 0), 2) if latest_snap else 0,
        },
        "overall": stats,
    }

    # 5. JSON speichern
    save_history(trades, snapshots, payload)

    # 6. HTML generieren
    html = generate_html(trades, snapshots)
    OUTPUT_HTML.write_text(html, encoding="utf-8")
    LOG.info(f"HTML gespeichert: {OUTPUT_HTML.name}")

    # 7. Welldone Marker
    stats_7d = calc_stats(trades, 7)
    welldone_content = f"{isoformat(now)}\nprofit_7d={stats_7d['profit']}\ntrades_7d={stats_7d['trades']}\n"
    OUTPUT_WELLDONE.write_text(welldone_content, encoding="utf-8")
    LOG.info(f"Welldone geschrieben: {OUTPUT_WELLDONE.name}")

    LOG.info("=" * 50)
    LOG.info("WebTicker FERTIG!")
    LOG.info("=" * 50)

    return 0


if __name__ == "__main__":
    sys.exit(main())
