# Status: Day 1 (24 Oct), 22:50 IST

For Aman and Bhawna. What works, what was measured, how to run it, and what is left.

## What works now

- **One engine (merge done)**: Bhawna's engine and console, with the agreed 50/50 combined score, merged with Aman's
  integration in `prototype/` of this repo. On this laptop it runs from `../satyapan/.venv`, with `prototype/`
  installed into it in editable mode; the old `../satyapan` copy is no longer what runs.
- **Face check (video)**: GenD CLIP-L/14 on faces found and aligned with YuNet, mirroring GenD's own preprocessing.
  Abstains with a plain reason when it cannot judge (no face, small face, too few frames, frames disagree, grey band,
  no calibration). Calibrated for HD and WhatsApp-size video (`calibration/video.json`).
- **Voice check**: DF Arena 500M, installed on this laptop and loading offline. Calibrated per language and channel:
  Hindi and English, each for clean, WhatsApp-style (Opus) and 8 kHz phone audio (cells in `calibration/audio.json`).
  It checks voice notes and the sound track of videos, and abstains with a plain reason (under 2 s of speech, parts
  of the recording disagree, grey band, no calibration).
- **Speech-to-text**: Whisper large-v3-turbo, local, greedy decoding (declared in `MODELS.md`).
- **OCR**: tesseract 5.3.4 with Hindi and English data, pytesseract and PyMuPDF in the engine's environment.
  `prototype/tests/test_ocr.py` passes (not skipped). Live, a synthetic summons image is read in about 2 s and reaches
  RED. For an English notice, pick English as the document language.
- **In the engine and console**:
  - every uploaded video gets a face result and a voice result, and every voice note a voice result, as F3 signals
    (`R-VIDEO-SYNTH`, `R-AUDIO-SYNTH`);
  - judged media counts half in the combined score (`docs/changes-2026-10-24.md`); "unsure" counts as no media;
  - forensics start at upload, alongside speech-to-text, so Run is quick;
  - uploads no longer freeze the server while Whisper works;
  - preflight has a `server forensics` line;
  - the GREY and coverage wording names quiet media checks by what they did, never as findings;
  - in the demo the website look-up uses the recorded registry answers (`scripts/demo_up.sh` sets
    `SATYAPAN_LIVE_WEB=0`), so nothing leaves the laptop.
- **Ready for a judge's own files** (24 Oct evening, after the merged-system review):
  - formats: voice notes and audio (ogg, opus, mp3, wav, m4a, weba, aac, amr, flac), video (mp4, mov, webm, 3gp, mkv),
    images, PDF and text, up to 100 MB; each must open as what its name says;
  - a video in which nobody speaks, or with no sound track, is still face-checked (a silent copy of the demo face
    swap gives AMBER at 35% on the face check alone); a voice note with no speech is refused with a sentence;
  - a browser voice recording gets no face check; a video re-filmed at the counter (live-replay) gets "unsure" from
    the face check; a video's voice is judged in the cell of its original sound (Opus, 8 kHz, clean);
  - the Evaluation page shows the face and voice checks' measured accuracy: per kind of input, false alarms on genuine
    clips that did not set the threshold (2.9% to 4.5%), catches, unsure and declined, and ten named failure cases
    (`scripts/accuracy_card.py` writes `calibration/accuracy.json` and `docs/accuracy.md`);
  - the screens say what is true now: a media flag that moves the verdict is never called too weak, media reasons say
    "one of the checks, not proof on its own", a scripted rehearsal figure is tagged Simulated on the band, and the
    disclosure sentence is built from what is actually loaded;
  - `/health` says whether the voice model actually loaded, and preflight fails if it did not.
- **Tests** (22:40 IST): detectors 87 pass (3 skipped); engine 1023 pass (7 skipped); console browser e2e 190 pass;
  preflight 7/7 PASS with `--server`. The real-model slow tests pass too: GenD smoke and output index, DF Arena smoke.
- **Live end to end** (`scripts/pipeline_check.py`: real API, real models, this laptop): 12 of 12 pass.
  - A cloned Hindi voice note, read by Whisper: AMBER at 35% (voice synthetic, moderate, cell `hi/whatsapp-opus`).
  - The same cloned note with an ED scam text: RED at 80% (instruction 90%, deepfake 70%).
  - A real Hindi note with a harmless text: GREY (voice clean, 0.056).
  - The same real note marked English: judged in cell `en/whatsapp-opus`.
  - A 1 s clip: the voice check abstains.
  - A silent clip: refused with HTTP 415 and a plain sentence.
  - The HD face swap with the ED text: RED at 80% (face 0.955, moderate).
  - A genuine HD video: GREY (face clean, 0.116). Its sound track scored 0.9986 and abstained, inside the grey band
    of `hi/clean` (0.9903 to 0.9996).
  - The WhatsApp-size copy of the face swap: the face check abstains (0.8715, grey band) and the rules give RED.
  - A genuine WhatsApp-size video: GREY (face clean, 0.138).
  - A browser voice recording (.weba, live-replay): a voice result, no face row.
  - The face swap re-filmed at the counter (live-replay): the face check says "unsure" (cell `video/live-replay`).
  - Upload to verdict takes about 40-60 s for the first check of a short video, about 2.5 minutes for a one-minute
    1080p video; the same bytes again are reused at once (cached by content hash in the running engine).

