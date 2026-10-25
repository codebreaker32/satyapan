---
version: 1
slug: "console-src-app-tsx"
primary_target: "console/src/App.tsx"
related_targets: ["console/src/index.css","console/src/main.tsx"]
---

# Surface brief: officer console (console/src/App.tsx)

## Scope and mode

The Satyapan officer console: one React + Vite single-page app served by the FastAPI service. Mode: Operate. The visitor is the bank's fraud-response officer completing a check in two to five minutes; at the finale the same screen is driven by the team and read by judges from five metres.

## Audience, job, action, proof, constraints

- Audience: fraud-response officer (branch counter or FRMU call-back); the customer hears the card read aloud; judges watch the projector.
- Job: when the bank's flag pauses a transfer, check the instruction behind the voice note, video or notice; see what it rests on; decide; read the customer three reasons; leave a signed pack.
- Primary action: run the check (a scenario at the finale, a pasted text / upload / picklist in use), then decide: hold, escalate, help report, or release (co-sign on RED).
- Proof/content: the engine's output only. Claim spans, signals with evidence keys and citations, verdict with anchor and second, Hindi/English card, evidence pack, mock labels, SIMULATED labels.
- Constraints (from PRODUCT.md, never contradicted on screen): RED rests on two independent families and the screen names both; a lone hard rule is AMBER; with judged media the 50/50 combined score decides (a face flag alone stays AMBER, a high voice flag with a money demand can be RED); GREY is never "safe"; no "fake/genuine/fraud"; no score for the customer; nothing auto-blocked; every mock labelled; verdict colour always paired with the word and a mark.

## Direction contract

THESIS: The message is held up like a banknote in the RBI's security-features guide, and each check points at the exact words it rests on. It refuses the fraud-ops dashboard: no KPI tiles, no case table as the home, no drawer with a score chip.

OWN-WORLD: Stone-grey shell rail (#2F3A47) on a white ground, ink #15181C, panels one tint step from the ground (#EEF1F4). One callout accent, ₹2000 magenta (#B5509C), owns span highlights, leader lines and selection. Verdict colours are state only: RED #C8102E, AMBER #D98E04 (black text), GREY #8A94A0, MATCHES #1B7F4B, always with the word and a drawn mark. Type: Hind for all UI and card text in both scripts; Khand for the verdict word, amounts and case ids. No cards, no hairlines, no monospace, no eyebrows, no gradients, no resting shadows. Density of a feature guide: one artifact large, a tight list of features beside it.

STORY: The officer sees the verdict and the two checks it rests on in one glance, sees where in the message each check points, reads the Hindi card aloud, decides, and leaves a signed pack. A judge understands "verify the instruction, not just the pixels" with no presenter.

FIRST VIEWPORT (1440 × 900): left rail 224 px with the bilingual wordmark (सत्यापन / Satyapan) and Scenarios, Cases, Memory, Rulebook. Across the top a verdict band ~176 px tall in the verdict colour: mark + word (Khand, ~88 px) left, bilingual headline centre, "rests on" naming the anchor and second signal right. Under it one action row: Hold, Escalate, Help report, Release (co-sign required on RED), Strike a field. Below, two columns: the message at 20 px with highlighted spans (left 62%), and "Features to check" (right 38%), one row per signal: family word, reason, evidence key once, citation, SIMULATED when true. Leader lines run from each feature to its span. Below the fold: the customer card (हिन्दी / English), consent and media with hashes, decisions with times, evidence pack with Verify and Flip a byte, mock labels.

FORM: Know Your Banknote (the RBI banknote security-features guide), candidate 1 of my ordered grounded list, chosen by the user as IMPECCABLE'S PICK over the roll's candidate 7 (bahi-khata ledger). Seed key 44f74b3e. Code-led; no comp.

SIGNATURE INTERACTION AND MOTION: hovering or focusing a feature lights its span and thickens its leader; selecting a span lights every feature that rests on it; leaders are an SVG overlay measured from DOM boxes, re-solved on resize and scroll. Motion grammar: one ease-out (220 ms) on the verdict band's colour and on leader draw; no entrance animations, no hover lifts.

FINISH: unreviewed and undocumented is unfinished; this build ends with the finish review, the verdict, DESIGN.md, and every shipping raster carrying its provenance

## Memorable moment

Flip one byte of the signed evidence pack on the projector and watch Verify fail, then restore it and watch it pass.

## Unresolved decisions

- Whether the scenario list shows what the fixture expects (muted "fixture expects RED") during the demo. Default: shown, muted, because the controls (GREY, MATCHES) are the point.
- Whether the card is shown on a second phone-sized window at the finale; the console shows it inline regardless.
