# Whisper on Hindi voice notes: accuracy and speed

8 FLEURS Hindi clips (read speech, google/fleurs, CC-BY-4.0), average 12.7 s each. CPU only (this laptop), int8, beam 1, threads 12. WER = word error rate against FLEURS's reference text (lower is better).

| Model | Audio | WER | Seconds per clip | Real-time factor |
|---|---|---|---|---|
| small | original | 61.7% | 22.2 | 1.75 |
| small | whatsapp-like opus 16 kbps | 58.4% | 19.4 | 1.52 |
| large-v3-turbo | original | 33.0% | 25.4 | 2.00 |
| large-v3-turbo | whatsapp-like opus 16 kbps | 34.0% | 25.0 | 1.97 |

Real-time factor below 1 means faster than the audio plays. Example output for one clip is not stored.
