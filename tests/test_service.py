import json
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

import pytest

from forensics.common import ForensicResult
from forensics.service import Service, make_handler


class StubVideo:
    calibration = type("C", (), {"cells": {"video/sd": object()}})()

    def analyse(self, path, cell=None):
        return ForensicResult(kind="video", status="clean", model="stub")


@pytest.fixture()
def server(tmp_path):
    svc = Service.__new__(Service)          # skip model loading
    svc.video, svc.audio, svc.lock = StubVideo(), None, threading.Lock()
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(svc))
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()


def post(url, body):
    req = urllib.request.Request(url, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
    return json.load(urllib.request.urlopen(req, timeout=10))


def test_health(server):
    h = json.load(urllib.request.urlopen(server + "/health", timeout=10))
    assert h["ok"] and h["video"]["calibrated_cells"] == ["video/sd"] and h["audio"]["installed"] is False
    assert h["audio"]["loaded"] is False and h["audio"]["error"] is None


def test_analyse_text_file_returns_no_results(server, tmp_path):
    t = tmp_path / "x.txt"
    t.write_text("hi")
    assert post(server + "/analyse", {"path": str(t)})["results"] == []


def test_relative_path_rejected(server):
    with pytest.raises(urllib.error.HTTPError) as e:
        post(server + "/analyse", {"path": "x.mp4"})
    assert e.value.code == 400


def test_missing_path_key_rejected(server):
    with pytest.raises(urllib.error.HTTPError) as e:
        post(server + "/analyse", {"file": "/x.mp4"})
    assert e.value.code == 400


def test_language_channel_and_kind_are_validated(server, tmp_path):
    t = tmp_path / "x.txt"
    t.write_text("hi")
    assert post(server + "/analyse", {"path": str(t), "language": "en", "channel": "live-replay"})["results"] == []
    assert post(server + "/analyse", {"path": str(t), "kind": "audio"})["results"] == []
    for bad in ({"language": "fr"}, {"channel": "carrier-pigeon"}, {"kind": "picture"}):
        with pytest.raises(urllib.error.HTTPError) as e:
            post(server + "/analyse", {"path": str(t), **bad})
        assert e.value.code == 400


class LazyVoice:
    """Loads its model on first use, like forensics/audio.py's DF Arena detector."""
    model_name = "lazy-voice"

    def __init__(self, fail: bool):
        self.fail, self._scorer = fail, None

    @property
    def scorer(self):
        if self._scorer is None:
            if self.fail:
                raise OSError("model files are not in the cache")
            self._scorer = lambda windows: [0.5] * len(windows)
        return self._scorer


def bare_service(audio) -> Service:
    svc = Service.__new__(Service)          # skip GenD loading
    svc.video, svc.audio, svc.lock = StubVideo(), audio, threading.Lock()
    return svc


def test_health_says_whether_the_voice_model_actually_loaded():
    """A detector object that exists is not a voice check that works: /health (and preflight, which reads it) must
    report a failed model load, with the reason, instead of "installed"."""
    broken = bare_service(LazyVoice(fail=True))
    broken.warm_audio()
    h = broken.health()["audio"]
    assert h["installed"] is True and h["loaded"] is False and "OSError" in h["error"]
    working = bare_service(LazyVoice(fail=False))
    working.warm_audio()
    h = working.health()["audio"]
    assert h["installed"] is True and h["loaded"] is True and h["error"] is None
    assert h["model"] == "lazy-voice"


def test_the_kind_hint_reaches_analyse(tmp_path, monkeypatch):
    import forensics.service as service
    seen = {}
    monkeypatch.setattr(service, "analyse", lambda p, **kw: seen.update(kw) or [])
    svc = bare_service(None)
    svc.run(str(tmp_path / "rec.weba"), "en", "live-replay", "audio")
    assert (seen["kind"], seen["language"], seen["channel"]) == ("audio", "en", "live-replay")
