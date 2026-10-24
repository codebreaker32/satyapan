# Model declaration

Every pre-trained model, embedding and third-party API that Satyapan brings into the finale, with its state at check-in.
No model has been trained, fine-tuned or adapted by the team. No weights file is stored in this repository.

| Model / API | Provider / framework | Checkpoint state at check-in | Licence / terms | Role in Satyapan |
|---|---|---|---|---|
| Tesseract OCR 5.3.4, with Hindi (`hin`) language data | tesseract-ocr (open source), called through `pytesseract` | Off-the-shelf | Apache-2.0 | Reads the text of a scanned notice (e.g. a forged summons) so the rules can check the instruction |
| DF Arena 500M (audio deepfake / voice-clone detection), `Speech-Arena-2025/DF_Arena_500M_V_1` | Speech-Arena-2025 (Hugging Face), PyTorch via `transformers` | Not loaded at check-in. Planned: off-the-shelf pre-trained weights, no fine-tuning | Custom non-commercial licence (LICENSE.txt: original contributions under a non-commercial licence; upstream portions MIT). Used for this non-commercial hackathon prototype only | Corroborating signal on voice notes. Never decides a verdict on its own |
| GenD, CLIP ViT-L/14 (video / face deepfake detection, WACV 2026), `yermandy/GenD_CLIP_L_14` | yermandy/GenD (GitHub, Hugging Face), PyTorch via `transformers`; faces found and aligned with YuNet (`opencv/opencv_zoo`, `face_detection_yunet_2023mar.onnx`, run through OpenCV) | Not loaded at check-in. Planned: off-the-shelf pre-trained weights, no fine-tuning | Code and weights MIT; YuNet MIT. The weights were trained by their authors on FaceForensics++, which has its own non-commercial research terms; we use the published weights only and do not download FF++ | Corroborating signal on video calls and recorded videos (face manipulation). Never decides a verdict on its own |

## Notes

- **Checkpoint state** uses the form's terms: off-the-shelf, LoRA, or custom fine-tune. Everything above is off-the-shelf or
  not yet loaded.
- **Why these detectors:** independent tests on deepfakes circulated in 2024 (Deepfake-Eval-2024, arXiv 2503.02857) show
  open-source detectors losing about half their accuracy in the wild, so we chose the models with the strongest published
  cross-dataset results and use them only to corroborate.
- **No training or fine-tuning.** Public datasets (listed in `README.md`) are used only to calibrate thresholds and
  measure accuracy. The data in `datasets/` is synthetic.
- **Forensics are corroboration only.** By design a forensic signal can raise a case to AMBER at most; a RED needs two
  independent checks (issuer rules and the bank's own records). Wherever a forensic result is simulated it is labelled
  SIMULATED.
