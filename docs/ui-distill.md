# UI distill (25 Oct 2026, branch `ui-distill`)

An impeccable "distill" pass on the officer console: less text, same Know Your Banknote world. No token, type
step, engine logic, threshold or customer-card copy changed. No Python touched.

Page height at 1280 wide, before → after: RED case 3145 → 2672 px, GREY case 2553 → 2113 px, Evaluation
3947 → 3309 px, New case 1238 → 1181 px.

## CHANGES

Case screen
- "What you do next": the action note ("RED asks you to pause the transfer...") is gone; the emphasised Hold
  button already says it. The receipt slot stays mounted (empty) so a recorded decision is still announced.
- "Read a field wrong? The rules re-run without it." removed; the strike's own confirm line still says it.
- FRMU line is now "Needs FRMU review: <trigger>." C2 line is now "Reporting is off: no consent to report (C2)."
  The unsigned hint is one sentence.
- Coverage strip: one line ("Read in ..., from .... It read .... It found ...."). Cut: "The checks that fired
  rest on ..." (the feature rows name them), "This message also names ...", and the gap footnote.
- Step 1: the extractor version string is gone from the message meta. The Bank flag row is hidden when the same
  reason already sits under "Also noted, never counted" and no check or payee needs it.
- GREY empty features row: "That is not a confirmation that the message is safe." (the band says it too, and
  that is still there).
- Record: the duplicate Bank flag row is gone; Consent is "check, report, memory · read in Hindi"; Mode is
  "media" or "claim-only"; "No decision yet." "In the engine's words" is folded behind a disclosure.
- Evidence pack: Mock signer is one line ("A local Ed25519 key; production would use AWS KMS ..."); the
  duplicate "Mock of ..." tag in the Signer row is gone. Verify / Flip a byte / Download unchanged.
- Media checks: the footnote is one line ("Unsure is not counted; no signs found never means genuine."). Each
  check's result and its sentence are unchanged.

Other screens
- Scenarios: lede cut to one line; section note "Nothing is pre-computed: press a row to run the engine.";
  the paragraph under "17 more cases" removed (the summary says it); the p50 line keeps "engine only" and
  "session timing, not a benchmark" and drops the rest.
- New case: lede removed; file hint is "Up to 100 MB. The file stays on this laptop."; the notice-language note
  removed; claim-only note is one line; "Recorded N s." without the speech-to-text explanation.
- Cases: lede removed. Memory: lede is one line (two-person rule, soft match); Seeded demo data is one line.
- Rulebook: lede is one line plus the hash; the integrations note keeps only the live honesty sentence.
- Evaluation: the intro is "Synthetic evaluation set, not field data. N labelled messages, run on <date>." with
  the commit, rulebook, detector and model folded under "How it was run". The accuracy section opens with
  "Public clips, never customer data. Made <date>."; the full method note, model revisions, sources and "Where it
  fails" are folded under "How it was measured, and where it fails". Tables unchanged.
- Rail: the rulebook/policy version line is gone (it is on the Rulebook page and in the case record). "Everything
  shown is synthetic" stays.

Kept, unchanged: the verdict band, the customer card and "You say next", every officer action and the co-sign
rule, every honesty label (Simulated, Mock lookup, Mock signer, Seeded demo data, "not a confirmation that the
message is safe", "never counted", "Everything shown is synthetic").

Folding uses one new class, `.fold`, which reuses the existing `.home-more` summary style.

## Checks

- `npx tsc -b` clean; `npm run build` clean.
- Console e2e against a fresh `satyapan serve --port 8010`: 192 PASS, 0 FAIL (the same count as before the
  pass). One assertion changed: "the action note says why" is now "before a decision the receipt slot is empty",
  because the note was removed. It was not an honesty assertion. No honesty assertion was touched.
- Engine and detector suites were not run: no Python changed.
- `e2e/capture.mjs` now also captures `#/evaluation`.

Screenshots (1280x720 fold and full page, before and after, RED = S3-ed-summons, GREY = S5b-real-rbi-advisory):
`s3://satyapan-finale-workbox-handoffbucket-48qesedk3zsy/from-workbox/ui-distill-shots/`.

Not covered: a RED case with judged media (three scores) was not captured, because this server ran without the
forensics service. The band and the media-check rows were not edited.
