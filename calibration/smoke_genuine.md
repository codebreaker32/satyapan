# Smoke test: genuine voices the calibration never used

Calibration: `audio.json` (DF_Arena_500M_V_1@8258fa8). Manifest: `smoke_manifest.csv`, 350 genuine clips, 800 scored versions. None of these clips was used to set the thresholds.

"Called fake" = status synthetic. The thresholds were set so that about 5% of the calibration's real clips are called fake; on unseen clips the share should be similar if the thresholds generalise.

| Cell | Versions | Called fake | of which high | moderate | Unsure | No signs |
|---|---|---|---|---|---|---|
| hi/aac | 150 | 1 (0.7%) | 0 | 1 | 61 | 88 |
| hi/clean | 150 | 6 (4.0%) | 0 | 6 | 61 | 83 |
| hi/phone-8k | 350 | 10 (2.9%) | 2 | 8 | 109 | 231 |
| hi/whatsapp-opus | 150 | 0 (0.0%) | 0 | 0 | 87 | 63 |

## What the wrongly flagged genuine clips have in common

Judged versions only (482: 17 called fake, 465 no signs). Medians:

| Measure | Called fake | No signs |
|---|---|---|
| seconds of voice | 8.3 | 8.5 |
| clip length, s | 11.6 | 10.1 |
| loud level, dBFS | -12.1 | -19.9 |
| background level, dBFS | -61.3 | -53.9 |
| signal-to-noise, dB | 48.9 | 30.5 |

Called fake, by source: gramvaani 10, fleurs-test 6, fleurs-test (sim) 1.

Raw model score on these genuine voices: 216 of 794 (27%) score 0.99 or more, which is why the thresholds sit near 1.0 and why a raw score is never shown as proof.

## Every genuine version called fake

| Clip | Cell | Band | Score | Voice s | SNR dB | Windows |
|---|---|---|---|---|---|---|
| 01-04100-03.mp3 | hi/phone-8k | high | 0.999972 | 5.16 | 48.1 | 1.0000 1.0000 |
| 01-08050-02.mp3 | hi/phone-8k | high | 0.999972 | 8.91 | 56.2 | 1.0000 0.9999 1.0000 |
| 01-04986-03.mp3 | hi/phone-8k | moderate | 0.999964 | 10.11 | 33.6 | 1.0000 1.0000 0.9999 |
| 01-01714-03.mp3 | hi/phone-8k | moderate | 0.999962 | 7.11 | 62.6 | 1.0000 1.0000 1.0000 |
| 01-04677-02.mp3 | hi/phone-8k | moderate | 0.999960 | 6.78 | 62.4 | 1.0000 0.9999 1.0000 |
| 01-01074-01.mp3 | hi/phone-8k | moderate | 0.999956 | 6.72 | 68.1 | 1.0000 1.0000 0.9998 |
| 13-00302-03.mp3 | hi/phone-8k | moderate | 0.999955 | 7.44 | 46.9 | 1.0000 1.0000 0.9999 |
| 01-06393-02.mp3 | hi/phone-8k | moderate | 0.999951 | 9.06 | 37.0 | 1.0000 1.0000 0.9999 |
| 01-02734-01.mp3 | hi/phone-8k | moderate | 0.999950 | 8.94 | 48.9 | 1.0000 0.9974 1.0000 |
| 01-11389-01.mp3 | hi/phone-8k | moderate | 0.999949 | 9.27 | 46.3 | 0.9999 0.9999 1.0000 |
| 8221165074366964434.wav | hi/aac | moderate | 0.999904 | 8.34 | 33.8 | 0.9999 0.9999 0.9999 |
| 11420171604929754563.wav | hi/clean | moderate | 0.999868 | 11.85 | 33.1 | 0.9999 0.9999 0.9993 |
| 8847810707227471662.wav | hi/clean | moderate | 0.999865 | 6.15 | 63.8 | 0.9999 0.9999 0.9997 |
| 427341939470870414.wav | hi/clean | moderate | 0.999850 | 14.07 | 61.9 | 0.9999 0.9998 0.9999 |
| 8221165074366964434.wav | hi/clean | moderate | 0.999844 | 8.19 | 33.5 | 0.9998 0.9999 0.9994 |
| 13776316053400783080.wav | hi/clean | moderate | 0.999768 | 8.37 | 67.0 | 0.9976 0.9998 0.9999 |
| 14633299830001558637.wav | hi/clean | moderate | 0.999760 | 7.14 | 71.0 | 0.9997 0.9998 1.0000 |
