"""`satyapan evaluate`: how often the engine is right on a labelled set, measured by running it.

The set is synthetic and says so everywhere it is shown. It is three sources, each labelled by what the message
really IS (a scam or a genuine message), never by what the engine is expected to say:
- the 22 demo scenarios (data/fixtures/scenarios.json), labelled in SCENARIO_LABELS below;
- the variant corpus (data/fixtures/variants.json), labelled by its own `from` and `expected` fields as set out in
  `variant_label`; three corporate demands whose legitimacy cannot be judged from the text are left out, with why;
- data/eval/labelled.json, written for this: genuine bank, government and personal messages, in-scope scams,
  and scam types Satyapan does not claim to cover (in_scope: false), which are reported apart and never hidden.

What is reported: of the in-scope scams, how many were stopped (RED) or sent to verification (AMBER) and how many
were missed; of the genuine messages, how many were stopped (a false stop, which must be zero), how many were asked
to verify first (AMBER), and how many were left alone; every miss and every false alarm by name.
"""
from __future__ import annotations

import json
import subprocess
from collections import Counter, defaultdict
from datetime import date, datetime
from pathlib import Path

from .cli import load_scenarios, run_scenario
from .models import Flag, Outcome, Severity
from .pipeline import DATA_DIR, Satyapan

ROOT = Path(__file__).resolve().parent.parent
LABELLED = DATA_DIR / "eval" / "labelled.json"
RESULTS = DATA_DIR / "eval" / "results.json"
REPORT = ROOT.parent / "docs" / "evaluation.md"
SYNTHETIC = "Synthetic evaluation set, not field data."

GENUINE_SCENARIOS = {"S5a-genuine-bank-notice", "S5b-real-rbi-advisory", "S5c-ed-summons-1h-old", "S5c2-ed-summons-valid",
                     "S5e-genuine-sms-1600", "S5f-court-hearing-notice", "S5g-it-refund-processed", "S5h-it-refund-probe",
                     "S9b-house-tax-official", "S10c-echallan-official"}
SCENARIO_CATEGORY = {"S1": "fake bank staff", "S2": "fake regulator investment", "S3": "digital arrest", "S4": "digital arrest",
                     "S5a": "bank sent it", "S5b": "awareness message", "S5c": "real government notice", "S5d": "digital arrest",
                     "S5e": "bank sent it", "S5f": "real government notice", "S5g": "real government notice",
                     "S5h": "real government notice", "S6": "fake refund", "S7": "fake court order",
                     "S8": "fake regulator investment", "S9": "copied tax notice", "S9b": "real government notice",
                     "S10": "copied challan or fine", "S10c": "real government notice"}
VARIANT_CATEGORY = {"S1-rm-voice-note": "fake bank staff", "S2-rbi-video": "fake regulator investment",
                    "S3-ed-summons": "digital arrest", "S4-claim-only": "digital arrest", "S6-fake-credit": "fake refund",
                    "S7-court-order": "fake court order"}
# Corporate demands: a company asking for its own money is legitimate or not depending on facts the text does not
# carry, so labelling them either way would put a guess into the numbers.
EXCLUDED_VARIANTS = {"V69-negative-corporate-masthead": "a company's invoice demand; legitimacy is not in the text",
                     "V70-negative-credit-bureau-limited": "a company's default demand; legitimacy is not in the text",
                     "V71-negative-corporate-masthead-devanagari": "an insurer's demand; legitimacy is not in the text"}


def scenario_category(sid: str) -> str:
    """The category of a scenario by its id prefix, longest prefix first ("S10c" before "S10" before "S1")."""
    prefix = sid.split("-")[0]
    return next((SCENARIO_CATEGORY[k] for k in sorted(SCENARIO_CATEGORY, key=len, reverse=True) if prefix.startswith(k)),
                "other")


