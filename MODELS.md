# Model declaration

Every pre-trained model, embedding and third-party API that Satyapan brings into the finale, with its state at check-in.
No model has been trained, fine-tuned or adapted by the team. No weights file is stored in this repository.

| Model / API | Provider / framework | Checkpoint state at check-in | Licence / terms | Role in Satyapan |
|---|---|---|---|---|
| Tesseract OCR 5.3.4, with Hindi (`hin`) language data | tesseract-ocr (open source), called through `pytesseract` | Off-the-shelf | Apache-2.0 | Reads the text of a scanned notice (e.g. a forged summons) so the rules can check the instruction |
| AASIST-L (audio anti-spoofing) | clovaai/aasist (GitHub), PyTorch | Not loaded at check-in. Planned: off-the-shelf pre-trained weights, no fine-tuning | MIT | Corroborating signal on voice notes. Never decides a verdict on its own |
| DFDC deepfake classifier: EfficientNet-B7 (Deepfake Detection Challenge, 1st place), with the MTCNN face detector it uses | selimsef/dfdc_deepfake_challenge (GitHub), PyTorch; MTCNN via facenet-pytorch | Not loaded at check-in. Planned: one published checkpoint used off-the-shelf, no fine-tuning | Code MIT. The weights were trained by their authors on Meta's DFDC dataset, which has its own research terms; we use the published weights only and do not download DFDC | Corroborating signal on video calls and recorded videos (face manipulation). Never decides a verdict on its own |

## Notes

- **Checkpoint state** uses the form's terms: off-the-shelf, LoRA, or custom fine-tune. Everything above is off-the-shelf or
  not yet loaded.
- **No external dataset** is used for training or evaluation. The data in `datasets/` is synthetic (see `README.md`).
- **Forensics are corroboration only.** By design a forensic signal can raise a case to AMBER at most; a RED needs two
  independent checks (issuer rules and the bank's own records). Wherever a forensic result is simulated it is labelled
  SIMULATED.
