from datetime import timedelta

import pytest
import yaml

from satyapan.models import Flag, Outcome, Severity
from satyapan.rulebook import load_rulebook
from tests.conftest import NOW, SCENARIOS, run_scenario_id, run_text, signal

S1 = SCENARIOS["S1-rm-voice-note"]["text"]
S3 = SCENARIOS["S3-ed-summons"]["text"]
# A real-looking challan SMS and a municipal tax notice. A copy of either is the same words with the payment
# detail swapped, which is what the four rules at the bottom of this file are about.
CHALLAN = ("Traffic Police Delhi e-Challan. Challan No. DL1234567890 issued for vehicle DL8CAF1234 for overspeeding on "
           "20 Oct 2026. Fine amount Rs 2,000. Pay within 7 days to avoid court action.")
TAX = ("Municipal Corporation of Delhi. Property tax notice 2026-27. Pay your house tax of Rs 12,500 before 31 Oct "
       "to A/c {acct}, IFSC HDFC0000213, to avoid penalty.")


def run_paying(engine, text, **payee):
    """A case whose paused payment has a receiver on the bank's flag (payee_account / payee_vpa)."""
    case = engine.open_case(Flag(reason="test flag", amount_inr=2000, customer_ref="cust-demo", **payee))
    engine.set_consent(case, check=True)
    engine.add_text(case, text)
    return engine.run(case)


def test_agency_pay(engine):
    case = run_text(engine, "CBI officer here. You are under digital arrest. Transfer Rs 2,00,000 to account 99887766554433 now.")
    s = signal(case, "R-AGENCY-PAY")
    assert s and s.severity == Severity.HARD and s.evidence_key == "claim" and s.citation_verified


def test_state_name_pay(engine):
    """The open-set half of CLAIMED_STATE_AUTHORITY: a body the enum has no row for, demanding money.

    "IRDAI Enforcement Cell, Mumbai" reads as Issuer.OTHER, and previously no rule asking whether a state
    body is demanding money could be asked about it, so the whole class of digital-arrest script built on a body
    the enum does not list landed on GREY. R-AGENCY-PAY carried it at first; the sentence it prints asserts
    what the sender claims to be, and the open-set net reads the form of a name rather than a claim of identity,
    so this is its own rule with its own sentence. Same family, same severity, same AMBER.
    """
    case = run_text(engine, "IRDAI Enforcement Cell, Mumbai. Deposit Rs 2,85,000 into the IRDAI Verification "
                            "Account 50100239847721 today or a PMLA arrest warrant will be issued.")
    assert case.claim.claimed_issuer.value == "OTHER"
    assert signal(case, "R-AGENCY-PAY") is None, "the open-set body has its own rule now"
    s = signal(case, "R-STATE-NAME-PAY")
    assert s and s.severity == Severity.HARD and s.evidence_key == "claim" and s.citation_verified
    assert "carries a government-sounding name" in s.reason_en
    assert "claims to be" not in s.reason_en and "दावा करता है" not in s.reason_hi
    # a lone hard rule is AMBER, and neither the widening nor the split may change that
    assert case.verdict.outcome == Outcome.AMBER


MOTIVATING = ("You are digitally arrested. You have to transfer all your bank account money to me. I am Prime "
              "Minister of India. Mr. Narendra Modi")


def test_digital_arrest_pay(engine):
    """A digital-arrest message used to read GREY: no law-enforcement body was named, so R-AGENCY-PAY could not fire,
    and "arrested" was only a pressure cue. There is no digital arrest in Indian law, so the sentence needs no
    sender. A lone hard rule: AMBER, never RED on its own."""
    case = run_text(engine, MOTIVATING)
    assert case.claim.digital_arrest_span.text == "You are digitally arrested"
    s = signal(case, "R-DIGITAL-ARREST-PAY")
    assert s and s.severity == Severity.HARD and s.evidence_key == "claim" and s.citation_verified
    assert "There is no “digital arrest” in Indian law" in s.reason_en and "a transfer to an account" in s.reason_en
    assert case.verdict.outcome == Outcome.AMBER and case.verdict.anchor_rule == "R-DIGITAL-ARREST-PAY"
    card = engine.card(case, "en")
    assert any(r.rule_id == "R-DIGITAL-ARREST-PAY" for r in card.reasons)


@pytest.mark.parametrize("text", [
    "u r under digital arrest dont tell anyone. transfer 2 lakh to this account today",
    "Do not tell anyone, you are under digital arrest. Transfer Rs 50,000 now.",
    "We have placed you under digital arrest. Transfer the security amount today.",
    "Aap digital arrest mein hain. Turant 2 lakh transfer karein.",
    "आप डिजिटल अरेस्ट में हैं। तुरंत 2 लाख रुपये इस खाते में ट्रांसफर करें।",
])
def test_digital_arrest_pay_reads_the_ways_a_script_says_it(engine, text):
    case = run_text(engine, text)
    assert case.claim.digital_arrest_span is not None, text
    assert case.claim.instruction.value != "NONE", "each line also asks for money"
    assert signal(case, "R-DIGITAL-ARREST-PAY") is not None


