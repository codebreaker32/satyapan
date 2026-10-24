# Design record — Satyapan officer console

<!-- impeccable:design-schema 1 · sidecar: .impeccable/design.json -->

Documented from the built console (`console/src`, served from `console/dist`) on 17 Oct 2026, after the finish
review's verdict pass. The direction contract lives in `console/.impeccable/surfaces/console-src-app-tsx.md`;
this file records what is actually shipped. Mode: Operate — the officer completes a check in 2–5 minutes, and at
the finale the same screen is read by judges from five metres.

## Direction

**Know Your Banknote** (seed `44f74b3e`, chosen as IMPECCABLE'S PICK in the round-1 decision over the roll's
bahi-khata ledger). The message is held up like a banknote in the RBI's security-features guide, and each check
points at the exact words it rests on. It refuses the fraud-ops dashboard: no KPI tiles, no case table as the
home, no drawer with a score chip. No cards, no hairlines, no monospace, no eyebrows, no gradients, no resting
shadows.

## Tokens (`console/src/index.css` `:root`)

| Token | Value | Role |
| --- | --- | --- |
| `--shell` / `--shell-2` | `#2F3A47` / `#26303B` | stone-grey left rail; hover step |
| `--shell-ink` / `--shell-dim` | `#FFFFFF` / `#B8C2CE` | rail text; rail secondary |
| `--ground` | `#FFFFFF` | page ground |
| `--panel` / `--panel-2` / `--panel-3` | `#EEF1F4` / `#E1E6EB` / `#CFD7DF` | panels one tint step from ground; controls; hover |
| `--ink` / `--ink-2` | `#15181C` / `#3F4956` | text; secondary text |
| `--accent` | `#B5509C` | the one callout accent (₹2000 magenta): span highlights, leader lines, callout numbers, selection, focus |
| `--accent-ink` / `--accent-wash` / `--accent-wash-2` | `#6B2359` / `#F4E3EF` / `#EBC9E0` | accent text on light; washes |
| `--red` / `--red-ink` | `#C8102E` / `#FFFFFF` | RED, state only |
| `--amber` / `--amber-ink` | `#D98E04` / `#15181C` | AMBER carries black text |
| `--grey` / `--grey-ink` | `#8A94A0` / `#15181C` | GREY (never "safe") |
| `--green` / `--green-ink` | `#1B7F4B` / `#FFFFFF` | MATCHES |
| `--text` | Hind, Noto Sans Devanagari Variable fallback | all UI and card text, both scripts |
| `--display` | Khand | verdict word, amounts (`.rupee`), case ids (`.num`), callout numbers |
| `--r` | `4px` | the only radius |
| `--t` / `--ease` | `220ms` / `cubic-bezier(0.2, 0.8, 0.2, 1)` | the one motion pair |

Verdict colours are state only and never appear without the word and a drawn mark (`ui/marks.tsx`). Fonts load
from local `@fontsource` packages (Hind 400/500/600/700, Khand 500/600, Noto Sans Devanagari variable); no
network at the finale.

## Type scale

Six steps and no more: **15 / 17 / 20 / 24 / 30 / 88**. Small print 15px; body 17px (set on `body`, so anything
that sets no size of its own lands on the ladder rather than beside it); message text and card reasons 20px;
section `h2` 24px; band headline 30px Hindi over 20px English, and the Devanagari verdict word 30px; the verdict
word itself 88px Khand. Page `h1` is 40px and the wordmark 40px Khand, both outside the content column's six.
Numerals are tabular wherever they align (hashes, times, amounts).

The ceiling is **measured, not counted by eye**: `node e2e/type-scale.mjs '#/case/<id>' --width 1280` reads the
computed size of every leaf text node in the content column, and `e2e/run.mjs` asserts it. It had been eight for
three passes, and two steps were accidents rather than decisions: a `1.15em` case id landing on 23px for one
element on the whole screen, and anything inheriting the 18px root. Raising the number is a design decision; the
e2e makes it a visible one.

**What the assertion actually covers, stated exactly, because the first version of this paragraph over-claimed
it:** six or fewer on a **scenario-run case screen at 1280**. Two shapes sit above it and are known: a case
opened by hand measures **seven**, because `.num`'s `1.2em` puts the `.rupee` chip on 20.4px beside the ladder's
20px (every scenario suppresses that chip, which is why the guarded screen never sees it); and **any** case at
390 measures eight, because `.step` is 16px and `.callout-no` 14px there. The 40px `h1` is inside the measured
set, not outside it. Closing those is a backlog item, not a claim this file may make.

