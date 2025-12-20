# 📊 Sharrow Live-Ticker (WebTicker)

Der WebTicker erzeugt aus MT5-Daten ein vollständiges Trading-Dashboard (JSON + HTML) und
pusht die Ergebnisse stündlich nach GitHub. Alle Pfade & Optionen kommen aus der
`../TKB-config.json`.

---

## 🔁 Überblick – Datenfluss

1. `RUN-WebTicker.sh` kopiert die aktuelle `Goldjunge-state.log` aus MT5 (`MQL5/Files`).
2. `TKB-WebTicker.py` liest die lokale Kopie + vorhandene `TKB-WebTicker.json`, merged neue Trades,
   berechnet 7/30/365-Tage-Statistiken und rendert `TKB-WebTicker.html`.
3. Bei Erfolg entsteht `TKB-WebTicker-welldone.txt`. Nur dann stößt das Runner-Skript den Git-Push
   (oder später FTP/API) an.
4. Das JSON dient gleichzeitig als Historien-Speicher und Website-Datenquelle.

Alle Skripte liegen in diesem Ordner, die globale Config eine Ebene höher.

---

## 📁 Wichtige Dateien

- `TKB-WebTicker.py` – Hauptskript (Merge, JSON, HTML, optional Upload)
- `TKB-WebTicker-initial.py` – Initialimport aus Konto-Statement + state.log
- `RUN-WebTicker.sh` – Cron-/Automationsskript (Copy, Call, Git-Push)
- `webticker_lib.py` – Parser & Shared Utils (nicht anfassen)
- `TKB-WebTicker.json` – Persistente History + aktuelle Ansicht
- `TKB-WebTicker.html` – Fertiges Dashboard (für GitHub Pages / iframe)
- `TKB-WebTicker-welldone.txt` – Marker für erfolgreichen Lauf
- `TKB-WebTicker.log` – Lauf- und Fehlermeldungen

---

## 🚀 Initiales Setup

Vor dem ersten Produktivlauf eine historische Basis erzeugen:

```bash
cd /media/shinpai/Shinpai-AI/Trading/Goldjunge/WebTicker
/usr/bin/python3 TKB-WebTicker-initial.py \
  --config ../TKB-config.json \
  --statement ReportHistory-8304024.html \
  --state-log ../MQL5/Files/Goldjunge-state.log \
  --output TKB-WebTicker.json
```

Das Initialskript akzeptiert HTML- oder XLSX-Statements (gleicher Name wie in der Config) und
bereitet alle Trades so auf, dass `TKB-WebTicker.py` anschließend inkrementell weiterarbeiten kann.

---

## ⏱ Regulärer Lauf (Cron-ready)

```bash
cd /media/shinpai/Shinpai-AI/Trading/Goldjunge/WebTicker
bash RUN-WebTicker.sh
```

Das Runner-Skript erledigt:

1. Config laden (`../TKB-config.json`)
2. MT5 `Goldjunge-state.log` → lokales Arbeitsverzeichnis kopieren
3. `TKB-WebTicker.py` ausführen (JSON/HTML/Welldone erzeugen, FTP optional)
4. Welldone-Datei prüfen und anschließend Git-Autopush auslösen

Cron-Eintrag (stündlich zur Minute 05):

```
5 * * * * /media/shinpai/Shinpai-AI/Trading/Goldjunge/WebTicker/RUN-WebTicker.sh >> /var/log/webticker.cron 2>&1
```

---

## ⚙️ Config-Hooks (`../TKB-config.json`)

Relevant sind vor allem diese Blöcke:

- `paths` → `mt5_path`, `mt5_files_subpath`, `python_bin`
- `web_ticker`
  - `state_log`, `output_json`, `output_html`, `welldone_file`, `log_file`
  - `upload` (FTP-Stub, aktuell optional)
- `git_push`
  - `enabled`, `repo_path`, `branch`, `remote`, `ssh_key`, `commit_message`
- `trade_active` + `trade_pause_message`
  - Wenn `trade_active=false`, friert `TKB-WebTicker.py` die Kennzahlen ein und blendet
    einen Hinweisbanner mit `trade_pause_message` im HTML ein.

Alle Pfade dürfen relativ zum WebTicker-Ordner oder absolut angegeben werden.

---

## 🖥 Output & Einbettung

- JSON / HTML liegen nach jedem Lauf hier im Ordner.
- Wird der Ordner auf GitHub Pages veröffentlicht, kann der Live-Ticker per iframe eingebunden
  werden:

```html
<iframe
  src="https://shinpai-ai.github.io/WebTicker/TKB-WebTicker.html"
  title="Sharrow Live-Ticker"
  style="width:100%;min-height:720px;border:none;">
</iframe>
```

Das HTML enthält:
- Kontostand & Equity Cards
- Gewinn/Verlust für 7/30/365 Tage
- Wochen/Monats/Jahresauswertung
- Pause-Banner (wenn Handel deaktiviert)
- Letzte 10 Trades + beste/schlechteste Symbole

---

## 🛠 Troubleshooting

- Läufe protokolliert in `TKB-WebTicker.log`
- Welldone-Datei fehlt → Python-Lauf fehlgeschlagen (Log prüfen)
- `RUN-WebTicker.sh` bricht ab, wenn MT5-State-Log fehlt oder Git-Repo nicht erreichbar ist
- Git-SSH-Key-Pfad muss in `git_push.ssh_key` hinterlegt sein (z. B. `/home/shinpai/.ssh/shinpai-ai`)

Damit ist der WebTicker komplett automatisierbar und jederzeit reproduzierbar.