@pytest.mark.parametrize("text", [
    "RBI never asks anyone to transfer money for verification, and there is no such thing as digital arrest.",
    "If anyone says you are under digital arrest, hang up and call 1930. Never transfer money to them.",
    "No agency will put you under digital arrest. Do not transfer money to callers.",
    "Agar koi aapko digital arrest ki dhamki de aur paise transfer karne ko kahe, toh 1930 par call karein.",
    "कोई भी एजेंसी आपको डिजिटल अरेस्ट नहीं करती। पैसे ट्रांसफर करने से पहले बैंक से पूछें।",
    "'You are under digital arrest' - no real officer will ever say this. It is a trick to make you transfer money.",
])
def test_digital_arrest_pay_is_silent_on_warnings(engine, text):
    """Bank and I4C awareness messages use the same words to say the opposite; none of them may fire the rule."""
    case = run_text(engine, text)
    assert case.claim.digital_arrest_span is None, (text, case.claim.digital_arrest_span)
    assert signal(case, "R-DIGITAL-ARREST-PAY") is None


def test_digital_arrest_pay_stands_down_for_a_named_agency(engine):
    """R-AGENCY-PAY already says there is no digital arrest, with the agency's name; one sentence, not two."""
    case = run_text(engine, "CBI officer here. You are under digital arrest. Transfer Rs 2,00,000 to account 99887766554433 now.")
    assert case.claim.digital_arrest_span is not None
    assert signal(case, "R-AGENCY-PAY") is not None and signal(case, "R-DIGITAL-ARREST-PAY") is None


def test_digital_arrest_without_a_money_demand_fires_nothing(engine):
    case = run_text(engine, "You are under digital arrest. Stay on the video call.")
    assert case.claim.digital_arrest_span is not None
    assert signal(case, "R-DIGITAL-ARREST-PAY") is None


def test_a_struck_digital_arrest_reading_drops_the_rule(engine):
    case = run_text(engine, MOTIVATING)
    case = engine.strike_field(case, "digital_arrest", "officer.test")
    assert case.claim.digital_arrest_span is None and signal(case, "R-DIGITAL-ARREST-PAY") is None


def test_state_name_pay_is_silent_on_a_body_that_is_not_the_state(engine):
    """The other half: a commercial sender's own unit is not a state authority, so no rule may fire."""
    case = run_text(engine, "Acme Logistics Billing Department. Please transfer Rs 12,500 to the account "
                            "mentioned in the invoice, account 99887766554433.")
    assert case.claim.claimed_issuer.value != "OTHER", case.claim.issuer_span
    assert signal(case, "R-AGENCY-PAY") is None and signal(case, "R-STATE-NAME-PAY") is None


def test_court_pay_is_soft(engine):
    case = run_scenario_id(engine, "S7-court-order")
    s = signal(case, "R-COURT-PAY")
    assert s and s.severity == Severity.SOFT and s.escalate_alone
    assert signal(case, "R-PAYEE-NAME") is None, "the registry account is allow-listed"
    assert case.verdict.outcome == Outcome.AMBER


def test_ed_summons_not_found(engine):
    text = ("DIRECTORATE OF ENFORCEMENT. Summon No. ED/DLZO/2026/4471. Passcode: ZZZZ99. Date 14-10-2026. "
            "Transfer Rs 5,00,000 to account 55443322110099 for verification.")
    case = run_text(engine, text, source="ocr")
    s = signal(case, "R-ED-SUMMONS-NOTFOUND")
    assert s and s.severity == Severity.HARD and s.evidence_key == "issuer:ed_portal"
    # two hard F1 rules on different evidence are still one family: no RED without F2/F3/F4
    assert case.verdict.outcome == Outcome.AMBER


def test_ed_no_passcode_is_amber(engine):
    text = "DIRECTORATE OF ENFORCEMENT. SUMMONS. Summon No. ED/DLZO/2026/4471. Date 14-10-2026. Appear in person on 20-10-2026."
    case = run_text(engine, text, source="ocr")
    s = signal(case, "R-ED-NO-PASSCODE")
    assert s and s.severity == Severity.SOFT and s.escalate_alone
    assert case.verdict.outcome == Outcome.AMBER


