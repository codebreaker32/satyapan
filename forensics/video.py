"""Video deepfake detector: GenD (CLIP ViT-L/14) on aligned faces, with explicit abstention.

Pipeline, mirroring GenD's reference preprocessing (yermandy/GenD, detector.py) except for the face detector:
  1. Frame order: start at the middle frame, then repeatedly take the frame farthest from all frames taken so far
     (GenD's "at_least" mode), until `n_frames` frames with a usable face have been scored or `max_tries` frames tried.
  2. Faces: YuNet (OpenCV, MIT) instead of GenD's InsightFace RetinaFace (research-only). Largest face per frame.
  3. Alignment: GenD's `align_face` (5 landmarks, scale 1.3, variable-size crop), then CLIP's own preprocessing.
  4. Score: the model's probability that the face is fake (output index 1, checked on GenD's own samples).
  5. Video score: the median over scored frames. The spread (interquartile range) is kept to detect disagreement.

The detector abstains, with a plain reason, when: the video cannot be read; no face is found; the face is too small;
a face is visible in too few frames; too few frames could be scored; frame scores disagree; the score is in the grey
band; or there is no calibration for this kind of video. It never decides a case on its own.
"""
from __future__ import annotations

import hashlib
import statistics
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional, Sequence

import cv2
import numpy as np

from .common import Calibration, ForensicResult, classify

GEND_MODEL_ID = "yermandy/GenD_CLIP_L_14"
GEND_REVISION = "891ce014a0308386c4d7d25b3dcf436a22db5504"
MODEL_NAME = f"GenD_CLIP_L_14@{GEND_REVISION[:7]}"
YUNET_PATH = Path(__file__).resolve().parent.parent / "models" / "face_detection_yunet_2023mar.onnx"

# A detected face: bounding box (x, y, w, h) in frame pixels, 5 landmarks (5x2) in frame pixels, detector confidence.
Face = tuple[tuple[float, float, float, float], np.ndarray, float]
Detector = Callable[[np.ndarray], list[Face]]                 # BGR frame -> faces
Scorer = Callable[[list[np.ndarray]], list[float]]            # aligned RGB faces -> P(fake) each


@dataclass
class VideoSettings:
    n_frames: int = 16            # face frames to score (GenD used 32; 16 keeps CPU time to ~15 s)
    max_tries: int = 48           # frames to try before giving up
    min_face_px: int = 80         # shorter side of the face box; smaller faces are not judged
    min_face_fraction: float = 0.5   # a usable face must appear in at least this share of the frames tried
    min_scored: int = 4           # fewer usable face frames than this -> abstain
    max_spread: float = 0.4       # interquartile range of frame scores above this -> abstain (frames disagree)
    det_score: float = 0.6        # YuNet confidence threshold
    det_max_side: int = 1280      # frames are downscaled to this for detection only; alignment uses full resolution
    batch_size: int = 8


# ---------------------------------------------------------------- frame order (GenD "at_least" mode)

def max_spread_order(n: int, k: int, start: Optional[int] = None) -> list[int]:
    """First k indices of GenD's max-spread permutation of 0..n-1, starting at the middle.

    Same greedy rule as GenD's `max_spread_permutation_pq` (take the index whose distance to all chosen indices is
    largest; ties go to the smaller index), computed for the first k picks only, so it stays fast for long videos.
    """
    if n <= 0 or k <= 0:
        return []
    start = n // 2 if start is None else start
    chosen = [start]
    dist = np.abs(np.arange(n) - start).astype(np.int64)
    dist[start] = -1
    while len(chosen) < min(k, n):
        i = int(np.argmax(dist))          # argmax returns the first (smallest) index among ties
        chosen.append(i)
        dist = np.minimum(dist, np.abs(np.arange(n) - i))
        dist[chosen] = -1
    return chosen


# ---------------------------------------------------------------- alignment (copied from GenD, MIT)

