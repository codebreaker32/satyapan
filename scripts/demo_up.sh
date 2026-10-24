#!/usr/bin/env bash
# Start the whole demo on this laptop, offline:
#   1. the forensics service from this repo (GenD face check + audio check), models loaded once and kept warm;
#   2. the engine and officer console (../satyapan), connected to it, with Whisper speech-to-text.
# Then open http://localhost:8000.   Stop everything: scripts/stop_demo.sh
set -euo pipefail
cd "$(dirname "$0")/.."
FIN=$(pwd)
PROTO=$(cd ../satyapan && pwd)
PORT=${FORENSICS_PORT:-8765}
LOGS="$FIN/clips/logs"
mkdir -p "$LOGS"

if ! curl -fs "http://127.0.0.1:$PORT/health" >/dev/null 2>&1; then
  echo "starting the forensics service (first start loads about 3 GB of model, ~10-60 s)..."
  nohup .venv/bin/python -m forensics.service --port "$PORT" >"$LOGS/forensics.log" 2>&1 &
  for _ in $(seq 1 180); do
    curl -fs "http://127.0.0.1:$PORT/health" >/dev/null 2>&1 && break
    sleep 1
  done
fi
if ! curl -fs "http://127.0.0.1:$PORT/health"; then
  echo; echo "the forensics service did not start; see $LOGS/forensics.log"; exit 1
fi
echo

cd "$PROTO"
export SATYAPAN_FORENSICS_URL="http://127.0.0.1:$PORT"
# Whisper large-v3-turbo with greedy decoding: on this laptop about 2x real time and about half the word errors of
# "small" on Hindi, 33% vs 62% (calibration/whisper_eval_fast.md).
export SATYAPAN_WHISPER_MODEL="${SATYAPAN_WHISPER_MODEL:-large-v3-turbo}"
export SATYAPAN_WHISPER_BEAM="${SATYAPAN_WHISPER_BEAM:-1}"
export SATYAPAN_WHISPER_PRELOAD=1   # load speech-to-text at start-up, not on the first voice note
echo "engine: forensics at $SATYAPAN_FORENSICS_URL, speech-to-text: Whisper $SATYAPAN_WHISPER_MODEL"
exec .venv/bin/satyapan serve