def test_ed_window_is_amber(engine):
    case = run_scenario_id(engine, "S5c-ed-summons-1h-old")
    s = signal(case, "R-ED-WINDOW")
    assert s and s.detail["lookup"]["status"] == "NOT_YET"
    assert case.verdict.outcome == Outcome.AMBER


def test_ed_found_is_info(engine):
    case = run_scenario_id(engine, "S5c2-ed-summons-valid")
    s = signal(case, "R-ED-FOUND")
    assert s and s.severity == Severity.INFO
    assert case.verdict.outcome == Outcome.GREY


def test_ed_channel(engine):
    case = run_text(engine, "ED officer on WhatsApp video call: transfer Rs 2,00,000 to account 99887766554433 immediately.")
    s = signal(case, "R-ED-CHANNEL")
    assert s and s.severity == Severity.HARD


def test_rbi_inv(engine):
    assert signal(run_scenario_id(engine, "S2-rbi-video"), "R-RBI-INV").severity == Severity.HARD
    advisory = run_scenario_id(engine, "S5b-real-rbi-advisory")
    assert signal(advisory, "R-RBI-INV") is None, "a genuine RBI advisory mentioning investment must not fire the rule"
    assert advisory.verdict.outcome == Outcome.GREY


def test_sebi_valid(engine):
    s = signal(run_scenario_id(engine, "S2-rbi-video"), "R-SEBI-VALID")
    assert s and s.severity == Severity.SOFT and "rbi.invest@okaxis" in s.reason_en
    ok = run_text(engine, "Invest in our mutual fund SIP, 12% expected returns. Pay to UPI fundhouse.mf@valid")
    assert signal(ok, "R-SEBI-VALID") is None


def test_caller_1600(engine):
    """The rule may only be stated about a bank call, because its reason says "this call" and "banks".

    Three gates, the first two each added after a false positive. First, a pasted bank letter with a helpline
    printed at its foot fired the rule, so the card read "Financial call not from the 1600 series" about a
    letter. Second, a pasted SMS saying "call our helpline" sets the channel to PHONE_CALL out of the message's
    own words, so the card read "This call came from ..." about an SMS. The channel read out of a pasted message
    is a fact about what the message DESCRIBES, never about the artefact in front of the officer. So the
    artefact has to be one that can carry a call (a transcript of one, or the officer's picklist) AND the
    channel has to say the call is a call. The third gate is the issuer: RBI/2024-25/105 directs banks and
    other regulated entities, and a regulator places no service calls to bank customers at all.

    Every gate is asserted in both directions, so none of them can quietly go away.
    """
    on_a_call = "Demo Bank calling about your account. Please call us back on this number today."
    s = signal(run_text(engine, on_a_call, sender="+919876500011", source="transcript"), "R-CALLER-1600")
    assert s and s.severity == Severity.SOFT and s.detail["channel"] == "PHONE_CALL"
    assert "This call came from +919876500011" in s.reason_en
    # a bank service number is what the rule looks for, so the same call from 1600xx does not fire
    assert signal(run_text(engine, on_a_call, sender="1600123456", source="transcript"), "R-CALLER-1600") is None
    # the same words pasted into the text box: a message that mentions calling is not a call
    assert signal(run_text(engine, on_a_call, sender="+919876500011"), "R-CALLER-1600") is None, \
        "an artefact that only describes a call cannot carry the sentence 'this call came from'"
    # an artefact that can carry a call, whose channel does not say one happened
    assert signal(run_text(engine, S1, sender="+919876500011", source="transcript"), "R-CALLER-1600") is None, \
        "a voice note is not a call: the number it came from is a sender, not a caller"
    letter = ("Demo Bank Loan Recovery Cell, Head Office. Your home loan account is overdue by Rs 2,84,000. "
              "You may pay at any branch counter. Helpline 022 4000 1234.")
    assert signal(run_text(engine, letter, sender="+919812345670"), "R-CALLER-1600") is None, \
        "a helpline printed on a letter is not a caller"
    # a real call, read as a call, from a number outside the series - but claiming to be a regulator
    rbi = "This is the Reserve Bank of India calling about your account. Please call us back on this number today."
    assert signal(run_text(engine, rbi, sender="+919876500011", source="transcript"), "R-CALLER-1600") is None, \
        "the 1600 series is a fact about the calls banks place, not about a regulator"


def test_domain_bankin(engine):
    assert signal(run_text(engine, "Demo Bank: update your KYC today at demobank-kyc.com"), "R-DOMAIN-BANKIN") is not None
    assert signal(run_text(engine, "Demo Bank: view your statement at demobank.bank.in"), "R-DOMAIN-BANKIN") is None
    assert signal(run_text(engine, "Demo Bank: view your statement at DemoBank.BANK.IN"), "R-DOMAIN-BANKIN") is None, "host comparison must be case-insensitive"


