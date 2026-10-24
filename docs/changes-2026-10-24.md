# Changes of 24 October 2026

This document records the changes of 24 October 2026, the first day of the finale. It is written for the team and
for any judge. Each change gives the previous behaviour, the present behaviour and the reason. Paths are relative to
the root of this repository; the engine and console are in `prototype/`.

## 1. Lane 1: the instruction checks and the deepfake check, combined

- **Before.** The deepfake check on media (family F3) could raise a case to AMBER at most. A RED needed a cited hard
  rule plus an independent second family.
- **Now** (set by Bhawna). Lane 1 has two tests: the instruction checks (Comparisons 1–4) and the deepfake check (a
  voice note, the sound of a video, or a document, which can also be AI-made).
  - With no media, or with media the detector could not judge, the instruction checks decide alone. The verdict is
    the same as before.
  - With judged media, the two tests count half each:
    `combined = 0.5 × instruction % + 0.5 × deepfake %`.
    - 40% or more → RED.
    - 15% to 39% → AMBER.
    - Under 15% → GREY, which is "could not confirm", never "safe".
  - The bank's own signed message (MATCHES) stays MATCHES. It becomes AMBER only when the media reaches 70% fake.
  - The existing guard still applies: a RED with no money demand read falls back to AMBER.
- **Instruction %**, read off the same ladder the rules already climb (`instruction_pct` in
  `prototype/satyapan/fusion.py`):

  | What the instruction checks found | % |
  |---|---|
  | A cited hard rule plus an independent second check (a RED pair) | 90 |
  | One hard rule alone | 70 |
  | Two independent soft signals, or one that escalates alone | 50 |
  | One soft signal | 20 |
  | Nothing | 0 |

  A rule whose citation is not verified counts 0, so it can never help a case to RED
  (`prototype/tests/test_forensics_combined.py`, `test_an_unverified_rule_counts_zero_so_it_never_helps_a_red`).
- **Deepfake %** comes from the detector's band (calibrated for voice and video; documents are different, see below),
  never the raw model score (`deepfake_pct` in `prototype/satyapan/forensics.py`). The 500M voice model gives many
  real Hindi voices a raw score of 0.99, so a raw score would make real voices look fake.

  | Band | % |
  |---|---|
  | high (above the 1% false-alarm line), or an AI-tool label on a document | 100 |
  | moderate (above the 5% line) | 70 |
  | low (weak document-editing signs) | 30 |
  | clean | 0 |
  | unsure or could not judge | not counted |

  With several files, the most fake one counts.

  Document bands are not calibrated. They come from the file itself (`DocumentForensics` in
  `prototype/satyapan/forensics.py`): an AI-tool label in the file's metadata gives "high" (section 2). Otherwise
  error-level analysis with fixed cut-offs gives "moderate" or "low", and an editing app (Photoshop, GIMP, Canva,
  Pixlr, Snapseed) named in the metadata gives "moderate". None of this was measured on genuine documents, so a real
  notice that was simply edited can count 70%. Error-level analysis abstains on images under 600 px on the short side
  and on recompressed JPEGs.
- **Examples** (`prototype/tests/test_forensics_combined.py`):

  | Instruction | Deepfake | Combined | Verdict |
  |---|---|---|---|
  | fake ED order, a RED pair (90) | real voice (0) | 45 | RED |
  | one hard rule (70) | real voice (0) | 35 | AMBER |
  | one hard rule (70) | cloned voice, moderate (70) | 70 | RED |
  | nothing (0) | cloned voice, high (100) | 50 | RED |
  | nothing (0) | cloned voice, moderate (70) | 35 | AMBER |
  | nothing (0) | real voice (0) | 0 | GREY |

- **Where it shows.**
  - The verdict carries `scores` (instruction %, deepfake %, combined %) into the case record and the evidence pack.
  - The officer's band shows the three numbers (`prototype/console/src/ui/band.tsx`).
  - The customer card shows no score.
