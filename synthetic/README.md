# synthetic/: the code that made our synthetic data

Every synthetic artefact Satyapan used is either made by a generator in this folder or written by hand and checked
by `validate_fixtures.py`. Generators write to `clips/synthetic/` by default, which git ignores; pass `--out` to
choose a folder. Nothing they make is committed.

| What | Made by | Runs on a Linux box with no TTS engine? |
|---|---|---|
| Synthetic notice images (`ED_summons_synthetic.png` and one per OCR scenario) | `make_notice_image.py` | yes |
| The "digital arrest" test voice note | `make_test_voice_note.py` | the encoding step only (the TTS needs PowerShell or espeak-ng) |
| WhatsApp-like and 8 kHz phone copies of audio, WhatsApp-size copies of video (calibration) | `channels.py` | yes |
| The two live demo cases (run-sheet beats 2 and 4) | `../scripts/build_demo_cases.py` | needs the running demo stack |
| The 10 format-test files | `make_format_sweep.py` | yes, with `--tone` or `--voice FILE` |
| Scenarios, variants, labelled evaluation set, mock bank records | written with Claude, not by code | `validate_fixtures.py` checks them |

Run from the repo root with the detectors' venv (`requirements.txt`), except the `aasist-*` channels, which import the
engine package and need the engine's venv (`prototype/pyproject.toml`).

## Notice images: `make_notice_image.py`

    python synthetic/make_notice_image.py --out /tmp/notices          # ED_summons_synthetic.png, from scenario S3
    python synthetic/make_notice_image.py --out /tmp/notices --all    # every scenario whose text arrives by OCR

Draws a scenario's notice text from `prototype/data/fixtures/scenarios.json` with `prototype/tests/notice_render.py`
(the renderer `prototype/tests/test_ocr.py` reads back with Tesseract): a 1200 px wide white page, black DejaVu Sans
32 px text wrapped at 58 characters, and a diagonal "SYNTHETIC" watermark at 30 degrees. No logo, emblem, seal,
signature or real official's name is drawn. `--all` covers S3, S5c, S5c2, S5d, S5f and S7.
Reproducibility: on the workbox (Pillow 12.3.0, DejaVu Sans) the S3 image came out byte-identical to the
`ED_summons_synthetic.png` the demo used (1200 x 544).

## The test voice note: `make_test_voice_note.py`

    python synthetic/make_test_voice_note.py --out /tmp/voice                  # TTS, then ffmpeg
    python synthetic/make_test_voice_note.py --out /tmp/voice --wav mine.wav   # only the ffmpeg step

The script read aloud (exact text):

> Listen carefully. You are digitally arrested. Do not disconnect this call, and do not tell anyone in your family.
> To clear your name, you must send all the money in your bank account today, to the R B I verification account.
> Account number: 3 0 0 1 1 2 2 3 3 4 4 5 5 6. I F S C code: D E M O 0 0 0 1 2 3 4. Send the money now, or you
> will be arrested.

- **Voice.** "Microsoft David Desktop", the stock English voice of Windows' System.Speech, called through
  `powershell.exe` (on Windows, or from WSL). Where PowerShell is missing it falls back to `espeak-ng` (or `espeak`),
  `-v en-us`. It uses no real person's voice: neither engine is a clone of anyone. The account number is invented and
  `DEMO` is an IFSC prefix no bank holds.
- **Encoding.** `ffmpeg -i note.wav -ac 1 -ar 16000 -c:a libopus -b:a 24k digital_arrest_test_voice_note.ogg`
  (Opus in Ogg, 16 kHz mono). The team's file is 34.17 s and 85,722 bytes, mono, 16 kHz input rate, written by the
  same ffmpeg 7.0 that imageio-ffmpeg bundles. We do not have the command that made it; re-encoding its own audio at
  24 kbit/s gives 85,218 bytes and at 16 kbit/s 59,350, so 24k is the setting here. espeak-ng speaks at its own
  speed, so its note will not be 34.17 s long.
- **On the workbox** there is neither PowerShell nor espeak-ng, so only the encoding step was run there (tests).

## Channel simulations for calibration: `channels.py`

Thin wrappers that import the code which made the calibration data, so each setting exists once.

    python synthetic/channels.py whatsapp-opus  in.wav out.ogg
    python synthetic/channels.py sim-phone-8k   in.wav out.wav
    python synthetic/channels.py whatsapp-video in.mp4 out.mp4

