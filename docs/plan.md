# Finale plan: deepfake forensics (Aman: video, Bhawna: audio)

What we build in this repo over the two days: two deepfake detectors for financial communications, each wrapped so it
knows when to say "unsure", calibrated on our own consented clips, and joined behind one shared result format. A
detector never decides on its own; its result is one piece of evidence the officer sees, with a plain reason.

Models are declared in `MODELS.md`. Data rules are in `README.md`: synthetic or consented only, no real official's
face or voice.

## 1. The shared contract (agree on it first, 15 minutes, then don't change it)

Every detector returns the same result:

| Field | Values |
|---|---|
| `kind` | `"audio"` or `"video"` |
| `status` | `synthetic` \| `clean` \| `abstain`, nothing else |
| `band` | `low` \| `moderate` \| `high`, only when `synthetic` |
| `score` | the model's raw score, or empty when it didn't run |
| `model` | name and version, e.g. `"GenD_CLIP_L_14"` |
| `cell` | calibration cell, e.g. `hi/whatsapp-opus`, `video/whatsapp-480p` |
| `reason` | one plain sentence, required when abstaining |

**One calibration rule for both:**
- score at or above the threshold that gives a 5% false-positive rate on real clips → `synthetic`;
- score between the 5% and 20% thresholds → `abstain` (grey band, "unsure");
- below the 20% threshold → `clean`;
- no calibration for this kind of input (cell) → `abstain`.

**Calibration file**, one per detector, in `calibration/<detector>.json`:

```json
{"model": "…", "cells": {"hi/whatsapp-opus": {"t_fpr5": 0.0, "t_fpr20": 0.0, "n_real": 0, "n_fake": 0}}}
```

**Suggested layout:**
- `forensics/common.py` holds the result type, the calibration loader and the band rule. Write it together.
- Bhawna owns `forensics/audio.py`; Aman owns `forensics/video.py`.
- `calibration/*.json`, `tests/`, and `requirements.txt` with exact versions.
- Clips stay out of git (`.gitignore` the `clips/` folder). Only the calibration numbers are committed.

## 2. Bhawna: audio (DF Arena 500M)

1. **Run it (first 2 h).** Load `Speech-Arena-2025/DF_Arena_500M_V_1` with
   `transformers.pipeline("antispoofing", trust_remote_code=True)` on CPU. Time one 30 s clip.
   If it takes over 15 s, score only the first 20 s.
2. **Wrapper.** Decode with ffmpeg to 16 kHz mono. Abstain on under 3 s of speech. Set `cell` from language + codec.
3. **Calibration** (public data; see the README's dataset table):
   - real Hindi: about 30 clips from `ai4bharat/Kathbath`;
   - fake Hindi: about 30 clips from `vdivyasharma/IndicSynth`;
   - WhatsApp cell: forward about 10 of each through WhatsApp between our phones and save them back, so the Opus
     compression is real;
   - cross-check: a sample of about 50 from `mueller91/In-The-Wild`;
   - a few genuine voice notes of our own (consented), to check real voices aren't flagged.
   Set the thresholds from the real clips. Record the catch rate on the fakes honestly, even if it's poor.
4. **Video audio track.** The same detector must also run on the audio extracted from a video file.
5. **Tests:**
   - a short clip abstains;
   - an uncalibrated cell abstains;
   - with a stub model returning fixed scores, each band maps to the right status.

## 3. Aman: video (GenD CLIP-L/14)

1. **Run it (first 2 h).** Load `yermandy/GenD_CLIP_L_14` (its `modeling_gend.py`, `trust_remote_code`). Find and align faces with
   YuNet (OpenCV's `FaceDetectorYN`, MIT): five landmarks, aligned exactly as GenD's own `align_face` does
   (scale 1.3). Time 16 frames on CPU. If it takes over 20 s, use 8 frames.
2. **Wrapper.**
   - Sample N frames evenly with ffmpeg.
   - Find the largest face in each frame and score each crop.
   - Take the median score.
   Abstain when:
   - fewer than half the frames have a face;
   - the face is under about 80 px (low-res WhatsApp);
   - frame scores disagree a lot;
   - the score is in the grey band.
3. **Calibration** (public data; see the README's dataset table):
   - about 40 DFDC sample videos (real and fake), which GenD never trained on;
   - Deepfake-Eval-2024 if access is approved (request it on Day 1, first thing);
   - WhatsApp cell: forward about 10 real and 10 fake clips through WhatsApp and save them back;
   - a few genuine phone clips of ourselves (consented), to check real faces aren't flagged.
   Set the thresholds and record the catch rate honestly.
4. **Tests:**
   - no face abstains;
   - a tiny face abstains;
   - with a stub scorer, the median and spread rules work.

## 4. Joining the two (Day 2 morning)

- **One entry point**, `analyse(path)`: an audio file runs the audio detector; a video file runs **both** (video on the
  frames, audio on its track). It returns a list of results.
- **A plain-language line per result** for the officer, e.g. "Voice: signs of cloning (high)" or "Video: unsure: face too
  small to judge". Never show a bare score as proof.
- **A record per run:** file hash, model and version, calibration cell, score, status. That is the evidence trail.

## 5. Demo beats this gives us

1. **Synthetic Hindi voice note** (from IndicSynth, labelled as a public research sample): the audio detector
   flags it, with its band and reason.
2. **Face-swapped video** (a public research sample, labelled): GenD flags it, and the audio track is checked too.
   No real official's face is shown; if a sample shows a recognisable public figure, pick another.
3. **Blurry WhatsApp forward:** the detector says "unsure", with its reason. This shows it won't guess.
4. **Line for Q&A:** open detectors lose about half their accuracy on 2024's real deepfakes (Deepfake-Eval-2024,
   arXiv 2503.02857), so a detector here never decides on its own.

## 6. Checkpoints

| When | Aman (video) | Bhawna (audio) |
|---|---|---|
| Day 1, +15 min | Contract and `forensics/common.py` agreed | same |
| Day 1, +2 h | GenD scores one clip on the laptop; time measured | DF Arena scores one note; time measured |
| Day 1, +6 h | Wrapper, abstain rules and tests pass | Wrapper, abstain rules and tests pass |
| Day 1, end | Public clips + WhatsApp cell scored, thresholds set | Public clips + WhatsApp cell scored, thresholds set |
| Day 2, +3 h | Joined entry point, officer lines, run records | Video audio track, officer lines, run records |
| Day 2, +5 h | Freeze; 2 full rehearsals | Freeze; 2 full rehearsals |

**Fallback:** a detector not calibrated by the end of Day 1 ships as "abstain: not calibrated". Never show an
uncalibrated score as a result.

## 7. Housekeeping

- Commit small and often. The commit log is our audit trail for the organisers.
- Record consent for every clip of ourselves in `docs/consent.md` (who, what, date). No real official's face or voice.
- Public datasets: keep them in `clips/` (never committed) and list the files used in `calibration/`.
- Request Deepfake-Eval-2024 access first thing on Day 1; approval is manual.
- If a model or tool changes, update `MODELS.md` in the same commit.
