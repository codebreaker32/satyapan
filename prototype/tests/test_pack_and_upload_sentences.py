"""Small truths the bug hunt's raw list found (raw findings 21 and 41).

- 21: the lenient base64 decoder let an altered signature text still verify ('!' or a newline inserted, bytes after
  the padding, a different last character that decodes to the same bytes).
- 41: the size refusal for a Hindi .txt reported its byte count as characters.
"""
from __future__ import annotations

import copy

import pytest
from fastapi.testclient import TestClient

from satyapan import api
from satyapan.evidence import verify_pack
from tests.conftest import run_scenario_id


def _alter(value: str, how: str) -> str:
    if how == "bang":
        return value[:10] + "!" + value[10:]
    if how == "newline":
        return value[:10] + "\n" + value[10:]
    if how == "after_padding":
        return value + "AAAA"
    raise ValueError(how)


@pytest.mark.parametrize("how", ["bang", "newline", "after_padding"])
@pytest.mark.parametrize("field", ["value", "public_key"])
def test_altered_signature_text_does_not_verify(engine, how, field):
    pack = engine.evidence_pack(run_scenario_id(engine, "S3-ed-summons"))
    key = engine.signer.public_key_b64()
    assert verify_pack(pack, key)[0]
    bad = copy.deepcopy(pack)
    bad["signature"][field] = _alter(bad["signature"][field], how)
    assert not verify_pack(bad, key if field == "value" else None)[0]


def test_txt_size_refusal_counts_bytes_as_bytes():
    client = TestClient(api.app)
    cid = client.post("/api/cases", json={"flag": {"reason": "t", "amount_inr": 1, "customer_ref": "x"}}).json()["case"]["id"]
    data = ("डिजिटल अरेस्ट " * 20000).encode("utf-8")
    r = client.post(f"/api/cases/{cid}/media", files={"file": ("long.txt", data, "text/plain")})
    assert r.status_code == 413
    assert "bytes" in r.json()["detail"] and "characters, the limit" not in r.json()["detail"]