| Channel | Used for | Exact settings | Defined in |
|---|---|---|---|
| `whatsapp-opus` | the `hi/whatsapp-opus` calibration clips of the voice detector (DF Arena) | `ffmpeg -i in -ac 1 -ar 16000 -c:a libopus -b:a 16k out.ogg` | `scripts/prepare_audio_clips.py` (`WHATSAPP_OPUS`, `whatsapp_opus()`) |
| `sim-whatsapp-opus` | in-memory copies scored as `simulated` rows in `calibration/audio_runs.csv` | PyAV: libopus in Ogg, stream rate 48000, mono, `bit_rate = 16000`; decoded back to 16 kHz mono | `scripts/calibrate_audio.py` (`through_channel`) |
| `sim-phone-8k` | the same, for the 8 kHz phone band | PyAV resampler 16 kHz to 8 kHz to 16 kHz, float mono, no codec | `scripts/calibrate_audio.py` (`through_channel`) |
| `whatsapp-video` | the WhatsApp-size cells of the video calibration (`clips/commons_wa`, `clips/unidata_wa`) | `ffmpeg -i in -vf "scale='if(lt(iw,ih),min(480,iw),-2)':'if(lt(iw,ih),-2,min(480,ih))'" -c:v libx264 -preset veryfast -crf 30 -maxrate 900k -bufsize 1800k -pix_fmt yuv420p -c:a aac -b:a 64k -movflags +faststart out.mp4` (short side at most 480 px) | `scripts/whatsappify.py` (`reencode`), run by `scripts/run_video_calibration.sh` |
| `aasist-clean-16k`, `aasist-amr-8k`, `aasist-whatsapp-opus` | the older AASIST-L fallback's thresholds (`prototype/data/forensics/aasist_calibration.json`) | PyAV: WAV pcm_s16le 16000 Hz; WAV pcm_s16le 8000 Hz (no AMR encoder in PyAV, so 8 kHz PCM); Ogg libopus 48000 Hz, `bit_rate = 16000` | `prototype/satyapan/calibrate.py` (`CHANNELS`, `_encode`) |

These are approximations of the real channels, not forwards made between phones: `scripts/whatsappify.py` says so
in its docstring, and `calibration/audio_report.md` marks the in-memory rows as simulated. The `sim-whatsapp-opus` path writes one scratch file, `clips/.channel_tmp.ogg`, inside the
git-ignored `clips/` folder, because that is what `calibrate_audio.py` does.

## The demo cases: `scripts/build_demo_cases.py`

Not in this folder because it needs the running demo stack (`scripts/demo_up.sh`). After "Reset the demo" it builds
the two live cases through the same API the console uses and exits 1 unless both come back RED with the real
detector flagging the media:

- **Beat 2, the cloned RM voice note:** `clips/audio/fake_opus/fake_000.ogg` (an IndicSynth Hindi FreeVC clone,
  CC-BY-NC-4.0, already put through the `whatsapp-opus` channel above) uploaded as `PTT-20261024-WA0011.opus`, with
  scenario S1's text and sender number.
- **Beat 4, the face swap:** `clips/demo/officer_faceswap.mp4` (a UniDataPro sample clip, CC-BY-NC-ND-4.0,
  unmodified) with an invented ED "digital arrest" text (account 30011223344556, IFSC DEMO0001234).

## The format sweep: `make_format_sweep.py`

    python synthetic/make_format_sweep.py --out /tmp/sweep --voice /tmp/voice/digital_arrest_test_voice_note.ogg
    python synthetic/make_format_sweep.py --out /tmp/sweep --tone

Inputs are synthetic only: the test voice note (or a 440 Hz sine with `--tone`), ffmpeg's `testsrc2` colour-bar
pattern (640 x 360, 25 fps, 6 s; no face, no person) and the S3 notice image.

| File | ffmpeg output options / how | Tests |
|---|---|---|
| `voice.mp3` | `-vn -ac 1 -ar 16000 -c:a libmp3lame -b:a 64k` | MP3 audio |
| `voice_8k.wav` | `-vn -ac 1 -ar 8000 -c:a pcm_s16le` | 8 kHz phone-band WAV |
| `voice.m4a` | `-vn -ac 1 -ar 16000 -c:a aac -b:a 64k` | AAC in MP4 |
| `clip.mov` | `-c:v libx264 -preset veryfast -pix_fmt yuv420p -c:a aac -b:a 64k -shortest` | QuickTime video with sound |
| `clip.webm` | `-c:v libvpx -b:v 500k -c:a libopus -b:a 32k -shortest` | WebM video with sound |
| `clip_no_audio.mp4` | `-c:v libx264 -preset veryfast -pix_fmt yuv420p -an` | a video in which nobody speaks |
| `notice.jpg` | Pillow, quality 85 | JPEG notice |
| `notice.webp` | Pillow, quality 80 | WebP notice |
| `renamed_clip.jpg` | a copy of `clip_no_audio.mp4` | an MP4 named as an image: the upload refuses it as renamed (`prototype/satyapan/media.py`, `contents_contradict_name`) |
| `message.txt` | scenario S1's text, UTF-8 | plain text |