def test_suspect_registry(engine):
    s = signal(run_scenario_id(engine, "S3-ed-summons"), "R-SUSPECT")
    assert s and s.evidence_key == "registry:suspect" and s.detail["what"] == "account"


def test_bank_never_move_fd(engine):
    s = signal(run_text(engine, S1, sender="+919876500011", source="transcript"), "R-BANK-NEVER-MOVE-FD")
    assert s and s.severity == Severity.HARD


def test_bank_self_not_sent(engine):
    case = run_scenario_id(engine, "S1-rm-voice-note")
    s = signal(case, "R-BANK-SELF")
    assert s and s.severity == Severity.HARD and s.evidence_key == "bank:outbound_log"
    assert case.verdict.outcome == Outcome.RED
    assert {case.verdict.anchor_rule, case.verdict.second_family} == {"R-BANK-NEVER-MOVE-FD", "R-BANK-SELF"}


def test_bank_self_names_the_reach_of_the_record_it_rests_on(engine):
    """"We never sent this message" was categorical over a log that is not. The reason now carries the log's reach
    in the same two sentences as the claim, and the channel list is read off the log's own records rather than
    written in the rulebook, so the card cannot name coverage the record does not have.

    This is the test that catches a bank letter being called something the bank had not sent: the
    boundary clause (a branch letter is outside this log) has to be in the sentence the customer hears.
    """
    log = engine.adapters.outbound_log
    channels = {str(r["channel"]).upper() for r in log.records}
    assert channels, "the mock outbound log declares no channels, so no scope sentence can be true of it"
    assert not channels & {"POST", "BRANCH", "COUNTER", "LETTER"}, \
        "the log now claims a channel the rule's reason says is outside it"

    s = signal(run_text(engine, "Demo Bank Head Office: your home loan is overdue. Pay at any branch counter."), "R-BANK-SELF")
    assert s is not None
    # The claim is still made, and the one boundary the customer needs is in the same breath as it. The first
    # version failed here: it put the computed channel list on the card, and a frightened
    # 70-year-old was read 44 words containing "outbound log" and "IVR". The customer gets the boundary in her
    # own words; the full computed coverage is the officer's, below.
    assert "has no record of sending this message" in s.reason_en
    assert "handed over at a branch" in s.reason_en
    assert "शाखा से हाथ में दिया गया पत्र" in s.reason_hi
    for jargon in ("outbound log", "IVR", "centrally", "आउटबाउंड", "IVR कॉल"):
        assert jargon not in s.reason_en and jargon not in s.reason_hi, f"{jargon!r} is jargon on a customer card"
    # the old categorical sentence is gone from both languages
    assert "It did not come from us" not in s.reason_en
    assert "हमने यह संदेश नहीं भेजा" not in s.reason_hi
    # the officer still gets the full reach, computed from the log's own records
    coverage = s.detail.get("lookup", {}).get("coverage", {})
    assert coverage.get("channels"), "the officer's evidence row lost the computed coverage"
    assert coverage.get("is_mock") is True
    # Every channel the OFFICER's scope clause names is one the log file actually carries, in both languages.
    # That clause moved off the card and into the detail the evidence panel and the signed pack render; the
    # property that matters — the sentence can only name coverage the record has — is unchanged.
    from satyapan.rules import LOG_CHANNEL_EN, LOG_CHANNEL_HI
    scope_en, scope_hi = s.detail["lookup"]["coverage"]["scope_en"], s.detail["lookup"]["coverage"]["scope_hi"]
    for ch in channels:
        assert LOG_CHANNEL_EN[ch] in scope_en, f"{ch} is in the log but not in the English scope clause"
        assert LOG_CHANNEL_HI[ch] in scope_hi, f"{ch} is in the log but not in the Hindi scope clause"
    named_en = {name for ch, name in LOG_CHANNEL_EN.items() if name in scope_en}
    assert named_en == {LOG_CHANNEL_EN[ch] for ch in channels}, \
        "the scope clause names a channel the outbound log does not carry"
    # the officer's expandable row and the evidence pack carry the measured scope, not just the prose
    cov = s.detail["lookup"]["coverage"]
    assert cov["entries"] == len(log.records) and set(cov["channels"]) == channels
    assert cov["retention_days_min"] == min(r["retention_days"] for r in log.records)
    assert cov["is_mock"] is True and cov["source"] == log.label.production_source


