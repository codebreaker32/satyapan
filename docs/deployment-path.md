# The deployment path

One page for a judge with five minutes: how Satyapan goes from this laptop into a bank. Every regulatory claim
here is recorded in `docs/fact-check.md` with the primary source and a verbatim quote.

## Where it sits in the bank's stack

Satyapan starts after the bank's own fraud-risk flag pauses a large, unusual transfer, and it finishes before
release. RBI's Fraud Risk Management Directions, 2026 (RBI/DoS/2026-27/412, 31 Jul 2026) require every commercial
bank to run a board-approved framework for Early Warning Signals and Red Flagging of Accounts, with transaction
monitoring "on real-time basis or with a minimum time lag". That flag and that pause already exist; Satyapan
builds no transaction monitoring of its own. It takes the paused case, helps the fraud-response officer check the
"official" voice note, video or notice behind it, and hands back a human decision, a three-reason customer card
and a signed evidence pack. The officer console is the only new surface. There is no customer-facing app: the
customer hears the card read aloud, in Hindi or English.

The legal basis today is the bank's duties under those FRM Directions. The DPDP Act's consent and processing
sections come into force only on 13 May 2027 (G.S.R. 843(E)), so we do not present them as a basis now; the
read-aloud consent at capture is designed so the same flow still works when they do. The pause itself is becoming
a formal duty: the Supreme Court on 4 Aug 2026 directed RBI to adopt an SOP for banks to place temporary debit
holds on suspected money-mule transactions, and RBI issued it on 11 Sep 2026 as draft KYC Amendment Directions,
proposed to take effect by 1 Apr 2027. Those are draft rules today, and we say so.

## Every mock has a named production route

The engine has seven adapters, and each carries a label naming its production source, owner and access route. Six
are mocks today. The seventh, the website registration look-up, reads public domain registries: answers recorded
on 23 Oct 2026 in the demo (`SATYAPAN_LIVE_WEB=0`), a live RDAP query with `SATYAPAN_LIVE_WEB=1`. `GET /api/meta`
returns the labels and the console shows them. Swapping a mock for the real system replaces one adapter and leaves
the engine alone. One row per adapter, labels word for word:

| Adapter | Owner | Production system and access route |
|---|---|---|
| ED verify-summon | Directorate of Enforcement | enforcementdirectorate.gov.in/verify-summon (CAPTCHA, no API); guided manual check by the officer; bilateral API if ED agrees |
| Beneficiary name lookup | Bank operations | Bank core banking / NPCI name lookup (RBI/2024-25/99, mandatory for RTGS/NEFT); read-only internal API |
| Outbound communications log | Bank contact centre + IT | Bank CRM / messaging gateway logs for centrally sent channels; read-only internal API; match by content hash or message id |
| Ledger credits | Bank operations | Core banking ledger, credits to the customer's account; read-only internal API, last 72 hours |
| I4C suspect registry | I4C (MHA) | NCRP 'Report & Check Suspect' / I4C Suspect Registry shared with banks; bank's existing registry feed |
| Bank content signature | Bank InfoSec | C2PA content credentials on bank-issued notices (bank signing key); public-key verification; demo uses HMAC with a shared demo key |
| Website registration look-up | Public internet (domain registries) | Domain registry RDAP records (rdap.org bootstrap to each registry); HTTPS query when online; recorded answers when offline |

Three of the seven are read-only calls on systems the bank already runs, and the name lookup has been mandatory for
RTGS and NEFT since RBI/2024-25/99 (offered by 1 Apr 2025). The suspect registry is a feed banks already receive:
I4C launched it with banks and financial institutions on 10 Sep 2024. ED verification starts as a guided manual
check because the real page has a CAPTCHA and no API. The content signature is the one genuinely new build, and
it only strengthens the positive path.

## The pilot, step by step

1. **Shadow.** Satyapan runs beside the existing call-back and counter process on already-flagged transfers.
   No customer impact: officers work exactly as today, and the system's verdicts are compared with their
   decisions afterwards. Measured: agreement with the officer's decision, and time to verdict on real case load.
2. **One branch cluster, with the FRMU.** Officers use the card live, with the Fraud Risk Management Unit owning
   escalations. Success is the metric in the product record, "customer persuaded": the share of flagged customers
   who stop and verify after hearing the card. False holds and complaints are tracked beside it, so restraint is
   measured too.
3. **FRMU-wide.** Rolled out across the unit once the cluster numbers hold, with the rulebook maintained from
   officer reports.

Honest prerequisites before any customer hears a card: an asymmetric AWS KMS signing key in place of the local
Ed25519 key; S3 Object Lock for escalated evidence packs; the seven adapter integrations above; officer training on
the console and the read-aloud consent; and the Hindi and English customer cards reviewed by the bank's own
compliance team.

## What it is not

- **No auto-block.** The system holds nothing on its own. The officer decides, and releasing a RED needs a
  co-sign under bank policy.
- **No customer scoring.** The checks are about the instruction, never about the person, and the customer never
  sees a score.
- **No new data collection.** Only the media the customer chooses to show, captured on a bank device after
  read-aloud consent; claim-only mode covers a customer who shows nothing. Satyapan adds no monitoring and no
  new customer data store.
- **The human decides.** Every verdict is advice to a trained officer, with the evidence each signal used shown
  beside it.
