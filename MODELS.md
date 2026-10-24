# Model declaration

Every pre-trained model, embedding and third-party API that Satyapan brings into the finale, with its state at check-in.
No model has been trained, fine-tuned or adapted by the team. No weights file is stored in this repository.

| Model / API | Provider / framework | Checkpoint state at check-in | Licence / terms | Role in Satyapan |
|---|---|---|---|---|
| Tesseract OCR 5.3.4, with Hindi (`hin`) language data | tesseract-ocr (open source), called through `pytesseract` | Off-the-shelf | Apache-2.0 | Reads the text of a scanned notice (e.g. a forged summons) so the rules can check the instruction |
| Whisper speech-to-text via faster-whisper: `Systran/faster-whisper-small` and `mobiuslabsgmbh/faster-whisper-large-v3-turbo` (CTranslate2 conversions of OpenAI Whisper) | SYSTRAN/faster-whisper (CTranslate2), Hugging Face | Off-the-shelf, int8 on CPU, no fine-tuning. Both evaluated on Hindi (`calibration/whisper_eval.md`, `calibration/whisper_eval_fast.md`); the demo uses `large-v3-turbo` with greedy decoding (about half the word errors of `small` (33% vs 62% on 8 FLEURS Hindi clips, greedy) at a similar speed on this laptop); set by `SATYAPAN_WHISPER_MODEL` | MIT (faster-whisper, CTranslate2, the converted weights and OpenAI Whisper) | Turns a voice note or a video's sound track into text, so the issuer rules can read what was asked. Runs locally; no paid API |
| DF Arena 500M (audio deepfake / voice-clone detection), `Speech-Arena-2025/DF_Arena_500M_V_1` at revision `8258fa8` | Speech-Arena-2025 (Idiap; Hugging Face), PyTorch + `transformers` `Wav2Vec2Model` | Off-the-shelf pre-trained weights, no fine-tuning. Model code imported at run time from the pinned download (never copied into this repo). About 2.2 s per 4-second window on the team laptop's CPU (Ryzen 5 5500U) | Custom non-commercial licence (LICENSE.txt: original contributions under a non-commercial licence; upstream portions MIT). Used for this non-commercial hackathon prototype only | Voice-clone check on voice notes and on the soundtrack of videos (`forensics/audio.py`). Its calibrated band counts half in the main app's combined score. Measured on our clips (`calibration/audio_report.md`): at most 5% of real voices flagged in every cell, 87% of Hindi fakes and 98% of English fakes caught. Never decides a verdict on its own |
| DF Arena 1B (same family, larger), `Speech-Arena-2025/DF_Arena_1B_V_1` at revision `fb6ce85` | Same | Off-the-shelf. Supported (`--size 1B`) but not used live: on the 7.3 GB team laptop it takes about 14 s per window and over 3 min to load | Same | Stronger on Hindi in an independent benchmark (LRLspoof: 93.66% of Hindi fakes caught, against 6.59% for the 500M); the right choice on a machine with 16 GB |
| GenD, CLIP ViT-L/14 (video / face deepfake detection, WACV 2026), `yermandy/GenD_CLIP_L_14` | yermandy/GenD (GitHub, Hugging Face), PyTorch via `transformers`; faces found and aligned with YuNet (`opencv/opencv_zoo`, `face_detection_yunet_2023mar.onnx`, run through OpenCV) | Not loaded at check-in. Planned: off-the-shelf pre-trained weights, no fine-tuning | Code and weights MIT; YuNet MIT. The weights were trained by their authors on FaceForensics++, which has its own non-commercial research terms; we use the published weights only and do not download FF++ | Corroborating signal on video calls and recorded videos (face manipulation). Never decides a verdict on its own |

## Notes

- **Checkpoint state** uses the form's terms: off-the-shelf, LoRA, or custom fine-tune. Everything above is off-the-shelf or
  not yet loaded.
- **Why these detectors:** independent tests on deepfakes circulated in 2024 (Deepfake-Eval-2024, arXiv 2503.02857) show
  open-source detectors losing about half their accuracy in the wild, so we chose the models with the strongest published
  cross-dataset results and use them only to corroborate.
- **No training or fine-tuning.** Public datasets (listed in `README.md`) are used only to calibrate thresholds and
  measure accuracy. The data in `datasets/` is synthetic.
- **A detector never decides alone.** In the main app its calibrated band (never its raw score) counts half in a
  combined score with the instruction checks: 50% instruction + 50% deepfake, RED from 40%. The officer still decides.
  Wherever a forensic result is simulated it is labelled SIMULATED.
