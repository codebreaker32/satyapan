# Model declaration

Every pre-trained model, embedding and third-party API that Satyapan brings into the finale, with its state at check-in.
No model has been trained, fine-tuned or adapted by the team. No weights file is stored in this repository.

| Model / API | Provider / framework | Checkpoint state at check-in | Licence / terms | Role in Satyapan |
|---|---|---|---|---|
| Tesseract OCR 5.3.4, with Hindi (`hin`) language data | tesseract-ocr (open source), called through `pytesseract` | Off-the-shelf | Apache-2.0 | Reads the text of a scanned notice (e.g. a forged summons) so the rules can check the instruction |
| AASIST-L (audio anti-spoofing) | clovaai/aasist (GitHub), PyTorch | Not loaded at check-in. Planned: off-the-shelf pre-trained weights, no fine-tuning | MIT | Corroborating signal on voice notes. Never decides a verdict on its own |
| faster-whisper (Whisper speech-to-text) | SYSTRAN/faster-whisper (CTranslate2), OpenAI Whisper weights | Not installed at check-in. Planned: off-the-shelf | MIT | Transcribes a voice note or video's audio track so the rules can check the instruction |
| Amazon Bedrock (foundation-model extraction) | AWS | Optional path, not active: Bedrock access on the team's account was not authorised at check-in | AWS Service Terms | Optional structured extraction of the claim from a message |
| AWS KMS (asymmetric signing, ECC_NIST_P256) | AWS | Not active at check-in; a local Ed25519 key stands in and is labelled as a mock | AWS Service Terms | Signs the evidence pack |
| Claude (via Claude Code) | Anthropic | API, off-the-shelf | Anthropic commercial terms | Development assistant and writing aid for the team. Not part of the product and not called at run time |

## Notes

- **Checkpoint state** uses the form's terms: off-the-shelf, LoRA, or custom fine-tune. Everything above is off-the-shelf or
  not yet loaded.
- **No external dataset** is used for training or evaluation. The data in `datasets/` is synthetic (see `README.md`).
- **Forensics are corroboration only.** By design a forensic signal can raise a case to AMBER at most; a RED needs two
  independent checks (issuer rules and the bank's own records). Wherever a forensic result is simulated it is labelled
  SIMULATED.
