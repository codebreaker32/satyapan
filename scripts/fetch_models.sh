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
# DF Arena 500M voice-clone detector (non-commercial licence; Bhawna's forensics/audio.py) at its pinned revision
# (about 1.7 GB), plus the config of its wav2vec2 backbone, which DF Arena's code fetches by name. The detector loads
# both with local_files_only=True, so they are downloaded here explicitly. Hugging Face's Xet transfer failed on the
# finale laptop with an I/O error; plain HTTP downloads work.
HF_HUB_OFFLINE=0 HF_HUB_DISABLE_XET=1 .venv/bin/python - <<'PY'
from huggingface_hub import snapshot_download     # forensics/__init__.py only sets HF_HUB_OFFLINE when unset
from transformers import Wav2Vec2Config
from forensics.audio import DF_ARENA
repo, rev, _, backbone = DF_ARENA["500M"]
snapshot_download(repo, revision=rev)
Wav2Vec2Config.from_pretrained(backbone)
print(f"DF Arena files cached: {repo}@{rev[:7]} and {backbone} config")
PY
# Check: load DF Arena offline, the way the forensics service does
HF_HUB_OFFLINE=1 .venv/bin/python -c "from forensics.audio import default_detector; default_detector().scorer; print('DF Arena ready')"
