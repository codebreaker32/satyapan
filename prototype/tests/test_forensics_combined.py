"""Lane 1's two tests, combined (Bhawna, 24 Oct 2026): the instruction checks and the deepfake check count half each
when media was attached and judged, and 40% or more is RED. With no media, or none the detector could judge, the
instruction checks decide alone, exactly as before."""
import pytest
from PIL import Image, PngImagePlugin

from satyapan.forensics import DocumentForensics, ForensicResult, deepfake_pct, to_signal
from satyapan.fusion import RED_LINE_PCT, fuse, instruction_pct
from satyapan.models import Claim, Family, Instruction, Issuer, Outcome, Severity, Signal
from satyapan.rulebook import load_rulebook

BOOK = load_rulebook()
CLAIM = Claim(source="text", text="x", claimed_issuer=Issuer.ED, instruction=Instruction.TRANSFER_TO_ACCOUNT)
NO_MONEY = Claim(source="text", text="x", claimed_issuer=Issuer.ED, instruction=Instruction.NONE)


def rule(rid, fam, sev, key, **detail):
    return Signal(rule_id=rid, family=fam, severity=sev, evidence_key=key, reason_en="r", reason_hi="र", citation="c",
                  citation_verified=True, escalate_alone=detail.pop("escalate_alone", False),
                  detail={"can_be_second": True} | detail)


RED_PAIR = [rule("A", Family.F1, Severity.HARD, "claim"), rule("B", Family.F2, Severity.SOFT, "bank:name_lookup")]
ONE_HARD = [rule("A", Family.F1, Severity.HARD, "claim")]
TWO_SOFT = [rule("A", Family.F1, Severity.SOFT, "claim"), rule("B", Family.F2, Severity.SOFT, "bank:ledger")]


def voice(status, band=""):
    reason = "too short" if status == "abstain" else ""
    return to_signal(BOOK, ForensicResult("audio", status, band=band, reason=reason, model="stub", cell="hi/clean"))


@pytest.mark.parametrize("rules, pct", [(RED_PAIR, 90), (ONE_HARD, 70), (TWO_SOFT, 50),
                                        ([rule("E", Family.F1, Severity.SOFT, "claim", escalate_alone=True)], 50),
                                        ([rule("S", Family.F1, Severity.SOFT, "claim")], 20), ([], 0)])
def test_instruction_pct_follows_the_rule_ladder(rules, pct):
    assert instruction_pct(rules) == pct


@pytest.mark.parametrize("status, band, pct", [("synthetic", "high", 100), ("synthetic", "moderate", 70),
                                               ("clean", "", 0), ("abstain", "", None)])
def test_deepfake_pct_comes_from_the_calibrated_band_not_the_raw_score(status, band, pct):
    res = ForensicResult("audio", status, band=band, score=0.99, reason="unsure" if status == "abstain" else "")
    assert deepfake_pct(res) == pct and voice(status, band).detail["deepfake_pct"] == pct


@pytest.mark.parametrize("rules, media, outcome, combined", [
    (RED_PAIR, voice("clean"), Outcome.RED, 45),                 # fake ED order, real voice
    (ONE_HARD, voice("clean"), Outcome.AMBER, 35),               # one hard rule, real voice
    (ONE_HARD, voice("synthetic", "moderate"), Outcome.RED, 70),  # one hard rule, cloned voice
    ([], voice("synthetic", "high"), Outcome.RED, 50),           # nothing in the text, very strong clone
    ([], voice("synthetic", "moderate"), Outcome.AMBER, 35),     # nothing in the text, moderate clone
    ([], voice("clean"), Outcome.GREY, 0),                       # nothing at all
    (TWO_SOFT, voice("clean"), Outcome.AMBER, 25),
])
def test_the_examples_in_the_plan(rules, media, outcome, combined):
    v = fuse(CLAIM, rules + [media])
    assert v.outcome == outcome and v.scores["combined_pct"] == combined
    assert f"combined {combined:g}%" in v.explanation


def test_bhawnas_example_80_percent_instruction_and_no_deepfake_is_red():
    assert 0.5 * 80 + 0.5 * 0 >= RED_LINE_PCT


def test_no_media_or_unjudged_media_leaves_the_instruction_verdict_alone():
    for rules in (RED_PAIR, ONE_HARD, TWO_SOFT, []):
        alone = fuse(CLAIM, rules)
        unsure = fuse(CLAIM, rules + [voice("abstain")])
        assert alone.scores is None and unsure.scores is None
        assert alone.outcome == unsure.outcome


def test_with_several_files_the_most_fake_one_counts():
    v = fuse(CLAIM, ONE_HARD + [voice("clean"), voice("synthetic", "moderate")])
    assert v.scores["deepfake_pct"] == 70 and v.outcome == Outcome.RED


def test_a_combined_red_with_no_money_demand_stops_at_amber():
    v = fuse(NO_MONEY, [voice("synthetic", "high")])
    assert v.outcome == Outcome.AMBER and "nothing in this message asked for money" in v.explanation


def test_the_banks_own_message_stays_matches_unless_the_media_is_fake():
    m = rule("R-OWN-SIGNATURE", Family.F2, Severity.MATCH, "bank:signature")
    assert fuse(CLAIM, [m, voice("clean")]).outcome == Outcome.MATCHES
    assert fuse(CLAIM, [m, voice("synthetic", "moderate")]).outcome == Outcome.AMBER


def test_scores_never_reach_the_customer_card():
    from satyapan.card import build_card
    card = build_card(fuse(CLAIM, RED_PAIR + [voice("clean")]), CLAIM, "en")
    assert "%" not in card.model_dump_json()


def test_an_ai_label_in_a_png_is_a_deepfake(tmp_path):
    info = PngImagePlugin.PngInfo()
    info.add_text("Software", "Made with Midjourney v7")
    path = tmp_path / "notice.png"
    Image.new("RGB", (800, 800), "white").save(path, pnginfo=info)
    res = DocumentForensics().analyse(path)
    assert res.status == "synthetic" and res.band == "high" and res.extra["ai_tool"] == "Midjourney"
    s = to_signal(BOOK, res)
    assert s.rule_id == "R-DOC-AI" and s.detail["deepfake_pct"] == 100 and "Midjourney" in s.reason_en


def test_a_content_credentials_label_is_read_and_a_plain_png_is_not(tmp_path):
    info = PngImagePlugin.PngInfo()
    info.add_text("XML:com.adobe.xmp", '<x:xmpmeta><Iptc4xmpExt:DigitalSourceType>http://cv.iptc.org/newscodes/'
                  'digitalsourcetype/trainedAlgorithmicMedia</Iptc4xmpExt:DigitalSourceType></x:xmpmeta>')
    labelled, plain = tmp_path / "a.png", tmp_path / "b.png"
    Image.new("RGB", (800, 800), "white").save(labelled, pnginfo=info)
    Image.new("RGB", (800, 800), "white").save(plain)
    assert DocumentForensics().analyse(labelled).status == "synthetic"
    assert DocumentForensics().analyse(plain).status != "synthetic"


def test_an_unverified_rule_counts_zero_so_it_never_helps_a_red():
    s = rule("A", Family.F1, Severity.SOFT, "claim")
    s.citation_verified = False
    v = fuse(CLAIM, [s, voice("synthetic", "moderate")])
    assert v.scores["instruction_pct"] == 0 and v.outcome == Outcome.AMBER
