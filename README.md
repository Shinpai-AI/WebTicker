# 📊 Sharrow WebTicker

Öffentliche Referenz von **Shinpai-AI (Hannes Kell)** für das interne Projekt **Goldjunge**.
Der WebTicker visualisiert die aktuelle Performance des MetaTrader 5 EAs „Sharrow“ und
liefert die Grundlage für Website-Einbindungen sowie Backoffice-Analysen.

- **Live-Dashboard:** https://shinpai-ai.github.io/WebTicker/TKB-WebTicker.html

---

## 🚀 Was liefert der WebTicker?

- Kontostand, Equity und Floating P/L
- Gewinn/Verlust für 7/30/365 Tage
- Letzte zehn Trades inkl. Symbol, Profit und Kommentar
- Top-/Tough-Performer (Symbolranking)
- Pause-Banner bei deaktiviertem Handel (`trade_active=false`)

Alle Daten werden als JSON (`TKB-WebTicker.json`) und als HTML-Dashboard bereitgestellt und
stündlich via GitHub Pages veröffentlicht.

---

## 🔁 Pipeline (Kurzüberblick)

1. **Kopieren** – `RUN-WebTicker.sh` zieht die aktuelle `Goldjunge-state.log` aus MT5.
2. **Mergen** – `TKB-WebTicker.py` fügt neue Trades/Snapshots in die History ein und generiert JSON + HTML.
3. **Deploy** – Bei Erfolg entsteht `TKB-WebTicker-welldone.txt` und ein Git-Push (bzw. später FTP/API).

Die Konfiguration liegt eine Ebene höher in `../TKB-config.json`.

---

## 📁 Schlüsseldateien

- `TKB-WebTicker.py` … Hauptlogik (Merge, Statistik, HTML/JSON)
- `TKB-WebTicker-initial.py` … einmaliger Import aus Konto-Report und state.log
- `RUN-WebTicker.sh` … Cron-/Automationsskript inkl. Git-Push
- `webticker_lib.py` … Parser/Utilities
- `TKB-WebTicker.json` … persistente History + Website-Feed
- `TKB-WebTicker.html` … fertiges Dashboard für GitHub Pages

---

## 🧩 Initialer Import

```bash
cd /media/shinpai/Shinpai-AI/Trading/Goldjunge/WebTicker
python3 TKB-WebTicker-initial.py
```

Das Skript nutzt automatisch:
- Config `../TKB-config.json`
- Konto-Report aus `web_ticker.initial_statement`
- State-Log aus `web_ticker.state_log` (lokal oder direkt aus dem MT5-Verzeichnis)

Parameter wie `--statement`, `--state-log` oder `--output` bleiben für Spezialfälle verfügbar.

---

## ⏱ Regulärer Lauf / Cron

```bash
cd /media/shinpai/Shinpai-AI/Trading/Goldjunge/WebTicker
bash RUN-WebTicker.sh
```

Typischer Cron-Eintrag (stündlich zur Minute 05):

```
5 * * * * /media/shinpai/Shinpai-AI/Trading/Goldjunge/WebTicker/RUN-WebTicker.sh >> /var/log/webticker.cron 2>&1
```

---

## ⚙️ Relevante Config-Blöcke (`../TKB-config.json`)

- `paths` → `mt5_path`, `mt5_files_subpath`, `python_bin`
- `web_ticker`
  - `state_log`, `initial_statement`, `output_json`, `output_html`, `welldone_file`, `log_file`
  - `upload` (für spätere FTP/API-Deployments)
- `git_push`
  - `enabled`, `repo_path`, `branch`, `remote`, `ssh_key`, `commit_message`
- `trade_active`, `trade_pause_message`

Alle Pfadangaben können relativ zum WebTicker-Ordner oder absolut erfolgen.

---

## 🖥 Einbettung / Verwendung

- JSON-Endpunkt: `https://shinpai-ai.github.io/WebTicker/TKB-WebTicker.json`
- HTML/iframe direkt nutzbar (s. oben verlinktes Dashboard)
- Für eigenständige Deployments können JSON und HTML auf jeden Webspace kopiert werden.

---

## ✅ Betrieb & Troubleshooting

- Lauf- und Fehlermeldungen: `TKB-WebTicker.log`
- „Welldone“-Marker signalisiert erfolgreichen Lauf; fehlt er, Details im Log prüfen
- Git-Push scheitert? Manuell `git pull --rebase` ausführen und Skript erneut starten
- Bei deaktiviertem Handel (`trade_active=false`) friert das Dashboard die Kennzahlen ein und
  blendet den Hinweistext `trade_pause_message` ein.

Dieses Repository dient als transparente Referenz für alle Beteiligten von Shinpai-AI und
zeigt jederzeit den realen Status des Sharrow-Projekts. Weitere Fragen gern an Hannes Kell /
Shinpai-AI.  
