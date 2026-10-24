# Voice detector calibration report

Model: `DF_Arena_500M_V_1@8258fa8`. Manifest: `audio_manifest.csv` (scored on an AWS T4 GPU; matches the laptop CPU to 4-5 decimals on the same clips), 1080 clips, 2520 scored versions.

Thresholds are set on real clips only. Catch rate = share of fake clips at or above the threshold.
Channels marked simulated were made from clean clips in memory (Opus 16 kbit/s; 8 kHz phone band; AAC 64 kbit/s, the sound of a WhatsApp-like video).

| Cell | Usable real | Usable fake | t_fpr20 | t_fpr5 | t_fpr1 | Catch at 5% FPR | Catch at 20% FPR | AUC | Real sources | Fake sources |
|---|---|---|---|---|---|---|---|---|---|---|
| en/aac | 84 | 99 | 0.950419 | 0.999501 | - | 0.980 | 1.000 | 0.997 | itw (sim) | itw (sim) |
| en/any | 353 | 393 | 0.717665 | 0.999168 | 0.999762 | 0.985 | 0.995 | 0.996 | itw, itw (sim) | itw, itw (sim) |
| en/clean | 92 | 98 | 0.383323 | 0.999153 | - | 0.990 | 0.990 | 0.997 | itw | itw |
| en/phone-8k | 89 | 98 | 0.717665 | 0.999168 | - | 0.980 | 0.990 | 0.996 | itw (sim) | itw (sim) |
| en/whatsapp-opus | 88 | 98 | 0.963223 | 0.999543 | - | 0.969 | 0.990 | 0.996 | itw (sim) | itw (sim) |
| hi/aac | 77 | 60 | 0.997876 | 0.999848 | - | 0.900 | 1.000 | 0.992 | fleurs (sim) | indicsynth (sim) |
| hi/any | 783 | 240 | 0.999771 | 0.999930 | 0.999962 | 0.817 | 0.954 | 0.964 | fleurs, fleurs (sim), gramvaani | indicsynth, indicsynth (sim) |
| hi/clean | 81 | 60 | 0.990331 | 0.999640 | - | 0.950 | 1.000 | 0.993 | fleurs | indicsynth |
| hi/phone-8k | 474 | 60 | 0.999865 | 0.999947 | 0.999964 | 0.650 | 0.883 | 0.938 | gramvaani | indicsynth (sim) |
| hi/whatsapp-opus | 69 | 60 | 0.999404 | 0.999916 | - | 0.867 | 0.983 | 0.986 | fleurs (sim) | indicsynth (sim) |

## Fakes caught at the 5% false-alarm threshold, by source

| Cell | Fake source | Clips | Caught |
|---|---|---|---|
| en/aac | itw | 99 | 97 of 99 |
| en/any | itw | 393 | 387 of 393 |
| en/clean | itw | 98 | 97 of 98 |
| en/phone-8k | itw | 98 | 96 of 98 |
| en/whatsapp-opus | itw | 98 | 95 of 98 |
| hi/aac | indicsynth:freevc24 | 31 | 25 of 31 |
| hi/aac | indicsynth:xtts_v2 | 29 | 29 of 29 |
| hi/any | indicsynth:freevc24 | 124 | 80 of 124 |
| hi/any | indicsynth:xtts_v2 | 116 | 116 of 116 |
| hi/clean | indicsynth:freevc24 | 31 | 28 of 31 |
| hi/clean | indicsynth:xtts_v2 | 29 | 29 of 29 |
| hi/phone-8k | indicsynth:freevc24 | 31 | 10 of 31 |
| hi/phone-8k | indicsynth:xtts_v2 | 29 | 29 of 29 |
| hi/whatsapp-opus | indicsynth:freevc24 | 31 | 23 of 31 |
| hi/whatsapp-opus | indicsynth:xtts_v2 | 29 | 29 of 29 |

## Clips not used for thresholds

- parts of the recording disagree with each other: 303
- only 1.6 s of voice (needs 2 s to judge): 45
- only 1.4 s of voice (needs 2 s to judge): 40
- only 0.8 s of voice (needs 2 s to judge): 38
- only 1.8 s of voice (needs 2 s to judge): 36
- only 1.1 s of voice (needs 2 s to judge): 32
- only 1.7 s of voice (needs 2 s to judge): 32
- only 1.9 s of voice (needs 2 s to judge): 31
- only 1.5 s of voice (needs 2 s to judge): 26
- only 1.0 s of voice (needs 2 s to judge): 24
- only 1.2 s of voice (needs 2 s to judge): 23
- only 0.5 s of voice (needs 2 s to judge): 22
- only 1.3 s of voice (needs 2 s to judge): 20
- only 0.7 s of voice (needs 2 s to judge): 18
- only 2.0 s of voice (needs 2 s to judge): 17
- only 0.9 s of voice (needs 2 s to judge): 14
- only 0.6 s of voice (needs 2 s to judge): 13
- only 0.4 s of voice (needs 2 s to judge): 9
- only 0.2 s of voice (needs 2 s to judge): 8

Scoring time per clip on this machine: median 0.1 s, max 15.4 s.

Where real clips came through the real channel (Gram Vaani phone calls), that cell's thresholds are set on them alone; simulated copies set a line only where no real-channel clips exist.

With few real clips these thresholds are coarse; the counts above say how much to trust them.
In-the-Wild is English celebrity speech; IndicSynth is lab-made Hindi; no public Indian scam-call audio exists.
