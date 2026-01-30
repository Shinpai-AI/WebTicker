# WebTicker

Trading-Dashboard Generator von **Shinpai-AI**.

**Live:** https://shinpai-ai.github.io/WebTicker/WebTicker.html

---

## Was macht es?

Generiert ein HTML-Dashboard aus MetaTrader 5 Daten:
- Balance, Equity, Floating P/L
- Performance (7/30/365 Tage)
- Letzte 10 Trades
- Win-Rate Statistiken

---

## Starten

```bash
bash RUN-WebTicker.sh
```

Fertig.

---

## Dateien

| Datei | Beschreibung |
|-------|--------------|
| `WebTicker.py` | Hauptlogik (alles in einer Datei!) |
| `RUN-WebTicker.sh` | Starter-Script |
| `requirements.txt` | Python Dependencies |

### Input (manuell reinkopieren):

| Datei | Beschreibung |
|-------|--------------|
| `ReportHistory-*.html` | MT5 Konto-Report (Hauptquelle) |
| `Goldjunge-state.log` | Live state.log (optional, für neuere Daten) |

### Output (wird generiert):

| Datei | Beschreibung |
|-------|--------------|
| `WebTicker.html` | Das Dashboard |
| `WebTicker.json` | Alle Daten als JSON |
| `WebTicker.log` | Log-Datei |
| `welldone` | Erfolgs-Marker |

---

## Daten-Logik

```
ReportHistory vorhanden?
├── JA → 100% als Basis nehmen
│       └── state.log hat NEUERE Daten? → Nachtragen
│
└── NEIN → state.log vorhanden?
           ├── JA → state.log als Basis
           └── NEIN → Fehler "Keine Daten anliegend!"
```

**Keine Duplikate** durch intelligentes Merging per Ticket-ID.

---

## Setup (einmalig)

```bash
pip install -r requirements.txt
```

Oder mit venv:
```bash
python3 -m venv venv
./venv/bin/pip install -r requirements.txt
```

---

## Cron (optional)

Stündlich aktualisieren:
```
5 * * * * /pfad/zu/WebTicker/RUN-WebTicker.sh
```

---

*Shinpai-AI | 2026*
