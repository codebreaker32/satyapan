# Overnight report: workbox, 24-25 Oct 2026

For Aman and Bhawna. Everything below is on the branch `overnight` of satyapan-finale and on the branch `overnight` of
the docs repo (`~/work/raksham`). Nothing was pushed to `main`, nothing was force-pushed, no history was rewritten.

## How to get it

The workbox has no GitHub credentials, so `git push` failed all night. The work came back through the handoff bucket
instead (`s3://satyapan-finale-workbox-handoffbucket-48qesedk3zsy/from-workbox/`):

```bash
# satyapan-finale: the overnight branch as a git bundle
aws s3 cp s3://satyapan-finale-workbox-handoffbucket-48qesedk3zsy/from-workbox/satyapan-overnight.bundle /tmp/
git -C ~/projects/raksham/satyapan-finale fetch /tmp/satyapan-overnight.bundle overnight:overnight
git -C ~/projects/raksham/satyapan-finale log --oneline main..overnight      # review, then merge what you like
# docs repo (run-sheet, Q&A crib, video and deck sources): branch overnight in raksham.bundle
aws s3 cp s3://satyapan-finale-workbox-handoffbucket-48qesedk3zsy/from-workbox/raksham.bundle /tmp/
git -C ~/projects/raksham fetch /tmp/raksham.bundle overnight:overnight
```

After merging, restart the demo (`scripts/stop_demo.sh && scripts/demo_up.sh`), because preflight now compares the
running server's engine code with the checkout and fails on a server started before the merge. Then the usual
checklist: preflight, reset, `scripts/build_demo_cases.py`.

## Deliverables in the bucket

- `satyapan-60s.mp4`: the demo video, 57.3 s, 1920x1080, no voiceover (every line is on screen). It opens with the
  problem statement (digital arrest and deepfake "official" instructions, the loss figure from fact-check S3, the
  officer at the pause, "verify the instruction, not the pixels"), then the live product from real captures of the
  running console on this box (the cloned-voice RED, the Hindi card, the face-swap RED, MATCHES, the pack verifying
  and failing on one byte), then measured accuracy and named limits, then the close.
- `satyapan-finale-deck.pptx` and `.pdf`: eight slides in the same order (problem, who it is for, how it decides, three
  live-product slides, measured accuracy, limits). Every number is from `docs/accuracy.md`, the labelled evaluation or
  fact-check S3.
- Sources: `video/src/overnight/Sixty.tsx`, `video/scripts/build_deck.py`, `video/scripts/capture-overnight.mjs`
  and the captures in `video/public/ov/` (docs repo, branch `overnight`).
- `satyapan-overnight.bundle` and `raksham.bundle`: the two branches.

## What changed (satyapan-finale, branch overnight)

Every fix was reproduced in-process first and has a regression test. "C" numbers are indices in
`bughunt_confirmed.json` (36 verified findings), "R" numbers in `bughunt_raw.json` (51 raw).

**Verdicts (extractor; the labelled evaluation is unchanged, row for row, after every one of these)**

