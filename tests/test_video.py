"""Video detector tests. Fast: a stub face detector and a stub scorer stand in for YuNet and GenD.
The real-model check runs only with RUN_SLOW=1 and a clip at $SMOKE_VIDEO."""
import heapq
import os
from pathlib import Path

import cv2
import numpy as np
import pytest

from forensics.common import Calibration, CellCalibration
from forensics.video import GenDVideoForensics, VideoSettings, align_face, max_spread_order, read_frames

LM = np.array([[40, 50], [80, 50], [60, 70], [45, 90], [75, 90]], dtype=np.float32)   # a plausible 5-point face


def gend_reference_permutation(N, start=0):
    """GenD's max_spread_permutation_pq, copied verbatim (yermandy/GenD detector.py, MIT) as the oracle."""
    chosen = [start]
    dist = {i: abs(i - start) for i in range(N) if i != start}
    heap = [(-d, i) for i, d in dist.items()]
    heapq.heapify(heap)
    while heap:
        while True:
            neg_d, candidate = heapq.heappop(heap)
            current = -neg_d
            if dist.get(candidate, -1) == current:
                break
        chosen.append(candidate)
        del dist[candidate]
        for other in list(dist.keys()):
            new_d = abs(other - candidate)
            if new_d < dist[other]:
                dist[other] = new_d
                heapq.heappush(heap, (-new_d, other))
    return chosen


@pytest.mark.parametrize("n", [1, 2, 3, 5, 8, 17, 30, 61, 120])
def test_frame_order_matches_gend(n):
    ref = gend_reference_permutation(n, start=n // 2)
    k = min(n, 48)
    assert max_spread_order(n, k) == ref[:k]


def test_frame_order_edge_cases():
    assert max_spread_order(0, 5) == []
    assert max_spread_order(10, 0) == []
    assert len(max_spread_order(5, 50)) == 5


def make_video(path: Path, n=40, size=(320, 240), fps=25):
    vw = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), fps, size)
    for i in range(n):
        frame = np.full((size[1], size[0], 3), i * 5 % 255, np.uint8)
        cv2.putText(frame, str(i), (10, 40), cv2.FONT_HERSHEY_SIMPLEX, 1, (255, 255, 255), 2)
        vw.write(frame)
    vw.release()
    return path


def test_read_frames_returns_requested_frames(tmp_path):
    p = make_video(tmp_path / "v.mp4", n=30)
    got = read_frames(str(p), [0, 7, 29, 50])
    assert set(got) == {0, 7, 29}                   # 50 does not exist
    assert all(f.shape == (240, 320, 3) for f in got.values())


def test_align_face_output_is_square_and_scales_with_face():
    img = np.random.default_rng(0).integers(0, 255, (200, 200, 3), dtype=np.uint8)
    a = align_face(img, LM)
    b = align_face(img, LM * 1.5)
    assert a.shape[0] == a.shape[1] and b.shape[0] > a.shape[0]


class StubDetector:
    """Returns one face of a given size on every frame (or none)."""

    def __init__(self, face_px=120, present=lambda i: True):
        self.face_px, self.present, self.calls = face_px, present, 0

    def __call__(self, frame):
        i = self.calls
        self.calls += 1
        if not self.present(i):
            return []
        s = self.face_px / 40.0
        return [((10.0, 10.0, float(self.face_px), float(self.face_px)), LM * s * 0.5 + 10, 0.99)]


def stub_scorer(values):
    it = iter(values)
    return lambda faces: [next(it) for _ in faces]


def detector_for(tmp_path, det, scores, cal=None, **settings):
    return GenDVideoForensics(calibration=cal, settings=VideoSettings(**settings), detector=det, scorer=stub_scorer(scores))


CAL = Calibration(model="stub", cells={"video/sd": CellCalibration(t_fpr5=0.8, t_fpr20=0.6, t_fpr1=0.95)})


def test_missing_file_abstains(tmp_path):
    r = GenDVideoForensics().analyse(tmp_path / "nope.mp4")
    assert r.status == "abstain" and "not found" in r.reason


def test_unreadable_file_abstains(tmp_path):
    p = tmp_path / "bad.mp4"
    p.write_bytes(b"not a video")
    r = detector_for(tmp_path, StubDetector(), [0.9] * 50).analyse(p)
    assert r.status == "abstain" and "could not be read" in r.reason


def test_no_face_abstains(tmp_path):
    p = make_video(tmp_path / "v.mp4")
    r = detector_for(tmp_path, StubDetector(present=lambda i: False), []).analyse(p)
    assert r.status == "abstain" and r.reason == "no face was found in the video"


def test_tiny_face_abstains_with_size_in_reason(tmp_path):
    p = make_video(tmp_path / "v.mp4")
    r = detector_for(tmp_path, StubDetector(face_px=40), []).analyse(p)
    assert r.status == "abstain" and "too small" in r.reason and "40 px" in r.reason


def test_face_in_too_few_frames_abstains(tmp_path):
    p = make_video(tmp_path / "v.mp4", n=48)
    r = detector_for(tmp_path, StubDetector(present=lambda i: i % 3 == 0), [0.9] * 48, cal=CAL, n_frames=16).analyse(p)
    assert r.status == "abstain" and "only" in r.reason


def test_disagreeing_frames_abstain(tmp_path):
    p = make_video(tmp_path / "v.mp4")
    r = detector_for(tmp_path, StubDetector(), [0.05, 0.95] * 8, cal=CAL, n_frames=16).analyse(p)
    assert r.status == "abstain" and "disagree" in r.reason


