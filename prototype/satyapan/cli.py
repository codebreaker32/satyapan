"""Command line: run the demo scenarios, check a pasted text, verify an evidence pack, or serve the API."""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

from .adapters import Adapters
from .evidence import canonical, load_pack, save_pack, verify_pack
from .models import Flag, Outcome, Severity
from .pipeline import DATA_DIR, Satyapan
from .rulebook import load_rulebook

FIXTURES = DATA_DIR / "fixtures" / "scenarios.json"
CONSOLE_DIST = Path(__file__).resolve().parent.parent / "console" / "dist"

# Any text that reaches the extractor is capped here (pasted text, a .txt upload, a supplied transcript, OCR'd
# pages): every extractor regex runs over it, and a whole-PDF paste must never stall the demo. The longest
# scenario text is well under 2k. The API and the CLI share this constant and this message.
MAX_TEXT_CHARS = 25_000


def text_too_long(n: int) -> str:
    return (f"That text is too long to check at once: {n:,} characters, the limit is {MAX_TEXT_CHARS:,}. "
            "Paste the part of the message that gives the instruction.")
COLOUR = {Outcome.RED: "\033[41;97m", Outcome.AMBER: "\033[43;30m", Outcome.GREY: "\033[100;97m", Outcome.MATCHES: "\033[42;97m"}
RESET = "\033[0m"


def load_scenarios(path: Path = FIXTURES) -> list[dict]:
    return json.loads(path.read_text(encoding="utf-8"))["scenarios"]


def run_scenario(sc: dict, engine: Satyapan | None = None) -> tuple[Satyapan, object]:
    now = datetime.fromisoformat(sc["now"]) if sc.get("now") else None
    engine = engine or Satyapan(now=now)
    case = engine.open_case(Flag(**sc["flag"]))
    engine.set_consent(case, check=True, report=sc.get("consent_report", True), memory=sc.get("consent_memory", True), lang=sc.get("lang", "hi"))
    if "picklist" in sc:
        engine.add_picklist(case, **sc["picklist"])
    else:
        signature = engine.adapters.signature.sign(sc["text"]) if sc.get("signed") else None
        engine.add_text(case, sc["text"], source=sc.get("source", "text"), sender_number=sc.get("sender_number"), signature=signature,
                        kind=sc.get("media_kind", "text"), filename=sc.get("media_filename", "message.txt"))
    if sc.get("forensics_sim"):
        engine.simulate_forensics(case, sc["forensics_sim"])
    engine.run(case)
    return engine, case


def print_case(engine: Satyapan, case, lang: str, show_signals: bool = True) -> None:
    v = case.verdict
    print(f"  {COLOUR[v.outcome]} {v.outcome.value} {RESET}  {v.headline_en}")
    print(f"  why: {v.explanation}")
    if show_signals:
        for s in v.signals:
            if s.severity in (Severity.HARD, Severity.SOFT, Severity.MATCH):
                sim = " [SIMULATED]" if s.detail.get("simulated") else ""
                print(f"    {s.family.value} {s.severity.value:6s} {s.rule_id:24s} evidence={s.evidence_key}{sim}")
            elif s.severity == Severity.ABSTAIN:
                print(f"    {s.family.value} abstain {s.rule_id:24s} {s.reason_en}")
    card = engine.card(case, lang)
    print("  card (" + lang + "):")
    for line in card.read_aloud.splitlines():
        print("    | " + line)
    trig = engine.review_triggers(case)
    if trig:
        print("  FRMU review required: " + "; ".join(trig))


def cmd_demo(args) -> int:
    scenarios = load_scenarios()
    failures = 0
    for sc in scenarios:
        if args.only and sc["id"] not in args.only:
            continue
        print(f"\n== {sc['id']}: {sc['title']}")
        engine, case = run_scenario(sc)
        print_case(engine, case, args.lang)
        exp = sc.get("expect")
        if exp:
            ok = case.verdict.outcome.value == exp
            failures += 0 if ok else 1
            print(f"  expected {exp}: {'PASS' if ok else 'FAIL'}")
        if sc.get("then_forensics"):
            print("  -- after re-encoding through WhatsApp / 8 kHz (forensics abstain):")
            engine.simulate_forensics(case, sc["then_forensics"])
            engine.run(case)
            print_case(engine, case, args.lang, show_signals=False)
            ok = case.verdict.outcome.value == (sc.get("expect_after") or exp)
            failures += 0 if ok else 1
            print(f"  verdict unchanged: {'PASS' if ok else 'FAIL'}")
        if args.evidence:
            out = Path(args.evidence) / f"{sc['id']}.evidence.json"
            save_pack(engine.evidence_pack(case), out)
            print(f"  evidence pack -> {out}")
    print(f"\n{len(scenarios)} scenarios, {failures} mismatches")
    return 1 if failures else 0


