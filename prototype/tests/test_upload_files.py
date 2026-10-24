"""A judge's own files, as phones and laptops actually write them (bug hunt findings 6, 7, 8, 9/34, 10/26, 11, 12).

- 6: a phone photo (landscape pixels plus EXIF Orientation 6 or 3) was OCR'd sideways and gave GREY.
- 7: a truncated PDF gave 422 and the console said no OCR was installed.
- 8: every PDF showed a raw PIL error with the laptop's upload path, signed into the pack.
- 9 / 34: a file name over 252 UTF-8 bytes gave HTTP 500, after the media was already added to the case.
- 10 / 26: an uploaded .txt was recorded as OCR output.
- 11: a UTF-16 .txt was read as NUL-interleaved bytes and a scam gave GREY.
- 12: a password-locked PDF was refused with a sentence saying it was not a PDF.
"""
from __future__ import annotations

import io

import pytest
from fastapi.testclient import TestClient

from satyapan import api
from satyapan.forensics import DocumentForensics
from satyapan.media import tesseract_cmd
from tests.conftest import SCENARIOS

client = TestClient(api.app)
S3 = SCENARIOS["S3-ed-summons"]["text"]


@pytest.fixture(autouse=True)
def clean_session():
    client.post("/api/demo/reset")
    yield
    client.post("/api/demo/reset")


def open_case() -> str:
    r = client.post("/api/cases", json={"flag": {"reason": "test flag", "amount_inr": 50000, "customer_ref": "cust-demo"}})
    cid = r.json()["case"]["id"]
    client.post(f"/api/cases/{cid}/consent", json={"check": True})
    return cid


def upload(cid, filename, data, content_type, **form):
    return client.post(f"/api/cases/{cid}/media", files={"file": (filename, data, content_type)}, data=form)


def pdf_bytes(text: str, **save) -> bytes:
    pymupdf = pytest.importorskip("pymupdf")
    doc = pymupdf.open()
    doc.new_page().insert_text((72, 72), text, fontsize=11)
    return doc.tobytes(**save)


@pytest.mark.skipif(tesseract_cmd() is None, reason="tesseract binary not installed")
@pytest.mark.parametrize("orientation, rotate", [(6, "ROTATE_90"), (3, "ROTATE_180")])
def test_a_phone_photo_with_exif_rotation_is_read_upright(tmp_path, orientation, rotate):
    from PIL import Image
    from tests.test_ocr import render_notice
    upright = tmp_path / "upright.png"
    render_notice(S3, upright)
    page = Image.open(upright).convert("RGB").transpose(getattr(Image.Transpose, rotate))
    exif = Image.Exif()
    exif[0x0112] = orientation
    buf = io.BytesIO()
    page.save(buf, format="JPEG", quality=95, exif=exif)
    cid = open_case()
    assert upload(cid, "IMG_4412.JPG", buf.getvalue(), "image/jpeg", language="en").status_code == 200
    view = client.post(f"/api/cases/{cid}/run").json()
    assert "ED/DLZO/2026/4471" in view["case"]["claim"]["text"]
    assert view["case"]["verdict"]["outcome"] == "RED"


def test_a_truncated_pdf_is_unreadable_not_missing_ocr():
    cid = open_case()
    r = upload(cid, "notice.pdf", pdf_bytes(S3)[:300], "application/pdf")
    assert r.status_code == 415, r.text
    assert "We could not read 'notice.pdf'" in r.json()["detail"]


def test_a_password_locked_pdf_says_so():
    pymupdf = pytest.importorskip("pymupdf")
    data = pdf_bytes(S3, encryption=pymupdf.PDF_ENCRYPT_AES_256, user_pw="1234", owner_pw="5678")
    r = upload(open_case(), "enc_user.pdf", data, "application/pdf")
    assert r.status_code == 415
    assert "locked with a password" in r.json()["detail"]


def test_a_pdf_gets_a_plain_document_check_reason(tmp_path):
    p = tmp_path / "text1.pdf"
    p.write_bytes(pdf_bytes(S3))
    r = DocumentForensics().analyse(p)
    assert r.status == "abstain" and "PDF" in r.reason and str(tmp_path) not in r.reason
    assert "cannot open" not in r.reason


@pytest.mark.parametrize("pad", [253, 256, 400])
def test_a_long_hindi_file_name_is_kept_not_a_500(pad):
    stem = "डीपफेक वीडियो आरबीआई गवर्नर के नाम पर "
    name = (stem * 20).encode("utf-8")[: pad - 4].decode("utf-8", errors="ignore") + ".txt"
    cid = open_case()
    r = upload(cid, name, S3.encode("utf-8"), "text/plain")
    assert r.status_code == 200, r.text
    media = r.json()["case"]["media"]
    assert len(media) == 1 and media[0]["filename"].endswith(".txt")
    kept = list((api.UPLOADS / cid).iterdir())
    assert len(kept) == 1 and kept[0].read_text(encoding="utf-8") == S3


def test_an_uploaded_txt_is_text_not_ocr():
    cid = open_case()
    upload(cid, "note.txt", S3.encode("utf-8"), "text/plain")
    view = client.post(f"/api/cases/{cid}/run").json()
    assert view["case"]["claim"]["source"] == "text"


@pytest.mark.parametrize("encoding", ["utf-16", "utf-16-be", "utf-8-sig"])
def test_a_utf16_or_bom_txt_is_read_as_written(encoding):
    data = S3.encode(encoding)
    if encoding == "utf-16-be":
        data = b"\xfe\xff" + data
    cid = open_case()
    assert upload(cid, "note.txt", data, "text/plain").status_code == 200
    view = client.post(f"/api/cases/{cid}/run").json()
    assert "\x00" not in view["case"]["claim"]["text"] and view["case"]["claim"]["text"].startswith(S3[:20])
    assert view["case"]["verdict"]["outcome"] == "RED"