On the workbox all 10 were made from the test voice note and with `--tone`. The engine's intake classed each one as
intended, and only `renamed_clip.jpg` was flagged as renamed.

## Hand-written text corpora and `validate_fixtures.py`

These files were **written with Claude (an AI assistant), not generated by code**:

| File | What | Size |
|---|---|---|
| `prototype/data/fixtures/scenarios.json` | the demo scenarios | 22 scenarios |
| `prototype/data/fixtures/variants.json` | Hinglish, Hindi and disguised rewrites of the scenario texts, plus benign controls | 73 variants |
| `prototype/data/eval/labelled.json` | the labelled evaluation messages | 64 messages |
| `prototype/data/eval/memory_pairs.json` | reworded and translated copies of stored scams | 14 copies |
| `prototype/data/mocks/*` (8 files) | the mock bank records behind the labelled adapters | ledger, name look-up, outbound log, RM phones, suspect registry, ED summons, campaign memory, bank policy |
| `datasets/` | the check-in copy of the scenarios, variants, mocks and rulebook | |

Not hand-written: `prototype/data/eval/results.json` and `docs/evaluation.md` are written by `satyapan evaluate`;
`prototype/data/eval/memory_calibration.json` by `satyapan calibrate-memory`; `prototype/data/mocks/web_registry.json`
holds real public answers recorded from the domain registries over RDAP (its `_note` says so).

The rules the corpora follow:

- **Names** are invented (for example Sharda, Rohit, "Demo Bank"); no real customer, official or official's name.
- **IFSC** codes should carry the `DEMO` prefix (`DEMO0001234`), which no bank holds.
- **Account and phone numbers** are invented and visibly patterned (`30011223344556`, `+919876500011`).
- **UPI IDs** use invented handles (`rbi.invest@okaxis`).

`python synthetic/validate_fixtures.py` checks that every corpus file still parses (JSON) and that every IFSC,
account number, UPI ID and phone number follows the rules: IFSC must start `DEMO0`; a number of 9 to 18 digits
(solid or in groups) must contain a run of at least 4 consecutive digits or at least 2 doubled digits; a numeric UPI
handle must pass the number rule. It reports what breaks a rule and exits 1; it never edits a fixture. These checks
catch a number that does not look invented; they cannot prove that a number belongs to no one. Names are not
checked by code.

What it reports today (25 Oct 2026), left as it is and pinned in `tests/test_synthetic.py`:

| Reported | Where | Why it is there |
|---|---|---|
| IFSC `SBIN0004321` | scenario S2 | a real bank prefix (SBI) with a branch code we did not check |
| IFSC `HDFC0000213` | S3, S5d, S9, S9b, the labelled set, campaign memory | a real bank prefix (HDFC) with a branch code we did not check |
| IFSC `SBIN0000691` | scenario S7 | a real bank prefix (SBI) with a branch code we did not check |

The three IFSCs appear in scam messages as the account a fraudster names, and `HDFC0000213` also in one control
(S9b, where it stands for the corporation's own collection account). A bank's IFSC directory would say whether
those branch codes exist; we did not check, and we did not change the fixtures to pass.

## Licences of what the generators touch

- **Pillow** (MIT-CMU licence) draws the images; **DejaVu Sans** (Bitstream Vera / DejaVu free font licence) on
  Linux, **Arial** (ships with Windows) on Windows.
- **ffmpeg**: the static 7.0.2 build that **imageio-ffmpeg** (BSD-2-Clause) bundles; that build is configured with
  `--enable-gpl --enable-version3` (libx264, libvpx, libopus, libmp3lame). It runs as a separate program and is not
  shipped in this repo. **PyAV** (BSD-3-Clause) for the in-memory channels.
- **Text to speech**: Windows System.Speech and its "Microsoft David Desktop" voice are part of Windows; espeak-ng is
  GPL-3.0.
- **Inputs**: the scenario texts (written with Claude for this repo, GPL-3.0 with the repo), ffmpeg's built-in
  `testsrc2` and `sine` sources. The generators download nothing. `channels.py` is applied to public clips whose
  licences are in the root README's dataset table: FLEURS (CC-BY-4.0), IndicSynth (CC-BY-NC-4.0), Wikimedia Commons
  clips (each file's own open licence, `calibration/sources_commons.csv`) and the UniDataPro sample (CC-BY-NC-ND-4.0:
  its compressed copies stay in `clips/` and are never shared).