def cmd_check(args) -> int:
    if len(args.text) > MAX_TEXT_CHARS:
        print(text_too_long(len(args.text)))
        return 1
    engine = Satyapan()
    case = engine.open_case(Flag(reason=args.flag or "manual check", amount_inr=args.amount, customer_ref=args.customer))
    engine.set_consent(case, check=True)
    engine.add_text(case, args.text, sender_number=args.sender)
    engine.run(case)
    print_case(engine, case, args.lang)
    if args.json:
        print(json.dumps(case.model_dump(mode="json"), indent=2, ensure_ascii=False))
    return 0


def cmd_verify(args) -> int:
    pack = load_pack(Path(args.pack))
    ok, reason = verify_pack(pack)
    print(("VALID   " if ok else "INVALID ") + reason)
    return 0 if ok else 2


def flip_manifest_byte(pack: dict) -> dict:
    """Flip one byte in the canonical manifest bytes (inside the rulebook sha string, so the JSON stays valid)
    and rebuild the manifest from them. Verification must reject the result."""
    raw = bytearray(canonical(pack["manifest"]))
    i = raw.find(pack["manifest"]["rulebook"]["sha256"].encode("ascii"))
    raw[i] = ord("0") if raw[i] != ord("0") else ord("1")
    return {**pack, "manifest": json.loads(raw.decode("utf-8"))}


def check_evidence(sc: dict, tamper=None) -> tuple[bool, str]:
    """Sign a pack for one scenario case, verify it, then flip one manifest byte and verify again.
    `tamper` (tests) alters the pack before the first verification."""
    engine, case = run_scenario(sc)
    pack = engine.evidence_pack(case)
    if tamper:
        pack = tamper(pack)
    ok_fresh, why_fresh = verify_pack(pack)
    ok_flipped, why_flipped = verify_pack(flip_manifest_byte(pack))
    fresh = "fresh pack verifies" if ok_fresh else f"fresh pack does not verify ({why_fresh})"
    flipped = "one flipped manifest byte is rejected" if not ok_flipped else f"one flipped manifest byte still verifies ({why_flipped})"
    return ok_fresh and not ok_flipped, f"{fresh}; {flipped} ({sc['id']})"


def cmd_preflight(args) -> int:
    results: list[tuple[str, bool | None, str]] = []  # (check, ok / None = skipped, text)

    def run(name: str, fn) -> None:
        try:
            ok, text = fn()
        except Exception as e:  # a crashed check is a failed check; keep running the rest
            ok, text = False, f"{type(e).__name__}: {e}"
        results.append((name, ok, text))

    loaded: dict = {}

    def chk_rulebook():
        book = load_rulebook()
        loaded["book"] = book
        unverified = [r.id for r in book.rules.values() if not r.citation.verified]
        if unverified:
            return False, (f"{len(unverified)} rule(s) without citation verified: true ({', '.join(unverified)}) — "
                           "demoted to soft at load, so a RED anchored on them would silently weaken on stage")
        return True, f"rulebook {book.version} loads; all {len(book.rules)} rule citations verified: true"

    def chk_scenarios():
        scenarios = load_scenarios()
        mismatched = []
        for sc in scenarios:
            engine, case = run_scenario(sc)
            ok = case.verdict.outcome.value == sc.get("expect")
            if ok and sc.get("then_forensics"):
                engine.simulate_forensics(case, sc["then_forensics"])
                engine.run(case)
                ok = case.verdict.outcome.value == (sc.get("expect_after") or sc["expect"])
            if not ok:
                mismatched.append(sc["id"])
        n = len(scenarios)
        if mismatched:
            return False, f"{n - len(mismatched)}/{n} scenarios match their expected verdict; mismatched: {', '.join(mismatched)}"
        return True, f"{n}/{n} scenarios match their expected verdict"

    def chk_console():
        dist = Path(args.dist)
        fonts = sorted((dist / "assets").glob("*devanagari*.woff2")) if (dist / "assets").is_dir() else []
        problems = []
        if not (dist / "index.html").is_file():
            problems.append(f"{dist / 'index.html'} missing (run `npm run build` in console/)")
        if not fonts:
            problems.append("no *devanagari*.woff2 under assets/ — the Hindi card will not render offline")
        if problems:
            return False, "; ".join(problems)
        return True, f"console/dist/index.html present; {len(fonts)} Devanagari woff2 bundled"

    def get_json(url: str) -> dict:
        import urllib.request
        with urllib.request.urlopen(url, timeout=5) as r:
            if r.status != 200:
                raise RuntimeError(f"{url} -> HTTP {r.status}")
            return json.loads(r.read().decode("utf-8"))

    base = args.server.rstrip("/") if args.server else None

    def chk_health():
        body = get_json(base + "/api/health")
        return bool(body.get("ok")), f"/api/health 200 (version {body.get('version')})"

    def chk_meta():
        remote = get_json(base + "/api/meta").get("rulebook", {}).get("sha256")
        local = loaded.get("book") or load_rulebook()
        if remote != local.sha256:
            return False, (f"/api/meta rulebook sha {str(remote)[:12]} != local {local.sha256[:12]} — "
                           "the server loaded an older rulebook; restart `satyapan serve`")
        return True, f"/api/meta 200; rulebook sha matches local ({local.sha256[:12]})"

    run("rulebook", chk_rulebook)
    run("scenarios", chk_scenarios)
    run("evidence", lambda: check_evidence(load_scenarios()[0]))
    run("console", chk_console)
    if base:
        run("server health", chk_health)
        run("server meta", chk_meta)
    else:
        results.append(("server health", None, "--server not given"))
        results.append(("server meta", None, "--server not given"))

    for name, ok, text in results:
        print(f"{'skip' if ok is None else 'PASS' if ok else 'FAIL'}  {name}: {text}")
    failing = [name for name, ok, _ in results if ok is False]
    npass = sum(1 for _, ok, _ in results if ok is True)
    nskip = sum(1 for _, ok, _ in results if ok is None)
    print(f"\n{len(results)} checks: {npass} pass, {len(failing)} fail{' (' + ', '.join(failing) + ')' if failing else ''}, {nskip} skipped")
    return 1 if failing else 0


