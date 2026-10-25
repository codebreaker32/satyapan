# Satyapan · सत्यापन

**Verify the instruction, not just the pixels.**

When a bank's own controls pause a large, unusual transfer, Satyapan helps the fraud-response officer check the
"official" voice note, video or notice behind it, in about ten seconds, against issuer rules and the bank's own
records. When a detector can judge the media, its calibrated deepfake check counts half, next to those checks. The
customer hears three reasons she can check herself, in Hindi or English, and every decision lands in a signed
evidence pack.

Team "Team" (Aman Bihari, Bhawna), RAKSHAM AI Cybersecurity Hackathon (Amazon × IIT Delhi), Track 03.

## Run it

```bash
cd prototype                        # in the satyapan-finale repository
python3 -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"             # engine + API + tests
python -m pytest -q                 # must pass clean: extraction, every rule, fusion, card, evidence, memory, scenarios
satyapan demo --lang hi             # the finale scenarios, with cards and signed packs
satyapan check "paste a message"    # check any text
satyapan serve                      # API on :8000 (serves the console once console/dist exists)
```

A cold clone was smoke-tested on 17 Oct 2026: `git clone` of this repo is instant on a local disk, and the
full test suite runs green from the cloned tree (151 passed, 8 skipped — the skips are the optional OCR/PDF
extras and the preflight checks that need `console/dist`, which is build output and not tracked). Two things
need the network once: `pip install -e ".[dev]"` into a fresh venv (PyPI) and `npm install && npm run build`
in `console/` (the npm registry). Budget a few minutes for each on conference Wi-Fi; after that everything
runs offline.

### Real models (optional; once, needs the network)

The engine runs without any of these: a missing layer is skipped and says so. With them, a voice note, video or
notice that is uploaded or recorded in the console is read and checked for real. Set up on Windows 11, Python 3.13,
CPU only:

```powershell
pip install -e ".[dev,stt,ocr,similarity]"                         # Whisper, OCR, PDF text, the meaning model
pip install torch --index-url https://download.pytorch.org/whl/cpu  # CPU torch, for AASIST-L
pip install -e ".[audio]"
winget install -e --id UB-Mannheim.TesseractOCR                     # the OCR program (one admin prompt)
satyapan setup-models                                               # weights and language data into vendor/ (about 0.7 GB)
```

- **Speech to text**: Whisper small (faster-whisper, CPU int8) reads uploads and recordings in Hindi and English. The
  engine's name is stored with the text it produced (`derived_text_engine`).
- **OCR**: tesseract 5.4 with English and Hindi data from `vendor/tessdata`. A PDF's own text layer is read directly.
- **Voice detector**: DF Arena 500M (`Speech-Arena-2025/DF_Arena_500M_V_1`, non-commercial licence), calibrated per
  language and channel on 630 public clips (`../calibration/audio.json`, `../calibration/audio_report.md`). In the
  demo it runs in the local forensics service of the parent repository (`../forensics/`, started by
  `../scripts/demo_up.sh`), next to the GenD face check. Without the service, the engine can run it in-process, given
  torch, the parent repository's detector packages (`../requirements.txt`) and the downloaded model. Under 2 s of
  speech it abstains. A voice flag counts half in the combined score: where the
  calibration has a 1% line (among the cells by channel, only 8 kHz Hindi phone audio), a "high" flag alone gives
  50%, RED when the message asks for money; elsewhere a flag is at most "moderate", 35% alone, AMBER.
  AASIST-L is the older fallback, used only when DF Arena is not available: thresholds measured on 150 genuine FLEURS
  clips per language and channel (`data/forensics/aasist_calibration.json`), clips under 3 s abstain, and it flagged
  the Windows built-in synthetic voice 6 times out of 6 in each English channel; how well it catches modern
  Indian-language voice clones is not measured.
- **Website check**: a link in an official-looking message is looked up live in the domain's registry (RDAP).
  Offline, and in the tests, the answers recorded in `data/mocks/web_registry.json` are used; `SATYAPAN_LIVE_WEB=0`
  makes the server use only those. `../scripts/demo_up.sh` sets it unless started with `SATYAPAN_LIVE_WEB=1`, so in
  the demo nothing leaves the laptop.
