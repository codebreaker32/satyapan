"""A bank's own transaction SMS reports money that already moved; it does not ask the customer to move any.

Regression: "Rs 5,000 credited to your A/c XX1234 by NEFT. - Demo Bank" gave RED. The bare
payment-rail word (NEFT, IMPS) or "fund transfer", "UPI payment", "FD ... closed" read as TRANSFER_TO_ACCOUNT or
MOVE_FD, R-BANK-NEVER-MOVE-FD fired on it, R-BANK-SELF (outbound-log miss) was the second family, and the card told
the customer to stop her own money. A completed-transaction marker in the same clause now makes that span a report.

The other half matters as much: a demand that sits next to a report, in its own clause or in the same clause with a
demand word, still reads and still gives RED.
"""
from __future__ import annotations

import pytest

from satyapan.extract import RulesExtractor
from satyapan.models import Instruction, Outcome
from tests.conftest import run_text

REPORTS = [
    "Rs 5,000 credited to your A/c XX1234 by NEFT. - Demo Bank",
    "Demo Bank: Rs 10,000 debited from A/c XX1234 via IMPS to Ramesh Kumar. Not you? Call 1800-123-4567.",
    "Demo Bank: Your fund transfer of Rs 3,000 to Sunita is successful.",
    "Demo Bank: Your UPI payment of Rs 250 to swiggy@icici is successful.",
    "Demo Bank: Your FD of Rs 2,00,000 has been closed prematurely as requested and the amount credited to your "
    "savings account.",
    "Demo Bank: Your IMPS limit has been increased to Rs 5,00,000 as requested.",
    "Dear Customer, Rs 85,000 salary credited to your Demo Bank account XX4411 through NEFT on 01-10-2026.",
    "Dear Customer, you have paid Rs 2,000 to account XX7788 via IMPS. - Demo Bank",
]

DEMANDS = [
    "Demo Bank: Rs 10,000 debited from your account. Now transfer Rs 49,000 to safe account 30011223344 today.",
    "Demo Bank: your FD has been closed and the amount must be transferred to safe account 30011223344 today.",
    "Demo Bank: Rs 2,000 credited by NEFT; transfer Rs 49,000 to A/c 30011223344, IFSC DEMO0001234 immediately.",
    # a report and a demand joined by a comma in one sentence: the demand still reads
    "Demo Bank: Rs 49,000 has been debited, to reverse it transfer Rs 1 to account 30011223344 and share the OTP.",
    "Demo Bank: your FD has been closed, so transfer the amount to account 30011223344 for safety.",
    "Your KYC has been completed, transfer Rs 1 to account 30011223344 to activate it. - Demo Bank",
]


@pytest.mark.parametrize("text", REPORTS)
def test_transaction_report_reads_no_instruction(text):
    claim = RulesExtractor().extract(text)
    assert claim.instruction not in (Instruction.TRANSFER_TO_ACCOUNT, Instruction.MOVE_FD), claim.instruction_span


@pytest.mark.parametrize("text", REPORTS)
def test_transaction_report_is_never_red(engine, text):
    case = run_text(engine, text)
    assert case.verdict.outcome is not Outcome.RED
    assert all(s.rule_id != "R-BANK-NEVER-MOVE-FD" for s in case.verdict.signals)


@pytest.mark.parametrize("text", DEMANDS)
def test_demand_next_to_a_report_still_reads(engine, text):
    claim = RulesExtractor().extract(text)
    assert claim.instruction in (Instruction.TRANSFER_TO_ACCOUNT, Instruction.MOVE_FD)
    assert run_text(engine, text).verdict.outcome is Outcome.RED
