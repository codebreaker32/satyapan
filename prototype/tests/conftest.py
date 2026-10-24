import json
import os
from datetime import datetime, timezone
from pathlib import Path

import pytest

# The suite never touches the network: the API's website check uses the recorded registry answers. Set before any
# test module imports satyapan.api, which reads it when the engine is built.
os.environ.setdefault("SATYAPAN_LIVE_WEB", "0")
os.environ.setdefault("SATYAPAN_AUDIO", "aasist")   # the suite never depends on the 1.7 GB DF Arena download
os.environ["SATYAPAN_LLM_READER"] = ""   # never the local model: the reader's tests use a stub server of their own

from satyapan.models import Flag
from satyapan.pipeline import DATA_DIR, Satyapan

NOW = datetime(2026, 10, 16, 13, 0, tzinfo=timezone.utc)
SCENARIOS = {s["id"]: s for s in json.loads((DATA_DIR / "fixtures" / "scenarios.json").read_text(encoding="utf-8"))["scenarios"]}


@pytest.fixture
def engine(tmp_path: Path) -> Satyapan:
    return Satyapan(now=NOW, state_dir=tmp_path / "state")


def run_text(engine: Satyapan, text: str, *, sender=None, signed=False, amount=0.0, source="text", kind="text",
             filename="message.txt", reason="test flag"):
    case = engine.open_case(Flag(reason=reason, amount_inr=amount, customer_ref="cust-demo"))
    engine.set_consent(case, check=True)
    signature = engine.adapters.signature.sign(text) if signed else None
    engine.add_text(case, text, source=source, sender_number=sender, signature=signature, kind=kind, filename=filename)
    return engine.run(case)


def run_scenario_id(engine: Satyapan, sid: str):
    from satyapan.cli import run_scenario
    _, case = run_scenario(SCENARIOS[sid], engine)
    return case


def signal(case, rule_id):
    return next((s for s in case.verdict.signals if s.rule_id == rule_id), None)