def align_face(img: np.ndarray, landmarks: np.ndarray, scale: float = 1.3) -> np.ndarray:
    """GenD's `align_face` with target_size=None (yermandy/GenD detector.py, MIT): similarity transform of the 5
    landmarks onto a fixed template, with a margin of (scale - 1) around the face; output size follows face size."""
    dst = np.array([[0.34, 0.46], [0.66, 0.46], [0.5, 0.64], [0.37, 0.82], [0.63, 0.82]], dtype=np.float32)
    desired = np.linalg.norm(landmarks[:, None, :] - landmarks[None, :, :], axis=-1)
    dst_d = np.linalg.norm(dst[:, None, :] - dst[None, :, :], axis=-1)
    iu = np.triu_indices(len(dst), k=1)
    size = int(np.round(np.mean(desired[iu] / dst_d[iu]) * scale))
    size = max(size, 8)
    target = (size, size)
    dst = dst.copy()
    dst[:, 0] *= target[0]
    dst[:, 1] *= target[1]
    xm, ym = target[0] * (scale - 1) / 2.0, target[1] * (scale - 1) / 2.0
    dst[:, 0] += xm
    dst[:, 1] += ym
    dst[:, 0] *= target[0] / (target[0] + 2 * xm)
    dst[:, 1] *= target[1] / (target[1] + 2 * ym)
    M = cv2.estimateAffinePartial2D(landmarks.astype(np.float32), dst, method=cv2.LMEDS)[0]
    if M is None:
        raise ValueError("could not align the face")
    return cv2.warpAffine(img, M, target, flags=cv2.INTER_LINEAR)


# ---------------------------------------------------------------- default detector and scorer

class YuNetDetector:
    """OpenCV YuNet. Landmark order (right eye, left eye, nose, right mouth corner, left mouth corner, from the
    subject's point of view) puts the image-left eye first, which is the order GenD's template expects."""

    def __init__(self, model_path: Path = YUNET_PATH, score_threshold: float = 0.6, max_side: int = 1280):
        if not Path(model_path).exists():
            raise FileNotFoundError(f"YuNet model not found at {model_path}")
        self.net = cv2.FaceDetectorYN.create(str(model_path), "", (320, 320), score_threshold, 0.3, 5000)
        self.max_side = max_side

    def __call__(self, frame: np.ndarray) -> list[Face]:
        h, w = frame.shape[:2]
        s = min(1.0, self.max_side / max(h, w))
        small = cv2.resize(frame, (max(1, int(w * s)), max(1, int(h * s))), interpolation=cv2.INTER_AREA) if s < 1 else frame
        self.net.setInputSize((small.shape[1], small.shape[0]))
        _, faces = self.net.detect(small)
        out: list[Face] = []
        if faces is None:
            return out
        for f in faces:
            box = tuple(float(v) / s for v in f[:4])
            lm = (np.asarray(f[4:14], dtype=np.float32).reshape(5, 2)) / s
            out.append((box, lm, float(f[14])))
        return out


class GenDScorer:
    """Loads the published GenD weights once (pinned revision) and returns P(fake) per aligned RGB face."""

    def __init__(self, batch_size: int = 8):
        import torch
        from PIL import Image

        from ._gend_model import GenD

        self.torch, self.Image = torch, Image
        self.model = GenD.from_pretrained(GEND_MODEL_ID, revision=GEND_REVISION).eval()
        self.batch_size = batch_size

    def __call__(self, faces_rgb: list[np.ndarray]) -> list[float]:
        torch = self.torch
        scores: list[float] = []
        for i in range(0, len(faces_rgb), self.batch_size):
            batch = faces_rgb[i:i + self.batch_size]
            x = torch.stack([self.model.feature_extractor.preprocess(self.Image.fromarray(f)) for f in batch])
            with torch.inference_mode():
                p = self.model(x).softmax(dim=-1)[:, 1]
            scores.extend(float(v) for v in p)
        return scores


# ---------------------------------------------------------------- reading frames

def _frame_count(path: str) -> int:
    cap = cv2.VideoCapture(path)
    try:
        if not cap.isOpened():
            return 0
        n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        if 0 < n < 1_000_000:
            return n
        n = 0                                   # unreliable header: count by grabbing
        while cap.grab():
            n += 1
        return n
    finally:
        cap.release()


