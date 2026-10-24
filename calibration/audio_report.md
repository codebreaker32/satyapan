# Voice detector calibration report

Model: `DF_Arena_500M_V_1@8258fa8`. Manifest: `audio_manifest.csv` (scored on an AWS T4 GPU; matches the laptop CPU to 4-5 decimals on the same clips), 630 clips, 1590 scored versions.

Thresholds are set on real clips only. Catch rate = share of fake clips at or above the threshold.
Channels marked simulated were made from clean clips in memory (Opus 16 kbit/s; 8 kHz phone band).

| Cell | Usable real | Usable fake | t_fpr20 | t_fpr5 | t_fpr1 | Catch at 5% FPR | Catch at 20% FPR | AUC | Real sources | Fake sources |
|---|---|---|---|---|---|---|---|---|---|---|
| en/any | 269 | 294 | 0.717665 | 0.999153 | 0.999744 | 0.983 | 0.993 | 0.996 | itw, itw (sim) | itw, itw (sim) |
| en/clean | 92 | 98 | 0.383323 | 0.999153 | - | 0.990 | 0.990 | 0.997 | itw | itw |
| en/phone-8k | 89 | 98 | 0.717665 | 0.999168 | - | 0.980 | 0.990 | 0.996 | itw (sim) | itw (sim) |
| en/whatsapp-opus | 88 | 98 | 0.963223 | 0.999543 | - | 0.969 | 0.990 | 0.996 | itw (sim) | itw (sim) |
| hi/any | 348 | 180 | 0.999472 | 0.999899 | 0.999955 | 0.872 | 0.978 | 0.978 | fleurs, fleurs (sim), gramvaani | indicsynth, indicsynth (sim) |
| hi/clean | 81 | 60 | 0.990331 | 0.999640 | - | 0.950 | 1.000 | 0.993 | fleurs | indicsynth |
| hi/phone-8k | 198 | 60 | 0.999670 | 0.999913 | 0.999981 | 0.817 | 0.967 | 0.967 | fleurs (sim), gramvaani | indicsynth (sim) |
| hi/whatsapp-opus | 69 | 60 | 0.999404 | 0.999916 | - | 0.867 | 0.983 | 0.986 | fleurs (sim) | indicsynth (sim) |

## Fakes caught at the 5% false-alarm threshold, by source

| Cell | Fake source | Clips | Caught |
|---|---|---|---|
| en/any | itw | 294 | 289 of 294 |
| en/clean | itw | 98 | 97 of 98 |
| en/phone-8k | itw | 98 | 96 of 98 |
| en/whatsapp-opus | itw | 98 | 95 of 98 |
| hi/any | indicsynth:freevc24 | 93 | 70 of 93 |
| hi/any | indicsynth:xtts_v2 | 87 | 87 of 87 |
| hi/clean | indicsynth:freevc24 | 31 | 28 of 31 |
| hi/clean | indicsynth:xtts_v2 | 29 | 29 of 29 |
| hi/phone-8k | indicsynth:freevc24 | 31 | 20 of 31 |
| hi/phone-8k | indicsynth:xtts_v2 | 29 | 29 of 29 |
| hi/whatsapp-opus | indicsynth:freevc24 | 31 | 23 of 31 |
| hi/whatsapp-opus | indicsynth:xtts_v2 | 29 | 29 of 29 |

## Clips not used for thresholds

- parts of the recording disagree with each other: 166
- only 1.6 s of voice (needs 2 s to judge): 33
- only 1.4 s of voice (needs 2 s to judge): 30
- only 0.8 s of voice (needs 2 s to judge): 28
- only 1.8 s of voice (needs 2 s to judge): 25
- only 1.1 s of voice (needs 2 s to judge): 25
- only 1.7 s of voice (needs 2 s to judge): 24
- only 1.9 s of voice (needs 2 s to judge): 23
- only 1.5 s of voice (needs 2 s to judge): 20
- only 1.2 s of voice (needs 2 s to judge): 17
- only 0.5 s of voice (needs 2 s to judge): 17
- only 1.0 s of voice (needs 2 s to judge): 16
- only 2.0 s of voice (needs 2 s to judge): 14
- only 1.3 s of voice (needs 2 s to judge): 14
- only 0.7 s of voice (needs 2 s to judge): 13
- only 0.9 s of voice (needs 2 s to judge): 12
- only 0.6 s of voice (needs 2 s to judge): 9
- only 0.4 s of voice (needs 2 s to judge): 7
- only 0.2 s of voice (needs 2 s to judge): 6

Scoring time per clip on this machine: median 0.1 s, max 132.8 s.

With few real clips these thresholds are coarse; the counts above say how much to trust them.
In-the-Wild is English celebrity speech; IndicSynth is lab-made Hindi; no public Indian scam-call audio exists.
