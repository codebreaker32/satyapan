"""The detectors in forensics/ reach the engine through the satyapan-finale forensics service. A stub HTTP server
stands in for it here, so these tests need no model. Off by default: with no service URL the engine behaves
exactly as before."""
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from satyapan.forensics import RemoteForensics, to_signal
from satyapan.models import Family, Flag, Outcome, Severity
from satyapan.pipeline import Satyapan

from conftest import NOW


def serve(reply):
    class H(BaseHTTPRequestHandler):
        def do_POST(self):  # noqa: N802
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            data = json.dumps(reply(body)).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):  # noqa: N802
            data = b'{"ok": true}'
            self.send_response(200)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *a):
            pass
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd, f"http://127.0.0.1:{httpd.server_address[1]}"


VIDEO_FAKE = {"kind": "video", "status": "synthetic", "band": "high", "score": 0.97, "model": "GenD_CLIP_L_14@891ce01",
              "cell": "video/sd", "reason": "", "extra": {"sha256": "ab" * 32, "frame_scores": [0.97] * 16}}
AUDIO_CLEAN = {"kind": "audio", "status": "clean", "band": "", "score": 0.1, "model": "stub-audio", "cell": "hi/wav",
               "reason": "", "extra": {}}


@pytest.fixture
def fake_service():
    httpd, url = serve(lambda body: {"results": [VIDEO_FAKE, AUDIO_CLEAN], "seconds": 1.0, "seen": body})
    yield url
    httpd.shutdown()


def video_file(tmp_path: Path) -> Path:
    p = tmp_path / "officer_call.mp4"
    p.write_bytes(b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 200)       # sniffed as video by satyapan.media
    return p


def test_client_converts_results(fake_service, tmp_path):
    rs = RemoteForensics(fake_service).analyse_all(video_file(tmp_path), "video")
    assert [(r.kind, r.status, r.band, r.cell) for r in rs] == [("video", "synthetic", "high", "video/sd"), ("audio", "clean", "", "hi/wav")]
    assert rs[0].extra["sha256"] == "ab" * 32 and "frame_scores" not in rs[0].extra


def test_service_down_abstains_instead_of_failing(tmp_path):
    rs = RemoteForensics("http://127.0.0.1:9", timeout=2).analyse_all(video_file(tmp_path), "video")
    assert len(rs) == 1 and rs[0].status == "abstain" and "not running" in rs[0].reason and rs[0].kind == "video"


def test_malformed_results_are_dropped(tmp_path):
    httpd, url = serve(lambda body: {"results": [{"kind": "video", "status": "FAKE!!"}, {"kind": "image", "status": "clean"}]})
    try:
        rs = RemoteForensics(url).analyse_all(video_file(tmp_path), "video")
    finally:
        httpd.shutdown()
    assert len(rs) == 1 and rs[0].status == "abstain" and "no result" in rs[0].reason


def test_video_result_maps_to_the_video_rule(engine):
    from satyapan.forensics import ForensicResult
    s = to_signal(engine.book, ForensicResult(kind="video", status="synthetic", band="high", score=0.97, model="m", cell="video/sd"))
    assert s.rule_id == "R-VIDEO-SYNTH" and s.family == Family.F3 and s.severity == Severity.SOFT
    assert "face" in s.reason_en and "not proof on its own" in s.reason_en
    clean = to_signal(engine.book, ForensicResult(kind="video", status="clean", model="m"))
    assert clean.rule_id == "R-VIDEO-SYNTH" and clean.severity == Severity.INFO and clean.detail["can_be_second"] is False


def test_engine_routes_a_video_to_face_and_voice_checks(fake_service, tmp_path):
    eng = Satyapan(now=NOW, state_dir=tmp_path / "state", forensics_service=fake_service)
    case = eng.open_case(Flag(reason="test flag", amount_inr=0.0, customer_ref="cust-demo"))
    eng.set_consent(case, check=True)
    eng.add_media(case, video_file(tmp_path), derived_text="Hello, see you at five.")   # benign words: no rule fires
    case = eng.run(case)
    f3 = [s for s in case.verdict.signals if s.family == Family.F3]
    assert {s.rule_id for s in f3} == {"R-VIDEO-SYNTH", "R-AUDIO-SYNTH"}
    assert case.verdict.outcome == Outcome.AMBER          # forensics alone: never above AMBER


