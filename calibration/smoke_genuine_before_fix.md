# Smoke test: genuine voices the calibration never used

Calibration: `audio.json` (DF_Arena_500M_V_1@8258fa8). Manifest: `smoke_manifest.csv`, 350 genuine clips, 800 scored versions. None of these clips was used to set the thresholds.

"Called fake" = status synthetic. The thresholds were set so that about 5% of the calibration's real clips are called fake; on unseen clips the share should be similar if the thresholds generalise.

| Cell | Versions | Called fake | of which high | moderate | Unsure | No signs |
|---|---|---|---|---|---|---|
| hi/aac | 150 | 1 (0.7%) | 0 | 1 | 61 | 88 |
| hi/clean | 150 | 6 (4.0%) | 0 | 6 | 61 | 83 |
| hi/phone-8k | 350 | 23 (6.6%) | 0 | 23 | 118 | 209 |
| hi/whatsapp-opus | 150 | 0 (0.0%) | 0 | 0 | 87 | 63 |

## What the wrongly flagged genuine clips have in common

Judged versions only (473: 30 called fake, 443 no signs). Medians:

| Measure | Called fake | No signs |
|---|---|---|
| seconds of voice | 8.3 | 8.3 |
| clip length, s | 10.9 | 9.9 |
| loud level, dBFS | -9.2 | -21.7 |
| background level, dBFS | -54.6 | -54.0 |
| signal-to-noise, dB | 47.0 | 30.0 |

Called fake, by source: gramvaani 23, fleurs-test 6, fleurs-test (sim) 1.

Raw model score on these genuine voices: 213 of 795 (27%) score 0.99 or more, which is why the thresholds sit near 1.0 and why a raw score is never shown as proof.

## Every genuine version called fake

| Clip | Cell | Band | Score | Voice s | SNR dB | Windows |
|---|---|---|---|---|---|---|
| 01-01356-01.mp3 | hi/phone-8k | moderate | 0.999978 | 6.06 | 40.1 | 1.0000 1.0000 |
| 01-04100-03.mp3 | hi/phone-8k | moderate | 0.999972 | 5.16 | 48.1 | 1.0000 1.0000 |
| 02-13326-02.mp3 | hi/phone-8k | moderate | 0.999972 | 8.7 | 40.1 | 1.0000 1.0000 1.0000 |
| 01-04721-02.mp3 | hi/phone-8k | moderate | 0.999971 | 10.86 | 47.7 | 0.9998 1.0000 1.0000 |
| 01-10815-01.mp3 | hi/phone-8k | moderate | 0.999965 | 9.24 | 47.7 | 1.0000 0.9999 1.0000 |
| 01-01252-02.mp3 | hi/phone-8k | moderate | 0.999964 | 6.93 | 57.1 | 1.0000 1.0000 0.9997 |
| 01-00264-02.mp3 | hi/phone-8k | moderate | 0.999962 | 9.69 | 61.5 | 0.9998 1.0000 1.0000 |
| 01-05357-03.mp3 | hi/phone-8k | moderate | 0.999961 | 3.06 | 51.9 | 0.9999 1.0000 |
| 01-06879-01.mp3 | hi/phone-8k | moderate | 0.999959 | 9.6 | 43.6 | 1.0000 0.9999 1.0000 |
| 01-07226-01.mp3 | hi/phone-8k | moderate | 0.999958 | 8.34 | 54.1 | 1.0000 1.0000 0.9999 |
| 01-11215-03.mp3 | hi/phone-8k | moderate | 0.999957 | 7.05 | 42.0 | 1.0000 0.9958 1.0000 |
| 01-00639-03.mp3 | hi/phone-8k | moderate | 0.999955 | 7.83 | 60.3 | 1.0000 1.0000 0.9998 |
| 01-01258-01.mp3 | hi/phone-8k | moderate | 0.999950 | 8.94 | 38.8 | 0.9999 1.0000 0.9999 |
| 01-11389-01.mp3 | hi/phone-8k | moderate | 0.999949 | 9.27 | 46.3 | 0.9999 0.9999 1.0000 |
| 01-06314-01.mp3 | hi/phone-8k | moderate | 0.999948 | 6.96 | 62.9 | 1.0000 0.9999 0.9999 |
| 01-01568-01.mp3 | hi/phone-8k | moderate | 0.999944 | 8.67 | 39.3 | 1.0000 0.9997 0.9999 |
| 01-00760-03.mp3 | hi/phone-8k | moderate | 0.999943 | 6.0 | 63.3 | 1.0000 0.9999 0.9999 |
| 01-00855-01.mp3 | hi/phone-8k | moderate | 0.999937 | 9.66 | 29.8 | 0.9999 0.9996 1.0000 |
| 01-02735-03.mp3 | hi/phone-8k | moderate | 0.999932 | 7.08 | 59.0 | 1.0000 0.9999 0.9999 |
| 01-06465-02.mp3 | hi/phone-8k | moderate | 0.999924 | 10.05 | 31.7 | 0.9999 0.9998 0.9999 |
| 01-06997-02.mp3 | hi/phone-8k | moderate | 0.999923 | 7.35 | 42.9 | 0.9999 0.9999 1.0000 |
| 01-09350-01.mp3 | hi/phone-8k | moderate | 0.999918 | 8.01 | 38.6 | 0.9939 0.9999 0.9999 |
| 01-10747-03.mp3 | hi/phone-8k | moderate | 0.999914 | 6.27 | 44.4 | 0.9999 0.9998 0.9999 |
| 8221165074366964434.wav | hi/aac | moderate | 0.999904 | 8.34 | 33.8 | 0.9999 0.9999 0.9999 |
| 11420171604929754563.wav | hi/clean | moderate | 0.999868 | 11.85 | 33.1 | 0.9999 0.9999 0.9993 |
| 8847810707227471662.wav | hi/clean | moderate | 0.999865 | 6.15 | 63.8 | 0.9999 0.9999 0.9997 |
| 427341939470870414.wav | hi/clean | moderate | 0.999850 | 14.07 | 61.9 | 0.9999 0.9998 0.9999 |
| 8221165074366964434.wav | hi/clean | moderate | 0.999844 | 8.19 | 33.5 | 0.9998 0.9999 0.9994 |
| 13776316053400783080.wav | hi/clean | moderate | 0.999768 | 8.37 | 67.0 | 0.9976 0.9998 0.9999 |
| 14633299830001558637.wav | hi/clean | moderate | 0.999760 | 7.14 | 71.0 | 0.9997 0.9998 1.0000 |
