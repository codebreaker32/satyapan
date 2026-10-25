"""A link, host or ID the sender chose never stops the customer card from being built.

Regression: a KYC link "https://demobank-fraud-check.com/kyc" (or www.cbi-criminal-case.com) was quoted in
the .bank.in / .gov.in reason, lint_card found "fraud" / "criminal" in it and raised, and the run and every later
GET of the case returned HTTP 500. The lint still catches a banned word the card itself would say.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from satyapan import api
from satyapan.card import Card, Reason, lint_card
from satyapan.models import Outcome
from tests.conftest import run_text

TEXTS = [
    "Dear customer, this is Demo Bank. Your account will be blocked today. Complete your KYC at "
    "https://demobank-fraud-check.com/kyc and pay Rs 10 to account 50100234567812 IFSC HDFC0001234.",
    "This is CBI. A criminal case is registered against your Aadhaar. See the case file at www.cbi-criminal-case.com "
    "and pay a security deposit of Rs 2,00,000 to avoid arrest.",
    "Delhi Police Cyber Cell: settle your case at www.genuine-police-scam-desk.com today or face arrest.",
]


@pytest.mark.parametrize("text", TEXTS)
@pytest.mark.parametrize("lang", ["en", "hi"])
def test_card_builds_when_a_quoted_link_holds_a_banned_word(engine, text, lang):
    case = run_text(engine, text)
    card = engine.card(case, lang)
    assert card.reasons


def test_case_view_is_200_through_the_api():
    client = TestClient(api.app)
    case = run_text(api.engine, TEXTS[0])
    r = client.get(f"/api/cases/{case.id}")
    assert r.status_code == 200
    assert r.json()["case"]["verdict"]["outcome"] in ("RED", "AMBER")


def test_a_banned_word_the_card_itself_says_still_raises():
    card = Card(lang="en", outcome=Outcome.RED, headline="h", stop_line="s", do_now="d", read_aloud="x",
                reasons=[Reason(text="This message is a fraud.", cite="c", rule_id="R")])
    with pytest.raises(ValueError):
        lint_card(card, quoted_from="This message is a fraud.")
