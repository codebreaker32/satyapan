# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this repo is

This repo holds a team entry for the **RAKSHAM AI Cybersecurity Hackathon** (Amazon × IIT Delhi; ARIES and DevClub; listed on Unstop). "Raksham" is the **hackathon's** name, not our team's or product's. The organisers' brief is `../Raksham by IIT_DELHI x Amazon.pdf`.

This file sits in `satyapan/` (the prototype). The Round-1 deck is in `../deck`, the research and fact register in `../docs`, and the AWS notes in `../infra`; paths below are relative to the repo root `..` unless they start with `satyapan/`.

- **Round 1:** one PDF (pitch deck plus architecture). It closes **10 Oct 2026, 00:23 IST**. The top 30 teams go to a 48-hour in-person build finale at IIT Delhi on **24–25 Oct 2026**.
- **Team:** the team is literally named "Team". Its two members are Aman Bihari and Bhawna. The 48-hour plan (slide 10) is scoped for two people: no face-swap model, the customer card is shown inside the officer console, and the deepfake-video demo uses only its audio track.
- **Chosen track:** 03, Deepfake Detection for Financial Communications.
- **Product:** **Satyapan** (सत्यापन, "verification"), tagline "verify the instruction, not the pixels". When a bank's existing controls pause a large, unusual transfer, the bank's fraud-response officer checks the "official" voice note, video or notice driving it. The checks use issuer verification services, the bank's own records (we-never-sent-this, beneficiary-name lookup, ledger) and calibrated, abstaining deepfake forensics. Forensics only corroborate and can never produce RED on their own. The output is a human decision, a three-reason customer card and a signed evidence pack for 1930.
- Why this track and concept won over the other eight concepts: `docs/track-decision.md`. The full concept spec is in `docs/concept-satyapan.md`. Its numbers are unverified; use `docs/fact-check.md` for anything that goes in the deck.
- Simulated-judge reviews of the rendered PDF (two rounds, with scores, applied fixes and rejected suggestions) are in `docs/review-notes.md`. Read it before changing the deck's logic, so earlier fixes aren't undone.

## The prototype (`satyapan/`, this directory)

The team qualified for the finale (24–25 Oct 2026, IIT Delhi; the listing gives the window as about 35 hours, not 48). Pre-built code is allowed, so this is the working prototype: a Python engine, a FastAPI service and a React + Vite officer console.

```bash
. .venv/bin/activate                      # first time: python3 -m venv .venv && pip install -e ".[dev]"
python -m pytest -q                       # must pass clean; every finale scenario asserts its verdict
satyapan demo --lang hi                   # every scenario with its card; --evidence DIR writes signed packs
satyapan check "text" --sender +91...     # check a pasted message
satyapan serve                            # API on :8000; serves console/dist when built
cd console && npm run dev                 # console dev server on :5173 (proxies /api to :8000)
```

- `README.md` has the architecture and the scenario table. `PRODUCT.md` is the product record the console design (impeccable) works from; the direction contract lives in the impeccable surface brief, never in source.
- Rules live in `data/rules/rulebook.yaml` (citations, reason text, severity) with logic in `satyapan/rules.py`. A rule without `verified: true` is demoted to soft at load time. Add a test per rule in `tests/test_rules.py`.
- Mocked integrations are in `data/mocks/`; each adapter has a `label` naming the production source. Never present a mock as live, and never fake detector output outside `SimulatedForensics`, which is labelled SIMULATED everywhere.
- The console (`console/`) is the officer UI: React + Vite, direction "Know Your Banknote" chosen in an impeccable round; tokens at the top of `console/src/index.css`, design record in `DESIGN.md`. `npm run build` writes `console/dist`, which the API serves at `/` (restart `satyapan serve` after a build).
- Evidence packs are canonicalised with integral floats written as integers (`evidence.canonical`), because browsers and case systems re-serialise `3800000.0` as `3800000`; `tests/test_evidence.py` covers the round trip. Keep that rule if the manifest format changes.
- Bedrock model access on the AWS account was `NOT_AUTHORIZED` on 16 Oct; the rules-based extractor is the default and the demo does not need Bedrock. `../infra/quota-requests.sh` documents the quota situation.

## Building the submission PDF (`../deck`)

The deck is HTML/CSS rendered to PDF by headless Chromium (Playwright). Fonts come from local `@fontsource` packages, so the build needs no network.

```bash
cd ../deck
npm install && npx playwright install chromium   # first time only
pip3 install --user --break-system-packages pymupdf   # used for page previews
npm run build    # -> out/Satyapan_Round1_Submission.pdf + out/preview/page-NN.png
npm run pdf      # PDF only, skip the PNG previews
```