## What was measured (quote only with the sample sizes)

| What | Result | Source |
|---|---|---|
| Face check, HD | AUC 0.97; 5% false-alarm threshold 0.92; 38 genuine, 2 fake clips | `calibration/video_report.md` |
| Face check, WhatsApp-size | AUC 0.87; 5% threshold 0.97, which no fake cleared; 26 genuine, 6 fake | same |
| Face check, declined to judge | 66 of 138 clips (frames disagree, small face, few faces) | same |
| Voice check, Hindi clean | at the 5% line: 4 of 81 real voices flagged, 57 of 60 fakes caught | `calibration/audio_report.md` |
| Voice check, Hindi WhatsApp-style (simulated) | 3 of 69 real flagged, 52 of 60 fakes caught | same |
| Voice check, Hindi phone 8 kHz (Gram Vaani real calls + simulated) | 9 of 198 real flagged, 49 of 60 fakes caught | same |
| Voice check, English, all channels (In-the-Wild) | 13 of 269 real flagged, 289 of 294 fakes caught | same |
| Voice check, by kind of fake (Hindi) | XTTS-v2 clones 87 of 87 caught; FreeVC conversions 70 of 93 | same |
| Whisper turbo, Hindi | about 33% word errors; about 2x real time on CPU | `calibration/whisper_eval_fast.md` |
| Whisper small, Hindi | about 60% word errors at similar speed (not used) | same |

Plain reading: on HD video the face check is useful. On compressed WhatsApp forwards it rarely flags and often says
"unsure" (counted as no media). The voice check catches most lab-made Hindi clones at the 5% line, and FreeVC voice
conversion less often. Since the 24 Oct merge the deepfake check counts half in a combined score
(`docs/changes-2026-10-24.md`). A face flag is at most "moderate", so alone it gives 35%, AMBER. A voice flag can be
"high" only where a cell has a 1% line; among the cells by channel only Hindi phone audio has one (198 real clips).
There a voice flag alone gives 50%, RED when the message asks for money.

## How to run the demo

```bash
cd satyapan-finale && scripts/demo_up.sh        # about a minute; then open http://localhost:8000
# in a second terminal, from satyapan-finale/:
../satyapan/.venv/bin/satyapan preflight --server http://127.0.0.1:8000   # 7 lines, all PASS
.venv/bin/python scripts/pipeline_check.py      # the 12 live end-to-end cases above
scripts/stop_demo.sh                            # stop the engine and the forensics service
```

After a console rebuild, restart with `scripts/stop_demo.sh && scripts/demo_up.sh`: `scripts/demo_up.sh` alone fails
while the engine is still running. Run-sheet and pre-demo checklist: `../docs/finale-runsheet.md`.

## Left to do

- **Paper disclosure form, Section 2A** (models), if not yet sent. The demo uses GenD CLIP-L/14 (MIT), YuNet (MIT),
  Whisper via faster-whisper (MIT), DF Arena 500M (non-commercial) and Tesseract OCR (Apache-2.0). The merged engine
  can also use AASIST-L (MIT; an older in-process fallback, not installed on this laptop), the meaning model
  paraphrase-multilingual-MiniLM-L12-v2 through fastembed (not installed on this laptop) and the public RDAP look-up
  at rdap.org (off in the demo). `MODELS.md` has the rows. The DFDC model is no longer used.
- **Paper disclosure form, Section 2B** (datasets), if not yet sent:
  - Wikimedia Commons videos (per-file open licences, `calibration/sources_commons.csv`);
  - the UniDataPro deepfake sample (CC-BY-NC-ND), Google FLEURS Hindi (CC-BY-4.0), IndicSynth Hindi (CC-BY-NC-4.0),
    In-the-Wild (CC-BY-SA-4.0 on Hugging Face) and Gram Vaani (OpenSLR 118, free for academic use);
  - the engine's synthetic labelled evaluation set and the real public registry answers it records
    (`prototype/data/`, see `README.md`);
  - Deepfake-Eval-2024 only if access is approved;
  - Kathbath and DFDC were not used: Kathbath is gated, and DFDC's competition has closed.
- **Deepfake-Eval-2024**: access requested; still waiting for the authors' manual approval.
- **Before the slot**: the run-sheet checklist ends with the reset, then building the beat-4 face-swap case, then
  opening Scenarios. The reset clears every case, so the beat-4 case must be built after it.
- **Optional, if time**:
  - more face-swap clips (Deepfake-Eval-2024) to turn the catch rates into measurements;
  - record your own genuine selfie clip (consented, in `docs/consent.md`) as a live "genuine" demo moment.
