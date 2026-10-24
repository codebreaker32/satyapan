import json
from datetime import timedelta

from satyapan.extract import RulesExtractor
from satyapan.memory import CampaignMemory
from satyapan.pipeline import DATA_DIR
from tests.conftest import NOW, SCENARIOS, run_scenario_id, signal

X = RulesExtractor(bank_names=("Demo Bank",))


def test_campaign_match(engine):
    s = signal(run_scenario_id(engine, "S3-ed-summons"), "R-CAMPAIGN-MATCH")
    assert s and s.detail["n"] == 4 and s.detail["entry_id"] == "CM-0001"
    s2 = signal(run_scenario_id(engine, "S2-rbi-video"), "R-CAMPAIGN-MATCH")
    assert s2 and s2.detail["entry_id"] == "CM-0002"


def test_pending_and_expired_entries_do_not_match(tmp_path):
    src = json.loads((DATA_DIR / "mocks" / "campaign_memory.json").read_text(encoding="utf-8"))
    for e in src["entries"]:
        if e["id"] == "CM-0001":
            e["last_seen"] = (NOW - timedelta(days=120)).isoformat()   # expired
    p = tmp_path / "mem.json"
    p.write_text(json.dumps(src), encoding="utf-8")
    mem = CampaignMemory(p, now=NOW)
    claim = X.extract(SCENARIOS["S3-ed-summons"]["text"])
    assert mem.match(claim) is None
    pending = X.extract("Your SIM will be blocked in 2 hours due to illegal activity. Press 9 to speak to the telecom officer.")
    assert mem.match(pending) is None, "a pending entry (one approval) never matches"


def test_a_known_script_with_a_new_account_says_what_changed(engine):
    """S3 is the confirmed CM-0001 letter with a different account in it: the same script, a receiver nobody has
    reported yet. Numbers stay out of the text comparison so it still matches, and the match says what changed."""
    s = signal(run_scenario_id(engine, "S3-ed-summons"), "R-CAMPAIGN-MATCH")
    assert s.detail["changed"] == [{"what": "account", "now": "30011223344556", "before": "30019988776655"}]
    assert s.reason_en.endswith("This time the account is different.")
    assert s.reason_hi.endswith("इस बार इसमें खाता अलग है।")
    # nothing changed, nothing said
    s2 = signal(run_scenario_id(engine, "S2-rbi-video"), "R-CAMPAIGN-MATCH")
    assert s2.reason_en == "A message like this one has been seen in 2 earlier cases confirmed by the bank."


def test_a_disguised_copy_still_matches():
    """Look-alike letters, a zero-width space and leetspeak: the same letter to a reader, and to the raw word overlap
    that shipped before 23 Oct a different one. The control half shows the raw measure really did miss it."""
    from satyapan.memory import jaccard, tokens
    mem = CampaignMemory(DATA_DIR / "mocks" / "campaign_memory.json", now=NOW)
    template = next(e for e in mem.entries if e["id"] == "CM-0001")["template_text"]
    disguised = template.replace("o", "о").replace("e", "​e").replace("transfer", "tr4nsfer")
    assert jaccard(tokens(disguised), tokens(template)) < mem.text_threshold, "control: raw words miss the copy"
    hit = mem.match(X.extract(disguised))
    assert hit and hit["entry"]["id"] == "CM-0001"


def test_a_misspelt_copy_matches_on_character_runs():
    mem = CampaignMemory(DATA_DIR / "mocks" / "campaign_memory.json", now=NOW)
    template = next(e for e in mem.entries if e["id"] == "CM-0001")["template_text"]
    typos = {"Enforcement": "Enforcment", "transfer": "transfr", "supervision": "supervison", "laundering": "laundring",
             "verification": "verfication", "refundable": "refundabel", "disclose": "discloze", "digital": "digitl",
             "arrest": "arest", "amount": "amout"}
    for right, wrong in typos.items():
        template = template.replace(right, wrong)
    hit = mem.match(X.extract(template))
    assert hit and hit["entry"]["id"] == "CM-0001"


def test_the_same_receiver_matches_whatever_the_words():
    """A confirmed case's account, in a message that shares none of its words, is still the same receiver."""
    mem = CampaignMemory(DATA_DIR / "mocks" / "campaign_memory.json", now=NOW)
    hit = mem.match(X.extract("Hi beta, send the money for the hospital to A/c 30019988776655 today please."))
    assert hit and hit["entry"]["id"] == "CM-0001" and hit["how"] == "same account"


def test_the_original_a_scam_copied_is_not_seen_before(tmp_path):
    """A confirmed copy of a real tax notice matches the real notice word for word. Its account is the corporation's
    own collection account, which the bank's look-up lists as official, so the text alone may not call it seen."""
    scam = ("Municipal Corporation of Delhi. Property tax notice 2026-27. Pay your house tax of Rs 12,500 before 31 Oct "
            "to A/c 40920011558866, IFSC HDFC0000213, to avoid penalty.")
    mem = CampaignMemory(tmp_path / "mem.json", now=NOW)
    e = mem.propose(X.extract(scam), "analyst.a")
    mem.approve(e["id"], "analyst.b")
    real = X.extract(scam.replace("40920011558866", "11220033445566"))
    assert mem.match(real, official={"11220033445566"}) is None
    # the same words with another private account are still the copy, and say so
    again = mem.match(X.extract(scam.replace("40920011558866", "20098765432109")))
    assert again and again["changed"][0]["what"] == "account"


def test_no_benign_control_is_seen_before(engine):
    for sid in ("S5a-genuine-bank-notice", "S5b-real-rbi-advisory", "S5c-ed-summons-1h-old", "S5c2-ed-summons-valid",
                "S5e-genuine-sms-1600", "S5f-court-hearing-notice", "S5g-it-refund-processed", "S5h-it-refund-probe",
                "S9b-house-tax-official", "S10c-echallan-official"):
        assert signal(run_scenario_id(engine, sid), "R-CAMPAIGN-MATCH") is None, sid


def test_two_person_rule(tmp_path):
    mem = CampaignMemory(tmp_path / "mem.json", now=NOW)
    claim = X.extract("Your parcel with drugs was seized by customs. Pay the clearance fee of Rs 25,000 to account 12345678901234.")
    e = mem.propose(claim, "analyst.a")
    assert e["status"] == "pending" and mem.match(claim) is None
    mem.approve(e["id"], "analyst.a")          # the same person again does not count
    assert mem.entries[-1]["status"] == "pending"
    mem.approve(e["id"], "analyst.b")
    assert mem.entries[-1]["status"] == "confirmed"
    assert mem.match(claim)["entry"]["id"] == e["id"]