- `deck/src/index.html` holds every page as a `<section class="slide">` at a fixed 1280×720 px. `deck/src/styles.css` holds the design tokens and components.
- Page order and budget: the cover plus pitch slides 02–10 (10 in total), then architecture A1–A3 (`#arch1`–`#arch3`), then appendix X1–X2 (`#appx1`, `#appx2`), which don't count toward the limits. Don't add pitch or architecture pages; cut content instead.
- The architecture diagrams (A1, A2) are absolutely positioned `.nd` HTML boxes with SVG wires underneath. Box coordinates and wire coordinates are hand-matched, so moving a box means editing its `path d=` endpoints too.
- `build.mjs` fails (exit code 1) and lists the page when any slide overflows its frame, or when an element marked `data-fit` or any diagram box (`.nd`) overflows. Fix the layout; never set `overflow: visible` to silence it. It also warns about any `[Placeholder]` text still in the PDF (the team block on the cover).
- After any change, look at the rendered pages in `deck/out/preview/`. They are rasterised from the final PDF, so they show exactly what reviewers will see.
- Inline references `[n]` in slides must match the numbered list on X2 (`#appx2`). When adding a source, add it there too.

## Design invariants the deck relies on (keep pages consistent)

- **RED needs two families:** a cited hard F1/F2 rule plus a signal from a different family (F1–F4). F5 pressure cues and officer clicks never count as the second family. A lone hard rule gives AMBER. Pages 5, 6, 8, 10, A1, A2 and X1 all state or show this.
- **RED needs a money demand to have been read** (added 18 Oct, pass 5). With `instruction` NONE and no payee account, IFSC or VPA, a RED pair is capped at AMBER. A judge pasted a genuine overdue-loan letter and the card told a real customer to stop her money on a message the extractor had read no instruction out of; "verify the instruction, not the pixels" is the product's own sentence. Enforced in `fusion.fuse` as the last check before a RED is returned, pinned by `tests/test_no_red_without_money.py`, and one-directional by construction: it can only make a verdict less severe. The submitted deck states the two-family rule and is not falsified by this, only incomplete.
- **Reporting rails:** a stopped attempt goes to I4C's Suspect Registry (payee) and Chakshu (caller). Money already lost goes to 1930 / NCRP and the bank's CFCFRMS workflow. Never tell a customer "we will call 1930" for a stopped attempt.
- **ED summons without a passcode means "confirm with ED", never "fake".** ED issues some summons outside its system.
- **Legal basis:** today it rests on the bank's duties under RBI's FRM Directions 2026. The DPDP Act and Rules apply only from 13 May 2027, so never present them as already in force.

## Hard constraints from the brief

- **Page limits:** the pitch deck is at most **10 slides** (an optional appendix doesn't count). The architecture overview is at most **3 pages**. Everything goes in one PDF, and it must make sense with no presenter and no external links.
- **Scoring (100):** problem fit 20; technical architecture and detection logic 20; value and differentiation 15; feasibility and 48h plan 15; safety, privacy and responsible AI 15; adoption, integration and scale 10; communication 5.
- **Data:** use only synthetic, public, consented or authorised data. Never use real bank, customer or platform data. Never use a real official's likeness in demo media.
- **Disclosure:** the appendix must list every AI-generated asset, dataset, model and third-party asset, including AI-assisted writing.
- **Safety:** never auto-block or accuse anyone on a single weak signal. A score alone is not an explanation. A human reviews before any high-impact action.

## Accuracy rules for deck content

- Every statistic and rule citation in the deck must come from `docs/fact-check.md`. That file records the primary source, a verbatim quote, and how each was checked.
- During research, an AI web-page summariser **fabricated a quote** from a PIB PDF. Confirm quotes against raw source text (curl + grep, or PDF text extraction) and never against a summary.
- State scale honestly. Digital arrest was about 8.5% of the amount reported lost in 2024 (our calculation from two MHA Rajya Sabha answers), and complaints fell to 58,239 in 2025. The often-quoted 9% / 6% / 76% splits appear only in ThePrint and are not used.

## Voice and look

- Write like the two of us would talk to a judge: plain sentences, few em-dashes, and no "X, not Y" or "A — because B" title formulas. Keep one claim per title.
- Section labels are sentence case (`.lbl2`). Keep the small all-caps mono style for tags, codes and stat sources only.
- A few handwritten margin notes (`.anno`, Kalam font) with drawn arrows add a human touch. Keep it to about one per page at most. Every note must point at the thing it talks about, and must not add a new factual claim beyond what's already on the page.
