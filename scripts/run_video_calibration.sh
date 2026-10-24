#!/usr/bin/env bash
# Build the video calibration set and calibrate. Clips stay in clips/ (never committed); only calibration/ is committed.
#   1. labelled manifests: Wikimedia Commons (real), UniDataPro sample (real + face-swapped pairs)
#   2. WhatsApp-like copies of every clip (scripts/whatsappify.py)
#   3. one combined manifest with absolute paths, then scripts/calibrate_video.py
set -euo pipefail
cd "$(dirname "$0")/.."
PY=.venv/bin/python

# UniDataPro pairs: video/N = genuine original, deepfake/N = the same clip face-swapped
if [ -d clips/unidata ]; then
  {
    echo "path,label,source"
    for f in clips/unidata/video/*; do echo "video/$(basename "$f"),real,unidatapro-sample"; done
    for f in clips/unidata/deepfake/*; do echo "deepfake/$(basename "$f"),fake,unidatapro-sample"; done
  } > clips/unidata/manifest.csv
fi

for m in clips/commons/manifest.csv clips/unidata/manifest.csv; do
  [ -f "$m" ] && $PY scripts/whatsappify.py "$m"
done

# Combined manifest (absolute paths).
$PY - <<'EOF'
import csv
from pathlib import Path
rows = []
for m in ["clips/commons/manifest.csv", "clips/commons_wa/manifest.csv", "clips/unidata/manifest.csv", "clips/unidata_wa/manifest.csv"]:
    p = Path(m)
    if not p.exists():
        continue
    for r in csv.DictReader(p.open()):
        rows.append({"path": str((p.parent / r["path"]).resolve()), "label": r["label"], "source": r["source"]})
out = Path("clips/video_manifest.csv")
with out.open("w", newline="") as f:
    w = csv.DictWriter(f, fieldnames=["path", "label", "source"])
    w.writeheader()
    w.writerows(rows)
print(f"{out}: {len(rows)} clips ({sum(r['label']=='real' for r in rows)} real, {sum(r['label']=='fake' for r in rows)} fake)")
EOF

$PY scripts/calibrate_video.py --manifest clips/video_manifest.csv
