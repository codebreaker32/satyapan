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


def test_language_and_channel_are_validated(server, tmp_path):
    t = tmp_path / "x.txt"
    t.write_text("hi")
    assert post(server + "/analyse", {"path": str(t), "language": "en", "channel": "live-replay"})["results"] == []
    for bad in ({"language": "fr"}, {"channel": "carrier-pigeon"}):
        with pytest.raises(urllib.error.HTTPError) as e:
            post(server + "/analyse", {"path": str(t), **bad})
        assert e.value.code == 400