def test_bank_self_scope_degrades_to_the_boundary_when_the_log_cannot_be_inspected(engine):
    """A production outbound-log adapter need not expose its records (the protocol is `label` plus `find`). With
    nothing to count, the sentence drops the channel list and keeps the boundary clause, which is the half that
    stops the claim being categorical. It must never fall back to the old "it did not come from us"."""
    from satyapan.rules import SCOPE_FALLBACK_EN, SCOPE_FALLBACK_HI, _log_coverage

    class OpaqueLog:
        label = engine.adapters.outbound_log.label
        def find(self, **kw):           # noqa: D102 - never called here
            return {"found": False, "record": None, "rm_personal_phone": False, "rm": None}

    cov = _log_coverage(OpaqueLog())
    assert cov["channels"] == [] and cov["entries"] == 0 and cov["retention_days_min"] is None
    assert cov["scope_en"] == SCOPE_FALLBACK_EN and cov["scope_hi"] == SCOPE_FALLBACK_HI
    # The customer-facing sentence no longer interpolates the scope at all (that was rejected as jargon
    # on the card), so what has to degrade safely is the officer's coverage record, not the card. The card's
    # boundary clause is fixed copy and is therefore true whether or not the log can be inspected.
    meta = engine.book.meta("R-BANK-SELF")
    for template in (meta.reason_en, meta.reason_hi):
        rendered = template.format(bank="Demo Bank")
        assert "{" not in rendered, "an unfilled placeholder reached a customer-facing sentence"
    assert "handed over at a branch" in meta.reason_en.format(bank="Demo Bank")


def test_bank_self_can_still_anchor_a_red_but_never_on_its_own(engine):
    """Recorded decision: R-BANK-SELF stays hard. The thinness of the record is coverage breadth, which
    the reason now names, not lookup reliability; inside its scope the match is an exact content hash. What keeps
    it safe is structural, and both halves are asserted here: it needs an independent family on different
    evidence, and it needs a money demand to have been read."""
    assert engine.book.meta("R-BANK-SELF").severity == Severity.HARD
    # alone on a message with a money demand: still only AMBER
    alone = run_text(engine, "Demo Bank Head Office. Pay Rs 2,00,000 at any branch counter to close your loan.")
    assert signal(alone, "R-BANK-SELF") is not None
    assert alone.verdict.outcome == Outcome.AMBER
    # with an independent family but no money read: still only AMBER
    no_money = run_text(engine, "Demo Bank: your KYC is due. Update your records at demobank-kyc.com within 7 days.")
    assert {"R-BANK-SELF", "R-DOMAIN-BANKIN"} <= {s.rule_id for s in no_money.verdict.signals}
    assert no_money.verdict.outcome == Outcome.AMBER
    # both: RED, anchored on it
    both = run_text(engine, "Demo Bank: break your FD today and move the money to safe account 50100248891776. "
                            "Confirm at demobank-kyc.com.")
    assert both.verdict.outcome == Outcome.RED
    assert "R-BANK-SELF" in (both.verdict.anchor_rule, both.verdict.second_family)


def test_rm_personal_phone_is_amber(engine):
    case = run_scenario_id(engine, "S1b-rm-own-phone")
    assert signal(case, "R-BANK-SELF") is None
    s = signal(case, "R-BANK-RM-PHONE")
    assert s and s.severity == Severity.SOFT and s.detail["can_be_second"] is False
    assert case.verdict.outcome == Outcome.AMBER


def test_payee_name_private(engine):
    s = signal(run_scenario_id(engine, "S3-ed-summons"), "R-PAYEE-NAME")
    assert s and s.severity == Severity.HARD and "Shiv Shakti Traders" in s.reason_en and s.evidence_key == "bank:name_lookup"


def test_ledger_no_credit(engine):
    case = run_scenario_id(engine, "S6-fake-credit")
    s = signal(case, "R-LEDGER")
    assert s and s.severity == Severity.HARD
    assert case.verdict.outcome == Outcome.AMBER, "one hard rule with no second family"
    # a matching credit within 72 h silences the rule
    engine.adapters.ledger.data = {"cust-demo": [{"at": (NOW - timedelta(hours=5)).isoformat(), "amount": 45000}]}
    case2 = run_scenario_id(engine, "S6-fake-credit")
    assert signal(case2, "R-LEDGER") is None


def test_own_signature_matches(engine):
    text = SCENARIOS["S5a-genuine-bank-notice"]["text"]
    assert run_text(engine, text, signed=True).verdict.outcome == Outcome.MATCHES
    unsigned = run_text(engine, text, signed=False)
    assert unsigned.verdict.outcome == Outcome.GREY
    assert signal(unsigned, "R-BANK-SELF") is None, "the message is in the outbound log"


def test_pressure_cues_info_only(engine):
    s = signal(run_scenario_id(engine, "S3-ed-summons"), "R-PRESSURE-CUES")
    assert s and s.severity == Severity.INFO and s.detail["can_be_second"] is False


