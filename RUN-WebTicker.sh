#!/bin/bash
# =============================================================================
# RUN-WebTicker.sh - Starter Script + Git Push
# =============================================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

LOG_FILE="$SCRIPT_DIR/WebTicker.log"
echo "[$(date '+%Y-%m-%d %H:%M:%S')] ===== RUN-WebTicker.sh START =====" >> "$LOG_FILE"

# Python finden (venv oder system)
if [ -f "$SCRIPT_DIR/venv/bin/python3" ]; then
    PYTHON="$SCRIPT_DIR/venv/bin/python3"
elif [ -f "$SCRIPT_DIR/../venv/bin/python3" ]; then
    PYTHON="$SCRIPT_DIR/../venv/bin/python3"
else
    PYTHON="python3"
fi

echo "[$(date '+%Y-%m-%d %H:%M:%S')] Starte: $PYTHON WebTicker.py" >> "$LOG_FILE"
$PYTHON "$SCRIPT_DIR/WebTicker.py"
EXIT_CODE=$?

if [ $EXIT_CODE -eq 0 ]; then
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] WebTicker OK — Git Push..." >> "$LOG_FILE"

    # Git Push (SSH-Key aus TKB-config.json)
    CONFIG_FILE="$SCRIPT_DIR/../TKB-config.json"
    if [ -f "$CONFIG_FILE" ]; then
        GIT_SSH_KEY=$($PYTHON -c "import json; c=json.load(open('$CONFIG_FILE')); print(c.get('git_push',{}).get('ssh_key',''))" 2>/dev/null)
        GIT_ENABLED=$($PYTHON -c "import json; c=json.load(open('$CONFIG_FILE')); print('1' if c.get('git_push',{}).get('enabled') else '0')" 2>/dev/null)
    else
        GIT_SSH_KEY=""
        GIT_ENABLED="0"
        echo "[$(date '+%Y-%m-%d %H:%M:%S')] WARNUNG: Keine TKB-config.json — Git deaktiviert" >> "$LOG_FILE"
    fi

    if [ "$GIT_ENABLED" = "1" ] && [ -n "$GIT_SSH_KEY" ]; then
        export GIT_SSH_COMMAND="ssh -i $GIT_SSH_KEY -o StrictHostKeyChecking=no"
        git add WebTicker.json WebTicker.html 2>> "$LOG_FILE"

        if ! git diff --cached --quiet; then
            git commit -m "chore: update web ticker ($(date '+%Y-%m-%d %H:%M:%S'))" >> "$LOG_FILE" 2>&1
            git push origin main >> "$LOG_FILE" 2>&1
            echo "[$(date '+%Y-%m-%d %H:%M:%S')] Git: Push erfolgreich" >> "$LOG_FILE"
        else
            echo "[$(date '+%Y-%m-%d %H:%M:%S')] Git: Keine Änderungen" >> "$LOG_FILE"
        fi
    else
        echo "[$(date '+%Y-%m-%d %H:%M:%S')] Git: Deaktiviert" >> "$LOG_FILE"
    fi
else
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] FEHLER (Exit: $EXIT_CODE)" >> "$LOG_FILE"
fi

exit $EXIT_CODE
