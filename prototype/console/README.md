# Satyapan officer console

React + Vite single-page app for the fraud-response officer. In development it runs on :5173 and proxies `/api` to
the FastAPI service on :8000; `npm run build` writes `dist/`, which `satyapan serve` serves at `/`.

```bash
npm install
npm run dev      # http://127.0.0.1:5173  (start `satyapan serve` in another shell)
npm run build    # dist/ for the FastAPI service
```

## What is on the screen

- **Scenarios**: the finale demo. Five beats that show the mechanism, then the controls that show it is not
  trigger-happy. Every verdict is produced by the engine when you press Run.
- **Case**: the verdict band (word, drawn mark, Hindi and English headline, and the two independent checks a RED
  rests on), the officer's actions (hold, escalate, help report, release with co-sign on RED, strike a wrong field),
  the message with its quoted spans, the features to check with leader lines to the words each rests on, the
  customer card in Hindi or English with read-aloud, consent and media hashes, decisions with times, and the signed
  evidence pack with Verify and Flip a byte.
- **Cases**, **New case** (flag, read-aloud consent, pasted text / a file chosen from this device / a voice or video
  recorded in the browser / claim-only picklist), **Memory** (two-person rule), **Rulebook** (every rule with its
  citation; every integration with its mock label), **Evaluation** (the labelled evaluation exactly as
  `satyapan evaluate` wrote it).

## Design

The direction (chosen in an Impeccable direction round) is the RBI's banknote security-features guide: the message
is held up like a note and each check points at the exact words it rests on. The world lends type (Hind for UI and
card text in both scripts, Khand for the verdict word and amounts), palette (stone-grey rail, white ground, one
magenta callout accent; verdict colours are state only and always carry the word and a mark) and one signature
move (the leader lines). Controls are standard web controls. Tokens live at the top of `src/index.css`; the design
record is `../DESIGN.md`.