- **Why it is better.** The two Lane 1 tests are weighed together, as Bhawna asked. A cloned voice now strengthens
  a weak instruction finding to RED, and a strong clone is stopped even when the text alone says little.
- **What to watch.** A very strong deepfake alone now reaches RED. The voice detector wrongly flags about 5% of real
  voices at the "moderate" line (section 3), and the face check is set the same way. When the message checks find
  nothing, such a false flag gives 35%, which is AMBER. When one soft check also fires, it gives
  0.5 × 20 + 0.5 × 70 = 45%, which is RED if a money demand was read. On 8 kHz Hindi phone audio a real voice can
  even reach "high" (1 of the 198 real phone clips in the calibration did), and that alone gives 50%, RED when the
  message asks for money. The officer still decides, and releasing a RED needs a second person.

## 2. Documents made by AI tools

- **Before.** Document forensics ran error-level analysis (ELA) and looked for editing software (Photoshop, Canva) in
  the file's metadata.
- **Now.** `DocumentForensics` first reads the file's own provenance label (`ai_tool_label` in
  `prototype/satyapan/forensics.py`):
  - the IPTC digital source type `trainedAlgorithmicMedia`, which C2PA content credentials carry;
  - an AI tool named in EXIF, PNG text or XMP: DALL·E, Midjourney, Stable Diffusion, Firefly, Imagen, Gemini,
    ChatGPT/OpenAI, Ideogram or Leonardo.

  A label gives the new rule R-DOC-AI (F3), at 100%. Rulebook 1.6 → 1.7.
- **Limitation.** A missing label proves nothing: labels are easy to strip, and WhatsApp strips them. Detecting an
  unlabelled AI-made image needs an image model, which is a later step.

## 3. Voice detector: DF Arena 500M, recalibrated

- **Before.** The 500M was calibrated at 13:45 on 460 clips. Scores were rounded to 4 decimals, and the model's
  probability reached exactly 1.0. Real and fake clips then tied at the top, so the "5% false-alarm" line actually
  flagged 8.8% of real Hindi phone audio and 7.3% of real Hindi overall.
- **Now.** P(spoof) is computed in float64 from the two logits (`forensics/audio.py`, `spoof_probability`), and the
  runs file keeps it unrounded. The calibration was re-run, scored on an AWS T4 GPU (last point below). Results: see
  the table below and `calibration/audio_report.md`.

  At the 5% false-alarm line (630 clips, 1,590 scored versions):

  | Group | Real voices wrongly flagged | Fakes caught |
  |---|---|---|
  | Hindi, clean | 4 of 81 (4.9%) | 57 of 60 |
  | Hindi, WhatsApp-style (simulated) | 3 of 69 (4.3%) | 52 of 60 |
  | Hindi, phone 8 kHz (Gram Vaani real calls + simulated) | 9 of 198 (4.5%) | 49 of 60 |
  | English, all channels (In-the-Wild) | 13 of 269 (4.8%) | 289 of 294 |

  - By fake type: XTTS-v2 clones are all caught (87 of 87). FreeVC voice conversion is caught less often: 70 of 93,
    and only 20 of 31 on phone audio.
  - 166 versions abstain because their parts disagree. A real 2-second note is the minimum length to judge.
  - A cell gets a 1% line ("high") only with at least 100 real clips. Of the cells the detector picks by channel,
    only Hindi phone audio has one (198 real clips); Hindi clean and WhatsApp-style audio do not, and neither do the
    English ones. So on clean or WhatsApp Hindi audio a voice flag is at most "moderate" (70%): a cloned voice alone
    with an ordinary message gives 35%, AMBER. On 8 kHz phone audio it can be "high" (100%): alone that gives 50%,
    RED when the message asks for money.
  - The re-run was scored on an AWS T4 GPU for speed: about 15 minutes, against about 3 hours on the laptop. The
    machine was terminated straight after. On the same clips, GPU and laptop scores agree to 4–5 decimal places.