## Layout

- Shell: 224px sticky rail (`--shell`) with the bilingual wordmark, the product's own sentence under it ("Verify
  the instruction, not the pixels", which used to sit at the foot below a column of empty dark), and Scenarios /
  Cases / Memory / Rulebook; content column fills the rest. **The active item is a 3px accent thread down its
  left edge with the full ink beside it, never a filled pill** (19 Oct). Two reasons: a filled highlight pill is
  the admin-template signature and the judge named it a generic tell on the main path every pass; and the accent
  has a recorded job — the one callout colour for span highlights, leader lines and callout numbers — so spending
  it on chrome made the nav the most saturated object on a GREY screen, competing with the verdict band. The
  item also holds the rail's own hover step (`--shell-2`) while it is current: the thread alone is 2.53:1
  against the rail, so at five metres the state was harder to find than the pill it replaced. Ink and weight
  carry it above 4.5:1 and the shelf is dark-on-dark, so the accent is still spent only on the thread. Under
  960px the thread runs along the bottom edge instead, because the rail is a top bar there.
- Case view, top to fold (**the counter pane**, 18 Oct): verdict band (min-height 176px, grid: mark + word |
  bilingual headline | "Rests on two independent checks" naming anchor and second), then `.counter` on `--panel`:
  the customer card at 56% on the left under "What you tell the customer", the officer's actions at 44% on the
  right under "What you do next". The card is the only artefact the customer ever sees, so it never sits below
  the officer's forensic detail. Under 1366px (the venue projector is 1280×720) the card steps down one notch
  (stop line 26px, reasons and do-now 18px, tighter padding) so the stop line, every numbered reason and the
  do-now line clear the fold on all four verdicts; e2e-guarded per verdict.
- Which action is emphasised comes from the engine's outcome and from nothing else: RED and AMBER mean the money
  must not go yet, so Hold is `btn-primary`; GREY is not "safe" and MATCHES is not permission, so neither
  emphasises anything. A one-line `.act-note` says which rule applied. Every action stays available under every
  outcome.
- The pane is not five peers (18 Oct, pass 2). Top to bottom: `Signing as` (attribution for the signed pack, a
  signature line rather than step 1), the one full-width decision about the money (Hold), a pair of equal routes to
  other people (Escalate to FRMU, Help the customer report), the quiet content-width release chip whose co-sign
  gate opens inline beneath it, then a separated group — "Read a field wrong? The rules re-run without it." and
  Strike a wrong field — because a correction to the extraction is not a decision about the money and its effect
  has to be readable before it is pressed.
- A recorded decision is acknowledged in the same column (`.act-done`, `role="status"`): "Recorded. Case status:
  On hold.", then the action, the actor and the time from the record the server returned, then one plain line about
  the way back. There is no undo by design: the evidence pack is signed over the decision list, so an undo that
  deleted a decision would make the pack lie. Where there is a way back it is another recorded decision, and the
  acknowledgement says the earlier one stays. The receipt takes the advice line's slot once a decision exists,
  because keeping both pushed the column past the card and clipped the step strip.
- Then `.steps`, a sticky strip naming the three steps of a case: 1 What the message claims · 2 What we checked it
  against · 3 The record and the evidence, with the way back to all cases on the right. They are buttons calling
  `scrollIntoView`, never anchors: the router owns the hash, and `#claims` would navigate home. The headings they
  jump to carry the same numbers (`.step-no`).
- The check (steps 1 and 2): two columns, message 62% / features 38%, 56px gutter, 36px top padding. The message at 20px with
  `mark.span` highlights; each span opens with its feature numbers in accent chips. Meta rows (Media, Sender,
  Bank signature, Whole message, Bank flag) and the "Also noted, never counted" context rows close the message
  column. The features column holds one row per counted signal: number chip, family word, severity tag, role tag
  (Anchor / Second), reason, evidence key once, citation; SIMULATED and Mock lookup tags when true. Anchor,
  second and match rows are expanded; soft signals collapse to one title line (6px vertical padding, no
  "Rests on …" line until pinned — it always shows when a citation is unverified so the demoted-to-soft note is
  never hidden). This keeps the features column level with the message column (fix 5 of the finish review).
