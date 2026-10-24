# Status: Day 1 (24 Oct), video track and integration

For Aman and Bhawna. What works, what was measured, how to run it, and what is left.

## What works now

- **Face check (video)**: GenD CLIP-L/14 on faces found and aligned with YuNet, mirroring GenD's own preprocessing.
  Abstains with a plain reason when it cannot judge (no face, small face, too few frames, frames disagree, grey band,
  no calibration). Calibrated for HD and WhatsApp-size video (`calibration/`).
- **Speech-to-text**: Whisper large-v3-turbo, local, greedy decoding (declared in `MODELS.md`).
- **Wired into the demo engine and console** (the prototype in `../satyapan`):
  - every uploaded video gets a face result and a voice result, as F3 "media forensics" signals;
  - new rule `R-VIDEO-SYNTH`, "Signs of face manipulation": alone it gives at most AMBER, and it can be the second,
    independent check behind a cited rule (RED);
  - forensics start at upload, alongside speech-to-text, so Run is quick;
  - uploads no longer freeze the server while Whisper works;
  - preflight has a `server forensics` line;
  - the GREY and coverage wording names quiet media checks by what they did, never as findings.
- **Tests**: finale repo 60 pass; prototype 868+ pass; console browser e2e passes against the live server.
- **Live end to end** (real API, real models, this laptop):
  - the face-swap sample with an ED "digital arrest" message gives RED on the two independent checks, with
    "Signs of face manipulation (moderate)", score 0.955;
  - a genuine HD video gives GREY, with the face check finding no signs (0.116) and Whisper's transcript recorded;
  - upload to verdict takes about 40-60 s for the first check of a clip; the same bytes again are reused at once
    (cached by content hash in the running engine).

## What was measured (quote only with the sample sizes)

| What | Result | Source |
|---|---|---|
| Face check, HD | AUC 0.97; 5% false-alarm threshold 0.92; 38 genuine, 2 fake clips | `calibration/video_report.md` |
| Face check, WhatsApp-size | AUC 0.87; 5% threshold 0.97, which no fake cleared; 26 genuine, 6 fake | same |
| Declined to judge | 66 of 138 clips (frames disagree, small face, few faces) | same |
| Whisper turbo, Hindi | about 33% word errors; about 2x real time on CPU | `calibration/whisper_eval_fast.md` |
| Whisper small, Hindi | about 60% word errors at similar speed (not used) | same |

Plain reading: on HD video the face check is useful corroboration. On compressed WhatsApp forwards it rarely flags
and often says "unsure". That is why it never decides a case.

## How to run the demo

```bash
cd satyapan-finale && scripts/demo_up.sh        # about a minute; then open http://localhost:8000
cd ../satyapan && .venv/bin/satyapan preflight --server http://127.0.0.1:8000   # 7 lines, all PASS
```

Run-sheet beat 4 is now a live face check: `../docs/finale-runsheet.md`.

## Left to do

- **Bhawna, audio**:
  - `scripts/prepare_audio_clips.py --download --n 60` builds the labelled Hindi set;
  - expose `default_detector()` from `forensics/audio.py`; the service, the joined entry point and preflight pick
    it up automatically;
  - calibrate the same way as video (`forensics/common.py` has the band rule and `threshold_at_fpr`);
  - until then the voice check says "the audio detector is not installed yet".
- **Paper disclosure form, Section 2A** (models). Add: GenD CLIP-L/14 (MIT), YuNet (MIT), Whisper via faster-whisper
  (MIT), DF Arena 500M (non-commercial). AASIST-L and the DFDC model are no longer used.
- **Paper disclosure form, Section 2B** (datasets):
  - add Wikimedia Commons videos (per-file open licences, `calibration/sources_commons.csv`);
  - add the UniDataPro deepfake sample (CC-BY-NC-ND), Google FLEURS Hindi (CC-BY-4.0) and IndicSynth Hindi
    (CC-BY-NC-4.0);
  - add Deepfake-Eval-2024 only if access is approved (requested; pending);
  - Kathbath and DFDC were not used: Kathbath is gated, and DFDC's competition has closed.
- **OCR on this laptop**: Tesseract is not installed here (it needs sudo). Before the demo:
  `sudo apt install tesseract-ocr tesseract-ocr-hin` and `../satyapan/.venv/bin/pip install pytesseract pymupdf`,
  then `../satyapan/.venv/bin/python -m pytest -q ../satyapan/tests/test_ocr.py`. Without it, an uploaded image notice
  asks the officer for its text; the scripted scenarios are unaffected.
- **Run-sheet beat 4**: build the face-swap case before the slot, after the final reset (see `../docs/finale-runsheet.md`).
- **Optional, if time**:
  - more face-swap clips (Deepfake-Eval-2024) to turn the catch rates into measurements;
  - record your own genuine selfie clip (consented) as a live "genuine" demo moment.