def test_challan_official_is_amber_alone(engine):
    """A challan that routes the payment off the official site fires it; the real one, pointing at the site, does not."""
    for tail, kind in ((" Pay now at https://echallan-parivahan.in/pay", "link"),
                       (" For payment call 9876543210.", "phone number")):
        case = run_text(engine, CHALLAN + tail)
        s = signal(case, "R-CHALLAN-OFFICIAL")
        assert s and s.severity == Severity.SOFT and s.escalate_alone and s.citation_verified
        assert s.detail["route_kind"] == kind
        assert case.claim.claimed_issuer.value == "TRANSPORT", "a traffic challan is not a police demand"
        assert signal(case, "R-AGENCY-PAY") is None
        assert case.verdict.outcome == Outcome.AMBER
    # an account or UPI ID to pay into is a route off the site too
    to_account = run_text(engine, CHALLAN + " Deposit the fine in A/c 40920011558866.")
    assert signal(to_account, "R-CHALLAN-OFFICIAL").detail["route_kind"] == "account"
    # the real one points at the official site and fires nothing; its GREY hands her that site
    real = run_text(engine, CHALLAN + " Pay now at https://echallan.parivahan.gov.in")
    assert signal(real, "R-CHALLAN-OFFICIAL") is None and signal(real, "R-DOMAIN-GOVIN") is None
    assert real.verdict.outcome == Outcome.GREY
    assert "echallan.parivahan.gov.in" in engine.card(real, "en").do_now
    # a helpline at the foot of a real challan is not a payment route
    helpline = run_text(engine, CHALLAN + " Pay at https://echallan.parivahan.gov.in. Helpline 8750871111.")
    assert signal(helpline, "R-CHALLAN-OFFICIAL") is None
    # the police stand-down is for the challan only: the CBI does not send challans, and keeps R-AGENCY-PAY
    cbi = run_text(engine, "This is the CBI. Pay the pending challan of Rs 50,000 for your vehicle DL8CAF1234 to "
                           "account 99887766554433 today.")
    assert cbi.claim.claimed_issuer.value == "CBI" and signal(cbi, "R-AGENCY-PAY") is not None


def test_domain_govin(engine):
    fake = run_text(engine, CHALLAN + " Pay now at https://echallan-parivahan.in/pay")
    s = signal(fake, "R-DOMAIN-GOVIN")
    assert s and s.severity == Severity.SOFT and s.citation_verified and "echallan-parivahan.in" in s.reason_en
    assert signal(run_text(engine, CHALLAN + " Pay at https://echallan.parivahan.gov.in"), "R-DOMAIN-GOVIN") is None
    nic = run_text(engine, TAX.format(acct="11220033445566") + " Pay online at https://MCDonline.NIC.in")
    assert signal(nic, "R-DOMAIN-GOVIN") is None, ".nic.in passes, and the host comparison ignores case"
    # RBI's own site is rbi.org.in, so a message in RBI's name is never asked this question
    rbi = run_text(engine, "This is the Reserve Bank of India. Read our advisory at https://www.rbi.org.in today.")
    assert rbi.claim.claimed_issuer.value == "RBI" and signal(rbi, "R-DOMAIN-GOVIN") is None
    # nor is a message that names no government body and asks for no government due
    assert signal(run_text(engine, "Your parcel is waiting. Track it at https://parcel-track.in"), "R-DOMAIN-GOVIN") is None


def test_payee_not_sender(engine):
    """A copied tax notice with the account swapped: no "government account" anywhere in it, and a scammer no list
    knows yet. The bank's look-up still names the account's holder, and it is not the body the notice is from."""
    case = run_text(engine, TAX.format(acct="40920011558866"))
    assert case.claim.claimed_issuer.value == "MUNICIPAL" and case.claim.instruction.value == "PAY_LOCAL_TAX"
    s = signal(case, "R-PAYEE-NOT-SENDER")
    assert s and s.severity == Severity.HARD and s.evidence_key == "bank:name_lookup" and s.citation_verified
    assert "the municipal corporation" in s.reason_en and "Sunil Yadav" in s.reason_en
    assert signal(case, "R-SUSPECT") is None, "a new scammer: the suspect registry does not hold this account"
    assert case.verdict.outcome == Outcome.AMBER, "one hard rule and no second family"
    # a payment link off .gov.in is the independent second family
    linked = run_text(engine, TAX.format(acct="40920011558866") + " Pay online at https://mcd-propertytax.in/pay")
    assert linked.verdict.outcome == Outcome.RED
    assert {linked.verdict.anchor_rule, linked.verdict.second_family} == {"R-PAYEE-NOT-SENDER", "R-DOMAIN-GOVIN"}
    # the body's own collection account is on the bank's official list
    assert signal(run_text(engine, TAX.format(acct="11220033445566")), "R-PAYEE-NOT-SENDER") is None
    # an account the look-up does not hold is UNKNOWN, and never read as private
    assert signal(run_text(engine, TAX.format(acct="12345678901234")), "R-PAYEE-NOT-SENDER") is None
    # the same account in a private sender's bill is that sender's business
    private = run_text(engine, "Acme Interiors: please pay the balance of Rs 12,500 to A/c 40920011558866 by Friday.")
    assert signal(private, "R-PAYEE-NOT-SENDER") is None
    # when the message itself says whose account it is, R-PAYEE-NAME speaks and this one stands down
    said = run_text(engine, TAX.format(acct="50100234567891").replace("to A/c", "to the government account A/c"))
    assert signal(said, "R-PAYEE-NAME") is not None and signal(said, "R-PAYEE-NOT-SENDER") is None


