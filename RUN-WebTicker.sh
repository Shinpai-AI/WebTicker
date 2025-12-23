#!/usr/bin/env bash
set -euo pipefail

SCRIPT_PATH="${BASH_SOURCE[0]:-$0}"
SCRIPT_DIR="$(cd -- "$(dirname -- "${SCRIPT_PATH}")" && pwd)"

CONFIG_FILE="${TKB_CONFIG_FILE:-${CONFIG_FILE:-}}"
if [[ -n "${CONFIG_FILE}" && -f "${CONFIG_FILE}" ]]; then
  CONFIG_FILE="$(realpath "${CONFIG_FILE}")"
else
  search_dir="${SCRIPT_DIR}"
  found_config=""
  while [[ "${search_dir}" != "/" ]]; do
    candidate="${search_dir}/TKB-config.json"
    if [[ -f "${candidate}" ]]; then
      found_config="${candidate}"
      break
    fi
    search_dir="$(dirname -- "${search_dir}")"
  done
  if [[ -z "${found_config}" ]]; then
    echo "Keine TKB-config.json gefunden (Startpunkt: ${SCRIPT_DIR}). Setze TKB_CONFIG_FILE oder CONFIG_FILE." >&2
    exit 1
  fi
  CONFIG_FILE="${found_config}"
fi

export CONFIG_FILE
export SCRIPT_DIR

eval "$(/usr/bin/python3 <<'PY'
import json
import os
import shlex
from pathlib import Path

config_file = Path(os.environ["CONFIG_FILE"])
script_dir = Path(os.environ["SCRIPT_DIR"])
cfg = json.loads(config_file.read_text(encoding="utf-8"))

paths = cfg.get("paths", {})
web = cfg.get("web_ticker", {})
git = cfg.get("git_push", {})

mt5_path = Path(paths.get("mt5_path", ""))
files_sub = paths.get("mt5_files_subpath", "MQL5/Files")
state_name = web.get("state_log", "Goldjunge-state.log")

state_remote = (mt5_path / files_sub / state_name).as_posix()
state_local = (script_dir / state_name).as_posix()
log_file = (script_dir / web.get("log_file", "TKB-WebTicker.log")).as_posix()
output_json = (script_dir / web.get("output_json", "TKB-WebTicker.json")).as_posix()
output_html = (script_dir / web.get("output_html", "TKB-WebTicker.html")).as_posix()
welldone = (script_dir / web.get("welldone_file", "TKB-WebTicker-welldone.txt")).as_posix()

def emit(key, value):
    print(f"{key}={shlex.quote(str(value))}")

emit("PYTHON_BIN", paths.get("python_bin", "python3"))
emit("STATE_LOG_REMOTE", state_remote)
emit("STATE_LOG_LOCAL", state_local)
emit("LOG_FILE", log_file)
emit("OUTPUT_JSON", output_json)
emit("OUTPUT_HTML", output_html)
emit("WELLDONE_FILE", welldone)

emit("GIT_ENABLED", "1" if git.get("enabled") else "0")
emit("GIT_REPO", git.get("repo_path", script_dir.as_posix()))
emit("GIT_BRANCH", git.get("branch", "main"))
emit("GIT_REMOTE", git.get("remote", "origin"))
emit("GIT_SSH_KEY", git.get("ssh_key", ""))
emit("GIT_COMMIT_MESSAGE", git.get("commit_message", "chore: update web ticker"))
PY
)"

timestamp() {
  date '+%Y-%m-%d %H:%M:%S'
}

mkdir -p "$(dirname -- "${LOG_FILE}")"

log() {
  local msg="$1"
  echo "[$(timestamp)] ${msg}" | tee -a "${LOG_FILE}"
}

fail() {
  local msg="$1"
  log "ERROR: ${msg}"
  exit 1
}

trap 'fail "Script abgebrochen (Zeile ${LINENO})"' ERR

log "===== START WebTicker ====="

if [[ ! -f "${STATE_LOG_REMOTE}" ]]; then
  fail "State-Log ${STATE_LOG_REMOTE} nicht gefunden"
fi

cp -f "${STATE_LOG_REMOTE}" "${STATE_LOG_LOCAL}"
log "State-Log aktualisiert: ${STATE_LOG_LOCAL}"

"${PYTHON_BIN}" "${SCRIPT_DIR}/TKB-WebTicker.py" \
  --config "${CONFIG_FILE}" \
  --state-log "${STATE_LOG_LOCAL}" \
  --output "${OUTPUT_JSON}" \
  --html-output "${OUTPUT_HTML}" \
  --marker-output "${WELLDONE_FILE}" \
  --pretty \
  2>&1 | tee -a "${LOG_FILE}"

if [[ ! -f "${WELLDONE_FILE}" ]]; then
  fail "Welldone-Datei ${WELLDONE_FILE} wurde nicht erzeugt"
fi

log "WebTicker erfolgreich generiert"

if [[ "${GIT_ENABLED}" != "1" ]]; then
  log "Git-Push deaktiviert"
  log "===== DONE ====="
  exit 0
fi

if [[ ! -d "${GIT_REPO}" ]]; then
  fail "Git-Repo ${GIT_REPO} nicht gefunden"
fi

log "Git-Push aktiviert – prüfe Änderungen"

export GIT_SSH_COMMAND="ssh -i ${GIT_SSH_KEY} -o StrictHostKeyChecking=no"

pushd "${GIT_REPO}" >/dev/null
git add "$(basename -- "${OUTPUT_JSON}")" "$(basename -- "${OUTPUT_HTML}")" "$(basename -- "${WELLDONE_FILE}")"

if git diff --cached --quiet; then
  log "Git: Keine Änderungen zum Push"
else
  git commit -m "${GIT_COMMIT_MESSAGE} ($(timestamp))"
  git push "${GIT_REMOTE}" "${GIT_BRANCH}"
  log "Git: Push erfolgreich"
fi
popd >/dev/null

log "===== DONE ====="
