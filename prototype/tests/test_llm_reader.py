"""The offline helper reader (llm_reader.py), against a stub of Ollama's /api/chat: it fills only what the rules left
empty with no candidate, every field quotes the message, a named agency can only ever become OTHER, and with no model
the rules' reading stands alone."""
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from satyapan.extract import ground
from satyapan.llm_reader import LocalLLMReader, find_span, instruction_for
from satyapan.models import Instruction, Issuer, Outcome
from tests.conftest import run_text, signal

EMPTY = {"sender_words": "", "sender_is_government": False, "money_request_words": "", "digital_arrest": False,
         "digital_arrest_words": ""}


@pytest.fixture
def stub():
    """An Ollama stand-in on a free port; set `answer` to what the model "says"."""
    state = {"answer": dict(EMPTY), "calls": 0}

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            self.rfile.read(int(self.headers.get("Content-Length", 0)))
            state["calls"] += 1
            body = json.dumps({"message": {"content": json.dumps(state["answer"])}}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *a):
            pass

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    state["url"] = f"http://127.0.0.1:{httpd.server_address[1]}"
    yield state
    httpd.shutdown()


def with_reader(engine, stub):
    engine.reader = LocalLLMReader("stub-model", url=stub["url"], timeout=5)
    return engine


def test_the_reader_is_off_unless_switched_on(engine):
    assert engine.reader is None


def test_a_government_name_the_rules_cannot_read_becomes_other_and_is_quoted(engine, stub):
    text = "Main PMO se bol raha hoon. Aapke naam par case hai, abhi 50000 rupaye bhejiye warna giraftari hogi."
    stub["answer"] = {**EMPTY, "sender_words": "PMO", "sender_is_government": True,
                      "money_request_words": "50000 rupaye bhejiye"}
    case = run_text(with_reader(engine, stub), text)
    c = case.claim
    assert c.claimed_issuer == Issuer.OTHER and c.issuer_span.text == "PMO"
    assert c.instruction == Instruction.TRANSFER_TO_ACCOUNT and c.instruction_span.text == "50000 rupaye bhejiye"
    assert set(c.read_by_llm) == {"claimed_issuer", "instruction"}
    assert c.extractor == "rules-1.0 + stub-model (offline, quote-checked)"
    assert ground(c.model_copy(deep=True)).claimed_issuer == Issuer.OTHER, "every filled span passes ground()"
    s = signal(case, "R-STATE-NAME-PAY")
    assert s is not None and case.verdict.outcome == Outcome.AMBER


def test_it_never_overrides_what_the_rules_read(engine, stub):
    stub["answer"] = {**EMPTY, "sender_words": "Prime Minister", "sender_is_government": True,
                      "money_request_words": "Transfer Rs 2,00,000"}
    case = run_text(with_reader(engine, stub), "CBI officer here. Transfer Rs 2,00,000 to account 99887766554433 now.")
    assert case.claim.claimed_issuer == Issuer.CBI and case.claim.read_by_llm == []
    assert stub["calls"] == 0, "nothing was empty, so the model was not asked"


def test_words_that_are_not_in_the_message_are_dropped(engine, stub):
    stub["answer"] = {**EMPTY, "sender_words": "Ministry of Finance", "sender_is_government": True,
                      "money_request_words": "send the money now"}
    case = run_text(with_reader(engine, stub), "Hello, this is about your parcel. Reply soon.")
    assert case.claim.claimed_issuer == Issuer.NONE and case.claim.instruction == Instruction.NONE
    assert case.claim.read_by_llm == [] and case.claim.extractor == "rules-1.0"


def test_a_suppressed_rules_reading_is_never_asked_about(engine, stub):
    """The rules saw "transfer" and set it aside (a warning, not a request): that choice stands."""
    stub["answer"] = {**EMPTY, "money_request_words": "transfer money"}
    case = run_text(with_reader(engine, stub), "RBI never asks anyone to transfer money for verification.")
    assert case.claim.instruction == Instruction.NONE and "instruction" not in case.claim.read_by_llm


def test_a_digital_arrest_reading_must_quote_the_phrase_and_not_be_a_warning(engine, stub):
    text = "Digital arrest order issued against your Aadhaar. Transfer Rs 2,00,000 to account 99887766554433 now."
    stub["answer"] = {**EMPTY, "digital_arrest": True, "digital_arrest_words": "Digital arrest order issued"}
    case = run_text(with_reader(engine, stub), text)
    assert case.claim.digital_arrest_span.text == "Digital arrest" and "digital_arrest_span" in case.claim.read_by_llm
    assert signal(case, "R-DIGITAL-ARREST-PAY") is not None

    stub["answer"] = {**EMPTY, "digital_arrest": True, "digital_arrest_words": "there is no digital arrest"}
    case = run_text(engine, "Remember, there is no digital arrest. Transfer requests on calls are tricks.")
    assert case.claim.digital_arrest_span is None


def test_no_model_means_the_rules_reading_stands(engine):
    engine.reader = LocalLLMReader("missing", url="http://127.0.0.1:9", timeout=1)
    case = run_text(engine, "Main PMO se bol raha hoon. abhi 50000 rupaye bhejiye.")
    assert case.claim.read_by_llm == [] and case.claim.extractor == "rules-1.0"


@pytest.mark.parametrize("words, kind", [("pay the verification fee of Rs 5,000", Instruction.PAY_FEE_TO_VERIFY),
                                         ("invest 1 lakh for 30% returns", Instruction.INVEST_FOR_RETURNS),
                                         ("50000 rupaye bhejiye", Instruction.TRANSFER_TO_ACCOUNT),
                                         ("break your FD and send it", Instruction.MOVE_FD)])
def test_the_kind_of_request_comes_from_its_own_words(words, kind):
    assert instruction_for(words) == kind


def test_find_span_quotes_the_original_characters():
    text = "Main  PMO se bol raha hoon"
    span = find_span(text, "pmo se")
    assert span.text == "PMO se" and text[span.start:span.end] == span.text
    assert find_span(text, "CBI") is None and find_span(text, "ab") is None


def test_a_bank_letters_order_form_is_never_read_into_a_demand(engine, stub):
    """Measured on 24 Oct with the real model: the genuine EMI letter V73 had its order form read as a transfer, which
    paired with the bank-record rules into a RED. Beside the bank's own name the reader now fills no instruction."""
    text = ("Demo Bank: You must push Rs 12,000 into the designated EMI collection account 50100234567891 before "
            "25 November.")
    stub["answer"] = {**EMPTY, "money_request_words": "push Rs 12,000 into the designated EMI collection account"}
    case = run_text(with_reader(engine, stub), text)
    assert case.claim.claimed_issuer == Issuer.BANK_SELF and case.claim.instruction == Instruction.NONE
    assert case.verdict.outcome != Outcome.RED


def test_a_model_read_government_due_is_dropped(engine, stub):
    """A challan or tax would switch on the receiver-name rule (bank-record family) on a model's reading alone."""
    stub["answer"] = {**EMPTY, "sender_words": "Nagar Nigam", "sender_is_government": True,
                      "money_request_words": "jama karein property tax 5000"}
    case = run_text(with_reader(engine, stub), "Nagar Nigam: aaj hi jama karein property tax 5000.")
    assert case.claim.instruction == Instruction.NONE
