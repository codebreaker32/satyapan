import math

import pytest

from forensics.common import Calibration, CellCalibration, ForensicResult, classify, threshold_at_fpr


def test_result_rejects_unknown_status():
    with pytest.raises(ValueError):
        ForensicResult(kind="video", status="fake")


def test_band_only_with_synthetic():
    with pytest.raises(ValueError):
        ForensicResult(kind="video", status="clean", band="high")
    assert ForensicResult(kind="video", status="synthetic", band="high").band == "high"


def test_abstain_needs_a_reason():
    with pytest.raises(ValueError):
        ForensicResult(kind="audio", status="abstain")


def test_officer_lines_never_show_a_bare_score():
    s = ForensicResult(kind="video", status="synthetic", band="high", score=0.97).officer_line()
    c = ForensicResult(kind="video", status="clean", score=0.1).officer_line()
    a = ForensicResult(kind="audio", status="abstain", reason="voice too short").officer_line()
    assert s == "Video: signs of face manipulation (high)"
    assert "does not prove" in c
    assert a == "Voice: unsure: voice too short"
    assert "0.97" not in s and "0.1" not in c


CAL = CellCalibration(t_fpr5=0.8, t_fpr20=0.6, t_fpr1=0.95)


@pytest.mark.parametrize("score,expected", [
    (0.99, ("synthetic", "high")),
    (0.95, ("synthetic", "high")),
    (0.85, ("synthetic", "moderate")),
    (0.80, ("synthetic", "moderate")),
    (0.70, ("abstain", "")),
    (0.60, ("abstain", "")),
    (0.59, ("clean", "")),
])
def test_band_rule(score, expected):
    status, band, reason = classify(score, CAL)
    assert (status, band) == expected
    assert bool(reason) == (status == "abstain")


def test_no_calibration_abstains():
    assert classify(0.99, None)[0] == "abstain"


def test_nan_score_abstains():
    assert classify(math.nan, CAL)[0] == "abstain"


def test_without_t_fpr1_synthetic_is_moderate():
    assert classify(0.99, CellCalibration(t_fpr5=0.8, t_fpr20=0.6)) == ("synthetic", "moderate", "")


def test_inverted_thresholds_rejected():
    with pytest.raises(ValueError):
        CellCalibration(t_fpr5=0.5, t_fpr20=0.6)
    with pytest.raises(ValueError):
        CellCalibration(t_fpr5=0.8, t_fpr20=0.6, t_fpr1=0.7)


def test_threshold_at_fpr_flags_at_most_that_share_of_real_clips():
    real = [i / 100 for i in range(100)]            # 0.00 .. 0.99
    for fpr in (0.01, 0.05, 0.2, 0.5):
        t = threshold_at_fpr(real, fpr)
        flagged = sum(s >= t for s in real) / len(real)
        assert flagged <= fpr + 1e-9
        assert flagged >= fpr - 0.011               # and not much less: it is the tightest such threshold


def test_threshold_with_too_few_clips_flags_none():
    real = [0.1, 0.2, 0.3]
    t = threshold_at_fpr(real, 0.05)                # 5% of 3 clips rounds down to 0 allowed
    assert all(s < t for s in real)


def test_threshold_needs_real_scores():
    with pytest.raises(ValueError):
        threshold_at_fpr([], 0.05)


def test_calibration_round_trip(tmp_path):
    cal = Calibration(model="m", cells={"video/sd": CellCalibration(t_fpr5=0.8, t_fpr20=0.6, n_real=40, n_fake=40)})
    p = tmp_path / "c.json"
    cal.save(p)
    back = Calibration.load(p)
    assert back.model == "m"
    assert back.cells["video/sd"].t_fpr5 == 0.8 and back.cells["video/sd"].n_real == 40
