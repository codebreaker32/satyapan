"""Two media files of the same kind are each named, never merged into one check saying two things."""
from __future__ import annotations

from satyapan.forensics import ForensicResult
from satyapan.fusion import fuse
from satyapan.models import Claim, Grounded, Instruction, Payee, Span
from satyapan.pipeline import to_signal
from satyapan.rulebook import load_rulebook

BOOK = load_rulebook()
CLAIM = Claim(source="text", text="x", instruction=Instruction.TRANSFER_TO_ACCOUNT,
              payee=Payee(account=Grounded(value="123456789012", span=Span(text="123456789012", start=0, end=12))))
CLEAN = to_signal(BOOK, ForensicResult("audio", "clean", score=0.05, model="m", cell="hi/clean"))
FLAGGED = to_signal(BOOK, ForensicResult("audio", "synthetic", band="moderate", score=0.99, model="m", cell="hi/clean"))
UNSURE = to_signal(BOOK, ForensicResult("audio", "abstain", reason="r", model="m"))


def test_a_clean_voice_note_beside_a_flagged_one_is_another_check():
    v = fuse(CLAIM, [CLEAN, FLAGGED])
    assert "The media shows" in v.explanation
    assert "Media checks: the voice check found no signs" not in v.explanation
    assert "another voice check found no signs" in v.explanation


def test_an_unsure_and_a_clean_voice_note_are_both_named():
    v = fuse(CLAIM, [UNSURE, CLEAN])
    assert "the voice check abstained" in v.explanation and "another voice check found no signs" in v.explanation


def test_one_voice_note_reads_as_before():
    v = fuse(CLAIM, [CLEAN])
    assert "Media checks: the voice check found no signs." in v.explanation
