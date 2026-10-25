"""Satyapan forensics: deepfake detectors that abstain ("unsure") when the evidence is not clear."""
import os

# Load models only from the local cache once they are downloaded (scripts/fetch_models.sh runs with
# HF_HUB_OFFLINE=0 to download them). Without this, every model load contacts the Hugging Face Hub: offline it can
# stall, and behind a captive portal it fails even with a full local cache. Must be set before transformers or
# huggingface_hub is imported, which is why it lives here, at the package entry point.
os.environ.setdefault("HF_HUB_OFFLINE", "1")