def read_frames(path: str, indices: Sequence[int]) -> dict[int, np.ndarray]:
    """Decode the requested frames in one sequential pass (seeking is unreliable in many containers)."""
    want = set(indices)
    got: dict[int, np.ndarray] = {}
    if not want:
        return got
    last = max(want)
    cap = cv2.VideoCapture(path)
    try:
        i = 0
        while i <= last and cap.grab():
            if i in want:
                ok, frame = cap.retrieve()
                if ok and frame is not None:
                    got[i] = frame
            i += 1
    finally:
        cap.release()
    if not got:
        # cv2's bundled FFmpeg has no software AV1 decoder ("Failed to get pixel format"), so an AV1 mp4 or webm
        # yields no frames and the face check would report the video as unreadable. PyAV, in the same venv, decodes it
        # with libdav1d. Only used when cv2 decoded nothing, so every clip the calibration saw reads as before.
        got = _read_frames_av(path, want, last)
    return got


def _read_frames_av(path: str, want: set[int], last: int) -> dict[int, np.ndarray]:
    """The same frames through PyAV, turned upright the way cv2 turns them (the display rotation)."""
    got: dict[int, np.ndarray] = {}
    try:
        import av
        with av.open(path) as container:
            for i, frame in enumerate(container.decode(video=0)):
                if i > last:
                    break
                if i in want:
                    img = frame.to_ndarray(format="bgr24")
                    turns = round((getattr(frame, "rotation", 0) or 0) / 90) % 4
                    got[i] = np.ascontiguousarray(np.rot90(img, turns)) if turns else img
    except Exception:  # noqa: BLE001 - a file PyAV cannot decode either stays "could not be read"
        return {}
    return got


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def cell_for(short_side: int) -> str:
    """Calibration cell from resolution: WhatsApp forwards are usually at most 480p on the short side."""
    return "video/sd" if short_side <= 480 else "video/hd"


# ---------------------------------------------------------------- the detector