def test_uncalibrated_abstains_even_with_high_score(tmp_path):
    p = make_video(tmp_path / "v.mp4")
    r = detector_for(tmp_path, StubDetector(), [0.99] * 16, n_frames=16).analyse(p)
    assert r.status == "abstain" and "not calibrated" in r.reason
    assert r.score == pytest.approx(0.99)


@pytest.mark.parametrize("score,status,band", [(0.97, "synthetic", "high"), (0.85, "synthetic", "moderate"),
                                               (0.7, "abstain", ""), (0.3, "clean", "")])
def test_calibrated_decisions(tmp_path, score, status, band):
    p = make_video(tmp_path / "v.mp4")                  # 320x240 -> cell video/sd
    r = detector_for(tmp_path, StubDetector(), [score] * 16, cal=CAL, n_frames=16).analyse(p)
    assert (r.status, r.band, r.cell) == (status, band, "video/sd")
    assert r.extra["faces_scored"] == 16 and len(r.extra["sha256"]) == 64


def test_median_resists_a_few_outliers(tmp_path):
    p = make_video(tmp_path / "v.mp4")
    scores = [0.9] * 13 + [0.1, 0.1, 0.1]
    r = detector_for(tmp_path, StubDetector(), scores, cal=CAL, n_frames=16).analyse(p)
    assert r.status == "synthetic" and r.score == pytest.approx(0.9)


def test_uncalibrated_cell_abstains_even_if_another_cell_is_calibrated(tmp_path):
    p = make_video(tmp_path / "v.mp4")                  # 320x240 -> video/sd, which is not calibrated here
    cal = Calibration(model="stub", cells={"video/hd": CellCalibration(t_fpr5=0.8, t_fpr20=0.6),
                                           "video/any": CellCalibration(t_fpr5=0.8, t_fpr20=0.6)})
    r = detector_for(tmp_path, StubDetector(), [0.9] * 16, cal=cal, n_frames=16).analyse(p)
    assert r.status == "abstain" and "not calibrated" in r.reason and r.cell == "video/sd"


def test_detector_crash_becomes_abstain(tmp_path):
    p = make_video(tmp_path / "v.mp4")

    def boom(frame):
        raise RuntimeError("detector exploded")
    r = detector_for(tmp_path, boom, []).analyse(p)
    assert r.status == "abstain" and "could not be analysed" in r.reason


def test_unreadable_file_abstains_instead_of_crashing(tmp_path):
    if os.geteuid() == 0:
        pytest.skip("root can read anything")
    p = make_video(tmp_path / "v.mp4")
    p.chmod(0)
    try:
        r = detector_for(tmp_path, StubDetector(), [0.9] * 16, cal=CAL).analyse(p)
    finally:
        p.chmod(0o644)
    assert r.status == "abstain" and "could not be read" in r.reason


def test_calibration_and_decision_use_the_same_rounded_median(tmp_path):
    # a top real clip whose raw median is not 4-dp exact must not be flagged when re-run against its own thresholds
    from forensics.common import threshold_at_fpr
    p = make_video(tmp_path / "v.mp4")
    det = detector_for(tmp_path, StubDetector(), [0.430031] * 16, n_frames=16)
    top = det.measure(p)["median"]
    reals = [0.1, 0.12, 0.15, 0.2, 0.22, 0.25, 0.3, 0.31, 0.35, 0.4, 0.41, top]
    cal = Calibration(model="stub", cells={"video/sd": CellCalibration(t_fpr5=threshold_at_fpr(reals, 0.05),
                                                                       t_fpr20=threshold_at_fpr(reals, 0.20))})
    r = detector_for(tmp_path, StubDetector(), [0.430031] * 16, cal=cal, n_frames=16).analyse(p)
    assert r.status != "synthetic" and r.score == top


def test_result_is_json_serialisable(tmp_path):
    import json
    p = make_video(tmp_path / "v.mp4")
    for scores in ([0.9] * 16, [0.05, 0.95] * 8):
        json.dumps(detector_for(tmp_path, StubDetector(), scores, cal=CAL, n_frames=16).analyse(p).to_dict())


@pytest.mark.skipif(not (os.environ.get("RUN_SLOW") and os.environ.get("SMOKE_VIDEO")),
                    reason="set RUN_SLOW=1 and SMOKE_VIDEO=path to a clip with a clearly visible face")
def test_real_model_smoke():
    det = GenDVideoForensics()
    m = det.measure(os.environ["SMOKE_VIDEO"])        # no catch-all here: a model load error fails the test
    assert m["faces_scored"] > 0 and 0.0 <= m["median"] <= 1.0
    r = det.analyse(os.environ["SMOKE_VIDEO"])
    assert r.model.startswith("GenD_CLIP_L_14@") and "could not" not in r.reason and "missing" not in r.reason


@pytest.mark.skipif(not (os.environ.get("RUN_SLOW") and os.environ.get("GEND_SAMPLES")),
                    reason="set RUN_SLOW=1 and GEND_SAMPLES=dir with GenD's README sample crops")
def test_fake_is_output_index_one():
    from PIL import Image
    from forensics.video import GenDScorer
    d = Path(os.environ["GEND_SAMPLES"])
    fake, real = GenDScorer()([np.asarray(Image.open(d / f).convert("RGB")) for f in ("fake_DF_000_003.png", "real_000.png")])
    assert fake > 0.9 and real < 0.5
