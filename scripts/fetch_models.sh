#!/usr/bin/env bash
# Download the model files this repo uses (never committed; see MODELS.md).
set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p models
# YuNet face detector (opencv/opencv_zoo, MIT)
YUNET=models/face_detection_yunet_2023mar.onnx
[ -f "$YUNET" ] || curl -fsSL -o "$YUNET" https://github.com/opencv/opencv_zoo/raw/main/models/face_detection_yunet/face_detection_yunet_2023mar.onnx
echo "8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4  $YUNET" | sha256sum -c -
# GenD CLIP-L/14 (MIT) at the pinned revision, plus its CLIP backbone (about 3 GB, cached by Hugging Face)
HF_HUB_OFFLINE=0 .venv/bin/python -c "from forensics.video import GenDScorer; GenDScorer(); print('GenD ready')"
# DF Arena 500M voice-clone detector (non-commercial licence; Bhawna's forensics/audio.py), at its pinned revision
HF_HUB_OFFLINE=0 .venv/bin/python -c "from forensics.audio import default_detector; d = default_detector(); d.scorer; print('DF Arena ready')"