class GenDVideoForensics:
    kind = "video"

    def __init__(self, calibration: Optional[Calibration] = None, settings: Optional[VideoSettings] = None,
                 detector: Optional[Detector] = None, scorer: Optional[Scorer] = None, model_name: str = MODEL_NAME):
        self.settings = settings or VideoSettings()
        self.calibration = calibration or Calibration.empty(model_name)
        self._detector = detector
        self._scorer = scorer
        self.model_name = model_name

    @property
    def detector(self) -> Detector:
        if self._detector is None:
            self._detector = YuNetDetector(score_threshold=self.settings.det_score, max_side=self.settings.det_max_side)
        return self._detector

    @property
    def scorer(self) -> Scorer:
        if self._scorer is None:
            self._scorer = GenDScorer(batch_size=self.settings.batch_size)
        return self._scorer

    def measure(self, path: Path | str) -> dict:
        """Run the pipeline and return raw measurements, without any decision. Calibration uses this too, so
        thresholds are set on exactly what `analyse` sees."""
        st = self.settings
        path = str(path)
        t0 = time.perf_counter()
        n = _frame_count(path)
        m: dict = {"frames_total": n, "frames_tried": 0, "faces_scored": 0, "no_face": 0, "too_small": 0,
                   "align_failed": 0, "frame_scores": [], "face_px": [], "short_side": None}
        if n == 0:
            m["seconds"] = round(time.perf_counter() - t0, 2)
            return m
        candidates = max_spread_order(n, st.max_tries)
        frames = read_frames(path, candidates)
        t1 = time.perf_counter()
        faces, frame_ids = [], []
        for idx in candidates:                       # keep GenD's spread order, stop once enough faces are found
            if len(faces) >= st.n_frames:
                break
            frame = frames.get(idx)
            if frame is None:
                continue
            m["frames_tried"] += 1
            if m["short_side"] is None:
                m["short_side"] = int(min(frame.shape[:2]))
            dets = self.detector(frame)
            if not dets:
                m["no_face"] += 1
                continue
            box, lm, _ = max(dets, key=lambda d: d[0][2] * d[0][3])       # largest face, as GenD does
            px = int(min(box[2], box[3]))
            m["face_px"].append(px)
            if px < st.min_face_px:
                m["too_small"] += 1
                continue
            try:
                face = align_face(frame, lm)
            except ValueError:
                m["align_failed"] += 1
                continue
            faces.append(cv2.cvtColor(face, cv2.COLOR_BGR2RGB))
            frame_ids.append(idx)
        t2 = time.perf_counter()
        scores = self.scorer(faces) if faces else []
        t3 = time.perf_counter()
        m["faces_scored"] = len(scores)
        m["frame_scores"] = [round(s, 4) for s in scores]
        m["frame_ids"] = frame_ids
        if scores:
            # Rounded once, here: calibration, the decision and the evidence record all use this exact number.
            q = np.percentile(scores, [25, 50, 75])
            m["median"] = round(float(q[1]), 4)
            m["spread"] = round(float(q[2] - q[0]), 4)
        m["seconds"] = {"decode": round(t1 - t0, 2), "detect_align": round(t2 - t1, 2), "score": round(t3 - t2, 2),
                        "total": round(t3 - t0, 2)}
        return m

    def gate(self, m: dict) -> Optional[str]:
        """The abstain gates that come before calibration. Returns a plain reason, or None if the clip can be judged.
        Calibration uses the same gates, so thresholds are only ever set on clips that could reach them."""
        st = self.settings
        if m.get("frames_total", 0) == 0 or m.get("frames_tried", 0) == 0:
            return "the video could not be read"
        if m.get("faces_scored", 0) == 0:
            if m.get("too_small"):
                med = int(statistics.median(m["face_px"]))
                return f"the face is too small to judge (about {med} px; needs {st.min_face_px})"
            if m.get("align_failed"):
                return "the face could not be aligned"
            return "no face was found in the video"
        tried = m["frames_tried"]
        if m["faces_scored"] / tried < st.min_face_fraction:
            return f"a usable face was visible in only {m['faces_scored']} of {tried} frames checked"
        if m["faces_scored"] < st.min_scored:
            return f"only {m['faces_scored']} frames had a usable face"
        if m["spread"] > st.max_spread:
            return "the frames disagree with each other"
        return None

    def decide(self, m: dict, cell: Optional[str] = None) -> tuple[str, str, str, Optional[float], str]:
        """Turn measurements into (status, band, reason, score, cell)."""
        cell = cell or (cell_for(m["short_side"]) if m.get("short_side") else "video/unknown")
        reason = self.gate(m)
        if reason:
            return "abstain", "", reason, m.get("median"), cell
        # Only the clip's own cell: an uncalibrated kind of video abstains.
        status, band, reason = classify(m["median"], self.calibration.cells.get(cell))
        return status, band, reason, m["median"], cell

    def analyse(self, path: Path | str, cell: Optional[str] = None) -> ForensicResult:
        path = Path(path)
        if not path.is_file():
            return ForensicResult(kind="video", status="abstain", reason="the file was not found", model=self.model_name)
        try:                                         # hash first: the record must name the exact bytes analysed
            digest = sha256_of(path)
        except OSError as e:                         # locked, still downloading, or no permission
            return ForensicResult(kind="video", status="abstain", reason=f"the file could not be read ({type(e).__name__})",
                                  model=self.model_name, extra={"sha256": None})
        try:
            m = self.measure(path)
        except Exception as e:                       # a detector must never crash the case; it abstains instead
            why = ("the detector's model files are missing; run scripts/fetch_models.sh" if isinstance(e, OSError)
                   else f"the video could not be analysed ({type(e).__name__})")
            return ForensicResult(kind="video", status="abstain", reason=why, model=self.model_name, extra={"sha256": digest})
        status, band, reason, score, cell = self.decide(m, cell)
        extra = {k: v for k, v in m.items()}
        extra["sha256"] = digest
        extra["settings"] = vars(self.settings).copy()
        return ForensicResult(kind="video", status=status, band=band, score=score, model=self.model_name, cell=cell,
                              reason=reason, extra=extra)