def test_receiver_name(engine):
    """The challan copy with a fake link has no account in it at all. The receiver of the paused payment, which the
    bank reads off its own transfer record, is the check that still runs, and it needs no list of scammers."""
    text = CHALLAN + " Pay now at https://echallan-parivahan.in/pay"
    case = run_paying(engine, text, payee_vpa="challan.clear@okicici")
    s = signal(case, "R-RECEIVER-NAME")
    assert s and s.severity == Severity.HARD and s.evidence_key == "bank:paused_payment" and s.citation_verified
    assert "Vikram Singh" in s.reason_en and "not to a government account" in s.reason_en
    assert case.verdict.outcome == Outcome.RED and case.verdict.anchor_rule == "R-RECEIVER-NAME"
    # the same message with no receiver on the flag stays AMBER
    assert run_text(engine, text).verdict.outcome == Outcome.AMBER
    # paying the body's own collection UPI ID fires nothing
    assert signal(run_paying(engine, text, payee_vpa="mcd.propertytax@sbi"), "R-RECEIVER-NAME") is None
    # a receiver account works the same way as a UPI ID
    assert signal(run_paying(engine, TAX.format(acct="11220033445566"), payee_account="40920011558866"),
                  "R-RECEIVER-NAME") is not None
    # paying a person is ordinary when the message is not in a government body's name and asks for no due
    rent = run_paying(engine, "Hi, please send the rent for October.", payee_vpa="challan.clear@okicici")
    assert signal(rent, "R-RECEIVER-NAME") is None


FINE = "pay your vehicle driving fine , you passes a red light at traffic signal, \npay at {upi} "


def test_a_fake_traffic_fine_is_checked_against_the_banks_own_name_for_the_upi_id(engine):
    """A message typed into the console, verbatim. Two steps: first, is the message trying to look official (a
    traffic fine is); only then, does the receiver's registered name, as the bank's own directory returns it, match
    the government. The mock directory's holder of this UPI ID ("Bhawna", an individual) does not."""
    paid = run_paying(engine, FINE.format(upi="9354209849@slc"), payee_vpa="9354209849@slc")
    assert paid.claim.instruction.value == "PAY_CHALLAN"
    s = signal(paid, "R-RECEIVER-NAME")
    assert s and "Bhawna" in s.reason_en and s.detail["holder_type_en"] == "an individual"
    assert signal(paid, "R-PAYEE-NOT-SENDER") is None, "the same UPI ID is the paused receiver: one reason, not two"
    assert paid.verdict.outcome == Outcome.RED
    assert "Bhawna" in engine.card(paid, "en").read_aloud and "Bhawna" in engine.card(paid, "hi").read_aloud
    # before any payment, the UPI ID written in the message is looked up the same way
    shown = run_text(engine, FINE.format(upi="9354209849@slc"))
    s = signal(shown, "R-PAYEE-NOT-SENDER")
    assert s and "UPI ID" in s.reason_en and "Bhawna" in s.reason_en and "दी गई UPI आईडी" in s.reason_hi
    assert shown.verdict.outcome == Outcome.RED
    # a handle that sounds official is still whoever the bank says it is
    handle = signal(run_text(engine, FINE.format(upi="traffic.fine.helpdesk@ybl")), "R-PAYEE-NOT-SENDER")
    assert handle and "Manoj Kumar" in handle.reason_en
    # the government's own collection ID matches the government: nothing about the payee fires
    real = run_paying(engine, FINE.format(upi="echallan.delhi@sbi"), payee_vpa="echallan.delhi@sbi")
    assert not {"R-RECEIVER-NAME", "R-PAYEE-NOT-SENDER", "R-CHALLAN-OFFICIAL"} & {x.rule_id for x in real.verdict.signals}


