# Satyapan (सत्यापन)

**Verify the instruction, not the pixels.**

When a bank pauses a large, unusual transfer, Satyapan helps the officer check the "official" voice note, video or
notice behind it against issuer rules and the bank's own records, with deepfake forensics as backup, so the customer
hears three reasons she can check herself before the money leaves.

Amazon AI Cyber Security Hackathon (RAKSHAM, IIT Delhi), finale 24–25 Oct 2026.
Track 3: Deepfake Detection for Financial Communications. Team "Team": Aman Bihari, Bhawna.

## Run it

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt --extra-index-url https://download.pytorch.org/whl/cpu
.venv/bin/pip install imageio-ffmpeg faster-whisper pyarrow soundfile
scripts/fetch_models.sh                       # YuNet + GenD (about 3 GB, once); then everything runs offline
.venv/bin/python -m pytest -q                 # fast tests use stubs, no model needed

.venv/bin/python scripts/score_video.py clip.mp4          # what the officer would see for one video
scripts/demo_up.sh                                        # forensics service + engine + console, offline
```

How it fits together, and where the deepfake check sits in a case: `docs/architecture.md`. The plan for the two
days: `docs/plan.md`.

## What is in this repository

| Path | What it is |
|---|---|
| `MODELS.md` | Declaration of every pre-trained model and third-party API, with checkpoint state and licence |
| `forensics/` | The detectors (built at the finale): shared contract, GenD video check, joined entry point, local service |
| `scripts/` | Model fetch, scoring, calibration, dataset download, WhatsApp-like re-encoding, demo start-up |
| `calibration/` | Thresholds, calibration reports and dataset attribution (numbers only, never clips) |
| `tests/` | Fast tests with stub models; slow real-model tests behind `RUN_SLOW=1` |
| `datasets/` | The synthetic datasets and the rulebook, described below |
| `LICENSE` | GPL-3.0 |

## Datasets

Only synthetic, public and consented data. No real bank, customer or platform data appears anywhere.

### Synthetic data in this repository

| Dataset | Format | Provenance / consent | Size |
|---|---|---|---|
| `datasets/fixtures/scenarios.json` | Text, JSON | Synthetic demo scenarios written with AI (Claude). All names, phone numbers, account numbers, IFSC codes, summons and case numbers are invented. No real person, bank or official appears. | 17 scenarios |
| `datasets/fixtures/variants.json` | Text, JSON | Synthetic robustness corpus written with AI: Hinglish misspellings, Devanagari rewrites, WhatsApp-style mangling of the scenario texts, plus benign controls. Invented data only. | 73 texts |
| `datasets/mocks/` | Tabular JSON, Markdown | Synthetic stand-ins for bank systems (ledger, beneficiary name look-up, outbound message log, registered RM phones, suspect registry, ED summons look-up, campaign memory, bank policy). Each is labelled as a mock of the production system it represents. | 8 files, about 15 records |
| `datasets/rules/rulebook.yaml` | YAML | Issuer and regulator rules drafted with AI. Each rule cites a public primary source (RBI, ED, MHA and others) with a URL and a `verified` flag; an unverified rule is demoted to a soft signal. | 23 rules |

Each JSON fixture carries a `_note` field restating that its contents are invented.

### Public datasets used to calibrate the detectors

These sets are used only to set the detectors' thresholds and to measure how often they are right. Nothing is trained
or fine-tuned on them. They are downloaded to a local `clips/` folder that is never committed. Only the resulting
calibration numbers, and a list of which files were used, go into `calibration/`. None of these clips appear in the
demo.

| Dataset | Used for | Format | Licence / access | How much we use |
|---|---|---|---|---|
| `google/fleurs`, Hindi (Hugging Face) | Real Hindi speech (audio detector; also to measure Whisper's Hindi accuracy). Kathbath was planned but is gated, so it is not used | Audio | CC-BY-4.0, open | 239 clips available; about 60 used |
| `vdivyasharma/IndicSynth` (Hugging Face) | Synthetic Hindi speech (audio detector) | Audio | CC-BY-NC-4.0 (non-commercial; this is a non-commercial hackathon prototype) | about 30 Hindi clips |
| `mueller91/In-The-Wild` (Hugging Face) | Real and fake speech recorded in the wild, as a cross-check (audio detector) | Audio | CC-BY-SA-4.0 | a sample of about 50 clips |
| Wikimedia Commons: interviews, talks and vlogs (incl. Indian speakers) | Genuine face video for setting the video thresholds | Video | Each file's own open licence (CC BY, CC BY-SA, CC0 or public domain), uploaded before 2021; title, author, licence and link for every clip in `calibration/sources_commons.csv` | about 60 clips, first 60 s of each |
| `UniDataPro/deepfake-videos-dataset` (Hugging Face, vendor sample) | 5 genuine clips and their face-swapped versions: a first check that face swaps score higher | Video | CC-BY-NC-ND-4.0 (non-commercial, no derivatives distributed) | 10 clips |
| `nuriachandra/Deepfake-Eval-2024` (Hugging Face) | Deepfakes circulated in 2024 (video detector catch rate) | Video | CC-BY-SA-4.0; access requested, awaiting the authors' manual approval; used only if approved | a sample, if approved |

**WhatsApp cell.** To match what a bank officer actually receives, we make WhatsApp-like copies (H.264, short side
480 px, low bitrate; `scripts/whatsappify.py`, an approximation) of the calibration clips, and forward a few real clips
through WhatsApp between our own phones as a check. All copies stay in `clips/`.

**Our own recordings.** A few genuine clips of the two of us (voice notes and phone video, both consenting) check that
the detectors don't flag real footage. Consent is recorded in `docs/consent.md`. We make no deepfakes of ourselves or
anyone else.

## Responsible use

- Synthetic, clearly labelled data only. No real official's name or likeness.
- No automatic blocking: Satyapan advises and the bank officer decides. Releasing a held transfer needs a second person.
- No scores shown to the customer: she gets plain reasons she can check herself.
- Forensic signals only corroborate. A RED needs two independent checks, never one weak signal.
