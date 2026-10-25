# Satyapan: the jury defence

For Aman and Bhawna to study before the finale slot on 25 Oct 2026, and to use in front of the jury. Every claim
carries its source file in brackets. Paths are relative to this repo; `raksham/` means the team's docs repo
(`raksham/docs/finale-runsheet.md`, `finale-qa.md`, `fact-check.md`, `since-round-1.md`, `track-decision.md`,
`concept-satyapan.md`, `disclosure.md`). Statistics about fraud come only from fact-check entries marked verified.

How the parts map to the rubric (weights from the organisers' Final Rubric.pdf, as briefed to the team; the PDF is not in this repo):

| Rubric line | Weight | Where to look here |
|---|---|---|
| Stage 1: working prototype | 25 | Part 2 (demo), 3.2 architecture |
| Stage 1: spot-check results and measured accuracy | 30 | 3.5 accuracy, Q1-Q5 |
| Stage 1: own engineering | 15 | 3.2 architecture, 3.3 models, 3.7 adversarial |
| Stage 1: alert and response flow | 15 | 3.2 (card, officer actions, pack), 3.6 safety |
| Stage 1: delivery vs Round 1 plan | 15 | 3.8 deployment (delivery table) |
| Stage 2: problem and user | 20 | 3.1 problem |
| Stage 2: deployability and scale | 15 | 3.8 deployment |
| Stage 2: communication and Q&A | 10 | Part 1 pitch, Part 4 questions |
| Stage 2: live user journey | 25 | Part 2 (demo), 3.6 (the genuine customer's path) |
| Stage 2: adversarial robustness | 20 | 3.7 adversarial |
| Stage 2: responsible AI and mistakes | 10 | 3.6 safety, Q6-Q9 |

Three things never to say: that the card calls anything fake (it never does; it does read one Hindi phrase about the caller's coaching, "इस धोखे का हिस्सा", part of this deception) [prototype/satyapan/card.py]; a catch
rate from memory (open the Evaluation page) [raksham/docs/finale-runsheet.md]; that the bank-record checks are live
(they are mocks; in the demo all seven outside look-ups carry the mock label on screen, the website one because it
replays recorded answers) [prototype/satyapan/adapters.py].

---

## Part 1. The 60-second pitch, word for word

> A customer walks into her branch to break her fixed deposits and send 38 lakh rupees by RTGS to a payee she
> has never paid before. A man claiming to be from the Enforcement Directorate has told her she is under "digital
> arrest" and must tell no one. The bank's own system already flags that transfer. Today the officer asks "are you
> sure?", and she says yes, because she was coached to.
>
> Satyapan is what the officer uses at that pause. It reads the voice note, video or notice she was sent.
> It checks the instruction against cited rules: there is no digital arrest under Indian law. It checks it against
> the bank's own records: did we send this, whose account is this. And it runs a calibrated deepfake check on the
> voice and the face. She hears up to three reasons she can check herself, in Hindi or English, and the card never
> calls anything fake. The officer decides, a red case needs a second person to release, and every case leaves a
> signed evidence pack.
>
> The amount reported for digital-arrest scams and related cyber crime rose from 91.14 crore rupees in 2022 to
> 1,935.51 crore in 2024. On deepfakes circulating in the wild, open detectors lose about half their AUC. So we
> verify the instruction, not just the pixels.

Sources: the flag and amount are the demo's own case (premature FD closure, RTGS to a first-time payee, Rs 38,00,000)
[scripts/build_demo_cases.py; prototype/data/fixtures/scenarios.json S3]; the flag, the officer's "are you sure?"
and the coached answer [raksham/docs/concept-satyapan.md]; the records checks [prototype/satyapan/adapters.py]; up to
three reasons in Hindi or English [prototype/satyapan/card.py]; the signed pack [prototype/satyapan/evidence.py]; no digital arrest in law [raksham/docs/fact-check.md A3]; co-sign for RED
[prototype/satyapan/pipeline.py `release_needs_co_sign`]; Rs 91.14 crore in 2022 to Rs 1,935.51 crore in 2024, amounts
reported for "digital arrest scams and related cyber crimes" [raksham/docs/fact-check.md S3, verified]; AUC fell 50%
(video), 48% (audio), 45% (image) on Deepfake-Eval-2024 [raksham/docs/fact-check.md T1, verified].

The pitch is for the opening or Q&A, not the demo beats: the run-sheet keeps statistics out of the demo itself
[raksham/docs/finale-runsheet.md]. If asked for the scale number's caveat: these are amounts reported on the national portal, not confirmed losses,
and the category is "digital arrest scams and related cyber crimes", not digital arrest alone
[raksham/docs/fact-check.md S3].

---

## Part 2. The live demo, beat by beat

The master plan is the 7-minute run-sheet: nine beats planned at 6:10 with 0:50 buffer, beat 6 cut first
[raksham/docs/finale-runsheet.md]. If the jury gives three minutes, run this cut; the cut and its clock are ours, not
the run-sheet's. Lines in quotes are the run-sheet's own, unless marked (new).

Before the slot, last and in this order: press "Reset the demo" twice, run `.venv/bin/python scripts/build_demo_cases.py`
(both lines must say OK and RED), check memory (`free -m`, at least 3 GB available), then open the Scenarios page. Do not reset again after this
[raksham/docs/finale-runsheet.md checklist].

| Clock | Beat | What the screen shows | Who clicks | Say |
|---|---|---|---|---|
| 0:00-0:15 | Frame | Scenarios page | Aman | Bhawna (new): "Banks already pause large unusual transfers; Satyapan is what the officer shows the customer in that pause. Everything you will see is synthetic or a public research sample." |
| 0:15-0:55 | RED on two checks plus a real voice clone (run-sheet beat 2) | the cloned-voice case: RED 80% (voice flagged "moderate" in the hi/whatsapp-opus cell [docs/overnight-report.md]; that is 90% for a RED pair plus 70% for a moderate band, halved each [prototype/satyapan/fusion.py]) | Aman opens it from Cases | Bhawna: "This voice note is a real voice clone and the voice check flags it; it counts half next to two independent checks on the message: Demo Bank never asks anyone to move money to a safe account, and the bank's own log shows it never sent this message." |
| 0:55-1:25 | The customer card, read aloud (beat 3) | card in हिंदी, Read aloud | Aman; both silent while it plays | Aman, after: "Everything she just heard she can check herself, and the card never uses the word fake." |
| 1:25-2:00 | Live face check on a real face swap (beat 4) | the face-swap case: RED 80%, face 0.955 "moderate", video/hd [docs/overnight-report.md] | Aman | Aman: "This video is a real face swap. The face check flags it, and it counts half in the combined score next to the instruction checks, which already found the rule and the bank's own records disagreeing with the message." |
| 2:00-2:25 | The negative control (beat 7) | S5a-genuine-bank-notice: MATCHES | Bhawna runs it | Bhawna: "A genuine bank SMS carries the bank's own signature and sits in its outbound log, so the system says MATCHES and proves it does not cry wolf." |
| 2:25-2:50 | The byte flip (beat 8) | evidence pack of the cloned-voice case: verifies, fails, verifies | Aman: Verify, Flip a byte, Restore | Aman: "The signed pack verifies, one flipped byte in the manifest makes the signature fail on screen, and restoring it verifies again, so this is what the officer hands to 1930." |
| 2:50-3:00 | Close (beat 9) | | nobody | Bhawna: "The officer decided, the customer heard three reasons in her own language, and every decision left a signed evidence pack." |

Cut from the three-minute version, kept for questions: beat 5, AMBER on a single verify-first signal
(S5c-ed-summons-1h-old), and beat 6, GREY is never called safe (S5b-real-rbi-advisory) [raksham/docs/finale-runsheet.md].
If a judge pushes on the invariant itself, S8-rbi-bond-no-payee shows one cited hard rule with no second family
staying AMBER, with the line "One rule alone never gives RED"; the run-sheet uses it in buffer time, and the
three-minute cut has none, so use it in Q&A [raksham/docs/finale-runsheet.md].

Disclosures to make if asked, in one line each:
- The beat-2 voice is IndicSynth Hindi (FreeVC voice conversion, CC-BY-NC-4.0), a lab recording, not any real
  person's voice; its words are a lab sentence and the RM's instruction came as WhatsApp text from the same number
  [raksham/docs/finale-runsheet.md; scripts/build_demo_cases.py].
- The beat-4 clip is a public research sample (UniDataPro, CC-BY-NC-ND-4.0), not a real official
  [raksham/docs/finale-runsheet.md].
- The face-swap clip (`clips/unidata/deepfake/2.mp4`) is one of the 2 HD face swaps in the accuracy table, scored
  0.955; it set no threshold, because fakes never set thresholds [raksham/docs/finale-runsheet.md;
  calibration/video_runs.csv; docs/accuracy.md]. The voice clone is an IndicSynth clip of the kind measured; we have
  not checked whether that exact clip is among the 60 Hindi fakes.
- Six of the seven outside look-ups are mocks; the website look-up replays real public registry answers recorded on
  23 Oct (and carries the mock label in the demo), so no check leaves the laptop [raksham/docs/finale-runsheet.md;
  prototype/satyapan/adapters.py].

If a judge hands over a file: Cases, Open a new case, Upload, pick the language. A voice note takes about 10-30 s, a
short video about 40-60 s, a notice image about 2 s for OCR. Still images get the document check only, never a face
check; say so if it is a face photo [raksham/docs/finale-runsheet.md].

Fallbacks: Wi-Fi dies, nothing changes. API dies: `scripts/demo_up.sh`, then rebuild the two cases; with no time, use
S1 from Scenarios (its media result is labelled Simulated) and drop "this voice note is a real voice clone". Console
dies: `satyapan demo --lang hi` in the terminal [raksham/docs/finale-runsheet.md].

---

## Part 3. The defence

Each item: what we used / why / what we considered instead / our evidence / its limits / say it in two sentences.

### 3.1 The problem and the user

The scam: someone poses as ED, CBI, police, a court, RBI or "your bank", and sends an official-looking voice note,
video or notice telling the customer to move money [prototype/PRODUCT.md]. In a digital arrest the victim is kept on a
video call, sent forged documents such as an "ED summons", told to tell no one and coached on a cover story for the
bank; then she breaks her FDs and sends the money by RTGS [raksham/docs/concept-satyapan.md]. The bank's controls often
flag that transfer, and today the officer has nothing that engages with the notice or the video
[raksham/docs/concept-satyapan.md].

**The user is the officer at the pause**
- What we used: the bank's fraud-response officer (a branch operations officer on a flagged counter request, or an
  FRMU analyst on a call-back); the customer is the protected person and never operates the console
  [prototype/PRODUCT.md].
- Why: a coached victim will not press a self-serve "verify" button, but she cannot move the money without passing
  through her bank [raksham/docs/concept-satyapan.md].
- Considered instead: citizen-facing concepts (a pay-screen nudge, a verify app, KinCheck) and a transaction-monitoring
  concept (ScamTrail). In our concept review Satyapan scored highest of nine (average 87.3) and three of four
  reviewers ranked it first [raksham/docs/track-decision.md].
- Evidence: RBI's Fraud Risk Management Directions, 2026 (RBI/DoS/2026-27/412) require transaction monitoring "on
  real-time basis or with a minimum time lag" [raksham/docs/fact-check.md R6, corrected wording]; the pause itself is
  becoming a formal duty through draft debit-hold directions proposed for 1 Apr 2027, which are draft today
  [docs/deployment-path.md]. Satyapan builds no monitoring of its own.
- Limits: that banks pause these transfers with an officer step is a stated assumption in our concept, and no
  interview with bank officers is recorded in our files [raksham/docs/concept-satyapan.md].
- Say it: "The victim is coached not to ask for help, but she cannot move the money without her bank. We give the
  officer at that pause something specific to show her."

**The threats: digital arrest, forged ED summons, cloned RM voice notes**
- What we used: demo scenarios S3 (a forged ED summons demanding Rs 38,00,000 into an "RBI supervision account"), S1
  (a Hindi voice note from "your RM Rohit": break your FD, move the money to a safe account) and S4 (claim-only, for
  when the chat was deleted) [prototype/data/fixtures/scenarios.json].
- Why: the instruction is impossible on its face. There is no "digital arrest" under Indian law
  [raksham/docs/fact-check.md A3]; ED summonses issued through its system carry a number and passcode that ED's site
  can check [raksham/docs/fact-check.md A1]; and only the bank can say "we never sent this" or "that is not our RM's
  registered phone" [prototype/data/fixtures/scenarios.json S1, S1b].
- Considered instead: the typical Track 3 entry, "upload, then % fake", which rests a verdict on one signal
  [raksham/docs/track-decision.md].
- Evidence: real cases in the fact-check register, for example a senior couple in Ambala coerced into transferring
  Rs 1,05,50,000 using forged Supreme Court orders and an ED "arrest order" [raksham/docs/fact-check.md L5].
- Limits: none of the famous digital-arrest cases is established as a deepfake; they were live impersonation and
  forged documents [raksham/docs/fact-check.md]. ED issues some summonses outside its system, so a missing passcode
  means "verify with ED", never "fake" [raksham/docs/fact-check.md A1].
- Say it: "Digital arrest does not exist in law, and a real ED summons can be checked on ED's own site. We check the
  instruction against that, whether the voice or face is real or not."

**Why pixel-only detection is not enough**
- What we used: the deepfake check counts as half of a combined score next to the instruction checks, and "unsure"
  counts as no media [README.md; prototype/satyapan/fusion.py].
- Why: on Deepfake-Eval-2024 the AUC of open-source detectors fell 50% (video), 48% (audio) and 45% (image) against
  earlier benchmarks [raksham/docs/fact-check.md T1]; people spotted speech deepfakes only 73% of the time in a
  529-person study [raksham/docs/fact-check.md T2].
- Considered instead: a detector-only verdict.
- Evidence: our own face check flags none of the 6 judged WhatsApp-size face-swap clips [docs/accuracy.md], which our
  video report calls consistent with that benchmark [calibration/video_report.md].
- Limits: if the attacker also avoids every rule (no money demand, an authority we have no rule for), the case is GREY
  [raksham/docs/finale-qa.md Q19].
- Say it: "Detectors decay in the wild and media gets deleted or re-encoded. The instruction does not decay."

**Scale, honestly**
- Verified figures only: Rs 91.14 crore (39,925 incidents) in 2022 to Rs 1,935.51 crore (1,23,672 incidents) in 2024
  for "digital arrest scams and related cyber crimes" [raksham/docs/fact-check.md S3]; in 2025 senior citizens filed
  1,03,488 financial-fraud complaints reporting Rs 4,005.12 crore [raksham/docs/fact-check.md S4].
- Limits: amounts reported, not confirmed losses; complaints, not distinct people [raksham/docs/fact-check.md S3, S4].
  If asked "isn't it falling?": our verified figures for this category stop at 2024; the register notes reports of a
  decline in complaints since then only as an additional finding under an entry that is not marked verified, so we do
  not quote a number for it [raksham/docs/fact-check.md R7]. Do not quote a "share of all fraud" figure either; the
  register does not verify one.
- Say it: "These are amounts reported, not confirmed losses. Our claim is narrow: where the money leaves through a
  flagged bank transfer, the pause is a place to stop it."

### 3.2 Architecture

```
Bank flag (paused transfer) -> open case -> consent C1 check / C2 report / C3 memory
  INTAKE   allow-list + magic-byte sniff, 100 MB cap, SHA-256 (perceptual hash for images)
  READ     audio/video: faster-whisper (Silero VAD first) | image/PDF: PDF text layer, else Tesseract (hin+eng or eng)
           text: as written | nothing shown: claim-only picklist
           -> rules-based extractor; every field must quote the message (offline LLM reader: built, shipped OFF)
  SIGNALS  F1 issuer rulebook | F2 bank's own records (labelled mocks) | F3 media forensics
           F4 campaign memory | F5 bank context / pressure cues (never a second family)
  FUSE     no judged media: rules ladder (RED = verified hard rule + independent second family)
           judged media:    0.5 x instruction % + 0.5 x deepfake %; RED >= 40, AMBER >= 15, else GREY
           always:          no RED without a money demand read (falls to AMBER)
  OUTPUT   officer view (reasons, quoted spans) | customer card (hi/en, no scores) | officer decision
           (release / hold / escalate / strike field / help report) | Ed25519-signed evidence pack
```
[prototype/satyapan/api.py; media.py; extract.py; models.py lines 226-231; fusion.py; card.py; pipeline.py; evidence.py]

**Reading the instruction**
- What we used: faster-whisper on CPU (int8; the demo script sets large-v3-turbo, beam 1), Silero VAD first; a PDF's
  own text layer, else Tesseract (`hin+eng` for a Hindi case, `eng` otherwise); then `RulesExtractor`, "regex + keyword lists for Hindi, English and
  Hinglish. Deterministic, offline, explainable", where `ground()` drops any field whose quote is not in the text
  [prototype/satyapan/media.py; scripts/demo_up.sh; prototype/satyapan/extract.py].
- Why: no extractor ever sets the verdict, and every reason the officer sees points at the customer's own words
  [prototype/satyapan/extract.py]. Matching runs on a normalised copy (zero-width characters, lookalike letters,
  leetspeak folded) mapped back to the original characters [prototype/satyapan/normalize.py].
- Considered instead: a Bedrock extractor, specified but not built (model access NOT_AUTHORIZED, 16 Oct)
  [prototype/satyapan/extract.py]; and the offline Llama reader, below.
- Evidence: prototype/tests/test_extract.py, test_grounded_clauses.py, test_ocr.py (renders the S3 summons as a
  synthetic PNG and reads it back with Tesseract), test_normalize.py.
- Limits: patterns miss wording they do not know (V13, a Devanagari RBI variant, is GREY) [docs/evaluation.md]; and
  "RBI safe account" scripts are GREY when the name look-up does not hold the account, because the issuer rule for
  them needs a verified quote and sign-off [docs/overnight-report.md, "Not done"]. Without the demo script the engine falls
  back to Whisper `small` [prototype/satyapan/media.py].
- Say it: "Whisper and Tesseract run on the laptop and turn media into text. A deterministic extractor reads who is
  claimed, what is asked and which payee, and every field must quote the message."

**The offline LLM reader, shipped OFF**
- What we used: Llama 3.2 3B through Ollama on 127.0.0.1, off unless `SATYAPAN_LLM_READER` names a model; the demo
  script exports it empty unless the shell already set it [prototype/satyapan/llm_reader.py; scripts/demo_up.sh]. (A
  stale comment in `llm_reader.py` says the script sets it; the script does not.)
- Why off: on the 156-message evaluation "it caught no scam the rules missed (77 of 79 either way) and turned two
  genuine bank letters from AMBER to RED"; V72 read differently between two runs; a read takes a median of 23 s
  (60 s at most) [docs/changes-2026-10-24.md; MODELS.md].
- Considered instead: letting it fill any field. It is now fenced: only fields the rules left empty, an authority only
  ever as OTHER, never a payee, never a verdict [prototype/satyapan/llm_reader.py].
- Evidence: prototype/tests/test_llm_reader.py (`test_the_reader_is_off_unless_switched_on`).
- Limits: it was measured, and the measurement said it does not help yet.
- Say it: "We built an offline LLM helper and measured it. It caught nothing extra, made two false REDs and was slow,
  so it ships off and we can show the numbers."

**Cited rules and bank-record checks**
- What we used: `prototype/data/rules/rulebook.yaml` version 1.7, 31 rules, each with a citation (source, URL, quote,
  date checked, sign-off); a hard rule whose citation is not verified is demoted to soft at load time
  [prototype/data/rules/rulebook.yaml; prototype/satyapan/rulebook.py]. All 31 are marked verified. The outside
  checks sit behind seven adapters (ED verify-summon, beneficiary name look-up, outbound communications log, which also
  holds the RM phones, ledger credits, I4C suspect registry, bank content signature, website registration look-up),
  each labelled with the production system it stands in for [prototype/satyapan/adapters.py].
- Why: compliance can sign off the YAML separately from the code [prototype/satyapan/rulebook.py].
- Considered instead: uncited heuristics; they can raise a soft signal but never anchor a RED
  [prototype/tests/test_demotion.py].
- Evidence: prototype/tests/test_rules.py, test_demotion.py (`test_demoted_rule_never_anchors_red`).
- Limits: six of seven look-ups are mocks with synthetic records (the name look-up holds 14 accounts and 12 UPI IDs;
  the crib's "a mock with four rows" is out of date) [prototype/data/mocks/name_lookup.json; raksham/docs/finale-qa.md
  Q16a].
- Say it: "Every hard rule quotes a primary source and is demoted if the citation is not verified. The bank-record
  checks are labelled mocks; three of them stand for read-only look-ups banks already run, such as the beneficiary
  name look-up."

**The 50/50 combined score**
- What we used, exactly [prototype/satyapan/fusion.py]:
  ```
  427  INSTRUCTION_WEIGHT = 0.5
  428  RED_LINE_PCT = 40
  429  AMBER_LINE_PCT = 15
  430  DEEPFAKE_PCT_BY_BAND = {"high": 100, "moderate": 70, "low": 30}
  473      c = INSTRUCTION_WEIGHT * i + (1 - INSTRUCTION_WEIGHT) * d
  ```
  The instruction % is 90 for a RED pair, 70 for one hard rule, 50 for two independent softs or one soft that
  escalates alone, 20 for a soft rule outside F5, else 0; unverified rules count 0 [prototype/satyapan/fusion.py lines
  447-461].
- Why: a cloned voice can now lift a weak instruction finding, and the deepfake % comes from the calibrated band,
  "never the raw model number: the 500M voice model gives many real Hindi voices a raw 0.99" [prototype/satyapan/fusion.py].
- Considered instead: the earlier policy, where media could raise a case to AMBER at most [docs/changes-2026-10-24.md].
- Evidence: worked examples 90 + 0 gives 45 (RED), 0 + 70 gives 35 (AMBER), 0 + 100 gives 50 (RED)
  [docs/changes-2026-10-24.md]; both live demo cases come out at 80%, that is 0.5 x 90 + 0.5 x 70
  [docs/overnight-report.md]; prototype/tests/test_forensics_combined.py.
- Limits: the weights and lines were set by Bhawna and agreed by the team on 24 Oct; no file shows them fitted to
  data [docs/changes-2026-10-24.md; MODELS.md]. One soft rule plus a false "moderate" voice flag gives 45%, RED if
  money was asked for; about 5% of real voices are flagged "moderate" by design. Document bands (an AI-tool label,
  edit traces) are not calibrated: an AI-tool label counts 100, and a real notice that was simply edited can count 70
  [docs/changes-2026-10-24.md].
- Say it: "With judged media the score is half the instruction checks and half the calibrated deepfake band; RED at
  40, AMBER at 15. Media the detector could not judge counts as no media, and the rules decide alone."

**The money-demand gate, abstention, and no green light**
- What we used: `_read_a_money_demand` must be true (a payment instruction, or a payee account, IFSC or UPI ID) for
  either path to give RED; otherwise it stops at AMBER [prototype/satyapan/fusion.py lines 360-376, 501-504]. The
  outcomes are RED, AMBER, GREY and MATCHES; there is no GREEN [prototype/satyapan/models.py]. Every GREY says "This is
  not a confirmation that the message is safe." [prototype/tests/test_grey_is_honest.py].
- Why: a judge pasted a genuine overdue-loan letter and the card told a real customer to stop
  [prototype/satyapan/fusion.py].
- Considered instead: a GREEN "looks genuine" outcome; rejected, because "no signs found" is not "genuine"
  [docs/architecture.md].
- Evidence: prototype/tests/test_no_red_without_money.py (`test_the_cap_never_makes_a_verdict_more_severe`),
  test_grey_is_honest.py, test_fusion.py (`test_empty_claim_is_grey_and_never_safe`).
- Limits: out-of-scope scams (lottery, jobs, family emergency) mostly stay GREY: 2 of 14 flagged [docs/evaluation.md].
- Say it: "No RED unless we actually read a demand for money. We have no green light: when we cannot confirm, we say
  so and send her to the official channel."

**The customer card, officer actions and the evidence pack**
- What we used: a card with up to three reasons, one thing to do, no score, in Hindi or English, linted against
  banned words in both languages [prototype/satyapan/card.py]. Officer decisions: release, hold, escalate, strike
  field, help report; releasing a RED (or a case that was RED before a strike) needs a co-signer who is a different
  person, compared after folding case, lookalike letters and invisible characters [prototype/satyapan/pipeline.py;
  prototype/satyapan/models.py]. The pack: canonical JSON, SHA-256, Ed25519 signature; verification trusts only the
  bank's key [prototype/satyapan/evidence.py].
- Why: the card is written for "a frightened 70-year-old" hearing it [prototype/satyapan/card.py]; the pack is what
  the officer hands to 1930 [raksham/docs/finale-runsheet.md beat 8].
- Considered instead: production signing with an AWS KMS key and S3 Object Lock; `KMSSigner` exists, the demo uses a
  local key [prototype/satyapan/evidence.py].
- Evidence: prototype/tests/test_card.py (`test_no_score_ever_reaches_the_customer`), test_four_eyes_identity.py,
  test_evidence.py (`test_one_flipped_signature_byte_fails`), test_evidence_trust.py
  (`test_pack_resigned_with_another_key_is_refused`).
- Limits: an AMBER release needs one officer, not two; staff names are typed, not authenticated; the demo key sits on
  the laptop [prototype/satyapan/pipeline.py; prototype/SECURITY.md (no authentication)].
- Say it: "The system decides nothing; one officer cannot release a RED alone. Every case ends in a signed record,
  and one flipped byte or a pack re-signed with another key fails verification."

### 3.3 Models

No model was trained or fine-tuned by us; no weights file is in the repo [MODELS.md]. The engineering is around the
models: thresholds per calibration cell set on genuine clips only, abstention with a reason, and use of the calibrated
band, never a raw score (document bands are the uncalibrated exception) [MODELS.md; forensics/common.py;
docs/changes-2026-10-24.md].

**GenD CLIP ViT-L/14 face check, with YuNet**
- What we used: YuNet finds the largest face per frame; GenD scores up to 16 aligned face frames; the median is the
  clip's score; it abstains on a face under 80 px, a face in under half the frames, fewer than 4 scored frames, or
  frames that disagree [forensics/video.py].
- Why: the strongest published cross-dataset results among the detectors we could run; YuNet (MIT) instead of GenD's
  own InsightFace detector, which is research-only [MODELS.md; forensics/video.py].
- Considered instead: a DFDC-trained model, no longer used [docs/status.md].
- Evidence: video/hd: 38 genuine judged, held-out false alarms 2.9%, AUC 0.974, 1 of 2 face swaps flagged; video/sd
  (480 px or less): 26 genuine judged, 4.0%, AUC 0.872, 0 of 6 flagged (5 unsure, 1 missed); 66 of 138 clips declined
  [docs/accuracy.md; calibration/video_report.md].
- Licence: code and weights MIT, YuNet MIT; the weights were trained by their authors on FaceForensics++, which has
  non-commercial research terms; we never download FF++ [MODELS.md].
- Limits: two HD face swaps is "an anecdote, not a measurement"; no 1% line, so a face flag is at most "moderate"
  (35% alone, AMBER); still images are not face-checked [docs/accuracy.md; README.md].
- Say it: "GenD is an off-the-shelf MIT face-forgery detector calibrated on genuine video (Commons clips plus the UniDataPro genuine clips). It is
  useful on HD, nearly blind on WhatsApp-size video, and so it can never push a case past AMBER alone."

**DF Arena 500M voice check**
- What we used: energy-based speech detection, up to 3 windows of about 4 s, median score; abstains under 2 s of
  speech or when windows disagree [forensics/audio.py].
- Why: it replaced AASIST-L, which is near chance on real circulated fakes [prototype/satyapan/forensics.py].
- Considered instead: DF Arena 1B, stronger on Hindi in an independent benchmark (LRLspoof: 93.66% of Hindi fakes
  caught against 6.59% for the 500M), but on the 7.3 GB team laptop it takes about 14 s per window and over 3 minutes to
  load [MODELS.md].
- Evidence: per channel at the 5% line, Hindi 57 of 60 clean, 52 of 60 WhatsApp-like, 49 of 60 phone; English 97, 95
  and 96 of 98; held-out false alarms 3.6% to 4.5% [docs/accuracy.md]. About 2.2 s per window on the laptop
  [MODELS.md].
- Licence: custom non-commercial licence, used for this non-commercial prototype only [MODELS.md].
- Limits: voice conversion (FreeVC) is harder than text to speech: 20 of 31 FreeVC clones caught on Hindi phone audio
  against 29 of 29 XTTS; a voice replayed through a speaker becomes "unsure" [docs/accuracy.md].
- Say it: "DF Arena 500M catches most lab-made Hindi clones and circulated English fakes with at most about 4.5% of
  held-out real voices flagged. It is weaker on voice conversion and replay, and it is non-commercial."

**Whisper large-v3-turbo via faster-whisper**
- What we used: local CPU speech-to-text, int8, beam 1 in the demo [scripts/demo_up.sh; prototype/satyapan/media.py].
- Why: on 8 FLEURS Hindi clips, word error rate 33.0% against 61.7% for `small`, at 25.4 s against 22.2 s per clip
  [calibration/whisper_eval_fast.md].
- Considered instead: `small` (above); with beam 5 on 12 clips turbo gave 26.7% but at 62.8 s per clip,
  a pessimistic time measured while video calibration was running [calibration/whisper_eval.md].
- Licence: MIT [MODELS.md].
- Limits: about one word in three wrong on read Hindi; 34.0% after WhatsApp-like Opus; Hinglish not measured
  [calibration/whisper_eval_fast.md].
- Say it: "Whisper turbo halves the Hindi word errors of the small model at about the same speed on the laptop. It
  still gets a third of words wrong, so every reason quotes the transcript and the officer can correct it."

**Tesseract, pytesseract and PyMuPDF**
- What we used: PyMuPDF reads a PDF's text layer; Tesseract `hin+eng` reads images and text-less pages; photos are
  turned upright by their EXIF tag [prototype/satyapan/media.py; docs/overnight-report.md].
- Why: local, so OCR needs no network [raksham/docs/finale-qa.md Q13].
- Considered instead: Amazon Textract as the named production route, not wired [prototype/satyapan/media.py].
- Licence: Tesseract Apache-2.0 [MODELS.md]; PyMuPDF AGPL-3.0 or a commercial Artifex licence
  [raksham/docs/disclosure.md].
- Limits: the Hindi+English model can misread Latin digits in an English notice; no character error rate measured
  [raksham/docs/finale-runsheet.md].
- Say it: "Tesseract with Hindi data reads notices on the laptop in about two seconds. A bank would buy PyMuPDF's
  commercial licence or swap the PDF reader."

**The rest, one line each**
- AASIST-L: MIT, older in-process fallback, not installed on the demo laptop; calibrated for false alarms only on 150
  genuine FLEURS clips per language and channel [MODELS.md; prototype/data/forensics/aasist_calibration.json].
- paraphrase-multilingual-MiniLM-L12-v2 (meaning-level campaign memory, soft only): Apache-2.0, threshold 0.72 set
  just above the highest non-copy, caught 8 of 14 reworded copies; not installed on the demo laptop, so the demo skips
  it [MODELS.md; prototype/data/eval/memory_calibration.json].
- Ed25519 (evidence pack): the demo stand-in for an AWS KMS key [prototype/satyapan/evidence.py].
- Llama 3.2 3B: above, shipped OFF.

### 3.4 Data

**Public clips: calibration and measurement only, never training**
- What we used: Wikimedia Commons genuine video (59 clips, each file's own open licence, all listed with author and
  link in `calibration/sources_commons.csv`); the UniDataPro face-swap sample (5 genuine plus 5 face-swapped,
  CC-BY-NC-ND-4.0); In-the-Wild English (150 real plus 150 fake, CC-BY-SA-4.0 on Hugging Face); Google FLEURS Hindi
  (120 clips, CC-BY-4.0); Gram Vaani real Hindi phone calls (OpenSLR 118, free for academic use); IndicSynth Hindi
  clones (60 clips, CC-BY-NC-4.0) [README.md; calibration/sources_commons.csv].
- Why: thresholds are set on genuine clips only; fakes never set a threshold; false alarms are reported held out by
  5-fold cross-validation [docs/accuracy.md].
- Considered instead: DFDC (competition closed) and Kathbath (gated), not used; Deepfake-Eval-2024 requested, still
  awaiting the authors' approval, not used [docs/status.md].
- Evidence: every clip used is listed by hash in `calibration/*_runs.csv`; clips stay in `clips/`, never committed
  [README.md].
- Limits: our fakes are lab-made or celebrity fakes; no public Indian scam-call audio or video exists to test on
  [docs/accuracy.md]. The WhatsApp and phone copies are simulated; phone-to-phone forwards were planned and not done
  [README.md]. IndicSynth, UniDataPro and Gram Vaani are non-commercial or academic-only.
- Say it: "Public clips only set thresholds and measure accuracy; nothing is trained on them. Every clip is
  attributed, and only numbers reach the repo."

**Synthetic text data, written with Claude**
- What we used: 22 scenarios, 73 variants, 64 labelled messages and 14 reworded copies, plus 8 mock bank-record files
  [synthetic/README.md]. They were written with Claude, not generated by code, with invented names and numbers
  [synthetic/README.md; raksham/docs/disclosure.md].
- Why: there is no field data, and real customer messages would raise consent and privacy problems.
- Considered instead: no alternative is recorded. The variants include judges' own probes from 18 Oct (V34-V42, with
  8 benign twins) and 19 Oct (V62-V65, with 3 benign twins) [prototype/data/fixtures/variants.json].
- Evidence: `python synthetic/validate_fixtures.py` checks every file parses and every IFSC, account, UPI ID and phone
  number is visibly invented [synthetic/validate_fixtures.py].
- Limits: the validator reports what it finds: three IFSCs use real bank prefixes (SBIN0004321, HDFC0000213,
  SBIN0000691) with branch codes we did not check [synthetic/README.md]. The one real record set is `web_registry.json`: public RDAP answers for 16 domains, recorded on 23 Oct
  [prototype/data/mocks/web_registry.json].
- Say it: "Every message in our evaluation was written for the repo and labelled by what it really is. Our own
  validator shows the exceptions instead of hiding them."

**Synthetic media we made, and the code that made it**
- What we used: notice images drawn as plain text with a SYNTHETIC watermark, no logo or official's name; the test
  voice note read by Windows' stock "Microsoft David Desktop" voice; the format-test files from synthetic inputs
  [synthetic/README.md].
- Why: the hackathon asks for the code that generated synthetic data (as briefed to the team); `synthetic/` reproduces each one. The S3
  notice image comes out byte-identical to the file the demo used [synthetic/README.md].
- Considered instead: teammate voice clones; not made, so no consent question arose [raksham/docs/since-round-1.md].
- Limits: the text-to-speech step needs Windows PowerShell or espeak-ng; the workbox has neither, so only the encoding
  step was run there [synthetic/README.md].
- Say it: "No real person's voice, face, emblem or name is in anything we generated. The generators are in the repo
  and our tests run them."

### 3.5 Accuracy

There are two kinds of number, and we never mix them [docs/evaluation.md; docs/accuracy.md].

**The whole engine on a labelled synthetic set**
- What we used: `satyapan evaluate` over 156 messages (22 scenarios, 73 variants, 64 labelled messages, with 3 left
  out because their legitimacy is not in the text) [prototype/data/eval/results.json].
- Evidence: in-scope scams 79: 34 RED, 43 AMBER, 2 GREY (97.5% flagged). Genuine 63: 0 RED, 7 AMBER, 50 GREY,
  6 MATCHES (0 stopped, 11.1% asked to verify). Out-of-scope scams 14: 2 flagged [prototype/data/eval/results.json].
- Why: a regression guard; the suite fails if any genuine message turns RED [prototype/tests/test_evaluation.py].
- Considered instead: field data, which does not exist yet.
- Limits: synthetic, written by us, and it helped find fixes, so it is optimistic [prototype/README.md]; the run had no
  media detector loaded [docs/evaluation.md]. "0 stopped" is narrower than it sounds: a genuine bank recovery letter
  with an account number still comes out RED, pinned as a strict xfail
  [prototype/tests/test_bank_order_is_not_a_demand.py].
- Say it: "On 156 synthetic messages we wrote, 77 of 79 in-scope scams were flagged and no genuine message was
  stopped. It is our own set, so treat it as a regression guard, not field accuracy."

**Face and voice checks per kind of input** [docs/accuracy.md]

| Check, cell | Genuine judged | Held-out false alarms | Fakes judged | Caught | Unsure | Missed |
|---|---|---|---|---|---|---|
| face, HD video | 38 | 2.9% | 2 | 1 | 1 | 0 |
| face, WhatsApp-size video (480 px or less) | 26 | 4.0% | 6 | 0 | 5 | 1 |
| voice, English clean | 92 | 4.0% | 98 | 97 | 0 | 1 |
| voice, English 8 kHz phone (simulated) | 89 | 4.3% | 98 | 96 | 1 | 1 |
| voice, English WhatsApp-like Opus (simulated) | 88 | 4.2% | 98 | 95 | 2 | 1 |
| voice, Hindi clean | 81 | 4.5% | 60 | 57 | 3 | 0 |
| voice, Hindi 8 kHz phone (FLEURS simulated + Gram Vaani real) | 198 | 4.3% | 60 | 49 | 9 | 2 |
| voice, Hindi WhatsApp-like Opus (simulated) | 69 | 3.6% | 60 | 52 | 7 | 1 |
| still image | not face-checked; document check only | | | | | |

The face-swap rows come from one vendor sample: 5 distinct face swaps. The 6 judged WhatsApp-size clips are 2
low-resolution originals plus 4 simulated WhatsApp copies of the same swaps [calibration/video_runs.csv].

- Limits: 52 of 150 English fakes were declined in every English cell, so catch rates count only fakes the detector
  judged [docs/accuracy.md]. The named failure cases are on the Evaluation page: WhatsApp-size video, 66 of 138 clips
  declined, only 2 HD face swaps, stills not face-checked, re-filmed screens, under 2 s of speech, voice conversion,
  replay, high raw scores on genuine Hindi, and no real Indian scam media [docs/accuracy.md].

**The live pipeline check**
- What we used: `scripts/pipeline_check.py` sends 12 voice and video cases through the running engine and both
  detectors [scripts/pipeline_check.py].
- Evidence: 12 of 12 PASS on the night before the finale [docs/overnight-report.md].
- Limits: it shows the pipeline works end to end, not how often it is right; some clips were also calibration clips
  [scripts/pipeline_check.py].

**"How accurate is it?" in 20 seconds**

> Two answers, both on the Evaluation page. On 156 synthetic messages we wrote, 77 of 79 in-scope scams were flagged
> and none of 63 genuine messages was stopped; it is our own set, so it is optimistic. The face and voice checks were
> measured on public clips: on genuine clips that never set the threshold, 2.9 to 4.5 percent are wrongly flagged.
> The voice check catches 49 to 57 of 60 Hindi clones depending on the channel. The face check is weak on WhatsApp
> video, which is why the instruction checks lead.

[docs/evaluation.md; docs/accuracy.md; raksham/docs/finale-qa.md Q18]

### 3.6 Safety and responsible AI

**A genuine customer flagged by mistake: what she goes through**
1. The bank's own monitoring pauses her transfer; Satyapan builds no monitoring [prototype/PRODUCT.md].
2. The officer reads the consent aloud: C1 check this message, C2 include it in a report, C3 add its fingerprint to
   campaign memory. Without C1 the server refuses to run the case [prototype/satyapan/api.py;
   prototype/tests/test_consent_enforced.py].
3. She shows what she received, or the officer ticks what she was told (claim-only) [prototype/PRODUCT.md].
4. The engine takes milliseconds; the whole counter flow is about ten seconds [raksham/docs/finale-qa.md Q17].
5. On our labelled set the worst a genuine message got was AMBER: 7 of 63 [docs/evaluation.md]. The AMBER card says
   "Verify before paying" and "Please wait before paying."; she never sees a score [prototype/satyapan/fusion.py;
   prototype/satyapan/card.py; prototype/tests/test_card.py].
6. If the engine misread a field, the officer strikes it and the rules re-run [prototype/PRODUCT.md].
7. She makes one call to the real RM or checks the issuer's site, and the officer releases. An AMBER release takes one
   officer; a RED release needs a second person; "so the delay is as long as that call" [raksham/docs/finale-qa.md Q20;
   prototype/satyapan/pipeline.py].

**Human in the loop, no automatic blocking**
- What we used: five recorded human decisions; the code says "nothing here acts on its own"; mandatory FRMU review
  triggers for large amounts, claim-only on a large amount, forensics flagging with no rule, and any RED release
  [prototype/satyapan/pipeline.py].
- Why: the brief's constraint: never auto-block or accuse on a single weak signal, and a human reviews before any
  high-impact action [prototype/CLAUDE.md].
- Considered instead: an automatic hold at RED; the hold stays a decision under bank policy [prototype/PRODUCT.md].
- Evidence: prototype/tests/test_evidence.py (`test_release_of_red_needs_co_sign`).
- Limits: decision names are typed, not authenticated; cases live in memory with no login, acceptable only for a
  single-laptop demo [prototype/SECURITY.md].
- Say it: "Satyapan never holds or blocks money by itself. Every hold, release and escalation is a named officer's
  decision."

**The card never says fake or fraud**
- What we used: `lint_card` checks every customer-facing field against a banned list in English (fake, genuine,
  fraud, scam, criminal, liar) and Hindi, on every card [prototype/satyapan/card.py].
- Why: a verdict word on a genuine message accuses a real customer; MATCHES only says "We sent this message
  ourselves", a provenance claim [prototype/satyapan/card.py; prototype/tests/test_card.py].
- Considered instead: a "genuine" outcome; rejected (above).
- Evidence: prototype/tests/test_card.py, test_card_reads_aloud.py (`test_every_scenario_card_passes_the_widened_lint`).
- Limits: one Hindi phrase about the caller's coaching ("इस धोखे का हिस्सा", "part of this deception") is deliberately
  allowed, and identifiers quoted from her message are masked from the lint, so a scammer's link with "fraud" in it can
  still appear [prototype/satyapan/card.py].
- Say it: "A test lints every card in both languages against fake, fraud and genuine, with one Hindi phrase about the
  caller's coaching allowed. On our labelled set the worst a genuine customer heard was: please wait before paying."

**Consent, privacy, and the legal basis**
- What we used: C1 gates a run, C2 gates "help the customer report", C3 gates campaign memory, each refused by the
  server (403) without it [prototype/satyapan/api.py; prototype/tests/test_consent_enforced.py]. Every check in the demo
  runs on the laptop; the one exception is Read aloud, which uses the browser's voices, some of them remote
  [raksham/docs/finale-qa.md Q13]. Campaign memory stores message wording (up to 600 characters),
  money-trail slots and file hashes, never the files; an entry counts only after two different analysts confirm it and
  expires after 90 days [prototype/satyapan/memory.py].
- Why: before the overnight fix, C2 was recorded and never read [prototype/tests/test_consent_enforced.py].
- Legal basis: the bank's duties under RBI's Fraud Risk Management Directions, 2026 [raksham/docs/finale-qa.md Q5]. The
  DPDP Act's consent and security sections come into force around 13 May 2027 (G.S.R. 843(E)); MeitY consulted on
  shortening that, so re-check; some DPDP Rules are already in force or start on 13 Nov 2026. So we say "designed to
  support", never "compliant" [raksham/docs/fact-check.md L1, L1-rules].
- Limits: the server checks the recorded consent flags; it cannot know what she understood. Campaign memory wording
  can include account and phone numbers [prototype/satyapan/memory.py]. The only deletion of uploads we have is the
  demo reset; no retention period is set [raksham/docs/finale-qa.md Q20; prototype/satyapan/api.py].
- Say it: "The server itself refuses to check a message without consent. Today we rest on the bank's FRM duties; DPDP's
  consent duties start around May 2027 and the flow is designed for them."

### 3.7 Adversarial robustness

Our position: the deepfake checks can be evaded, and the Evaluation page says how. Evasion makes them say "unsure",
which counts as no media, and the instruction checks then decide alone. The money still has to go somewhere, and
that account has to survive the issuer's rules and the bank's records [raksham/docs/finale-qa.md Q19;
docs/changes-2026-10-24.md].

| Attack | What Satyapan does | Pinned by | What it still misses |
|---|---|---|---|
| WhatsApp-compressed cloned voice | per-channel thresholds, channel read from the codec | 52 of 60 Hindi WhatsApp-like clones caught [docs/accuracy.md]; tests/test_audio.py | copies are simulated; no real Indian scam audio |
| WhatsApp-compressed face swap | abstains or flags only above 0.97 | 0 of 6 flagged [docs/accuracy.md] | the face check is nearly blind on forwards |
| Replay through a speaker at the counter | a "clean" voice result becomes "unsure"; a flag still counts | tests/test_audio.py (`test_live_replay_never_says_clean_but_still_flags`) | known only when recorded at the counter; no replay calibration |
| Voice conversion instead of TTS | same calibrated bands | FreeVC 20 of 31 on Hindi phone audio [docs/accuracy.md] | about a third get through on phone audio |
| Very short speech, or a still image | abstains under 2 s; stills get the document check only | tests/test_audio.py (`test_a_short_clip_abstains`) | no media verdict, by design |
| Rewording, euphemisms, Hinglish, Devanagari | widened verb families that count only when pointed at a destination | prototype/tests/test_euphemism_bounds.py, test_normalize.py | a new euphemism not in the tables; V13 (Devanagari RBI variant) still GREY [docs/evaluation.md] |
| Homoglyphs, zero-width spaces, leetspeak | normalised copy with an offset map | prototype/tests/test_normalize.py | only listed lookalikes are folded |
| Prompt injection, fake tool output | no LLM sets a verdict; the issuer is chosen by anchor strength, not position | prototype/tests/test_injection_steering.py; S5d in test_scenarios.py | covers the steering pattern we found |
| Lookalike or invisible co-signer name | identity key folds case, lookalikes, invisibles; a blank-looking name is nobody | prototype/tests/test_four_eyes_identity.py, test_invisible_names.py | names typed, not authenticated |
| Strike a field, then release a RED alone | a was-RED case still needs a co-sign | test_four_eyes_identity.py (`test_a_strike_does_not_let_one_officer_release_a_red_alone`) | none found |
| Tamper with the pack and re-sign it | verifies only against the bank's own key | prototype/tests/test_evidence_trust.py | demo key is a local file |
| Copy-paste a real notice with a swapped account | judged by where the money goes | prototype/tests/test_copy_paste_notices.py | stops at AMBER when the name look-up lacks the account [raksham/docs/finale-qa.md Q16a] |

**What the overnight bug hunt fixed**
- What we used: an adversarial bug hunt on 24-25 Oct: 36 verified findings; the engine suite went from 1055 to 1293
  passing tests; 0 server errors under API fuzzing; an 86-message before/after probe came out 25 better, 0 worse
  [docs/overnight-report.md].
- Why: every hole found becomes a regression test (four-eyes, consent C2, re-signed packs, Devanagari bank names)
  [docs/overnight-report.md].
- Considered instead: leaving fixes undocumented; instead the gaps that remain are named, below.
- Evidence: prototype/tests/test_overnight_probe.py, test_evidence_trust.py, test_four_eyes_identity.py,
  test_consent_enforced.py.
- Limits, still open: a genuine bank recovery letter with an account number comes out RED (strict xfail); "RBI safe
  account" and "pay a refundable fee under RBI review" scripts are GREY when the look-up lacks the account, because the
  fix needs a verified issuer quote and sign-off [prototype/tests/test_bank_order_is_not_a_demand.py;
  docs/overnight-report.md].
- Say it: "We attacked our own system overnight and fixed what we found, each with a test. What is still open is
  written down, and we will show you."

**What we would change next**: measure on Deepfake-Eval-2024 once access comes; calibrate a replay setting and a
still-image face check; turn each evasion a pilot finds into a cited rule [raksham/docs/finale-qa.md Q19]; add the
"RBI safe account" rule once its citation is verified [docs/overnight-report.md].

### 3.8 Deployment, scale and delivery

**How a bank runs it**
- What we used: a step after the bank's existing flag and before release, owned by the FRMU [docs/deployment-path.md].
  Seven adapters, each with a label naming its production source, owner and route, shown on screen through
  `GET /api/meta`: ED verify-summon, beneficiary name look-up, outbound communications log, ledger credits, I4C suspect
  registry, bank content signature, website registration look-up [prototype/satyapan/adapters.py;
  docs/deployment-path.md].
- Why: integration is one adapter at a time, and nobody can mistake a mock for a live look-up.
- Considered instead: a citizen WhatsApp bot, designed and not built; without bank records more cases would end GREY
  [docs/architecture.md].
- Evidence: name look-up is mandatory for RTGS/NEFT under RBI/2024-25/99, and banks already receive the I4C registry
  feed [docs/deployment-path.md].
- Limits: ED's page has a CAPTCHA and no API, so that check starts as a guided manual step; the bank content signature
  is a new build [docs/deployment-path.md]. Cases are in memory with no login [prototype/SECURITY.md].
- Say it: "Each outside system is one labelled adapter naming its owner and production route. A bank swaps them one
  at a time, starting with look-ups it already runs."

**The pilot path, and cost honesty**
- What we used: shadow mode beside the existing call-back (no customer impact; measure agreement with officers and time
  to verdict), then one branch cluster with the FRMU (success is the share of flagged customers who stop and verify,
  next to false holds and complaints), then FRMU-wide [docs/deployment-path.md].
- Evidence on cost: the demo runs on the team laptop's CPU (7.3 GB, Ryzen 5 5500U) with no paid API at demo time
  [MODELS.md]; the voice calibration itself was scored on an AWS GPU [calibration/audio_report.md]. A voice note takes about
  10-30 s, a short video about 40-60 s, a one-minute 1080p video about 2.5 minutes [raksham/docs/finale-runsheet.md];
  repeated files are reused by content hash [raksham/docs/finale-runsheet.md].
- Limits: no file costs a deployment per case or per branch, and there is no load test; we say so.
- Licences that block production: DF Arena is non-commercial; GenD's training data has non-commercial research
  terms; PyMuPDF is AGPL or commercial; IndicSynth, UniDataPro and Gram Vaani are non-commercial or academic
  [MODELS.md; README.md; raksham/docs/disclosure.md]. The detectors sit behind one result contract, so a licensed model
  plus re-calibration would replace one without touching the engine (our reading of the design) [forensics/common.py].
- Say it: "Load follows the hold queue, not every payment. We have not costed a bank deployment and will not guess;
  shadow mode measures it."

**Delivery against the Round 1 plan** [raksham/docs/since-round-1.md]

| Round 1 said | What we delivered | Gap |
|---|---|---|
| No face-swap model | GenD face check, calibrated on HD and WhatsApp-size video | one vendor sample: 5 distinct face swaps (2 judged HD, 6 judged WhatsApp-size clips) |
| Voice note plus audio forensics | DF Arena 500M per language and channel; Whisper on the laptop | a different model from the deck's AASIST-L |
| Never cut: S1, S3, S4, evidence pack | all ship with tested verdicts; the pack fails on one byte | none |
| Metrics board | Evaluation page with measured face and voice accuracy | the message set is synthetic |
| Report pre-fills | "Help the customer report" routing panel | no form is pre-filled |
| Clip of the real ED page | not in the demo | dropped |
| Teammate voice clones, own consented clips | not made; public labelled sets instead | by choice |
| Citizen bot | designed, not built | not built |
| Live WhatsApp / 8 kHz squashing on stage | the S1 re-encode step works, with scripted (SIMULATED) forensics | not the real detector |
| S2 RBI video | shipped as a transcript | no video file |
| H48 backup video | not recorded at the time; a 57.3 s video was made overnight [docs/overnight-report.md] | late |
| Face check on still images | not built | stills get the document check only |

---

## Part 4. The 20 hardest questions

1. **"You wrote the evaluation set and fixed the engine on it. Isn't 97.5% circular?"** Partly, yes. It is synthetic,
   it helped find fixes, and our own README calls it optimistic; we use it as a regression guard. The held-out numbers
   are the detectors' false alarms [prototype/README.md; docs/accuracy.md].
2. **"Did the evaluation include your deepfake detectors?"** No. That run had no media detector loaded; the detectors
   are measured separately on public clips, and the joined system passed a 12-case live check, which shows it works,
   not how accurate it is [docs/evaluation.md; scripts/pipeline_check.py].
3. **"Your face check caught zero of six WhatsApp face swaps. Is it useless?"** (Six judged clips of five swaps from one vendor sample.) On WhatsApp-size video, mostly, and we
   say so on screen. That is why a face flag is at most "moderate" (35% alone, AMBER) and "unsure" counts as no media
   [docs/accuracy.md; README.md].
4. **"Two HD face swaps is not a measurement."** Agreed, and our docs use those words. Deepfake-Eval-2024 access is
   requested and still pending [docs/accuracy.md; docs/status.md].
5. **"MODELS.md says the 500M catches 6.59% of Hindi fakes on LRLspoof, yet you report 87%."** Different benchmarks.
   Ours is at our thresholds against IndicSynth lab clones (49 to 57 of 60 per channel); LRLspoof is independent, and
   we quote it ourselves as the reason the 1B is better on a bigger machine. Real-world catch rates may be lower than
   ours [MODELS.md; docs/accuracy.md].
6. **"A 4% false-alarm rate at bank scale wrongly flags a lot of people."** It only sees transfers the bank already
   paused, and a face or voice flag alone is AMBER except in Hindi phone audio, the one cell with a 1% line for "high".
   AMBER asks her to verify; it blocks nothing, and the officer decides [README.md; docs/deployment-path.md].
7. **"A genuine customer is flagged. What happens and how fast?"** The worst on our labelled set is AMBER (7 of 63 genuine): she
   hears "please wait before paying", makes one call, and one officer releases; the delay is that call. We have no
   pilot data on real false holds, and a genuine bank recovery letter with an account number is a known false RED
   (pinned as a strict xfail) [prototype/tests/test_bank_order_is_not_a_demand.py; docs/evaluation.md; raksham/docs/finale-qa.md Q20].
8. **"Does the card really never say fraud?"** The lint runs on every card in both languages. One Hindi phrase about
   the caller's coaching is deliberately allowed, and a scammer's own link quoted from her message is not censored
   [prototype/satyapan/card.py].
9. **"Is this DPDP compliant?"** We do not claim that. Those sections come into force on 13 May 2027; our basis today
   is the bank's duties under the RBI FRM Directions, 2026 [raksham/docs/fact-check.md L1; raksham/docs/finale-qa.md Q5].
10. **"What is real and what is mocked?"** Real and running: speech-to-text, OCR, the extractor, the rules, the face
    and voice checks on uploaded media, the fusion, the card and the signed pack. The scripted scenarios on the
    Scenarios page use SIMULATED forensics and say so. Mocked: six of seven bank and agency look-ups; the seventh
    replays recorded real registry answers, and in the demo the screen labels all seven as mocks
    [raksham/docs/finale-qa.md Q3; prototype/satyapan/adapters.py].
11. **"Your flagship RED rests on a mock look-up table."** True, and the screen labels it a mock (it holds 14
    synthetic accounts and 12 UPI IDs) [prototype/data/mocks/name_lookup.json]. The real
    facility, beneficiary name look-up, is mandatory for RTGS/NEFT, so a bank already has it
    [raksham/docs/finale-qa.md Q16a; docs/deployment-path.md].
12. **"Where is the AI? Your extractor is regex."** The AI is Whisper, the GenD face check and the DF Arena voice check,
    all local. We built and measured an LLM reader and switched it off: no extra catches, two false REDs, 23 s a read
    [MODELS.md; docs/changes-2026-10-24.md].
13. **"Can a deepfake alone give RED?"** Yes, since 24 Oct, and only with a money demand read: a "high" voice flag
    (50%) where a cell has a 1% line (Hindi phone audio), or a document whose metadata names an AI tool (band "high",
    uncalibrated). Elsewhere a face or voice flag alone is 35%, AMBER [README.md; docs/changes-2026-10-24.md;
    prototype/satyapan/forensics.py].
14. **"Why 50/50, and why 40%?"** Set by Bhawna and agreed by the team on 24 Oct; no file shows it fitted to
    data, and the voice and face bands under it are calibrated. We don't know the best weights yet; a pilot would tell
    us [docs/changes-2026-10-24.md; MODELS.md].
15. **"What happens when scammers learn your rulebook?"** The rules encode what an institution never does, not wording: RBI
    gives no investment advice, ED summonses carry a passcode its own site can check, no "digital arrest" exists in
    Indian law. A scammer who stops demanding money into an account the institution would never use has stopped the
    theft [raksham/docs/finale-qa.md Q6]. Rewording within a known campaign relies on the
    meaning memory, which is not installed on the demo laptop [MODELS.md].
16. **"I play your cloned voice through a speaker at the counter."** If the officer records it at the counter, a "no
    signs" result becomes "unsure", but a flag still counts. The same bytes forwarded as a file are judged as an ordinary
    file; we have no replay calibration yet [tests/test_audio.py; prototype/satyapan/pipeline.py; docs/accuracy.md].
17. **"Can one officer release a RED alone?"** Not by striking a field first, and not with a lookalike or invisible
    co-signer name; tests pin both. Staff names are typed, though, and the prototype has no login
    [prototype/tests/test_four_eyes_identity.py; prototype/satyapan/pipeline.py; prototype/SECURITY.md].
18. **"Can a bank deploy this tomorrow?"** No. Six of seven integrations are mocks, cases live in memory with no login,
    and the voice detector is non-commercial. What is ready is the boundary: each mock names its production system,
    and the pilot starts in shadow mode [docs/deployment-path.md; prototype/SECURITY.md; MODELS.md].
19. **"What does it cost per branch?"** We don't know; we have not measured it. The demo runs on a 7.3 GB CPU laptop with
    no paid API, and a voice note takes 10-30 s [MODELS.md; raksham/docs/finale-runsheet.md].
20. **"Have you talked to a bank officer? Will a coached victim even show you the media?"** No interview is recorded in
    our files; it is a stated assumption. We don't know what share will show it; claim-only mode covers those who refuse or deleted it, and the
    hold rests on bank policy, not her cooperation [raksham/docs/concept-satyapan.md; prototype/PRODUCT.md].

---

## Part 5. The plan for today and after

**Today** [raksham/docs/finale-runsheet.md]
- Earlier in the day, once: the engine tests are green.
- In the hour before the slot: console built; `scripts/demo_up.sh`; preflight every line PASS; walk S1 once
  off-projector; test room volume with Read aloud. Then, last and in order: press Reset the demo twice,
  `scripts/build_demo_cases.py` (both OK and RED), check memory (`free -m`, at least 3 GB available), open Scenarios.
- Roles: Aman clicks beats 1-4 and 8; Bhawna runs beats 5-7 and keeps the timer; in the 7-minute plan she calls the
  beat-6 cut if beat 4 ends after 3:10.
- Fallbacks as in Part 2. If a judge asks how good the checks are, open Evaluation and read the row with its sample
  sizes; never quote a catch rate from memory.
- No statistics in the demo itself; if a judge asks for numbers, point to the fact register.

**After the hackathon** [docs/deployment-path.md; raksham/docs/finale-qa.md Q19]
- A shadow pilot beside a bank's existing call-back, then one branch cluster with the FRMU, then FRMU-wide.
- Before any customer hears a card: an AWS KMS signing key, S3 Object Lock for escalated packs, the real adapter
  integrations, officer training, and the bank's compliance review of the Hindi and English cards
  [docs/deployment-path.md]; and staff authentication, which the prototype lacks [prototype/SECURITY.md].
- Replace or license the non-commercial voice detector and re-calibrate on commercially usable data (our conclusion
  from the licence column of MODELS.md).
- Measure on circulated deepfakes (Deepfake-Eval-2024), calibrate replay and still-image face checks, and add the
  "RBI safe account" rule once its citation is verified [raksham/docs/finale-qa.md Q19; docs/overnight-report.md].

---

## Part 6. Sources

This repo: `README.md`, `MODELS.md`, `docs/accuracy.md`, `docs/evaluation.md`, `docs/architecture.md`,
`docs/changes-2026-10-24.md`, `docs/deployment-path.md`, `docs/overnight-report.md`, `docs/status.md`,
`calibration/audio_report.md`, `calibration/video_report.md`, `calibration/whisper_eval.md`,
`calibration/whisper_eval_fast.md`, `calibration/sources_commons.csv`, `prototype/README.md`, `prototype/PRODUCT.md`,
`prototype/CLAUDE.md`, `prototype/SECURITY.md`, `prototype/satyapan/` (`adapters.py`, `api.py`, `card.py`,
`evidence.py`, `extract.py`, `forensics.py`, `fusion.py`, `llm_reader.py`, `media.py`, `memory.py`, `models.py`,
`normalize.py`, `pipeline.py`, `rulebook.py`), `prototype/data/` (rulebook, fixtures, eval, mocks), `prototype/tests/`
(the tests named above), `forensics/` (`audio.py`, `video.py`, `common.py`), `tests/test_audio.py`,
`scripts/build_demo_cases.py`, `scripts/demo_up.sh`, `scripts/pipeline_check.py`, `synthetic/README.md`,
`synthetic/validate_fixtures.py`.

Team docs repo: `raksham/docs/finale-runsheet.md`, `finale-qa.md`, `fact-check.md` (entries S3, S4, T1, T2, A1, A3, L1,
L1-rules, L5, R6, R7), `since-round-1.md`, `track-decision.md`, `concept-satyapan.md`, `disclosure.md`.

The section drafts behind this document were written by one agent per section, each citing the files it read. A separate
fact-checking agent then tried to refute every number and quote in this combined version against those files
(about 390 claims); the problems it found were corrected before this version was committed.