- **Meaning-level memory**: a multilingual sentence model matches reworded, Hindi and Hinglish copies of a confirmed
  case, only when they name the same body. It catches 8 of the 14 labelled copies at a threshold with no false match
  among the repo's other messages (`data/eval/memory_calibration.json`).

The calibration results ship, so re-measuring is optional: `satyapan calibrate-memory`, and `satyapan calibrate-audio`
once FLEURS `data/hi_in/audio/dev.tar.gz` and `data/en_us/audio/dev.tar.gz` (https://huggingface.co/datasets/google/fleurs,
CC-BY-4.0) are saved in `data/forensics/fleurs/` as `hi_in_dev.tar.gz` and `en_us_dev.tar.gz` (git-ignored).
`tests/test_ocr.py` and `tests/test_real_models.py` run the real models and skip cleanly where one is missing. The
finale scenarios carry their text, so nothing in the scripted demo depends on these. `".[aws]"` (boto3) is used by
the KMS signer; a Bedrock extractor is specified but not built.

**A digital-arrest rule and an offline helper reader (24 Oct).** `R-DIGITAL-ARREST-PAY` (F1, hard, the I4C advisory
"There is no concept of Digital Arrest under any Indian Laws") fires when the message tells the customer she is under
"digital arrest" and asks for money, with no law-enforcement body named (`R-AGENCY-PAY` covers a named one). The
words must be addressed to her (`extract.digital_arrest_to_you`: "you are digitally arrested", "aap digital arrest
mein hain", "आप डिजिटल अरेस्ट में हैं"); a sentence that warns about, denies or quotes them does not count. Alone it
gives AMBER. `SATYAPAN_LLM_READER=llama3.2:3b` turns on an offline helper reader (`satyapan/llm_reader.py`, Llama 3.2
3B through Ollama on 127.0.0.1; Built with Llama): after the rules-based extractor it fills only what that extractor
left empty without seeing a candidate, every field quoting the message, a government-sounding sender only ever as
OTHER, never a payee, and the rules still decide. It is off by default and in the demo: on the 156-message evaluation it caught no scam the rules missed and turned two
genuine bank letters into RED (now blocked: it fills no money request beside the bank's own name or a named body),
and a read takes a median of 23 s on the laptop's CPU.

## Evaluation (`satyapan evaluate`)

156 messages, each labelled scam or genuine by what it really is: the 22 scenarios, the variant corpus and 64 new
messages in `data/eval/labelled.json`. They are synthetic, not field data. The run writes `data/eval/results.json` and
`../docs/evaluation.md`, and the console's **Evaluation** page shows the same file. Latest run: of 79 in-scope scams,
97.5% flagged (34 RED, 43 AMBER) and 2 missed; of 63 genuine messages, none stopped and 7 asked to verify first
(11.1%); of 14 scams outside scope (family emergency, lottery, jobs), 2 flagged. The set helped find three general
fixes, so these numbers are optimistic. `tests/test_evaluation.py` fails if a genuine message is ever stopped. It
also compares the committed report with a fresh run, but only when the same optional models are installed as for the
committed run; otherwise that comparison is skipped (it is skipped in the finale laptop's engine environment).

## How a case flows

```
     bank's own fraud flag pauses the transfer and opens a case
                              ▼
   media (audio / video / image / PDF / text) or the claim-only picklist
                              ▼
   claim: issuer, instruction, payee; every field grounded in a quoted span
                              │
        ┌─────────┬──────────┼──────────┬─────────┐
        ▼         ▼          ▼          ▼         ▼
       F1        F2         F3         F4        F5
     issuer     bank     forensics   campaign  context
    rulebook   truth    (half score)  memory  (never counts)
        └─────────┴──────────┼──────────┴─────────┘
                              ▼
   fusion: no judged media, RED only with a hard rule plus a second family on other evidence;
           judged media, half instruction checks + half deepfake check, RED from 40%
                              ▼
     verdict (RED / AMBER / GREY / MATCHES) + customer card (hi / en)
                              ▼
      signed evidence pack (Ed25519; one flipped byte fails verification)
```

| Family | What it checks | Can it anchor a RED? |
|---|---|---|
| F1 issuer rulebook | `data/rules/rulebook.yaml`: no "digital arrest" in law, ED passcodes, RBI gives no investment advice, @valid, 1600xx, .bank.in, new or suspended websites, suspect registry | yes, with a verified citation |
| F2 bank truth | the bank's own records: we never sent this; whose account is this; that credit never arrived; our own signature | yes, with a verified citation |
| F3 forensics | face check (GenD) and voice-clone check (DF Arena 500M), calibrated, abstain when unsure; documents: error-level analysis, editing-app names and AI-tool labels, not calibrated | yes, through the 50/50 combined score: a high voice flag alone with a money demand gives 50%, RED; a lone hard rule plus a moderate face flag gives 70%, RED |
| F4 campaign memory | fingerprints of cases two analysts confirmed, and reworded or translated copies of them (meaning model) | no, soft only |
| F5 context | pressure cues, the bank's flag | never counts |

**Fusion** (`satyapan/fusion.py`): with no judged media, RED needs a hard rule plus a signal from a different family
resting on different evidence, and one hard rule alone gives AMBER. When media was attached and the detector could
judge it, the instruction checks and the deepfake check count half each, and 40% or more is RED (a very strong
deepfake alone reaches it). Either way, **a money demand must have been read out of the message**: with no
instruction and no payee, a RED is capped at AMBER, because a verdict that stops a payment the engine never saw
contradicts "verify the instruction, not just the pixels". "Could not confirm" is never shown as "safe". The card never
says "fake", "genuine" or "fraud" (tests enforce it).

**Rulebook** (`data/rules/rulebook.yaml`): every rule has a primary citation, the date it was checked, sign-off
and a test. A rule whose citation is not verified is demoted to soft at load time, so it can never anchor a RED.

**Evidence** (`satyapan/evidence.py`): a canonical manifest (media hashes, claim, signals, verdict, versions,
consent, decisions) signed with Ed25519 locally; `satyapan verify pack.json` checks it. Flip one byte and it fails. The canonical form
writes integral floats as integers, so a pack still verifies after a JSON round trip through a browser.
Production: AWS KMS asymmetric key and S3 Object Lock.

## The finale scenarios (`data/fixtures/scenarios.json`)

One row per fixture; `tests/test_docs.py` fails if this table drifts from the file.

| Scenario | What it is | Verdict |
|---|---|---|
| S1-rm-voice-note | cloned "bank RM" voice note (Hindi) from an unknown number; forensics abstain after re-encoding and the verdict holds | RED |
| S1b-rm-own-phone | the same voice note, but from the RM's registered personal phone; call the RM back | AMBER |
| S2-rbi-video | deepfake "RBI official" investment video (transcript); RBI gives no investment advice + the payee is an individual | RED |
| S3-ed-summons | forged ED summons + "RBI supervision account" letter; no passcode means "confirm with ED" | RED |
| S4-claim-only | the media was deleted; the officer's picklist alone, under 2 s | RED |
| S5a-genuine-bank-notice | control: a genuine Demo Bank SMS, signed by the bank and in its outbound log | MATCHES |
| S5b-real-rbi-advisory | control: a real RBI advisory about deepfakes; no instruction, no payee | GREY |
| S5c-ed-summons-1h-old | control: a summons issued an hour ago; ED's site can't check it for 24 h | AMBER |
| S5c2-ed-summons-valid | control: a summons found in ED's system, with no payment demand | GREY |
| S5d-injection | control: the forged summons plus a prompt-injection line; same anchor, same second family as S3 | RED |
| S5e-genuine-sms-1600 | control: the genuine SMS respaced and recased, from the bank's 1600-series number | MATCHES |
| S5f-court-hearing-notice | control: a court hearing notice that asks for nothing but attendance | GREY |
| S5g-it-refund-processed | control: an income-tax refund SMS with no payee and no action asked | GREY |
| S5h-it-refund-probe | control: a refund-credited SMS where "your bank account" is the customer's own account | GREY |
| S6-fake-credit | "I sent you money by mistake, please return it"; no such credit in the ledger, one family only | AMBER |
| S7-court-order | "Supreme Court order" demanding a deposit into the registry account, a real official one | AMBER |
| S8-rbi-bond-no-payee | "RBI officer" pitches a guaranteed-return bond but names no account yet; one hard rule, no second family | AMBER |
| S9-house-tax-copy | a municipal house-tax notice copied word for word, account and link swapped for a new scammer's; the name look-up says the account is an individual's and the link is off .gov.in | RED |
| S9b-house-tax-official | control: the same notice with the corporation's own collection account and its .nic.in portal | GREY |
| S10-echallan-copy | an e-challan SMS copied word for word with the payment link swapped; no payment made yet, so one family | AMBER |
| S10b-echallan-paid-to-person | the same copy, and the paused UPI payment goes to an individual: the bank's own transfer record is the second family | RED |
| S10c-echallan-official | control: the e-challan SMS pointing at echallan.parivahan.gov.in | GREY |

Everything is synthetic. Forensics in S1 are **SIMULATED** (the scenario ships a transcript, not audio, so there is
nothing for the detector to hear) and labelled so on every surface.

## Mocks, honestly labelled

Every adapter carries a label with the production source, the owner and the access route. `GET /api/meta` returns
the labels and the console shows them, so nothing mocked is ever presented as live. One row per adapter:

| Adapter | In the demo | Stands in for |
|---|---|---|
| ED verify-summon | summons number + passcode looked up in `data/mocks/ed_summons.json`, with the real 24-hour and 180-day windows | enforcementdirectorate.gov.in/verify-summon (CAPTCHA, no API): a guided manual check by the officer, or a bilateral API if ED agrees |
| Beneficiary name lookup | holder name and type from `data/mocks/name_lookup.json`, plus an official allow-list | the bank's core banking / NPCI name lookup (RBI/2024-25/99, mandatory for RTGS/NEFT) |
| Outbound communications log | content-hash match against `data/mocks/outbound_log.json`; knows the RMs' registered phones | the bank's CRM / messaging gateway logs for centrally sent channels |
| Ledger credits | the customer's last-72-hour credits from `data/mocks/ledger.json` | the core banking ledger, read-only |
| I4C suspect registry | account / UPI ID / phone checked against `data/mocks/suspect_registry.json` | NCRP "Report & Check Suspect" / the I4C Suspect Registry feed banks already receive |
| Bank content signature | HMAC-SHA256 with a shared demo key over the message text | C2PA content credentials on bank-issued notices, verified with the bank's public key |
| Website registration look-up | live RDAP query to the domain's registry when online (3 s timeout); the real answers recorded on 23 Oct 2026 in `data/mocks/web_registry.json` offline, in tests and in the demo (`SATYAPAN_LIVE_WEB=0`) | the same public registries; a bank would run its own RDAP client and cache |

`/api/meta` also labels the forensics and the signer. In the demo, voice notes and videos go to the local forensics
service (`SATYAPAN_FORENSICS_URL`, set by `../scripts/demo_up.sh`): the GenD face check and the DF Arena 500M voice
check, each calibrated per kind of input and abstaining when unsure. Without the service, audio forensics runs
in-process when torch is installed (DF Arena 500M when its files are present, else the older AASIST-L once
`satyapan setup-models` has fetched it) and abstains otherwise; the scenario-scripted results used in rehearsal are marked SIMULATED on every surface.
Document forensics (error-level analysis, editing-app names in the metadata and AI-tool labels; not calibrated on
genuine documents) runs in-process. The evidence signer is a local Ed25519 key standing in for an AWS KMS
asymmetric key with S3 Object Lock. The one-page path from these mocks to a bank deployment, with the stepped
pilot, is `../docs/deployment-path.md`.

## Layout

```
satyapan/         engine: models, extract, rulebook, rules, adapters, forensics, memory, fusion, card, evidence, pipeline, api, cli
data/rules/       rulebook.yaml
data/mocks/       mocked integrations + bank policy document
data/fixtures/    scenarios.json
data/eval/        labelled evaluation set, meaning-memory pairs, results and calibration
data/forensics/   AASIST-L calibration (FLEURS audio, when downloaded, is gitignored)
vendor/           downloaded model weights and OCR data (gitignored; `satyapan setup-models`)
tests/            pytest suite
console/          React + Vite officer console (see console/README.md); `npm run build` → console/dist, served by the API
evidence/         local signing key and uploads (gitignored)
```
