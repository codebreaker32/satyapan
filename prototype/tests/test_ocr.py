"""The real OCR path: render the S3 summons TEXT to a synthetic PNG (plain white page, black DejaVu text, a diagonal
SYNTHETIC watermark — no logos, no emblems, no official's name), run tesseract through satyapan.media, and check the
extractor still finds the fields the rules rest on. Skips cleanly where pytesseract or the tesseract binary is absent."""
import textwrap
from pathlib import Path

import pytest

pytesseract = pytest.importorskip("pytesseract")

from satyapan.media import ingest, tesseract_cmd  # noqa: E402

# The engine's own finder: PATH, then the Windows install folders the installer uses without touching PATH.
pytestmark = pytest.mark.skipif(tesseract_cmd() is None, reason="tesseract binary not installed")

from satyapan.models import ClaimedOwner, Flag, Issuer  # noqa: E402
from tests.conftest import SCENARIOS  # noqa: E402

# DejaVu on Linux; Arial, the plain sans-serif every Windows install ships, on the finale laptop.
FONT_PATHS = ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "/usr/share/fonts/dejavu/DejaVuSans.ttf",
              "/usr/share/fonts/TTF/DejaVuSans.ttf", "C:/Windows/Fonts/arial.ttf")


def _font(size: int):
    from PIL import ImageFont
    for p in FONT_PATHS:
        if Path(p).exists():
            return ImageFont.truetype(p, size)
    pytest.skip("no DejaVu font on this box")


def render_notice(text: str, path: Path) -> None:
    """Plain synthetic notice: black text on white at a size tesseract reads reliably, SYNTHETIC watermark behind."""
    from PIL import Image, ImageDraw
    lines = textwrap.wrap(text, width=58)
    width, line_h, margin = 1200, 48, 80
    height = 2 * margin + line_h * len(lines)
    img = Image.new("RGBA", (width, height), "white")
    watermark = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    ImageDraw.Draw(watermark).text((width // 2, height // 2), "SYNTHETIC", font=_font(110), fill=(0, 0, 0, 40), anchor="mm")
    img = Image.alpha_composite(img, watermark.rotate(30, center=(width // 2, height // 2)))
    draw, body = ImageDraw.Draw(img), _font(32)
    for i, line in enumerate(lines):
        draw.text((margin, margin + i * line_h), line, font=body, fill="black")
    img.convert("RGB").save(path)


@pytest.fixture(scope="module")
def summons_png(tmp_path_factory) -> Path:
    path = tmp_path_factory.mktemp("ocr") / "ED_summons_synthetic.png"
    render_notice(SCENARIOS["S3-ed-summons"]["text"], path)
    return path


# language="en" because the S3 notice is English: the hin+eng model used for Devanagari notices reads the Latin
# digit "1" unreliably (ED/DLZO/2026/4471 -> .../447), so the officer's language choice matters and is a real input.

def test_ingest_runs_tesseract_and_records_engine(summons_png):
    ref = ingest(summons_png, language="en")   # no derived_text: the real OCR path
    assert ref.kind == "image"
    assert ref.derived_text_engine is not None and ref.derived_text_engine.startswith("tesseract ")
    assert "SUMMONS" in ref.derived_text.upper()
    assert "ED/DLZO/2026/4471" in ref.derived_text


def test_ocr_text_extracts_summons_and_payee(engine, summons_png):
    sc = SCENARIOS["S3-ed-summons"]
    case = engine.open_case(Flag(**sc["flag"]))
    engine.set_consent(case, check=True)
    engine.add_media(case, summons_png, language="en")   # no derived_text: tesseract reads the image
    engine.run(case)

    assert case.media[0].derived_text_engine.startswith("tesseract ")
    c = case.claim
    assert c.source == "ocr"
    assert c.claimed_issuer == Issuer.ED
    assert c.mentions_summons
    assert c.document_ids.summons_no.value == "ED/DLZO/2026/4471"
    assert c.payee.account.value == "30011223344556"
    # OCR wraps the line mid-phrase ("RBI\nsupervision account"); the owner claim must still extract so the RED
    # rests on the designed second family, not on campaign memory and its 90-day fixture TTL
    assert c.payee.claimed_owner == ClaimedOwner.RBI
    assert case.verdict.outcome.value == sc["expect"]   # RED: same verdict as the pre-written transcript
    assert case.verdict.anchor_rule == "R-AGENCY-PAY"
    assert case.verdict.second_family == "R-PAYEE-NAME"
    second = next(s for s in case.verdict.signals if s.rule_id == "R-PAYEE-NAME")
    assert second.evidence_key == "bank:name_lookup"
    # the deck's "campaign-memory match on a re-upload": an uploaded render of the forged summons fires F4
    assert any(s.rule_id == "R-CAMPAIGN-MATCH" for s in case.verdict.signals)

    # the provenance travels into the evidence pack, so the pack names the real engine
    pack = engine.evidence_pack(case)
    assert pack["manifest"]["case"]["media"][0]["derived_text_engine"].startswith("tesseract ")
