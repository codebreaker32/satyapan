#!/usr/bin/env bash
# Start Satyapan's Telegram bot (bot/README.md):
#   1. its own engine from this checkout's prototype/ on port 8100 (never the demo's 8000), connected to the
#      forensics service on 8765 when that answers, so voice and face checks run; otherwise the instruction rules only;
#   2. the bot, in the foreground. Logs go to clips/logs/tg-engine.log and clips/logs/tg-bot.log.
# On the workbox run it inside tmux:  tmux new -s tgbot scripts/run_tg_bot.sh
# Stop with Ctrl-C (or kill the bot's PID): the check in progress finishes, then the engine started here stops too.
set -euo pipefail
cd "$(dirname "$0")/.."
FIN=$(pwd)
PROTO="$FIN/prototype"
[ -d "$PROTO/satyapan" ] || { echo "no prototype/satyapan in $FIN"; exit 1; }
# The engine's Python environment: SATYAPAN_ENGINE_VENV, else the laptop's sibling checkout ../satyapan/.venv, else
# prototype/.venv (as in scripts/demo_up.sh). Its code is always this checkout's prototype/ (PYTHONPATH below).
if [ -n "${SATYAPAN_ENGINE_VENV:-}" ]; then ENGINE_VENV="$SATYAPAN_ENGINE_VENV"
elif [ -x "$FIN/../satyapan/.venv/bin/python" ]; then ENGINE_VENV="$FIN/../satyapan/.venv"
else ENGINE_VENV="$PROTO/.venv"; fi
if [ ! -x "$ENGINE_VENV/bin/python" ]; then
  echo "no engine environment at $ENGINE_VENV. Make one, or point SATYAPAN_ENGINE_VENV at one:"
  echo "  python3 -m venv prototype/.venv && prototype/.venv/bin/pip install -e 'prototype[dev,stt,ocr]'"
  exit 1
fi
# The bot needs only the standard library.
BOT_PY=${SATYAPAN_BOT_PYTHON:-$(command -v python3 || echo "$ENGINE_VENV/bin/python")}
PORT=${SATYAPAN_BOT_ENGINE_PORT:-8100}
FORENSICS=${SATYAPAN_BOT_FORENSICS_URL:-http://127.0.0.1:8765}
LOGS="$FIN/clips/logs"
mkdir -p "$LOGS"

# The token first, so a missing or open token file fails before anything starts. It is never printed.
"$BOT_PY" -m bot --check-token

if [ "$PORT" = 8000 ]; then echo "port 8000 is the demo's engine; the bot needs its own (default 8100)"; exit 1; fi
if (exec 3<>"/dev/tcp/127.0.0.1/$PORT") 2>/dev/null; then
  # Never reuse whatever is there: it may be an engine on older code, or someone else's server.
  echo "port $PORT is already in use. Stop what runs there, or pick another: SATYAPAN_BOT_ENGINE_PORT=8110 $0"
  exit 1
fi

if curl -fs -m 3 "$FORENSICS/health" >/dev/null 2>&1; then
  export SATYAPAN_FORENSICS_URL="$FORENSICS"
  CHECKS="instruction rules, plus the voice and face checks of the forensics service at $FORENSICS"
else
  unset SATYAPAN_FORENSICS_URL
  CHECKS="instruction rules only: no forensics service answers at $FORENSICS, so no voice or face check runs"
fi
# As in scripts/demo_up.sh: Whisper large-v3-turbo with greedy decoding, loaded at start-up; the website check
# answers from the recorded registry data (nothing leaves the machine); the offline helper reader stays OFF.
export SATYAPAN_WHISPER_MODEL="${SATYAPAN_WHISPER_MODEL:-large-v3-turbo}"
export SATYAPAN_WHISPER_BEAM="${SATYAPAN_WHISPER_BEAM:-1}"
export SATYAPAN_WHISPER_PRELOAD=1
export SATYAPAN_LIVE_WEB=0
export SATYAPAN_LLM_READER=""

echo "=== $(date '+%F %T') run_tg_bot.sh starts the bot's engine on $PORT" >>"$LOGS/tg-engine.log"
(cd "$PROTO" && PYTHONPATH="$PROTO" exec "$ENGINE_VENV/bin/python" -u -m satyapan.cli serve --port "$PORT") \
  >>"$LOGS/tg-engine.log" 2>&1 &
ENGINE_PID=$!
# Keeps the bot's exit status: under set -e the engine's own 143 from `wait` would otherwise become the script's.
stop_engine() { local rc=$?; kill "$ENGINE_PID" 2>/dev/null || true; wait "$ENGINE_PID" 2>/dev/null || true; exit "$rc"; }
trap stop_engine EXIT

for _ in $(seq 1 120); do
  curl -fs -m 2 "http://127.0.0.1:$PORT/api/health" >/dev/null 2>&1 && break
  if ! kill -0 "$ENGINE_PID" 2>/dev/null; then
    echo "the bot's engine stopped while starting. The end of $LOGS/tg-engine.log:"; tail -20 "$LOGS/tg-engine.log"
    exit 1
  fi
  sleep 1
done
curl -fs -m 2 "http://127.0.0.1:$PORT/api/health" >/dev/null || { echo "the engine did not answer on $PORT"; exit 1; }
echo "engine pid $ENGINE_PID on $PORT ($PROTO), log $LOGS/tg-engine.log"
echo "checks: $CHECKS"
echo "speech-to-text: Whisper $SATYAPAN_WHISPER_MODEL; live website look-up: off; offline helper reader: off"

SATYAPAN_API="http://127.0.0.1:$PORT" "$BOT_PY" -u -m bot --uploads "$PROTO/evidence/uploads" --log "$LOGS/tg-bot.log"