def test_without_a_service_url_nothing_changes(tmp_path, monkeypatch):
    monkeypatch.delenv("SATYAPAN_FORENSICS_URL", raising=False)
    eng = Satyapan(now=NOW, state_dir=tmp_path / "state")
    assert eng.remote is None
    case = eng.open_case(Flag(reason="test flag", amount_inr=0.0, customer_ref="cust-demo"))
    eng.set_consent(case, check=True)
    eng.add_media(case, video_file(tmp_path), derived_text="Hello, see you at five.")
    case = eng.run(case)
    f3 = [s for s in case.verdict.signals if s.family == Family.F3]
    assert [s.rule_id for s in f3] == ["R-AUDIO-SYNTH"] and f3[0].severity == Severity.ABSTAIN


def test_strike_passes_the_corrected_claim_without_patching_the_shared_engine(tmp_path):
    """strike_field used to patch build_claim on the shared engine for the whole re-run; with the forensics call in
    run() that window lasts seconds, and another case run in it was judged on the struck case's claim."""
    from conftest import run_text
    eng = Satyapan(now=NOW, state_dir=tmp_path / "state")
    a = run_text(eng, "This is ED. You are under digital arrest. Transfer 5 lakh to A/c 50100234567891 IFSC DEMO0001234 today.")
    original = eng.build_claim
    seen = []
    real_run = eng.run

    def spy(case, claim=None):
        seen.append(claim)
        # while the struck case re-runs, the shared engine must still build each case's own claim
        assert eng.build_claim == original
        return real_run(case, claim=claim)
    eng.run = spy
    eng.strike_field(a, "ifsc", actor="officer.test")
    assert seen and seen[0] is not None and seen[0].payee.ifsc is None
    b = run_text(eng, "Hi, your electricity bill of Rs 2000 is due on Friday.")
    assert b.claim is not None and "electricity" in b.claim.text and "digital arrest" not in b.claim.text


def test_prefetch_starts_at_upload_and_run_reuses_it(tmp_path):
    """The face check starts when the file is uploaded; run() picks the result up by content hash, even though the
    upload was moved to its kept path in between, and the service is called once."""
    import shutil
    calls = []
    httpd, url = serve(lambda body: (calls.append(body["path"]), {"results": [VIDEO_FAKE], "seconds": 1.0})[1])
    try:
        rf = RemoteForensics(url)
        staged = video_file(tmp_path)
        rf.prefetch(staged, "video")
        kept = tmp_path / "kept.mp4"
        shutil.move(str(staged), str(kept))
        rs = rf.analyse_all(kept, "video")
    finally:
        httpd.shutdown()
    assert [r.status for r in rs] == ["synthetic"] and len(calls) == 1


def test_a_service_down_at_upload_is_retried_at_run(tmp_path):
    rf = RemoteForensics("http://127.0.0.1:9", timeout=2)
    staged = video_file(tmp_path)
    rf.prefetch(staged, "video")                    # service down: the prefetch records "not running"
    httpd, url = serve(lambda body: {"results": [VIDEO_FAKE], "seconds": 1.0})
    try:
        rf.url = url                                # the service comes up before the officer clicks Run
        rs = rf.analyse_all(staged, "video")
    finally:
        httpd.shutdown()
    assert [r.status for r in rs] == ["synthetic"]


AUDIO_NOT_INSTALLED = {"kind": "audio", "status": "abstain", "band": "", "score": None, "model": "none", "cell": "",
                       "reason": "the audio detector is not installed yet", "extra": {}}