- **A pill on a feature row means one of exactly two things** (19 Oct): this row is why the verdict is legal
  (`Anchor`, `Second`), or trust what it says less (`Simulated`, `Mock lookup`). Everything else that used to be
  a pill — the severity word, "verify first" — is a phrase in the secondary ink beside the family word, because
  "Soft signal · verify first" is a sentence about the check rather than a badge on it. Five chips a row made
  eight distinct pill shapes on one case screen, which a judge counted as tag soup, and flattening them into one
  chip shape is what cost the two honesty labels their weight.
- Leaders: an SVG overlay (`ui/check.tsx` `Leaders`) measured from DOM boxes, re-solved on resize, scroll and
  font load. Lines run only in the gutter, from the feature row to the message column's right edge on the
  phrase's line, 2.5px accent strokes with a dot terminal.
- The customer card itself (हिन्दी / English tabs, Read aloud, Copy text; stop line, three numbered reasons, the
  do-now line, no score, no "fake/genuine/fraud" in either script) lives in the counter pane, not below the check.
  It carries **one instruction** (18 Oct, pass 2): a judge read it aloud as a frightened 70-year-old and counted
  four things to remember. Everything else the officer does moved to `say_next`, rendered below the card as "You
  say next · not read aloud, not on her card" — officer-only, never in `read_aloud`, still bound by the
  forbidden-word lint. The money wording is gated on whether a payment was actually asked for, so a message that
  demanded nothing no longer gets a card telling her to stop paying. Step 3 below the check holds the case record with consent and policy, the decisions, and the signed
  evidence pack with Verify this pack / Flip a byte / Download JSON. The pack panel opens with its Mock signer
  label, so nobody reads "Ed25519" on a projector without reading what signs it.
- The "Features to check" empty state is a sentence in its own `.feat-empty` row, not a `.feat` grid cell: as a
  bare text node it rendered one word per line, in the exact place a judge looks to see why nothing fired.
- **Three prefixes when something did not work, and only three** (19 Oct, `ui/trouble.tsx`): `Refused:` the
  service answered and said no; `Not recorded:` the wire was dead on a write, so nothing changed behind her;
  `Not loaded:` the same dead wire on a read, where nothing was being recorded at all. The third is the second
  with the verb the path was doing — a separate vocabulary for reads would give the officer two things to learn
  about one cut wire. No browser string ever reaches her ("Failed to fetch", "NetworkError", "TypeError" are not
  sentences about her case), and a read failure names what did not arrive ("the case list", "campaign memory",
  "case SP-1042") and says plainly that nothing is shown because nothing was read, not because there is nothing
  there. The sentence sits where the data should have been with Retry under it; **Retry re-runs the fetch in
  place and never reloads the page**, because the app holds every case view the officer has opened this session
  and the wire coming back is not a reason to lose them. Until this pass only the action path had any of it, and
  `#/cases` with the wire cut rendered a heading and a blank page.
- Breakpoint 960px: single column, leaders hidden, rail collapses to a top bar, band word 64px, meta rows stack,
  the counter pane stacks card over actions, and the step strip stops being sticky (the rail is already a top
  bar, so a sticky strip would eat the case).

## Signature interaction and motion

Hovering or focusing a feature lights its spans and thickens its leader; selecting (click / Enter / Space) pins
it and expands a collapsed row; selecting a span lights every feature that rests on it. Motion grammar: one
ease-out pair (220ms) on the band colour, row washes and leader weight, plus a one-time leader draw (640ms,
60ms stagger) on first solve. No entrance animations, no hover lifts. `prefers-reduced-motion` drops the draw
and the transitions.

## The landing (18 Oct, pass 3)