def variant_label(v: dict) -> dict | None:
    """A variant's label, from its own fields. None means left out (EXCLUDED_VARIANTS)."""
    if v["id"] in EXCLUDED_VARIANTS:
        return None
    exp = v.get("expected", {})
    issuer, instruction = exp.get("issuer", "NONE"), exp.get("instruction", "NONE")
    if v["from"] == "negative":
        # A probe written against the extractor, not a scam: except one that is a textbook CBI demand.
        if issuer in {"CBI", "ED", "POLICE", "CUSTOMS", "COURT", "RBI", "OTHER"} and instruction != "NONE":
            return {"label": "scam", "in_scope": True, "category": "digital arrest"}
        return {"label": "genuine", "category": "everyday or awareness text"}
    category = VARIANT_CATEGORY.get(v["from"], "other")
    if instruction == "NONE":
        # "Come to the branch and sign the form" is benign; "your KYC has expired" is a scam opener with no demand yet.
        if "branch" in v["text"].lower():
            return {"label": "genuine", "category": "everyday or awareness text"}
        return {"label": "scam", "in_scope": False, "category": "scam opener, no demand yet"}
    if issuer == "NONE" and instruction != "RETURN_EXCESS_CREDIT":
        # A fragment of a scenario script with no sender at all: nothing in it claims to be anyone official.
        return {"label": "scam", "in_scope": False, "category": "script fragment, no sender"}
    return {"label": "scam", "in_scope": True, "category": category}


def _fired(case) -> list[str]:
    return sorted({s.rule_id for s in case.verdict.signals if s.severity in (Severity.HARD, Severity.SOFT, Severity.MATCH)})


def _run_message(engine: Satyapan, item: dict):
    f = item.get("flag", {})
    case = engine.open_case(Flag(reason=f.get("reason", "evaluation message"), amount_inr=f.get("amount_inr", 0),
                                 customer_ref="cust-demo", payee_account=f.get("payee_account"),
                                 payee_vpa=f.get("payee_vpa")))
    engine.set_consent(case, check=True)
    signature = engine.adapters.signature.sign(item["text"]) if item.get("signed") else None
    engine.add_text(case, item["text"], source=item.get("source", "text"), sender_number=item.get("sender"),
                    signature=signature)
    return engine.run(case)


def environment(engine: Satyapan) -> dict:
    """Which optional layers were present, so two runs are only compared like for like."""
    from .memory import meaning_model
    return {"audio_detector": type(engine.audio).__name__,
            "meaning_model": bool(engine.memory.meaning_threshold is not None and meaning_model() is not None),
            "website_registry": type(engine.adapters.website).__name__,
            "reader": engine.reader.name if engine.reader is not None else None,
            "rulebook": f"{engine.book.version} ({engine.book.sha256[:12]})"}


def run_evaluation() -> dict:
    rows: list[dict] = []
    for sc in load_scenarios():
        _, case = run_scenario(sc)
        gen = sc["id"] in GENUINE_SCENARIOS
        rows.append({"id": sc["id"], "source": "scenario", "label": "genuine" if gen else "scam", "in_scope": not gen or None,
                     "category": scenario_category(sc["id"]), "lang": sc.get("lang", ""), "outcome": case.verdict.outcome.value,
                     "fired": _fired(case)})
    doc = json.loads(LABELLED.read_text(encoding="utf-8"))
    now = datetime.fromisoformat(doc["now"])
    engine = Satyapan(now=now)
    excluded = []
    for v in json.loads((DATA_DIR / "fixtures" / "variants.json").read_text(encoding="utf-8"))["variants"]:
        lab = variant_label(v)
        if lab is None:
            excluded.append({"id": v["id"], "why": EXCLUDED_VARIANTS[v["id"]]})
            continue
        case = _run_message(engine, {"text": v["text"]})
        rows.append({"id": v["id"], "source": "variant", "label": lab["label"], "in_scope": lab.get("in_scope"),
                     "category": lab["category"], "lang": v.get("style", ""), "outcome": case.verdict.outcome.value,
                     "fired": _fired(case)})
    for item in doc["messages"]:
        case = _run_message(engine, item)
        rows.append({"id": item["id"], "source": "labelled", "label": item["label"], "in_scope": item.get("in_scope"),
                     "category": item["category"], "lang": item.get("lang", ""), "outcome": case.verdict.outcome.value,
                     "fired": _fired(case)})
    return {"rows": rows, "excluded": excluded, "environment": environment(engine), "summary": summarise(rows)}


