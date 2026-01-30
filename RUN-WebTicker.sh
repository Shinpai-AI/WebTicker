#!/bin/bash
# =============================================================================
# RUN-WebTicker.sh - Starter Script
# =============================================================================
# Aktiviert venv und startet WebTicker.py
# =============================================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Logging
LOG_FILE="$SCRIPT_DIR/WebTicker.log"
echo "[$(date '+%Y-%m-%d %H:%M:%S')] ===== RUN-WebTicker.sh START =====" >> "$LOG_FILE"

# Python finden (venv oder system)
if [ -f "$SCRIPT_DIR/venv/bin/python3" ]; then
    PYTHON="$SCRIPT_DIR/venv/bin/python3"
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Nutze venv: $PYTHON" >> "$LOG_FILE"
elif [ -f "$SCRIPT_DIR/../venv/bin/python3" ]; then
    PYTHON="$SCRIPT_DIR/../venv/bin/python3"
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Nutze parent venv: $PYTHON" >> "$LOG_FILE"
else
    PYTHON="python3"
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Nutze system python3" >> "$LOG_FILE"
fi

# Starten
echo "[$(date '+%Y-%m-%d %H:%M:%S')] Starte: $PYTHON WebTicker.py" >> "$LOG_FILE"
$PYTHON "$SCRIPT_DIR/WebTicker.py"
EXIT_CODE=$?

if [ $EXIT_CODE -eq 0 ]; then
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] ===== ERFOLG =====" >> "$LOG_FILE"
else
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] ===== FEHLER (Exit: $EXIT_CODE) =====" >> "$LOG_FILE"
fi

exit $EXIT_CODE