def test_prefetch_is_reused_when_the_service_itself_abstains_on_audio(tmp_path):
    """The service's own 'audio detector not installed yet' (model 'none') is a real answer: reuse it, one POST.
    Regression: the reuse check keyed on model == 'none' and analysed every video twice."""
    calls = []
    httpd, url = serve(lambda body: (calls.append(1), {"results": [VIDEO_FAKE, AUDIO_NOT_INSTALLED], "seconds": 1.0})[1])
    try:
        rf = RemoteForensics(url)
        v = video_file(tmp_path)
        rf.prefetch(v, "video")
        first = rf.analyse_all(v, "video")
        again = rf.analyse_all(v, "video")           # a re-run, e.g. after striking a field
    finally:
        httpd.shutdown()
    assert [r.status for r in first] == ["synthetic", "abstain"] and again == first and len(calls) == 1


def test_a_retry_after_unreachable_is_cached_for_later_runs(tmp_path):
    rf = RemoteForensics("http://127.0.0.1:9", timeout=2)
    v = video_file(tmp_path)
    rf.prefetch(v, "video")
    calls = []
    httpd, url = serve(lambda body: (calls.append(1), {"results": [VIDEO_FAKE], "seconds": 1.0})[1])
    try:
        rf.url = url
        rf.analyse_all(v, "video")
        rf.analyse_all(v, "video")
    finally:
        httpd.shutdown()
    assert len(calls) == 1


def test_quiet_media_checks_read_in_plain_words(engine):
    from satyapan.forensics import ForensicResult
    clean = to_signal(engine.book, ForensicResult(kind="video", status="clean", model="m"))
    unsure = to_signal(engine.book, ForensicResult(kind="audio", status="abstain", reason="the audio detector is not installed yet", model="none"))
    assert clean.reason_en.startswith("Face check: no signs found.") and "does not confirm" in clean.reason_en
    assert unsure.reason_en == "Voice check: unsure: the audio detector is not installed yet."
    assert clean.reason_hi.startswith("चेहरे की जाँच") and unsure.reason_hi == "आवाज़ की जाँच: अनिश्चित।"
    for s in (clean, unsure):
        assert "abstain" not in s.reason_en and "Forensics (" not in s.reason_en


def test_language_and_channel_travel_to_the_service_and_key_the_cache(tmp_path):
    bodies = []
    httpd, url = serve(lambda body: (bodies.append(body), {"results": [VIDEO_FAKE, AUDIO_NOT_INSTALLED], "seconds": 1.0})[1])
    try:
        rf = RemoteForensics(url)
        v = video_file(tmp_path)
        rf.prefetch(v, "video", language="en", channel="live-replay")
        rf.analyse_all(v, "video", language="en", channel="live-replay")     # reuses the prefetch
        rf.analyse_all(v, "video", language="hi")                             # a different calibration cell: new call
    finally:
        httpd.shutdown()
    assert [(b.get("language"), b.get("channel")) for b in bodies] == [("en", "live-replay"), ("hi", None)]


def test_a_voice_note_says_it_is_audio_and_never_gets_a_face_row(tmp_path):
    """A browser voice recording is WebM, which the service once took for a video and face-checked."""
    bodies = []
    httpd, url = serve(lambda body: (bodies.append(body), {"results": [VIDEO_FAKE, AUDIO_CLEAN], "seconds": 1.0})[1])
    try:
        note = tmp_path / "recording.weba"
        note.write_bytes(b"\x1aE\xdf\xa3voice")
        rs = RemoteForensics(url).analyse_all(note, "audio")
    finally:
        httpd.shutdown()
    assert bodies[0]["kind"] == "audio"
    assert [r.kind for r in rs] == ["audio"]


def test_a_slow_check_is_not_called_a_dead_service_and_is_not_sent_twice(tmp_path):
    """A long video once outlasted the wait: the case said "the forensics service is not running" while the service
    was still working, and a second request queued behind the first."""
    import time
    bodies = []
    httpd, url = serve(lambda body: (bodies.append(body), time.sleep(2.5), {"results": [VIDEO_FAKE]})[2])
    try:
        rs = RemoteForensics(url, timeout=1).analyse_all(video_file(tmp_path), "video")
    finally:
        httpd.shutdown()
    assert len(bodies) == 1
    assert rs[0].status == "abstain" and "did not finish" in rs[0].reason and "not running" not in rs[0].reason