- A genuine bank transaction SMS ("Rs 5,000 credited ... by NEFT", "IMPS transfer ... is successful", "FD ... has
  been closed ... and credited", "you have paid ... via IMPS") no longer gives RED: a clause that reports a completed
  transaction is a report, unless it also demands something. A demand next to a report, in its own clause or after a
  comma ("has been debited, to reverse it transfer Rs 1 to account ..."), still reads and still gives RED. (C0)
- "Please transfer 5000 to my Demo Bank account" (a mother), an employer's salary credit and a tenant's rent are not
  read as the bank speaking (GREY, not RED). Scams that pose as the bank and say "your Demo Bank account" keep their
  bank claim, and so do stranger "sent to your account by mistake, send it back" scams. (C1)
- Demands worded with pay / make a payment / payment karo / bharo / भुगतान करें / भरें are read, still behind the money
  and pointed-destination gate; rupay, hazaar and लाख count as money, यूपीआई as a destination. (C2)
- Authorities named with a city ("This is Delhi Police", "calling from Mumbai Police"), as a masthead ("CBI:",
  "दिल्ली पुलिस:"), as "ED office se bol raha hoon" or as "यह मुंबई पुलिस है" are anchored. These reach AMBER (a lone
  agency rule), never RED on their own. (C3)
- A demand put as a condition about someone else ("If someone asks you to pay ... it is a scam") is not the
  message's own demand, so police and RBI awareness messages stay GREY.
- The bank's name in Devanagari ("डेमो बैंक") is read as the bank.

Three of these were corrections to my own earlier fixes, found by probing old against new code (two by an
independent 86-message probe). The probe set is kept as `prototype/tests/test_overnight_probe.py`: no genuine
message RED, every scam flagged today stays flagged.

**Evidence pack**

- Verification trusts only the bank's own key (the API, the CLI and preflight pass it), so a pack altered and
  re-signed with another key is refused. The byte-flip demo still works. (C29)
- A null, empty or list signature is a sentence, not HTTP 500; a missing algorithm is named plainly. (C35)
- The signature and key are read as canonical base64; the shown signing time and the signer label are inside the
  signed manifest and checked. (R21)
- The console downloads the pack it shows (same hash as the one just verified) and reloads it when a re-run moves
  the verdict. (R5, R24)

**The four-eyes rules, strikes and consent**

- A case that was RED before a strike still needs a co-sign to release, and raises a review trigger. (C14, C33)
- The RED co-sign and the campaign-memory two-person rule compare an identity key: case, full-width letters,
  Cyrillic or Greek lookalikes and invisible marks no longer make the same person a second person, and Hangul
  fillers or the Braille blank are nobody. (C24, C30, C31, C32)
- A strike of an unknown field or of a field the claim does not have is refused (422); the console's strike picker
  opens on the field it shows; a strike stays struck on every later run. (C16, C17, C22)
- Consent is enforced by the service: a run needs C1, helping the customer report needs C2 (403 otherwise; the
  console disables the button and says why). (R19, R31)
- Approving an unknown campaign-memory entry is a 404 sentence, not a 500. (R25)

**Screens and sentences**

- A link the scammer chose (demobank-fraud-check.com) no longer crashes the customer card with HTTP 500. (C13)
- The band tells a capped AMBER ("two independent checks agree, and nothing here asked for money") from a one-rule
  AMBER; the verdict carries `no_money_cap`. (C15, C21)
- Highlighted spans stay on their words when the message has emoji (e2e-guarded). (C23)
- A GREY reached through the account look-up no longer says the records "found nothing wrong". (C5)
- Two media files of the same kind are each named in the explanation. (R32)
- The Scenarios disclosure says it holds controls and further attacks. (R7)

**Uploads**

- EXIF-rotated phone photos are read upright (OCR and the perceptual hash). (C6)
- A truncated PDF is "could not read" (415), not "no OCR installed"; a locked PDF says it is locked. (C7, C12)
- The document check gives a PDF a plain reason, never a PIL error with the laptop's path. (C8)
- File names over 200 UTF-8 bytes are shortened instead of HTTP 500. (C9, C34)
- An uploaded .txt is source "text", not "ocr"; UTF-16 and BOM text files are decoded. (C10, C11, C26)
- The .txt size refusal counts bytes as bytes. (R41)

**Detectors (forensics/)**

- AV1 videos are face-checked: frames come from PyAV when cv2 decodes none. (C18)
- "No sound track" only when the container has none; otherwise "the sound track could not be read". (C19)
- 1.98 s of speech no longer prints "only 2.0 s (needs 2 s)". (C20)

**Operations**

- `satyapan preflight --server` FAILs when the server runs older engine code than the checkout (new code hash in
  `/api/meta`) or has no forensics service connected. (R48, R50)
- Demo reset removes uploads left from before a restart. (R23)
- `scripts/demo_up.sh` waits for a loader that is already starting, reports a loader that died at once with the end
  of its log, and appends to forensics.log. (R47)
- Run-sheet (docs repo): the API-dies fallback rebuilds both live cases, checklist commands run as written, a memory
  check before the slot, preflight's new code check. (C27, C28, R46)
- README run steps, `docs/status.md` and the Q&A crib (Q21-23) are updated; `prototype/DESIGN.md` records each
  console change.

**A trap worth knowing:** `scripts/stop_demo.sh` uses `pkill -f "[s]atyapan serve"`. On the workbox that pattern also
matches the `claude -p` process (its prompt contains the phrase), so it was never run here; the smoke test used a
fresh engine on port 8020 next to the old one.

## Test results

Run on the workbox at the end of the night, on the final commit of `overnight`:

| Check | Result |
|---|---|
| Engine suite (`cd prototype && SATYAPAN_LIVE_WEB=0 .venv/bin/python -m pytest -q`) | 1293 passed, 6 skipped, 6 xfailed (was 1055 at the start of the night) |
| Detector suite (`.venv/bin/python -m pytest -q tests/`) | 95 passed, 3 skipped (was 88) |
| Console build and e2e (`npm run build`, `npm run e2e` against `serve --port 8010`) | build OK, 192 of 192 checks pass (two checks added: spans survive emoji, Download JSON is the pack on screen) |
| `satyapan preflight` | 22/22 scenarios; 7/7 PASS with `--server` on a fresh engine with the forensics service |
| Labelled evaluation (`satyapan evaluate --no-write`) | unchanged after every verdict change, and row for row against the session-start code: in-scope scams 97.5% flagged (34 RED, 43 AMBER, 2 missed); genuine 0 stopped, 11.1% asked to verify; out of scope 14.3% |
| Live end to end (`scripts/pipeline_check.py --server http://127.0.0.1:8020`) | 12 of 12 PASS |
| `scripts/build_demo_cases.py` | both OK: cloned voice RED 80% (voice synthetic, moderate, hi/whatsapp-opus), face swap RED 80% (face 0.955, moderate, video/hd) |
| Real-model tests | GenD smoke PASS; DF Arena tests 18 pass with RUN_SLOW=1; OCR tests 2 pass. An AV1 copy of the face swap is now scored (0.963) instead of "could not be read" |
| API fuzz (odd bodies, names, ids and files at every endpoint, in-process) | 0 server errors |
| Before/after probe (86 synthetic messages, written by an independent agent) | after the fixes: 25 better, 0 worse; kept as `tests/test_overnight_probe.py` |

The numbers in `prototype/data/eval/results.json` and `docs/evaluation.md` were not regenerated, because the summary
did not move; they still name the commit they were made at (33d874a).

## Not done, and why

- **RBI or SEBI demanding a transfer or a fee** (C4, C25, R12): the "RBI safe account" script and "under RBI review,
  pay a refundable fee" still come out GREY when the name look-up does not hold the account. The fix is a new F1 hard
  rule, which needs a verified issuer quote in `docs/fact-check.md` and the rulebook's compliance and legal sign-off;
  rule 3 of the night (no rulebook or citation changes) kept it out. Suggested source: an RBI public advisory that
  it holds no accounts for individuals and never asks anyone to transfer money, checked against the raw PDF text.
- **Unverified rules in the combined score** (R33): only matters if a rule ships with `verified: false`; none does.
- **Scams outside scope** stay GREY: electricity disconnection, customs parcel, lottery, a tax-refund fee and similar
  messages with no authority named (the probe lists them as `known_gap`). That is the product's scope, and the
  Evaluation page already says so.
- **`git push`**: no GitHub credentials on the workbox; the branches came back through the bucket (see the top).
- **The old demo stack on this box** (engine on :8000, forensics service on :8765, both started before the night) was
  left running and untouched, because `scripts/stop_demo.sh` would have killed this session (see above). The engine on
  :8000 runs the pre-overnight code, and the new preflight correctly fails it. The forensics service on :8765 runs
  the pre-overnight detector code too; the AV1 fallback and the new sound-track reasons apply after its restart.
- **UI polish (E)**: kept to the changes the fixes needed, each checked at 1280x720 and recorded in
  `prototype/DESIGN.md`; no redesign was attempted.
- **Voiceover**: none, by choice (the brief allowed none or a free local voice). Every line of the video is on
  screen, which also keeps it readable with the sound off in a hall.