- **In the running app** (through the API, model loaded on the laptop CPU):

  | Case | Verdict |
  |---|---|
  | Bhawna's challan message, text only | RED, as before (no score: no media) |
  | The same message + a real Hindi voice (FLEURS) | RED, 90% + 0% → 45% |
  | An ordinary "please send money" + a cloned Hindi voice (IndicSynth XTTS-v2) | AMBER, 0% + 70% → 35% |
  | Bhawna's challan message + a cloned Hindi voice | RED, 90% + 70% → 80% |
  | An AI-labelled PNG + the challan message | RED, 90% + 100% → 95% |
  | An AI-labelled PNG + "your bill is attached" | AMBER: 50%, but no money demand, so the guard caps it |

  These runs loaded the model in-process: the first voice note took about 60 s for the load, later notes about
  5 s. In the demo the forensics service loads the voice model when it starts (`scripts/demo_up.sh`), so no voice
  note waits for the load.

- **The 1B model was not measured.** It is stronger on Hindi in an independent benchmark, but the laptop is too slow
  for it, and the 1B test was dropped to save cost. Only the 500M recalibration ran on the GPU.

## 4. "You are digitally arrested": a rule, and an offline helper reader that stays off

- **Before.** A judge recorded "You are digitally arrested. You have to transfer all your bank account money to me.
  I am Prime Minister of India." It came out GREY. No law-enforcement body was named, so `R-AGENCY-PAY` could not
  fire; "arrested" was read only as a pressure cue, and pressure never counts.
- **Now: `R-DIGITAL-ARREST-PAY`** (F1, hard, the verified I4C advisory TAU/ADV/003: "There is no concept of Digital
  Arrest under any Indian Laws."). It fires when the message tells the customer she is under "digital arrest", a
  payment instruction was read, and no law-enforcement body is named (there `R-AGENCY-PAY` already says the same
  thing with the body's name). The words must be addressed to her: "you are (now) under digital arrest", "you have
  been digitally arrested", "we have placed you under digital arrest", "your digital arrest", "aap digital arrest
  mein hain", "आप डिजिटल अरेस्ट में हैं" (`prototype/satyapan/extract.py`, `digital_arrest_to_you`). A sentence
  that warns about it ("if anyone says you are under digital arrest"), denies it ("there is no such thing as
  digital arrest", "कोई भी एजेंसी आपको डिजिटल अरेस्ट नहीं करती") or quotes it does not count, because bank and I4C
  awareness messages use the same words. Alone it gives AMBER; it never makes a RED on its own.
- **Effect on the evaluation** (`docs/evaluation.md`): two in-scope scams that were GREY are now AMBER
  (V14-whatsapp-trnsfr and E-S29), so 77 of 79 are flagged (97.5%, was 94.9%); the 63 genuine messages are
  unchanged (none stopped, 7 asked to verify). The judge's message is AMBER, and the card's first reason reads
  "There is no “digital arrest” in Indian law. This message says you are under one and asks for a transfer to an
  account."
- **An offline helper reader, built and measured, OFF in the demo.** `prototype/satyapan/llm_reader.py` runs Meta's
  Llama 3.2 3B (Ollama, on the laptop; Llama 3.2 Community License; Built with Llama) after the rules-based
  extractor. It fills only what that extractor left empty without having seen a candidate, so the rules' deliberate
  choices (a reported claim, a negated request, two bodies at once) stand. Every field must quote the message's own
  words; a named agency can only become OTHER ("a government-sounding name"), so a model's guess can never reach a
  RED through the bank-record rules; it never fills a payee. Measured on the 156 messages: it caught no scam the rules missed (77 of 79 either way) and turned two genuine
  bank letters from AMBER to RED. One (V73) had its EMI order form, which the rules deliberately stopped reading as a
  demand on 19 Oct, read as a transfer; since then it fills no money request beside the bank's own name or a named
  body, and never a challan or tax. The same letter set also read differently between two runs (V72 was RED in the
  evaluation and AMBER on a re-run). A read takes a median of 23 s (60 s at most) on this laptop's CPU, which would
  hold up Run, so it stays off (`SATYAPAN_LLM_READER` unset in `scripts/demo_up.sh`).

