"""`satyapan preflight`: the machine-checkable half of the pre-demo checklist as one command."""
import pytest

from satyapan.cli import CONSOLE_DIST, check_evidence, flip_manifest_byte, main
from tests.conftest import SCENARIOS

# A fresh clone has no console/dist (build output is untracked), so preflight's console check rightly fails
# there. These tests assert a FULLY healthy checkout; on a clone they skip with the remedy instead of failing.
needs_console = pytest.mark.skipif(not (CONSOLE_DIST / "index.html").exists(),
                                   reason="console not built; run `npm run build` in console/ first")


def marked_lines(out: str) -> list[str]:
    return [l for l in out.splitlines() if l.startswith(("PASS", "FAIL", "skip"))]


@needs_console
def test_preflight_healthy_checkout_all_pass(capsys):
    assert main(["preflight"]) == 0
    out = capsys.readouterr().out
    lines = marked_lines(out)
    assert {l.split(":")[0].split(None, 1)[1] for l in lines} == {"rulebook", "scenarios", "evidence", "console", "server health", "server meta", "server forensics"}
    assert all(l.startswith("PASS") for l in lines if not l.startswith("skip"))
    assert "FAIL" not in out
    assert sum(1 for l in lines if l.startswith("skip")) == 3, "server checks skip cleanly without --server"
    assert out.splitlines()[-1].endswith("0 fail, 3 skipped")


def test_preflight_missing_console_dist_fails_and_still_runs_the_rest(tmp_path, capsys):
    (tmp_path / "assets").mkdir()  # a dist dir with neither index.html nor fonts
    rc = main(["preflight", "--dist", str(tmp_path)])
    out = capsys.readouterr().out
    assert rc != 0
    lines = marked_lines(out)
    assert any(l.startswith("FAIL  console:") and "index.html" in l for l in lines)
    for name in ("rulebook", "scenarios", "evidence"):
        assert any(l.startswith(f"PASS  {name}:") for l in lines), f"{name} must still run after the console failure"
    assert "(console)" in out.splitlines()[-1], "the summary names every failing check"


def test_evidence_check_fails_on_a_tampered_pack_byte():
    sc = SCENARIOS["S3-ed-summons"]
    ok, text = check_evidence(sc)
    assert ok, text
    assert "fresh pack verifies" in text and "flipped manifest byte is rejected" in text
    ok, text = check_evidence(sc, tamper=flip_manifest_byte)
    assert not ok and "does not verify" in text


@needs_console
def test_preflight_server_checks_match_and_catch_a_stale_rulebook(capsys):
    import json
    import threading
    from http.server import BaseHTTPRequestHandler, HTTPServer

    from satyapan.codehash import code_sha256
    from satyapan.rulebook import load_rulebook
    sha = {"value": load_rulebook().sha256}
    code = {"value": code_sha256()}

    class Stub(BaseHTTPRequestHandler):
        def do_GET(self):
            ready = {"service": {"route": "x", "health": {"ok": True, "video": {"model": "GenD", "calibrated_cells": ["video/sd"]},
                                                          "audio": {"installed": False}}}}
            body = {"/api/health": {"ok": True, "version": "test"},
                    "/api/meta": {"rulebook": {"sha256": sha["value"]}, "forensics": ready,
                                  "code": {"sha256": code["value"]}}}[self.path]
            data = json.dumps(body).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *a):  # keep pytest output clean
            pass

    srv = HTTPServer(("127.0.0.1", 0), Stub)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{srv.server_port}"
    try:
        assert main(["preflight", "--server", url]) == 0
        out = capsys.readouterr().out
        assert any(l.startswith("PASS  server meta:") and "matches local" in l for l in out.splitlines())
        sha["value"] = "0" * 64  # the server now reports a rulebook that is not the one on disk
        assert main(["preflight", "--server", url]) != 0
        out = capsys.readouterr().out
        assert any(l.startswith("FAIL  server meta:") and "restart" in l for l in out.splitlines())
        sha["value"] = load_rulebook().sha256
        code["value"] = "0" * 64  # same rulebook, older engine code: the server was not restarted after a fix
        assert main(["preflight", "--server", url]) != 0
        out = capsys.readouterr().out
        assert any(l.startswith("FAIL  server meta:") and "engine code" in l for l in out.splitlines())
    finally:
        srv.shutdown()


@needs_console
def test_preflight_exits_nonzero_when_evidence_is_tampered(monkeypatch, capsys):
    import satyapan.cli as cli
    monkeypatch.setattr(cli, "check_evidence", lambda sc, tamper=None: check_evidence(sc, tamper=flip_manifest_byte))
    assert main(["preflight"]) != 0
    out = capsys.readouterr().out
    assert any(l.startswith("FAIL  evidence:") for l in out.splitlines())
    assert "(evidence)" in out.splitlines()[-1]


def _meta_server(meta):
    import json
    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    class H(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            body = {"ok": True, "version": "t"} if self.path == "/api/health" else meta
            data = json.dumps(body).encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *a):
            pass
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd, f"http://127.0.0.1:{httpd.server_address[1]}"


def _forensics_line(meta, capsys):
    from satyapan.rulebook import load_rulebook
    meta = {"rulebook": {"sha256": load_rulebook().sha256}, **meta}
    httpd, url = _meta_server(meta)
    try:
        main(["preflight", "--server", url])
    finally:
        httpd.shutdown()
    return next(l for l in capsys.readouterr().out.splitlines() if "server forensics" in l)


def test_preflight_forensics_not_connected_is_a_fail(capsys):
    """It was a skip, and preflight then exited 0 on a server whose uploads got no face or voice check at all, while
    the run-sheet says every line must PASS (bug hunt raw finding 48)."""
    line = _forensics_line({"forensics": {"service": None}}, capsys)
    assert line.startswith("FAIL") and "no face or voice check" in line and "SIMULATED" not in line


def test_preflight_forensics_down_or_uncalibrated_fails(capsys):
    down = {"forensics": {"service": {"route": "local service", "health": None}}}
    assert _forensics_line(down, capsys).startswith("FAIL")
    uncal = {"forensics": {"service": {"route": "x", "health": {"ok": True, "video": {"model": "m", "calibrated_cells": []}}}}}
    assert "no calibration" in _forensics_line(uncal, capsys)


def test_preflight_forensics_ready_passes(capsys):
    ok = {"forensics": {"service": {"route": "x", "health": {"ok": True, "video": {"model": "GenD", "calibrated_cells": ["video/sd"]},
                                                             "audio": {"installed": False}}}}}
    line = _forensics_line(ok, capsys)
    assert line.startswith("PASS") and "video/sd" in line and "not installed yet" in line


def test_preflight_fails_when_the_voice_model_did_not_load(capsys):
    """A missing download once looked 'installed' here while every voice note abstained with a reason that blamed
    the customer's file."""
    video = {"model": "GenD", "calibrated_cells": ["video/sd"]}
    broken = {"forensics": {"service": {"route": "x", "health": {"ok": True, "video": video, "audio": {
        "installed": True, "loaded": False, "error": "OSError: no snapshot"}}}}}
    line = _forensics_line(broken, capsys)
    assert line.startswith("FAIL") and "did not load" in line and "fetch_models.sh" in line
    ready = {"forensics": {"service": {"route": "x", "health": {"ok": True, "video": video, "audio": {
        "installed": True, "loaded": True, "error": None}}}}}
    assert "voice detector loaded" in _forensics_line(ready, capsys)
