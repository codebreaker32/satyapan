# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Stack

React + Vite for the officer console (user's choice, 16 Oct 2026). Backend: Python FastAPI service in this repo serves the API and, in production, the built console. Deploy target for the finale: a laptop running both locally.

## Users

**Primary user: the bank's fraud-response officer.** Either a branch operations officer releasing a flagged counter request (an early FD closure plus an RTGS/NEFT to a first-time payee) with the customer standing in front of them, or an FRMU (Fraud Risk Management Unit) analyst on a call-back for a flagged digital transfer. They have 2–5 minutes, a coached and frightened customer, and today nothing specific to show her.

**Protected person: the customer**, often a senior, acting on an "instruction" that appears to come from an authority (ED, CBI, police, a court, RBI, SEBI, or "your bank"). She may be on a live video call with the scammer while at the counter. She never operates the console; she hears the card read aloud, in Hindi or English.

**Secondary: the FRMU analyst** reviewing escalations, and **auditors / law enforcement** reading signed evidence packs.

**For the 24–25 Oct 2026 finale**, the console is operated by the team on a laptop and shown on a projector to judges 5+ metres away; the customer card is read aloud or shown on a phone.

## Product Purpose

When a bank's existing controls pause a large, unusual transfer, Satyapan lets the officer check the "official" voice note, video or notice behind it in about 10 seconds, against issuer rules and the bank's own records, with deepfake forensics only as backup. It turns a blind "Are you sure?" into three reasons the customer can verify herself, and leaves a signed evidence pack. Success in the pilot is "customer persuaded": the share of flagged customers who stop and verify after hearing the card.

## Positioning

"Verify the instruction, not just the pixels." Detectors chase every new generator and lose 45–50% accuracy on real 2024 deepfakes. Satyapan checks facts the scam cannot fake: whether the authority could ever have sent that instruction (no "digital arrest" exists in Indian law; ED summonses carry a verifiable passcode; RBI gives no investment advice) and what the bank itself knows (we never sent this message; that refund never arrived; the "RBI account" belongs to a private firm). A perfect deepfake still fails because the instruction is impossible. Only a bank can run the bank-truth checks, which is why it lives at the bank's pause and is owned by its fraud unit.

## Operating Context

- Trigger: the bank's own fraud flag opens a case (reason, amount, payee references). Satyapan builds no transaction monitoring.
- Inputs: only the media the customer chooses to show, captured on a bank device after read-aloud consent (C1 check, C2 report, C3 campaign memory); or claim-only mode, where the officer ticks what she was told.
- Five signal families: F1 issuer rulebook, F2 bank-truth provenance, F3 media forensics (counts half in the combined score when media is judged), F4 campaign memory, F5 bank context. Four outcomes: RED, AMBER, GREY, MATCHES.
- Officer actions: release (co-sign if RED), time-boxed hold under bank policy, escalate to FRMU, help the customer report; strike a wrongly extracted field (rules re-run).
- Reporting rails: a stopped attempt goes to I4C's Suspect Registry (payee) and Chakshu (caller); money already lost goes to 1930 / NCRP and the bank's CFCFRMS workflow.
- Every outside integration (ED verify-summon, name lookup, outbound log, ledger, suspect registry) is a labelled mock in the prototype; the console must show that label.
- Finale: a 7-minute live demo of five scenarios (cloned bank-RM voice note; deepfake "RBI official" video; forged ED summons + "RBI account" letter; claim-only mode; controls that prove it is not trigger-happy), plus a byte-flip on the evidence pack failing verification live.

## Capabilities and Constraints

- The engine (Python, this repo) is the source of truth: claim extraction with quote-grounding, YAML rulebook with verified citations, ordered fusion, Hindi/English card, Ed25519-signed evidence pack, campaign memory with a two-person rule.
- Invariants the UI must never contradict: with no judged media, RED needs two independent families (F5 never counts); RED also needs a money demand to have been read, so with no instruction and no payee the verdict is capped at AMBER; a lone hard rule gives AMBER; with judged media the combined score decides (50% instruction + 50% deepfake, RED from 40%, AMBER from 15%); "no warning signs" is never shown as "safe"; the system never says "fake", "genuine" or "fraud"; customers never see a score; nothing is auto-blocked.
- Terminology: case, flag, claim (extracted), signal, family F1–F5, verdict/outcome, card, evidence pack, hold, escalation ladder, claim-only mode, campaign memory.
- Languages: Hindi and English on the customer card (Devanagari must render); officer UI in English.
- Video: a face check (GenD CLIP-L/14 with YuNet) runs on uploaded video next to the voice check; `docs/accuracy.md`
  says where it holds and where it does not (WhatsApp-size video is the weak cell).
- The Bedrock LLM extractor stays an optional path: model access on the team's AWS account was NOT_AUTHORIZED as of 16 Oct 2026 (../docs/disclosure.md), the rules-based extractor is the default, and the demo does not need Bedrock.

## Brand Commitments

- Name: **Satyapan** (सत्यापन, "verification"); team name "Team" (Aman Bihari, Bhawna).
- Voice: plain sentences a 70-year-old can check, no jargon on the card; the officer UI may use the team's terminology.
- The Round-1 deck (../deck) established an identity: Inter / Inter Tight / JetBrains Mono, near-black and white with a saffron accent, RED/AMBER/GREY/MATCHES verdict colours, Kalam handwritten notes. It is reference, not a binding system for the console; the console may replace it if the direction round decides so, but the four verdict words and their meanings are fixed.
- No logos or trademarks of Amazon, RBI, ED, CBI or any bank.

## Evidence on Hand

- Verified fact register: ../docs/fact-check.md (every statistic and citation with verbatim source quotes).
- Rulebook with citations: data/rules/rulebook.yaml.
- Demo scenarios with synthetic texts: data/fixtures/scenarios.json (22 scenarios, each verdict asserted in tests); mocks under data/mocks/.
- Round-1 PDF and its console mock-up: ../deck/out/Satyapan_Round1_Submission.pdf (slide 5).
- Absent, must not be fabricated: real customer or bank data, real officials' likenesses, real detector accuracy on Indian telephony audio, pilot results.

## Product Principles

1. The officer decides; the screen advises. Every RED shows the two signals it rests on and which evidence each used.
2. Everything the customer hears must be checkable by her, in her language, without a score.
3. Mocks are labelled; synthetic is labelled; "could not confirm" is never dressed as "safe".
4. Ten seconds to a verdict, five minutes to a decision: density serves the officer's glance, not completeness.
5. Evidence outlives the conversation: every decision lands in a signed pack.

## Accessibility & Inclusion

Projector legibility at 5 m (large type, high contrast, verdict colours paired with words and icons, never colour alone); Devanagari text rendering; keyboard-operable actions; low-literacy customer copy (short sentences, three reasons).