def test_an_ordinary_transfer_is_never_compared_with_the_government(engine):
    """The same UPI ID, paid for something ordinary. Nothing in the message tries to look official, so the receiver
    is never compared with anything and nothing fires."""
    sister = run_paying(engine, "Didi, sending you the money for your books and bus pass. Pay the college fee before "
                                "Friday.", payee_vpa="9354209849@slc")
    assert not {"R-RECEIVER-NAME", "R-PAYEE-NOT-SENDER", "R-CHALLAN-OFFICIAL"} & {x.rule_id for x in sister.verdict.signals}
    assert sister.verdict.outcome == Outcome.GREY


def test_a_police_fine_that_threatens_arrest_keeps_the_agency_rule(engine):
    """The police stand-down is for a traffic challan. A "fine" with an arrest threat is a digital-arrest script."""
    case = run_text(engine, "This is the Cyber Crime Police Station. Your vehicle was used in a crime. Pay the fine "
                            "of Rs 50,000 to account 99887766554433 now or you will be arrested.")
    assert case.claim.claimed_issuer.value == "POLICE" and case.claim.instruction.value == "PAY_CHALLAN"
    assert signal(case, "R-AGENCY-PAY") is not None


def test_the_bank_directory_names_every_holder():
    """The mock directory is what a real bank returns for an account or a UPI ID: every entry has a name and a known
    kind of holder, and every official collection account it lists really is a government one."""
    from satyapan.adapters import MockNameLookup
    d = MockNameLookup()
    kinds = {"INDIVIDUAL", "PRIVATE_FIRM", "GOVT", "BANK"}
    for key, rec in list(d.accounts.items()) + list(d.vpas.items()):
        assert rec["holder_name"].strip() and rec["holder_type"] in kinds, key
    for key in d.allow_list:
        rec = d.accounts.get(key) or d.vpas.get(key)
        assert rec and rec["holder_type"] == "GOVT", f"{key} is on the official list but is not a government account"
    assert d.lookup_vpa("9354209849@SLC")["holder_name"] == "Bhawna", "UPI IDs are matched without case"
    assert d.lookup_vpa("nobody.listed@okicici")["status"] == "UNKNOWN", "an ID the bank does not hold is never guessed"


def test_website_new(engine):
    """The registry's own record of a link (recorded answers in the suite, so it never touches the network)."""
    held = run_text(engine, CHALLAN + " Pay now at https://echallanparivahan.in/pay")
    s = signal(held, "R-WEBSITE-NEW")
    assert s and s.severity == Severity.SOFT and s.evidence_key == "web:registry" and s.citation_verified
    assert "registered only" in s.reason_en and "suspended" in s.reason_en and "निलंबित" in s.reason_hi
    missing = signal(run_text(engine, CHALLAN + " Pay now at https://rto-challan-pay.com/pay"), "R-WEBSITE-NEW")
    assert missing and "not registered with any domain registry" in missing.reason_en
    # official sites are never looked up, and an old site the registry says the body itself holds is passed over
    assert signal(run_text(engine, CHALLAN + " Pay at https://echallan.parivahan.gov.in"), "R-WEBSITE-NEW") is None
    kmc = run_text(engine, "Kolkata Municipal Corporation: property tax for 2026-27 is overdue. Pay at https://www.kmcgov.in")
    assert signal(kmc, "R-WEBSITE-NEW") is None and signal(kmc, "R-DOMAIN-GOVIN") is None, \
        "kmcgov.in is held by Kolkata Municipal Corporation according to its registry"
    # a domain nobody has recorded and the network was not asked about: silence, never a guess
    assert signal(run_text(engine, CHALLAN + " Pay at https://never-recorded-example.in"), "R-WEBSITE-NEW") is None
    # not an official-looking message: the link is not looked up at all
    assert signal(run_text(engine, "Track your parcel at https://echallanparivahan.in"), "R-WEBSITE-NEW") is None


def test_a_bank_pointing_at_a_government_site_is_not_a_bank_link(engine):
    """Found by the labelled evaluation: a bank's awareness SMS naming echallan.parivahan.gov.in was flagged."""
    case = run_text(engine, "Demo Bank alert: pay traffic fines only on echallan.parivahan.gov.in.")
    assert signal(case, "R-DOMAIN-BANKIN") is None
    assert signal(run_text(engine, "Demo Bank: update your KYC today at demobank-kyc.com"), "R-DOMAIN-BANKIN") is not None


def test_unverified_citation_is_demoted(tmp_path):
    src = load_rulebook()
    doc = yaml.safe_load(open(src.path, encoding="utf-8"))
    for r in doc["rules"]:
        if r["id"] == "R-AGENCY-PAY":
            r["citation"]["verified"] = False
    p = tmp_path / "rulebook.yaml"
    p.write_text(yaml.safe_dump(doc, allow_unicode=True), encoding="utf-8")
    book = load_rulebook(p)
    assert book.meta("R-AGENCY-PAY").severity == Severity.SOFT