def cmd_serve(args) -> int:
    import uvicorn
    uvicorn.run("satyapan.api:app", host=args.host, port=args.port, reload=args.reload)
    return 0


def cmd_setup_models(args) -> int:
    from .setup_models import setup_models
    return setup_models()


def cmd_calibrate_audio(args) -> int:
    from .calibrate import calibrate_audio
    return calibrate_audio(per_language=args.per_language)


def cmd_calibrate_memory(args) -> int:
    from .calibrate import calibrate_memory
    return calibrate_memory()


def cmd_evaluate(args) -> int:
    from .evaluate import evaluate
    return evaluate(write=not args.no_write)


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="satyapan", description="Verify the instruction, not the pixels.")
    sub = p.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("demo", help="run the finale scenarios from data/fixtures/scenarios.json")
    d.add_argument("--lang", default="hi", choices=["hi", "en"])
    d.add_argument("--only", nargs="*", help="scenario ids")
    d.add_argument("--evidence", help="directory to write signed evidence packs into")
    d.set_defaults(fn=cmd_demo)
    c = sub.add_parser("check", help="check a pasted message")
    c.add_argument("text")
    c.add_argument("--sender")
    c.add_argument("--lang", default="en", choices=["hi", "en"])
    c.add_argument("--flag")
    c.add_argument("--amount", type=float, default=0)
    c.add_argument("--customer", default="cust-demo")
    c.add_argument("--json", action="store_true")
    c.set_defaults(fn=cmd_check)
    v = sub.add_parser("verify", help="verify a signed evidence pack")
    v.add_argument("pack")
    v.set_defaults(fn=cmd_verify)
    f = sub.add_parser("preflight", help="pre-demo checks: rulebook citations, scenario verdicts, evidence signing, console build")
    f.add_argument("--server", help="base URL of a running `satyapan serve`, e.g. http://127.0.0.1:8000 (optional)")
    f.add_argument("--dist", default=str(CONSOLE_DIST), help="console build directory (default: console/dist)")
    f.set_defaults(fn=cmd_preflight)
    s = sub.add_parser("serve", help="run the API (and the console, if built)")
    s.add_argument("--host", default="127.0.0.1")
    s.add_argument("--port", type=int, default=8000)
    s.add_argument("--reload", action="store_true")
    s.set_defaults(fn=cmd_serve)
    m = sub.add_parser("setup-models", help="download speech-to-text, OCR language data, AASIST-L and the meaning model (once, for offline use)")
    m.set_defaults(fn=cmd_setup_models)
    a = sub.add_parser("calibrate-audio", help="measure AASIST-L false alarms on genuine FLEURS speech per channel and write the calibration")
    a.add_argument("--per-language", type=int, default=150, help="genuine clips per language (default 150)")
    a.set_defaults(fn=cmd_calibrate_audio)
    cm = sub.add_parser("calibrate-memory", help="set the meaning-match threshold from data/eval/memory_pairs.json")
    cm.set_defaults(fn=cmd_calibrate_memory)
    e = sub.add_parser("evaluate", help="run the labelled evaluation set and write data/eval/results.json and docs/evaluation.md")
    e.add_argument("--no-write", action="store_true", help="print the numbers without writing the files")
    e.set_defaults(fn=cmd_evaluate)
    args = p.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
