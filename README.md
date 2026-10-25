# Satyapan (सत्यापन)

**Verify the instruction, not the pixels.**

When a bank pauses a large, unusual transfer, Satyapan helps the officer check the "official" voice note, video or
notice behind it against issuer rules and the bank's own records, together with a calibrated deepfake check on the
media, so the customer hears three reasons she can check herself before the money leaves.

Amazon AI Cyber Security Hackathon (RAKSHAM, IIT Delhi), finale 24–25 Oct 2026.
Track 3: Deepfake Detection for Financial Communications. Team "Team": Aman Bihari, Bhawna.

| Read this | For |
|---|---|
| [Run the demo](#run-the-demo) | the commands the finale run-sheet uses |
| [Evidence](#evidence-what-we-measured) | measured accuracy, the labelled evaluation, calibration reports, what changed overnight |
| [`synthetic/`](synthetic/README.md) | the code that made every synthetic file we used, and the validator for the hand-written data |
| [`MODELS.md`](MODELS.md) | every pre-trained model and third-party API, with checkpoint, licence and why it was chosen |
| [`docs/jury-defence.md`](docs/jury-defence.md) | the team's pitch, demo story and answers to the hardest questions, each with its source |
| [`docs/architecture.md`](docs/architecture.md) | how it fits together, and where the deepfake check sits in a case |

## Run the demo

One laptop runs everything, offline. From the repo root, once the two environments below are installed:

```bash
scripts/demo_up.sh                                          # forensics service (face + voice models) on :8765, then the engine and console on :8000; about a minute
prototype/.venv/bin/satyapan preflight --server http://127.0.0.1:8000   # every line PASS, exit 0, including "server forensics"
# open http://localhost:8000, press "Reset the demo" on the Scenarios page, then:
.venv/bin/python scripts/build_demo_cases.py                # builds the live cloned-voice and face-swap cases (about 1-2 minutes); both lines must say OK
scripts/stop_demo.sh                                        # stop both
```

- `scripts/demo_up.sh` runs the engine from `$SATYAPAN_ENGINE_VENV` if it is set, else from the `.venv` of a sibling
  `../satyapan` checkout if there is one (the team laptop), else from `prototype/.venv`. It loads Whisper
  large-v3-turbo at start-up, keeps the offline LLM reader OFF, and turns the live website look-up off
  (`SATYAPAN_LIVE_WEB=0`), so the demo uses recorded registry answers and nothing leaves the laptop. Start it with
  `SATYAPAN_LIVE_WEB=1` to ask rdap.org live.
- `scripts/build_demo_cases.py` needs the face swap at `clips/demo/officer_faceswap.mp4` and the voice clone at
  `clips/audio/fake_opus/fake_000.ogg` (both public research clips; see `synthetic/README.md`). Run it after every
  reset, because a reset clears all cases.
- If the console dies: `prototype/.venv/bin/satyapan demo --lang hi` plays the same scenarios in the terminal, with
  the customer cards as text.
- One video, scored the way the officer would see it: `.venv/bin/python scripts/score_video.py clip.mp4`.

### Install

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
(cd prototype && SATYAPAN_LIVE_WEB=0 .venv/bin/python -m pytest -q)   # engine tests, offline
(cd prototype/console && npm run e2e)                         # console browser checks, against `satyapan serve --port 8010`
```

More on the engine's optional models: `prototype/README.md`.

## Evidence: what we measured

| File | What it shows |
|---|---|
| `docs/accuracy.md` | the face and voice checks per kind of input: catch rate, held-out false alarms and sample sizes, plus named failure cases (made by `scripts/accuracy_card.py` from `calibration/`) |
| `docs/evaluation.md` | the whole decision engine on a labelled synthetic set (156 messages; `prototype/data/eval/`), made by `satyapan evaluate` |
| `calibration/audio_report.md`, `calibration/video_report.md` | how the thresholds were set, per calibration cell, with AUC and catch rate at each threshold |
| `calibration/whisper_eval.md`, `calibration/whisper_eval_fast.md` | speech-to-text word error rates on Hindi clips |
| `scripts/pipeline_check.py` | the live end-to-end check against a running demo (a smoke test, not an accuracy measurement) |
| `docs/overnight-report.md` | what changed on the night before the finale, the checks it passed and what was not done |
| `docs/changes-2026-10-24.md` | the 24 Oct merge: the combined score and why the offline LLM reader ships OFF |

## What is in this repository

| Path | What it is |
|---|---|
| `MODELS.md` | Declaration of every pre-trained model and third-party API, with checkpoint state and licence |
| `forensics/` | The detectors (built at the finale): shared contract, GenD face check, DF Arena 500M voice check, joined entry point, local service |
| `prototype/` | The demo engine and officer console (Python + React), with the combined score: Bhawna's copy merged with Aman's integration on 24 Oct. This is what the demo runs; its data is in `prototype/data/` |
| `synthetic/` | The generators for every synthetic file we used, and `validate_fixtures.py` for the hand-written text data |
| `scripts/` | Model fetch, scoring, calibration, dataset download, WhatsApp-like re-encoding, demo start-up and checks |
| `calibration/` | Thresholds, calibration reports and dataset attribution (numbers only, never clips) |
| `docs/` | Architecture, accuracy, evaluation, deployment path, the jury defence and the finale reports |
| `tests/` | Detector and generator tests with stub models; slow real-model tests behind `RUN_SLOW=1` |
| `datasets/` | The synthetic datasets and the rulebook as declared at check-in, described below |
| `LICENSE` | GPL-3.0 |

## Datasets

Only synthetic, public and consented data. No real bank, customer or platform data appears anywhere. How every
synthetic file was made, and the rules the hand-written data follows: `synthetic/README.md`.

### Data in this repository

All synthetic, except the recorded registry answers in `prototype/data/mocks/web_registry.json`, which are real
public records, and one team member's own UPI test ID in the name look-up mock, added at her request.

| Dataset | Format | Provenance / consent | Size |
|---|---|---|---|
| `datasets/fixtures/scenarios.json` | Text, JSON | Synthetic demo scenarios written with AI (Claude). All names, phone numbers, account numbers, summons and case numbers are invented; some IFSC codes use real bank prefixes with branch codes we did not check (`synthetic/README.md` lists them). No real person or official appears. | 17 scenarios |
| `datasets/fixtures/variants.json` | Text, JSON | Synthetic robustness corpus written with AI: Hinglish misspellings, Devanagari rewrites, WhatsApp-style mangling of the scenario texts, plus benign controls. Invented data only. | 73 texts |
| `datasets/mocks/` | Tabular JSON, Markdown | Synthetic stand-ins for bank systems (ledger, beneficiary name look-up, outbound message log, registered RM phones, suspect registry, ED summons look-up, campaign memory, bank policy). Each is labelled as a mock of the production system it represents. | 8 files, about 15 records |
| `datasets/rules/rulebook.yaml` | YAML | Issuer and regulator rules drafted with AI. Each rule cites a public primary source (RBI, ED, MHA and others) with a URL and a `verified` flag; an unverified rule is demoted to a soft signal. | 23 rules |
| `prototype/data/fixtures/` | Text, JSON | The scenarios and variant corpus the demo engine runs: the sets above plus the finale additions (house-tax and e-challan copies and their controls). Written with AI. | 22 scenarios, 73 variants |
| `prototype/data/mocks/` | Tabular JSON, Markdown | The engine's synthetic stand-ins for bank systems, as in `datasets/mocks/`, each labelled as a mock | 8 files, plus `web_registry.json` below |
| `prototype/data/mocks/web_registry.json` | JSON | Real public answers from the domain registries, read over RDAP (rdap.org) on 23 Oct 2026 for the website check: registration date, holder, registrar and status, or "not found". Not invented; used by the tests, the preflight and the offline demo. | 16 domains |
| `prototype/data/rules/rulebook.yaml` | YAML | The rulebook the demo engine loads (version 1.7), drafted with AI; every rule cites a public primary source and is marked `verified` | 31 rules |
| `prototype/data/eval/` | Text, JSON | Labelled evaluation set: synthetic messages written for this repo, each labelled scam or genuine (`labelled.json`), reworded copies for the meaning-memory calibration (`memory_pairs.json`), and the latest run (`results.json`, report in `docs/evaluation.md`). Not field data. | 64 messages and 14 copies; 156 messages evaluated |
| `prototype/data/forensics/aasist_calibration.json` | JSON | AASIST-L thresholds measured on genuine FLEURS speech (numbers only, no audio) | 6 cells |

Each JSON fixture carries a `_note` field restating that its contents are invented; `web_registry.json` carries one
saying its answers are real public records. `python synthetic/validate_fixtures.py` checks that every fixture parses
and reports any IFSC, account number, UPI ID or phone number that does not follow the synthetic-data rules.

### Public datasets used to calibrate the detectors

These sets are used only to set the detectors' thresholds and to measure how often they are right. Nothing is trained
or fine-tuned on them. They are downloaded to a local `clips/` folder that is never committed. Only the resulting
calibration numbers, and a list of which files were used, go into `calibration/`. Two exceptions in the demo: the
live face check (run-sheet beat 4) shows one UniDataPro face-swap clip, unmodified, and the live voice-clone case
(beat 2) uploads one IndicSynth clip as a WhatsApp-like voice note. No other calibration clip is shown.

| Dataset | Used for | Format | Licence / access | How much we use |
|---|---|---|---|---|
| `mueller91/In-The-Wild` (Hugging Face) | Real and fake speech of public figures collected from the internet, the main test of the voice detector | Audio (English) | CC-BY-SA-4.0 on Hugging Face (the project page says Apache-2.0) | 150 real + 150 fake, spread over speakers; only these clips are downloaded (range requests) |
| OpenSLR 118, Gram Vaani | Real, spontaneous Hindi phone calls: how often real callers are wrongly flagged | Audio (8 kHz phone) | Free for academic use | the dev and eval sets, sampled |
| `google/fleurs`, `hi_in` dev | Real, read Hindi speech (clean, then sent through simulated WhatsApp and phone channels) | Audio | CC-BY-4.0 | 120 clips; the older AASIST-L calibration in `prototype/data/forensics/` used 150 clips per language from the `hi_in` and `en_us` dev sets |
| `vdivyasharma/IndicSynth` (Hugging Face) | Lab-made Hindi voice clones and TTS, reported separately from real circulated fakes | Audio | CC-BY-NC-4.0 (non-commercial; this is a non-commercial hackathon prototype) | 60 clips, spread over the dataset |
| Wikimedia Commons: interviews, talks and vlogs (incl. Indian speakers) | Genuine face video for setting the video thresholds | Video | Each file's own open licence (CC BY, CC BY-SA, CC0 or public domain), uploaded before 2021; title, author, licence and link for every clip in `calibration/sources_commons.csv` | 59 clips listed, first 60 s of each |
| `UniDataPro/deepfake-videos-dataset` (Hugging Face, vendor sample) | 5 genuine clips and their face-swapped versions: a first check that face swaps score higher | Video | CC-BY-NC-ND-4.0 (non-commercial, no derivatives distributed) | 10 clips |
| `nuriachandra/Deepfake-Eval-2024` (Hugging Face) | Would have measured the video detector on deepfakes circulated in 2024 | Video | CC-BY-SA-4.0; access requested, still awaiting the authors' approval (`docs/status.md`) | not used |

`scripts/fetch_audio_clips.py` downloads the audio sets above into `clips/` and writes `clips/audio_manifest.csv`;
`scripts/calibrate_audio.py` sets the voice thresholds and writes `calibration/audio_report.md`. DF Arena did not train
on any of these sets. No public recording of a real Indian voice-clone fraud call exists, so that case is tested only
with lab-made and circulated fakes sent through simulated phone and WhatsApp channels, and labelled as simulated.

**WhatsApp cell.** To match what a bank officer actually receives: for video, we make WhatsApp-like copies (H.264, short
side 480 px, low bitrate; `scripts/whatsappify.py`, an approximation) of the calibration clips; for voice, Hindi clips
are also re-encoded as WhatsApp-like Opus voice notes (`scripts/prepare_audio_clips.py`) and clean clips are scored
after simulated Opus and 8 kHz phone channels (`scripts/calibrate_audio.py`). The exact settings are in
`synthetic/README.md`. Forwarding clips through WhatsApp between our own phones was planned as a check and not done,
so every WhatsApp figure comes from these simulated copies. All copies stay in `clips/`.

**Our own recordings.** Planned and not made: a few genuine clips of the two of us (voice notes and phone video, both
consenting) to check that the detectors don't flag real footage. `docs/consent.md` would record consent before any
such clip is used; it lists none. We make no deepfakes of ourselves or anyone else.

## Responsible use

- Synthetic, clearly labelled data only. No real official's name or likeness.
- No automatic blocking: Satyapan advises and the bank officer decides. Releasing a held transfer that was RED needs
  a second, different person to co-sign; an AMBER release needs one officer.
- No scores shown to the customer: she gets plain reasons she can check herself.
- A detector counts only through its calibrated band (never a raw score), as half of a combined score with the
  instruction checks: 40% or more is RED, 15% or more AMBER (`fusion.py` in `prototype/satyapan`, `docs/changes-2026-10-24.md`).
  With nothing else found, a high-confidence voice flag reaches 50%, RED only when the message asks for money (only
  cells with a 1% line can give "high"; among the voice cells by channel, only 8 kHz Hindi phone audio has one); a
  face flag is at most "moderate" (35% alone, AMBER). "Unsure" counts as no media. The officer decides.
