# Satyapan (सत्यापन)

**Verify the instruction, not the pixels.**

When a bank pauses a large, unusual transfer, Satyapan helps the officer check the "official" voice note, video or
notice behind it against issuer rules and the bank's own records, together with a calibrated deepfake check on the
media, so the customer hears three reasons she can check herself before the money leaves.

Amazon AI Cyber Security Hackathon (RAKSHAM, IIT Delhi), finale 24–25 Oct 2026.
Track 3: Deepfake Detection for Financial Communications. Team "Team": Aman Bihari, Bhawna.

## Run it

```bash
# The detectors and the forensics service
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt --extra-index-url https://download.pytorch.org/whl/cpu
.venv/bin/pip install imageio-ffmpeg faster-whisper pyarrow soundfile
scripts/fetch_models.sh                       # YuNet, GenD (about 3 GB) and DF Arena 500M (about 1.7 GB), once; then everything runs offline
.venv/bin/python -m pytest -q                 # fast tests use stubs, no model needed

# The engine and officer console (prototype/), in their own environment
python3 -m venv prototype/.venv
prototype/.venv/bin/pip install -e "prototype[dev,stt,ocr]"   # OCR also needs tesseract with Hindi data (Ubuntu: sudo apt install tesseract-ocr tesseract-ocr-hin)
SATYAPAN_WHISPER_MODEL=large-v3-turbo prototype/.venv/bin/satyapan setup-models   # speech-to-text and OCR language data, once; steps for extras you did not install say FAIL
(cd prototype/console && npm install && npm run build)        # the console the engine serves
(cd prototype && .venv/bin/python -m pytest -q)               # engine tests

.venv/bin/python scripts/score_video.py clip.mp4          # what the officer would see for one video
scripts/demo_up.sh                                        # forensics service + engine + console, offline
scripts/stop_demo.sh                                      # stop both
```

`scripts/demo_up.sh` runs the engine from `$SATYAPAN_ENGINE_VENV` if it is set, else from the `.venv` of a sibling
`../satyapan` checkout if there is one (the team laptop), else from `prototype/.venv`. By default it turns the live
website look-up off (`SATYAPAN_LIVE_WEB=0`), so the demo uses recorded registry answers and nothing leaves the laptop;
start it with `SATYAPAN_LIVE_WEB=1` to ask rdap.org live. More on the engine's optional models: `prototype/README.md`.

How it fits together, and where the deepfake check sits in a case: `docs/architecture.md`. The plan for the two
days: `docs/plan.md`.

## What is in this repository

| Path | What it is |
|---|---|
| `MODELS.md` | Declaration of every pre-trained model and third-party API, with checkpoint state and licence |
| `forensics/` | The detectors (built at the finale): shared contract, GenD face check, DF Arena 500M voice check, joined entry point, local service |
| `scripts/` | Model fetch, scoring, calibration, dataset download, WhatsApp-like re-encoding, demo start-up |
| `calibration/` | Thresholds, calibration reports and dataset attribution (numbers only, never clips) |
| `tests/` | Fast tests with stub models; slow real-model tests behind `RUN_SLOW=1` |
| `datasets/` | The synthetic datasets and the rulebook as declared at check-in, described below |
| `prototype/` | The demo engine and officer console (Python + React), with the combined score: Bhawna's copy merged with Aman's integration on 24 Oct. This is what the demo runs; its data is in `prototype/data/` |
| `LICENSE` | GPL-3.0 |

## Datasets

Only synthetic, public and consented data. No real bank, customer or platform data appears anywhere.

### Data in this repository

All synthetic, except the recorded registry answers in `prototype/data/mocks/web_registry.json`, which are real
public records.

| Dataset | Format | Provenance / consent | Size |
|---|---|---|---|
| `datasets/fixtures/scenarios.json` | Text, JSON | Synthetic demo scenarios written with AI (Claude). All names, phone numbers, account numbers, IFSC codes, summons and case numbers are invented. No real person, bank or official appears. | 17 scenarios |
| `datasets/fixtures/variants.json` | Text, JSON | Synthetic robustness corpus written with AI: Hinglish misspellings, Devanagari rewrites, WhatsApp-style mangling of the scenario texts, plus benign controls. Invented data only. | 73 texts |
| `datasets/mocks/` | Tabular JSON, Markdown | Synthetic stand-ins for bank systems (ledger, beneficiary name look-up, outbound message log, registered RM phones, suspect registry, ED summons look-up, campaign memory, bank policy). Each is labelled as a mock of the production system it represents. | 8 files, about 15 records |
| `datasets/rules/rulebook.yaml` | YAML | Issuer and regulator rules drafted with AI. Each rule cites a public primary source (RBI, ED, MHA and others) with a URL and a `verified` flag; an unverified rule is demoted to a soft signal. | 23 rules |
| `prototype/data/fixtures/` | Text, JSON | The scenarios and variant corpus the demo engine runs: the sets above plus the finale additions (house-tax and e-challan copies and their controls). Written with AI; invented data only. | 22 scenarios, 73 variants |
| `prototype/data/mocks/` | Tabular JSON, Markdown | The engine's synthetic stand-ins for bank systems, as in `datasets/mocks/`, each labelled as a mock | 8 files |
| `prototype/data/mocks/web_registry.json` | JSON | Real public answers from the domain registries, read over RDAP (rdap.org) on 23 Oct 2026 for the website check: registration date, holder, registrar and status, or "not found". Not invented; used by the tests, the preflight and the offline demo. | 16 domains |
| `prototype/data/rules/rulebook.yaml` | YAML | The rulebook the demo engine loads (version 1.7), drafted with AI; every rule cites a public primary source with a `verified` flag | 30 rules |
| `prototype/data/eval/` | Text, JSON | Labelled evaluation set: synthetic messages written for this repo, each labelled scam or genuine (`labelled.json`), reworded copies for the meaning-memory calibration (`memory_pairs.json`), and the latest run (`results.json`, report in `docs/evaluation.md`). Not field data. | 64 messages and 14 copies; 156 messages evaluated |
| `prototype/data/forensics/aasist_calibration.json` | JSON | AASIST-L thresholds measured on genuine FLEURS speech (numbers only, no audio) | 6 cells |

