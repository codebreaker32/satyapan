#!/usr/bin/env bash
# Start the whole demo on this laptop, offline:
#   1. the forensics service from this repo (GenD face check + audio check), models loaded once and kept warm;
#   2. the engine and officer console (prototype/), connected to it, with Whisper speech-to-text.
# Then open http://localhost:8000.   Stop everything: scripts/stop_demo.sh
set -euo pipefail
cd "$(dirname "$0")/.."
FIN=$(pwd)
# The engine and console: prototype/ in this repo (merged 24 Oct), else the older sibling checkout ../satyapan.
if [ -d prototype/satyapan ]; then PROTO="$FIN/prototype"; else PROTO=$(cd ../satyapan && pwd); fi
# Its Python environment (pip install -e prototype into it): SATYAPAN_ENGINE_VENV, else the sibling checkout's
# ../satyapan/.venv (this laptop), else prototype/.venv. No command substitution that can fail here: under set -e a
# failing `cd` inside one ended the script silently on any machine without the sibling checkout.
if [ -n "${SATYAPAN_ENGINE_VENV:-}" ]; then ENGINE_VENV="$SATYAPAN_ENGINE_VENV"
elif [ -x "$FIN/../satyapan/.venv/bin/satyapan" ]; then ENGINE_VENV="$FIN/../satyapan/.venv"
else ENGINE_VENV="$PROTO/.venv"; fi
if [ ! -x "$ENGINE_VENV/bin/satyapan" ]; then
  echo "no engine environment at $ENGINE_VENV. Make one:"
  echo "  python3 -m venv prototype/.venv && prototype/.venv/bin/pip install -e 'prototype[dev,stt,ocr]'"
  exit 1
fi
PORT=${FORENSICS_PORT:-8765}
LOGS="$FIN/clips/logs"
mkdir -p "$LOGS"

if ! curl -fs "http://127.0.0.1:$PORT/health" >/dev/null 2>&1; then
  echo "starting the forensics service (first start loads about 3 GB of model, ~10-60 s)..."
  nohup .venv/bin/python -u -m forensics.service --port "$PORT" >"$LOGS/forensics.log" 2>&1 &   # -u: the log shows a failed model load at once
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
# The website registration look-up uses its recorded answers, so no check leaves the laptop and a slow venue network
# cannot stall a verdict. SATYAPAN_LIVE_WEB=1 scripts/demo_up.sh asks the public RDAP registry (rdap.org) live instead.
export SATYAPAN_LIVE_WEB="${SATYAPAN_LIVE_WEB:-0}"
# The offline helper reader (prototype/satyapan/llm_reader.py, Llama 3.2 3B through Ollama) stays OFF for the demo:
# on this laptop's CPU each read takes about half a minute, which would hold up Run on any message the rules read
# only in part (docs/changes-2026-10-24.md, section 4). To try it: ollama pull llama3.2:3b, then
# SATYAPAN_LLM_READER=llama3.2:3b scripts/demo_up.sh
export SATYAPAN_LLM_READER="${SATYAPAN_LLM_READER:-}"
echo "engine: forensics at $SATYAPAN_FORENSICS_URL, speech-to-text: Whisper $SATYAPAN_WHISPER_MODEL, live website look-up: $([ "$SATYAPAN_LIVE_WEB" = 1 ] && echo on || echo off)"
exec "$ENGINE_VENV/bin/satyapan" serve
