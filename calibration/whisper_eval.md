# Whisper on Hindi voice notes: accuracy and speed

12 FLEURS Hindi clips (read speech, google/fleurs, CC-BY-4.0), average 11.4 s each. CPU only (this laptop), int8. WER = word error rate against FLEURS's reference text (lower is better).

| Model | Audio | WER | Seconds per clip | Real-time factor |
|---|---|---|---|---|
| small | original | 48.6% | 17.9 | 1.57 |
| small | whatsapp-like opus 16 kbps | 48.0% | 14.8 | 1.30 |
| large-v3-turbo | original | 26.7% | 62.8 | 5.51 |
| large-v3-turbo | whatsapp-like opus 16 kbps | 29.1% | 69.2 | 6.07 |

Real-time factor below 1 means faster than the audio plays. Measured while the video calibration was also running
(4 threads, beam 5), so these times are pessimistic; see the re-measure below if present. Example output for one clip is not stored.