One headline, one lede, one primary action, then the five beats as a numbered sequence (`.beats .beat`, the
numeral in Khand accent, matching the case screen's `.step-no`). Each section's note sits beside its heading
(`.home-sec`) rather than under it, so the credibility sentence ("Nothing is pre-computed; the verdict you see is
produced by the engine when you press Run") costs no vertical space and sits where a sceptical judge looks. The
judge had measured about 140 words before the first Run button, leaving 1.3 rows visible at 1280x720; three and a
half beats now sit in the first frame, which the e2e asserts. **Before a run a row says nothing at all about the
answer** (19 Oct): it used to carry "pytest asserts RED", so the first thing a juror's eye met on the product's
home screen was a test runner's name, and the pass-1 judge capped quality of demonstration on labels like it. The
claim is worth keeping and is now made once, in the section note, in words the room can follow; saying nothing per
row until the engine answers is also the stronger version of "nothing is pre-computed". The rehearsal "Reset the demo" control moved to a
foot section labelled "Rehearsal controls": it is a rehearsal artefact and it was the most prominent button on the
product's home screen. The Cases list got a fixed 112px verdict column so the eye reads a column of outcomes down
the page instead of five identical text rectangles.

## The detectors on screen (25 Oct, refinement for the live face and voice checks)

Refined, not redesigned: every token, the type ladder and the material rules above are unchanged. The gate was
taste-skill v2's house rules (no eyebrows, hairlines, monospace, gradients or resting shadows), which this world
already keeps.

- **"What the face and voice checks found"** (`ui/mediachecks.tsx`, `.mc-*`) closes step 2 as an `h3.case-head`,
  not a fourth section. One row per F3 check on a `--panel` tone step: the check's name with the same
  `.callout-no` number its feature row carries, the result word at 20px (accent ink only when signs were found;
  verdict colours stay on the band), and one sentence that makes the result checkable: the score against the line
  for that kind of input, how many genuine clips set the line, the false-alarm rate on genuine clips that did not
  (from `/api/accuracy`), and how much it counted. A score that rounds to 1 prints "above 0.99999", because
  "1.00000" read as certainty. Until the figures are read the result word stands alone; a failed read shows the
  standard `Not loaded:` sentence with Retry. Face and voice lines no longer appear under "Also noted, never
  counted", which made that heading true again (a clean check counts 0% in the combined score).
- **"In the engine's words"** (`.record-why`): the verdict's explanation sits under the case record at full width.
  In the Policy row's value column it ran one word per line on the projector.
- **New case progress** (`.run-progress`): while the checks run, one sentence names the stage the form is in
  (opening, reading, running the checks, with the typical time for that kind of file) and the elapsed seconds beside
  it. Only the stage is a live region; the seconds are `aria-hidden`. The file picker states the formats and the
  100 MB limit, and says the file stays on this laptop.
- **Evaluation accuracy** (`.acc-*`): one table per check, four columns; the false-alarm rate on genuine clips the
  line never saw and the fakes caught are set at 24px with their counts at 15px beneath. Under 960px the
  "not judged" column hides and tables scroll inside their box (`.table-scroll`, `min-width: 0` in the grid).
- The shared `.grid-2` minimum is `min(360px, 100%)`: at 390 the content box is 358px, and the old 360px minimum
  pushed every two-column page 2px wider than the screen.

## Truthful controls (25 Oct, overnight bug-hunt fixes)

No new look; the same components say what the engine actually did.

- The band on a capped AMBER (two independent checks agree, no money demand read) now says "Two independent checks
  agree, and nothing here asked for money" and shows the engine's own sentence. The one-rule heading is kept for
  the lone-hard-rule AMBER only. The engine marks the capped case with `verdict.no_money_cap`.
- The co-sign panel appears whenever the engine says a release needs one (`inputs.release_needs_co_sign`), which
  includes a case that was RED before a field was struck. Its lead sentence says which of the two it is.
- The strike picker opens on the first field it lists, so the field struck is the one shown.
- Highlighted spans slice the message by code point, so emoji before a span no longer shift marks and leader
  lines onto other words (e2e-guarded: "spans: emoji before a span ...").
- The Memory page's approve guard ignores letter case, matching the engine's two-person rule.

## Memorable moment

Flip a byte of the signed evidence pack on the projector and watch Verify fail (`.verify-bad`, red), restore it
and watch it pass (`.verify-ok`, green); re-encode the media and watch the fingerprint hold.

## Invariants the screen must never contradict

From PRODUCT.md and the engine: the four verdict words RED / AMBER / GREY / MATCHES are fixed; with no judged
media, RED rests on two independent families and the band names both, and a lone hard rule is AMBER; with judged
media the combined score decides (half instruction checks, half deepfake check, RED from 40%, AMBER from 15%) and the
band shows the three numbers; a RED also needs a money demand to have been read, so with no instruction and no payee
it is capped at AMBER and the band says so; a voice flag in a calibration cell with a 1% line can reach "high", which
alone gives 50%, RED when money is asked, while a face flag is at most "moderate", which alone gives 35%, AMBER;
GREY is never shown as safe, and since pass 2 the GREY band never claims the message looks clean either: it prints
the engine's own account of what was read out of the message and says nothing could check it, because "No warning
signs found" was false whenever the extractor had taken an authority, an instruction, a payee or a pressure cue out
of the very message the screen was describing; the customer card never says "fake", "genuine" or "fraud" (or Hindi equivalents)
and never shows a score; every mock is labelled (Mock lookup tags, the rail's reconciled mock sentence computed
from `/api/meta` so it can never disagree with the Rulebook's integrations table, the Mock signer line at the top
of the evidence pack, the Seeded demo data marker on Memory); SIMULATED is stamped wherever simulated forensics
appear; nothing is auto-blocked — the screen advises, the officer decides, and no outcome gets a visually
dominant action unless the engine's own outcome says the money must stop.

## Accessibility

Projector legibility at 5m (88px verdict word, 20px message, high-contrast panels); verdict colour always
paired with word and mark; Devanagari renders in both families; spans, meta rows and features are keyboard
targets (tabIndex, Enter/Space to pin) with a 3px accent `:focus-visible` ring; AMBER and GREY carry dark ink
because their fills fail with white.

Measured WCAG contrast of the shipped tokens (sRGB relative-luminance formula, computed 17 Oct 2026; AA for
normal text is 4.5:1 — every pair passes):

| Pair | Ratio |
|---|---|
| AMBER chip ink `#15181C` on `#D98E04` | 6.63:1 |
| GREY chip ink `#15181C` on `#8A94A0` | 5.79:1 |
| RED band ink `#FFFFFF` on `#C8102E` | 5.88:1 |
| MATCHES band ink `#FFFFFF` on `#1B7F4B` | 5.02:1 |
| Rail dim text `#B8C2CE` on `#2F3A47` | 6.41:1 |
| Rail ink `#FFFFFF` on `#2F3A47` | 11.56:1 |
| Body ink `#15181C` on `#FFFFFF` | 17.81:1 |
| Secondary ink `#3F4956` on panel `#EEF1F4` | 8.06:1 |

The console is verified at 1440×900, at 1280×720 (the common venue-projector resolution; e2e-guarded — the S1
band word, both named checks and the action row sit above the fold with no horizontal overflow) and at 390.
Since the counter pane the e2e also measures, on RED, AMBER, GREY and MATCHES at 1280×720, that the card's stop
line, its last numbered reason and its do-now line all end above y=720, that the hold carries `btn-primary` only
on RED and AMBER, that step 2 scrolls without changing the route, and that the GREY empty state is a sentence
wider than 200px.

The keyboard path is e2e-guarded: `console/e2e/run.mjs` walks the S1 case with real Tab presses and asserts
the order card → actions → features (the counter pane's reading order: what you tell her, what you do, then the
detail), that focus alone never pins (the light clears on blur), and that Enter on a focused feature row pins it
in a way that survives blur.

## Provenance

- Direction round: `satyapan/.impeccable/decision/direction-round-1.json`; boards under
  `satyapan/.impeccable/boards/` (AI-generated mood boards, hero rasters carry their provenance in the round
  record).
- Finish review: recaptures and the verdict pass under `satyapan/.impeccable/review/` —
  `verdict-pass1.md`, `pass1-*.png` (fresh, from the served build), `pass0-s3-*.png` (before fix 5),
  older `case-*.png`, `desktop*.png`, `mobile*.png`, `flow-*.png`.
- Counter pane (18 Oct, cloud-run pass 1): `docs/cloud-run/captures/pass1-after/` (four verdicts × three
  viewports, from the served production build). The before state is `docs/cloud-run/captures/` and
  `captures/ux-audit/`.
- Captures are taken by **`console/e2e/capture.mjs <label>`** (19 Oct), one command for every route at 1440x900,
  1280x720 and 390, writing to `docs/cloud-run/captures/<label>/`. It replaced four one-off scripts, every one of
  which had silently stopped working when the landing rewrite changed a row class, so its selectors live beside
  the e2e that has to keep them true. `console/e2e/taste-inspect.mjs <url>` runs the taste skill's rendered-page
  audit by pointing it at the chromium Playwright already installs for the deck.
- Everything on screen is synthetic and labelled so; no logos or real officials' likenesses.