Each JSON fixture carries a `_note` field restating that its contents are invented; `web_registry.json` carries one
saying its answers are real public records.

### Public datasets used to calibrate the detectors

These sets are used only to set the detectors' thresholds and to measure how often they are right. Nothing is trained
or fine-tuned on them. They are downloaded to a local `clips/` folder that is never committed. Only the resulting
calibration numbers, and a list of which files were used, go into `calibration/`. One exception in the demo: the
live face check (run-sheet beat 4) shows one UniDataPro face-swap clip, unmodified. No other calibration clip is shown.

| Dataset | Used for | Format | Licence / access | How much we use |
|---|---|---|---|---|
| `mueller91/In-The-Wild` (Hugging Face) | Real and fake speech of public figures that actually circulated online, the main test of the voice detector | Audio (English) | CC-BY-SA-4.0 on Hugging Face (the project page says Apache-2.0) | 150 real + 150 fake, spread over speakers; only these clips are downloaded (range requests) |
| OpenSLR 118, Gram Vaani | Real, spontaneous Hindi phone calls: how often real callers are wrongly flagged | Audio (8 kHz phone) | Free for academic use | 600 calls sampled for calibration (474 usable); 200 other calls held out for the smoke test |
| `google/fleurs`, `hi_in` dev and test | Real, read Hindi speech (clean, then sent through simulated WhatsApp, AAC video-sound and phone channels) | Audio | CC-BY-4.0 | dev: 120 clips for calibration; test: 150 clips held out for the smoke test; the older AASIST-L calibration in `prototype/data/forensics/` used 150 clips per language from the `hi_in` and `en_us` dev sets |
| `vdivyasharma/IndicSynth` (Hugging Face) | Lab-made Hindi voice clones and TTS (freevc24, xtts_v2, vits), reported separately from real circulated fakes | Audio | CC-BY-NC-4.0 (non-commercial; this is a non-commercial hackathon prototype) | 60 clips, spread over the dataset |
| Wikimedia Commons: interviews, talks and vlogs (incl. Indian speakers) | Genuine face video for setting the video thresholds | Video | Each file's own open licence (CC BY, CC BY-SA, CC0 or public domain), uploaded before 2021; title, author, licence and link for every clip in `calibration/sources_commons.csv` | about 60 clips, first 60 s of each |
| `UniDataPro/deepfake-videos-dataset` (Hugging Face, vendor sample) | 5 genuine clips and their face-swapped versions: a first check that face swaps score higher | Video | CC-BY-NC-ND-4.0 (non-commercial, no derivatives distributed) | 10 clips |
| `nuriachandra/Deepfake-Eval-2024` (Hugging Face) | Deepfakes circulated in 2024 (video detector catch rate) | Video | CC-BY-SA-4.0; access requested, awaiting the authors' manual approval; used only if approved | a sample, if approved |

`scripts/fetch_audio_clips.py` downloads the audio sets above into `clips/` and writes `clips/audio_manifest.csv`;
`scripts/calibrate_audio.py` sets the voice thresholds and writes `calibration/audio_report.md`. DF Arena did not train
on any of these sets. No public recording of a real Indian voice-clone fraud call exists, so that case is tested only
with real circulated fakes sent through simulated phone and WhatsApp channels, and labelled as simulated.

**WhatsApp cell.** To match what a bank officer actually receives: for video, we make WhatsApp-like copies (H.264, short side
480 px, low bitrate; `scripts/whatsappify.py`, an approximation) of the calibration clips; for voice, clean clips are
also scored after simulated WhatsApp Opus and 8 kHz phone channels (`scripts/calibrate_audio.py`). We also forward a few real
and fake clips through WhatsApp between our own phones as a check. All copies stay in `clips/`.

**Our own recordings.** Planned, not yet made: a few genuine clips of the two of us (voice notes and phone video, both
consenting) to check that the detectors don't flag real footage. Consent will be recorded in `docs/consent.md` before
any such clip is used. We make no deepfakes of ourselves or anyone else.

## Responsible use

- Synthetic, clearly labelled data only. No real official's name or likeness.
- No automatic blocking: Satyapan advises and the bank officer decides. Releasing a held transfer needs a second person.
- No scores shown to the customer: she gets plain reasons she can check herself.
- A detector counts only through its calibrated band (never a raw score), as half of a combined score with the
  instruction checks: 40% or more is RED, 15% or more AMBER (`fusion.py` in `prototype/satyapan`, `docs/changes-2026-10-24.md`).
  With nothing else found, a high-confidence voice flag reaches 50%, RED only when the message asks for money (only
  cells with a 1% line can give "high"; among the voice cells by channel, only 8 kHz Hindi phone audio has one); a
  face flag is at most "moderate" (35% alone, AMBER). "Unsure" counts as no media. The officer decides, and releasing a held transfer needs a second person.
