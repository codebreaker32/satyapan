"""No raw rule id in anything a person reads.

`verdict.explanation` used to print "R-BANK-RM-PHONE means the customer should verify before paying." An earlier
fix patched one branch of that in the console by swapping ids for rulebook titles at render time, but the engine
string still carried the id, and the explanation also reaches the CLI, `satyapan demo` and the evidence pack. It is
fixed in `fusion` now, at compose time, where the rule's own title is available.

The id is not removed from the data. It stays on `anchor_rule`, on `second_family` and on every `signals[].rule_id`,
which is what the case record and the signed pack carry, and what the officer expands on the signal row.
"""
from __future__ import annotations

import json
import re

import pytest

from satyapan.fusion import FAMILY_WORDS, EVIDENCE_WORDS, _shipped_titles, fuse
from satyapan.models import Claim, Family, Instruction, Issuer, Outcome, Severity, Signal
from satyapan.rulebook import load_rulebook
from tests.conftest import SCENARIOS, run_scenario_id

RULE_ID = re.compile(r"R-[A-Z0-9-]+")
BOOK = load_rulebook()


def customer_facing(card) -> list[tuple[str, str]]:
    """Every string on the card a person hears or reads. `Reason.rule_id` is a structured field, not prose."""
    fields = [("headline", card.headline), ("stop_line", card.stop_line), ("do_now", card.do_now),
              ("coaching", card.coaching or ""), ("read_aloud", card.read_aloud)]
    fields += [(f"reason[{i}]", r.text) for i, r in enumerate(card.reasons)]
    fields += [(f"say_next[{i}]", line) for i, line in enumerate(card.say_next)]
    return fields


@pytest.mark.parametrize("sid", sorted(SCENARIOS))
@pytest.mark.parametrize("lang", ["hi", "en"])
def test_no_rule_id_in_any_customer_facing_string(engine, sid, lang):
    card = engine.card(run_scenario_id(engine, sid), lang)
    for field, text in customer_facing(card):
        assert not RULE_ID.search(text), f"{sid} ({lang}): rule id in {field}: {text!r}"


@pytest.mark.parametrize("sid", sorted(SCENARIOS))
def test_no_rule_id_in_the_verdict_explanation(engine, sid):
    case = run_scenario_id(engine, sid)
    assert not RULE_ID.search(case.verdict.explanation), f"{sid}: {case.verdict.explanation!r}"


@pytest.mark.parametrize("sid", sorted(SCENARIOS))
def test_the_id_is_still_verbatim_in_the_record_and_the_signed_pack(engine, sid):
    """The audit trail cannot lose the id: the explanation stopped being where a human reads it, nothing more."""
    case = run_scenario_id(engine, sid)
    ids = {s.rule_id for s in case.verdict.signals}
    assert ids, f"{sid}: no signals at all"
    pack = json.dumps(engine.evidence_pack(case), ensure_ascii=False)
    for rule_id in ids:
        assert rule_id in pack, f"{sid}: {rule_id} is not in the signed pack"
    if case.verdict.anchor_rule:
        assert case.verdict.anchor_rule in ids


def test_every_shipped_rule_has_a_title_so_no_id_can_fall_through():
    """`_named` falls back to the id for a rule the loaded book does not know. Nothing shipped is unknown."""
    titles = _shipped_titles()
    missing = [rid for rid in BOOK.rules if not titles.get(rid)]
    assert not missing, f"rules with no title would print their id: {missing}"
    assert set(FAMILY_WORDS) == set(Family), "a family with no words would print its code"


def test_every_evidence_key_the_rules_can_produce_has_words():
    """A key with no words prints prettified, which is legible but not written. These are the shipped ones."""
    from satyapan import rules as _rules      # noqa: F401  (registers the rule functions)
    for key in ("claim", "issuer:ed_portal", "registry:suspect", "bank:outbound_log", "bank:name_lookup",
                "bank:ledger", "bank:signature", "memory:template", "flag"):
        assert key in EVIDENCE_WORDS, f"{key} has no words in the explanation"


CLAIM = Claim(source="text", text="x", claimed_issuer=Issuer.CBI, instruction=Instruction.TRANSFER_TO_ACCOUNT)


def _sig(rule_id: str, fam: Family, sev: Severity, key: str, **detail) -> Signal:
    return Signal(rule_id=rule_id, family=fam, severity=sev, evidence_key=key, reason_en="r", reason_hi="र",
                  citation="c", citation_verified=True, escalate_alone=detail.get("escalate_alone", False),
                  detail={"can_be_second": True} | detail)


def test_the_title_substitution_is_what_keeps_the_id_out():
    """Pass titles={} — the state the engine was in before this change — and the id comes straight back. Without
    this, the tests above would pass just as well on an explanation that never named a rule at all."""
    signals = [_sig("R-BANK-RM-PHONE", Family.F2, Severity.SOFT, "bank:outbound_log", escalate_alone=True)]
    leaked = fuse(CLAIM, signals, titles={})
    assert leaked.explanation == "R-BANK-RM-PHONE means the customer should verify before paying."
    assert RULE_ID.search(leaked.explanation)

    named = fuse(CLAIM, signals)
    assert not RULE_ID.search(named.explanation)
    assert "Message came from a relationship manager's personal phone" in named.explanation
    assert named.outcome == leaked.outcome == Outcome.AMBER


def test_every_explanation_branch_names_rules_by_title():
    hard = _sig("R-AGENCY-PAY", Family.F1, Severity.HARD, "claim")
    second = _sig("R-PAYEE-NAME", Family.F2, Severity.SOFT, "bank:name_lookup")
    soft = _sig("R-CALLER-1600", Family.F1, Severity.SOFT, "claim")
    info = _sig("R-ED-FOUND", Family.F1, Severity.INFO, "issuer:ed_portal")
    no_money = Claim(source="text", text="x", claimed_issuer=Issuer.CBI, instruction=Instruction.NONE)
    branches = {
        "red": fuse(CLAIM, [hard, second]),
        # the RED pair capped to AMBER because no money demand was read; it names both rules, so both need titles
        "red capped with no money demand": fuse(no_money, [hard, second]),
        "lone hard": fuse(CLAIM, [hard]),
        "two softs": fuse(CLAIM, [soft, second]),
        "escalate alone": fuse(CLAIM, [_sig("R-COURT-PAY", Family.F1, Severity.SOFT, "claim", escalate_alone=True)]),
        "grey with an info row": fuse(CLAIM, [info]),
    }
    for name, v in branches.items():
        assert not RULE_ID.search(v.explanation), f"{name}: {v.explanation!r}"
        assert "“" in v.explanation or "‘" in v.explanation, f"{name} names no rule at all: {v.explanation!r}"


def test_the_families_and_evidence_read_as_words_not_schema_keys():
    v = fuse(CLAIM, [_sig("R-BANK-SELF", Family.F2, Severity.HARD, "bank:outbound_log"),
                     _sig("R-SUSPECT", Family.F1, Severity.SOFT, "registry:suspect")])
    assert v.outcome == Outcome.RED
    assert "the bank's own records" in v.explanation and "the bank's outbound log" in v.explanation
    assert "F1" not in v.explanation and "F2" not in v.explanation
    assert "evidence:" not in v.explanation and "bank:outbound_log" not in v.explanation
    # the audit fields still carry the ids
    assert (v.anchor_rule, v.second_family) == ("R-BANK-SELF", "R-SUSPECT")