def summarise(rows: list[dict]) -> dict:
    def tally(rs):
        c = Counter(r["outcome"] for r in rs)
        return {"n": len(rs), "RED": c["RED"], "AMBER": c["AMBER"], "GREY": c["GREY"], "MATCHES": c["MATCHES"]}

    scams = [r for r in rows if r["label"] == "scam" and r["in_scope"]]
    outside = [r for r in rows if r["label"] == "scam" and not r["in_scope"]]
    genuine = [r for r in rows if r["label"] == "genuine"]
    s, g, o = tally(scams), tally(genuine), tally(outside)

    def pct(a, b):
        return round(100.0 * a / b, 1) if b else 0.0

    by_cat = defaultdict(list)
    for r in rows:
        by_cat[(r["label"], r["category"])].append(r)
    return {
        "in_scope_scams": {**s, "flagged_pct": pct(s["RED"] + s["AMBER"], s["n"]), "stopped_pct": pct(s["RED"], s["n"]),
                           "missed_pct": pct(s["GREY"] + s["MATCHES"], s["n"])},
        "genuine": {**g, "false_stop_pct": pct(g["RED"], g["n"]), "asked_to_verify_pct": pct(g["AMBER"], g["n"]),
                    "left_alone_pct": pct(g["GREY"] + g["MATCHES"], g["n"])},
        "out_of_scope_scams": {**o, "flagged_pct": pct(o["RED"] + o["AMBER"], o["n"])},
        "by_category": [{"label": lab, "category": cat, **tally(rs)} for (lab, cat), rs in sorted(by_cat.items())],
        "missed": [r["id"] for r in scams if r["outcome"] in ("GREY", "MATCHES")],
        "false_stops": [r["id"] for r in genuine if r["outcome"] == "RED"],
        "asked_to_verify": [r["id"] for r in genuine if r["outcome"] == "AMBER"],
        "total": len(rows),
    }


def _commit() -> str:
    try:
        return subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, capture_output=True, text=True,
                              timeout=5).stdout.strip()
    except Exception:  # noqa: BLE001
        return ""


