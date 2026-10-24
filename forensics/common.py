"""The contract both detectors share (docs/plan.md, section 1).

Every detector returns a ForensicResult whose status is one of: synthetic, clean, abstain. A detector never decides on
its own; the result is one piece of evidence an officer sees, with a plain reason.

Calibration turns a raw model score into a status. Thresholds are set on REAL clips only:
  - t_fpr5:  the score that 5% of real clips exceed  (5% false-positive rate)
  - t_fpr20: the score that 20% of real clips exceed (20% false-positive rate)
  - t_fpr1:  optional, the score that 1% of real clips exceed
  score >= t_fpr5             -> synthetic  (band "high" if t_fpr1 is set and score >= t_fpr1, else "moderate")
  t_fpr20 <= score < t_fpr5   -> abstain    (grey band: unsure)
  score < t_fpr20             -> clean
  no calibration for the cell -> abstain
"""
from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Optional

STATUSES = ("synthetic", "clean", "abstain")
BANDS = ("low", "moderate", "high")


@dataclass
class ForensicResult:
    kind: str                       # "audio" | "video"
    status: str                     # "synthetic" | "clean" | "abstain"
    band: str = ""                  # "low" | "moderate" | "high", only when status == "synthetic"
    score: Optional[float] = None   # the model's raw score; None when it didn't run
    model: str = ""                 # name and version
    cell: str = ""                  # calibration cell, e.g. "video/sd"
    reason: str = ""                # one plain sentence; required when abstaining
    extra: dict = field(default_factory=dict)

    def __post_init__(self):
        if self.status not in STATUSES:
            raise ValueError(f"status must be one of {STATUSES}, got {self.status!r}")
        if self.band and (self.status != "synthetic" or self.band not in BANDS):
            raise ValueError(f"band {self.band!r} is only allowed with status 'synthetic' and must be one of {BANDS}")
        if self.status == "abstain" and not self.reason:
            raise ValueError("an abstaining result needs a plain reason")

    def to_dict(self) -> dict:
        return asdict(self)

    def officer_line(self) -> str:
        """The plain-language line an officer sees. Never a bare score."""
        what = {"audio": "Voice", "video": "Video"}.get(self.kind, self.kind.capitalize())
        if self.status == "synthetic":
            sign = {"audio": "signs of cloning", "video": "signs of face manipulation"}.get(self.kind, "signs of manipulation")
            return f"{what}: {sign} ({self.band or 'moderate'})"
        if self.status == "clean":
            return f"{what}: no signs found (this does not prove it is genuine)"
        return f"{what}: unsure: {self.reason}"


@dataclass
class CellCalibration:
    t_fpr5: float
    t_fpr20: float
    t_fpr1: Optional[float] = None
    n_real: int = 0
    n_fake: int = 0

    def __post_init__(self):
        for name in ("t_fpr5", "t_fpr20"):
            v = getattr(self, name)
            if v is None or not math.isfinite(v):
                raise ValueError(f"{name} must be a finite number")
        if self.t_fpr20 > self.t_fpr5:
            raise ValueError("t_fpr20 must not exceed t_fpr5 (a stricter false-positive rate needs a higher threshold)")
        if self.t_fpr1 is not None and self.t_fpr1 < self.t_fpr5:
            raise ValueError("t_fpr1 must not be below t_fpr5")


@dataclass
class Calibration:
    model: str
    cells: dict[str, CellCalibration]

    @classmethod
    def load(cls, path: Path | str) -> "Calibration":
        raw = json.loads(Path(path).read_text())
        cells = {k: CellCalibration(**{f: v[f] for f in ("t_fpr5", "t_fpr20", "t_fpr1", "n_real", "n_fake") if f in v})
                 for k, v in raw.get("cells", {}).items()}
        return cls(model=raw.get("model", ""), cells=cells)

    @classmethod
    def empty(cls, model: str = "") -> "Calibration":
        return cls(model=model, cells={})

    def save(self, path: Path | str) -> None:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_text(json.dumps({"model": self.model, "cells": {k: asdict(v) for k, v in self.cells.items()}}, indent=1) + "\n")


def classify(score: float, cal: Optional[CellCalibration]) -> tuple[str, str, str]:
    """Apply the shared band rule. Returns (status, band, reason)."""
    if cal is None:
        return "abstain", "", "not calibrated for this kind of input"
    if score is None or not math.isfinite(score):
        return "abstain", "", "the model returned no usable score"
    if score >= cal.t_fpr5:
        band = "high" if (cal.t_fpr1 is not None and score >= cal.t_fpr1) else "moderate"
        return "synthetic", band, ""
    if score >= cal.t_fpr20:
        return "abstain", "", "the score is in the grey band, too close to call"
    return "clean", "", ""


def threshold_at_fpr(real_scores: list[float], fpr: float) -> float:
    """The threshold that a fraction `fpr` of real scores meet or exceed (higher score = more likely fake).

    Uses the empirical upper quantile with no interpolation, so on these clips exactly floor(fpr * n) real scores reach
    the threshold (more only if several real clips share the same score). With few real clips this is coarse; the
    calibration report states n_real so nobody over-reads it.
    """
    xs = sorted(s for s in real_scores if s is not None and math.isfinite(s))
    if not xs:
        raise ValueError("no real scores to calibrate on")
    k = math.floor(fpr * len(xs))          # number of real clips allowed at or above the threshold
    if k <= 0:
        return math.nextafter(xs[-1], math.inf)   # nothing real may be flagged: threshold just above the max
    return xs[len(xs) - k]