def write_report(result: dict) -> str:
    s = result["summary"]
    sc, ge, out = s["in_scope_scams"], s["genuine"], s["out_of_scope_scams"]
    env = result["environment"]
    lines = [
        "# Evaluation", "",
        f"**{SYNTHETIC}** Every message below was written for this repository. The numbers say how the engine behaves "
        "on this set; they are not a measurement on real customers' messages, and no field data exists yet.", "",
        f"Generated by `satyapan evaluate` on {result['made']} (commit {result['commit'] or 'n/a'}, rulebook "
        f"{env['rulebook']}). Audio detector: {env['audio_detector']}; meaning model for campaign memory: "
        f"{'on' if env['meaning_model'] else 'off'}; website look-up: {env['website_registry']} (recorded registry "
        f"answers, so the run is repeatable offline); offline helper reader: {env.get('reader') or 'off'}.", "",
        "## Headline", "",
        f"- **Scams in scope ({sc['n']}):** {sc['RED']} stopped (RED), {sc['AMBER']} sent to verification (AMBER), "
        f"{sc['GREY'] + sc['MATCHES']} missed. Flagged: **{sc['flagged_pct']}%**; stopped: {sc['stopped_pct']}%.",
        f"- **Genuine messages ({ge['n']}):** {ge['RED']} stopped (**{ge['false_stop_pct']}% false stops**), "
        f"{ge['AMBER']} asked to verify first ({ge['asked_to_verify_pct']}%), {ge['GREY'] + ge['MATCHES']} left alone "
        f"({ge['left_alone_pct']}%).",
        f"- **Scams outside scope ({out['n']}):** {out['RED'] + out['AMBER']} flagged ({out['flagged_pct']}%). Satyapan "
        "does not claim to cover these (family emergency, lottery, job, sextortion and similar); they are listed so "
        "the gap is visible.", "",
        "An AMBER on a genuine message is not a block: the card asks the customer to confirm through the official "
        "channel before paying. A RED on a genuine message would be the serious error, and the test suite fails if "
        "one appears (`satyapan/tests/test_evaluation.py`).", "",
        "## By category", "",
        "| Label | Category | n | RED | AMBER | GREY | MATCHES |", "|---|---|---|---|---|---|---|",
    ]
    lines += [f"| {c['label']} | {c['category']} | {c['n']} | {c['RED']} | {c['AMBER']} | {c['GREY']} | {c['MATCHES']} |"
              for c in s["by_category"]]
    rows = {r["id"]: r for r in result["rows"]}

    def listed(ids, title):
        out_lines = ["", f"## {title}", ""]
        if not ids:
            return out_lines + ["None."]
        return out_lines + [f"- `{i}` ({rows[i]['category']}, {rows[i]['source']}): {rows[i]['outcome']}"
                            + (f"; fired {', '.join(rows[i]['fired'])}" if rows[i]["fired"] else "") for i in ids]

    lines += listed(s["missed"], "In-scope scams missed")
    lines += listed(s["false_stops"], "Genuine messages stopped (false stops)")
    lines += listed(s["asked_to_verify"], "Genuine messages asked to verify first")
    lines += ["", "## Left out of the numbers", ""]
    lines += [f"- `{e['id']}`: {e['why']}" for e in result["excluded"]] or ["None."]
    lines += ["", "## How the set is labelled", "",
              "- Demo scenarios: labelled in `satyapan/satyapan/evaluate.py` (GENUINE_SCENARIOS; every other scenario is "
              "an in-scope scam).",
              "- Variant corpus: by each variant's own `from` and `expected` fields (`evaluate.variant_label`). Script "
              "fragments with no sender, and scam openers with no demand yet, count as scams outside scope.",
              "- `satyapan/data/eval/labelled.json`: labelled by hand, one line each, with the category shown above.", ""]
    return "\n".join(lines)


def evaluate(write: bool = True, log=print) -> int:
    result = run_evaluation()
    result["made"] = date.today().isoformat()
    result["commit"] = _commit()
    result["_note"] = SYNTHETIC
    s = result["summary"]
    log(f"{SYNTHETIC}")
    log(f"scams in scope: {s['in_scope_scams']['n']}, flagged {s['in_scope_scams']['flagged_pct']}% "
        f"(stopped {s['in_scope_scams']['stopped_pct']}%), missed {s['in_scope_scams']['missed_pct']}%")
    log(f"genuine: {s['genuine']['n']}, false stops {s['genuine']['false_stop_pct']}%, "
        f"asked to verify {s['genuine']['asked_to_verify_pct']}%, left alone {s['genuine']['left_alone_pct']}%")
    log(f"scams outside scope: {s['out_of_scope_scams']['n']}, flagged {s['out_of_scope_scams']['flagged_pct']}%")
    if s["missed"]:
        log(f"missed: {', '.join(s['missed'])}")
    if s["false_stops"]:
        log(f"FALSE STOPS: {', '.join(s['false_stops'])}")
    if write:
        RESULTS.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
        REPORT.write_text(write_report(result), encoding="utf-8")
        log(f"wrote {RESULTS.relative_to(ROOT)} and docs/{REPORT.name}")
    return 1 if s["false_stops"] else 0
