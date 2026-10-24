"""Audio deepfake (voice-clone) detector: DF Arena on 4-second windows, with honest abstention.

Pipeline:
  1. Decode any audio or video file with PyAV (FFmpeg inside) to 16 kHz mono float32. A video's soundtrack is read
     the same way, so the same detector checks the voice in a video (docs/plan.md, section 2, step 4).
  2. Find speech with a simple energy detector: 30 ms frames that are clearly above the clip's own noise floor and
     above an absolute floor (a muted microphone stays far below it).
  3. Windows: up to `max_windows` windows of 64,600 samples (4.04 s, the model's own input length), spread over the
     part of the clip that holds speech. A clip shorter than one window is tiled, as DF Arena's feature extractor does.
  4. Score: DF Arena's probability that a window is spoofed (output index 0, "spoof" in its config).
  5. Clip score: the median over windows. The range (max - min) is kept to detect windows that disagree.

The detector abstains, with a plain reason, when: the file cannot be decoded; there is less than `min_speech_s` of
speech; the windows disagree; the score is in the grey band; or there is no calibration for this kind of audio.
It never decides a case on its own.

Model choice (MODELS.md): DF Arena 1B is the stronger model (In-the-Wild EER 0.91% on its card; 93.66% of Hindi fakes
caught in the independent LRLspoof benchmark, against 6.59% for the 500M). The 500M is the fallback for a laptop
that cannot hold the 1B. Both are loaded from a pinned Hugging Face revision. DF Arena's own code is under a
non-commercial licence, so it is never copied into this repository: it is imported at run time from the pinned
download, which stays in the Hugging Face cache.
"""
from __future__ import annotations

import hashlib
import importlib.util
import math
import statistics
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional, Sequence

import numpy as np

from .common import Calibration, ForensicResult, classify

SAMPLE_RATE = 16000
LIVE_REPLAY = "live-replay"      # channel for a recording made by playing a phone's speaker into a microphone
WINDOW = 64600                   # DF Arena's input length (feature_extraction_antispoofing.py pads or cuts to this)

DF_ARENA = {
    "1B": ("Speech-Arena-2025/DF_Arena_1B_V_1", "fb6ce85de12c2c5a509d89114adaf827dd75f49f", "DF_Arena_1B",
           "facebook/wav2vec2-xls-r-1b"),
    "500M": ("Speech-Arena-2025/DF_Arena_500M_V_1", "8258fa8e74ff9b8ad20d4c939c1a7f694a6e4080", "DF_Arena_500M",
             "facebook/wav2vec2-xls-r-300m"),
}


def model_name(size: str) -> str:
    repo, rev, _, _ = DF_ARENA[size]
    return f"{repo.split('/')[-1]}@{rev[:7]}"


Scorer = Callable[[list[np.ndarray]], list[float]]            # 16 kHz windows -> P(spoof) each


@dataclass
class AudioSettings:
    max_windows: int = 3          # windows to score (3 x 4.04 s ~ 12 s; about 7 s of CPU with the 500M model)
    min_speech_s: float = 2.0     # less voice than this -> abstain (detectors fail below about 2 s: Pindrop; SpecRNet)
    max_range: float = 0.6        # max - min of window scores above this -> abstain (windows disagree)
    frame_ms: int = 30            # speech detector frame
    speech_below_peak_db: float = 30.0    # a voiced frame is within this of the clip's loud level (99th percentile)
    speech_min_dbfs: float = -65.0        # and above this absolute level (a muted microphone sits near -90 dBFS)


# ---------------------------------------------------------------- reading audio

def decode_audio(path: Path | str) -> tuple[np.ndarray, int, str]:
    """The first audio track of any file PyAV can open, as 16 kHz mono float32, plus source sample rate and codec."""
    import av
    with av.open(str(path)) as container:
        stream = next((s for s in container.streams if s.type == "audio"), None)
        if stream is None:
            raise ValueError("no audio track")
        source_rate = int(stream.codec_context.sample_rate or stream.rate or 0)
        codec = stream.codec_context.name
        resampler = av.AudioResampler(format="flt", layout="mono", rate=SAMPLE_RATE)
        chunks = []
        for frame in container.decode(stream):
            chunks += [f.to_ndarray().reshape(-1) for f in resampler.resample(frame)]
        chunks += [f.to_ndarray().reshape(-1) for f in resampler.resample(None)]
    wav = np.concatenate(chunks).astype(np.float32) if chunks else np.zeros(0, np.float32)
    return wav, source_rate, codec


def speech_mask(wav: np.ndarray, st: AudioSettings) -> np.ndarray:
    """One boolean per frame: is this frame voiced? Measured from the clip's loud level, not its quietest frames,
    because in non-stop speech the quietest frames are speech too. Pauses fall well below the loud level, and a muted
    microphone never reaches the absolute floor."""
    n = int(SAMPLE_RATE * st.frame_ms / 1000)
    if len(wav) < n:
        return np.zeros(0, bool)
    frames = wav[: len(wav) // n * n].reshape(-1, n)
    db = 10 * np.log10(np.mean(frames.astype(np.float64) ** 2, axis=1) + 1e-12)
    loud = np.percentile(db, 99)
    return (db > loud - st.speech_below_peak_db) & (db > st.speech_min_dbfs)


def speech_windows(wav: np.ndarray, mask: np.ndarray, st: AudioSettings) -> list[np.ndarray]:
    """Up to max_windows windows of WINDOW samples spread over the stretch that holds speech."""
    if len(wav) == 0:
        return []
    n = int(SAMPLE_RATE * st.frame_ms / 1000)
    idx = np.flatnonzero(mask)
    lo, hi = (int(idx[0]) * n, int(idx[-1] + 1) * n) if len(idx) else (0, len(wav))
    span = wav[lo:hi]
    if len(span) <= WINDOW:                               # short clip: tile it, as DF Arena's extractor does
        reps = WINDOW // max(len(span), 1) + 1
        return [np.tile(span, reps)[:WINDOW]]
    k = min(st.max_windows, int(np.ceil(len(span) / WINDOW)))
    starts = np.linspace(0, len(span) - WINDOW, k).astype(int)
    return [span[s:s + WINDOW] for s in starts]


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def channel_for(codec: str, source_rate: int) -> str:
    """How the audio reached us. WhatsApp voice notes and browser recordings are Opus; the sound of a phone or
    WhatsApp video (and an iPhone voice memo) is AAC; phone calls are 8 kHz."""
    if source_rate and source_rate <= 8000 or codec in ("amr_nb", "amrnb", "gsm", "pcm_mulaw", "pcm_alaw"):
        return "phone-8k"
    if codec == "opus":
        return "whatsapp-opus"
    if codec == "aac":
        return "aac"
    return "clean"


def cell_for(language: str, channel: str) -> str:
    return f"{language}/{channel}"


# ---------------------------------------------------------------- the model

class DFArenaScorer:
    """Loads DF Arena once from the pinned Hugging Face download and returns P(spoof) per 4.04 s window.

    The model code (backbone.py, conformer.py) comes from the pinned snapshot in the Hugging Face cache and is imported
    from there; it is not copied into this repository because of its non-commercial licence. Weights are loaded with
    torch.load(weights_only=True, mmap=True), so a 4.6 GB checkpoint is paged in rather than copied into memory.
    `int8=True` quantises the Linear layers dynamically, which roughly quarters their memory and speeds up a CPU.
    `device` defaults to the GPU when there is one (the team's EC2 g4dn box) and the CPU otherwise."""

    def __init__(self, size: str = "500M", int8: bool = False, threads: Optional[int] = None,
                 device: Optional[str] = None):
        import torch
        from huggingface_hub import snapshot_download

        repo, rev, cls_name, ssl_id = DF_ARENA[size]
        snap = Path(snapshot_download(repo, revision=rev, local_files_only=True))
        pkg = f"_dfarena_{size.lower()}"
        if pkg not in sys.modules:                         # import backbone.py and conformer.py as one package
            spec = importlib.util.spec_from_file_location(pkg, snap / "backbone.py", submodule_search_locations=[str(snap)])
            module = importlib.util.module_from_spec(spec)
            sys.modules[pkg] = module

            class _LocalConfig:                            # the backbone fetches its SSL config by name: read the cache
                @staticmethod
                def from_pretrained(name, **kw):
                    from transformers import Wav2Vec2Config
                    return Wav2Vec2Config.from_pretrained(name, local_files_only=True, **kw)

            import transformers
            real = transformers.Wav2Vec2Config
            transformers.Wav2Vec2Config = _LocalConfig   # only while backbone.py runs `from transformers import ...`
            try:
                spec.loader.exec_module(module)
            finally:
                transformers.Wav2Vec2Config = real
        net = getattr(sys.modules[pkg], cls_name)()
        state = torch.load(snap / "pytorch_model.bin", map_location="cpu", weights_only=True, mmap=True)
        state = {k.removeprefix("backbone."): v for k, v in state.items() if k.startswith("backbone.")}
        missing, unexpected = net.load_state_dict(state, strict=False)
        if missing or unexpected:
            raise RuntimeError(f"DF Arena weights do not match its code: missing {missing[:3]}, unexpected {unexpected[:3]}")
        net.eval()
        device = device or ("cuda" if torch.cuda.is_available() else "cpu")
        if int8 and device == "cpu":
            net = torch.ao.quantization.quantize_dynamic(net, {torch.nn.Linear}, dtype=torch.qint8)
        net = net.to(device)
        if threads:
            torch.set_num_threads(threads)
        self.torch, self.net, self.size, self.int8, self.device = torch, net, size, int8, device

    def __call__(self, windows: list[np.ndarray]) -> list[float]:
        torch = self.torch
        out = []
        with torch.inference_mode():
            for w in windows:
                logits = self.net(torch.from_numpy(np.ascontiguousarray(w, dtype=np.float32)).to(self.device))
                out.append(spoof_probability(float(logits[0, 0]), float(logits[0, 1])))
        return out


def spoof_probability(spoof_logit: float, bonafide_logit: float) -> float:
    """P(spoof) from the two logits (index 0 = "spoof" in config.json id2label), the same value as the 2-class
    softmax but in float64. A float32 softmax reaches exactly 1.0 once the margin passes about 17, and then real and
    fake clips tie at the top and the 5% threshold flags more than 5% of real clips."""
    d = spoof_logit - bonafide_logit
    return 1.0 / (1.0 + math.exp(-d)) if d > -700 else 0.0


# ---------------------------------------------------------------- the detector

class DFArenaAudioForensics:
    kind = "audio"

    def __init__(self, calibration: Optional[Calibration] = None, settings: Optional[AudioSettings] = None,
                 scorer: Optional[Scorer] = None, size: str = "500M", int8: bool = False, name: Optional[str] = None):
        self.settings = settings or AudioSettings()
        self.size, self.int8 = size, int8
        self.model_name = name or (model_name(size) + ("+int8" if int8 else ""))
        self.calibration = calibration or Calibration.empty(self.model_name)
        self._scorer = scorer

    @property
    def scorer(self) -> Scorer:
        if self._scorer is None:
            self._scorer = DFArenaScorer(self.size, int8=self.int8)
        return self._scorer

    def measure_wave(self, wav: np.ndarray, source_rate: int = SAMPLE_RATE, codec: str = "pcm") -> dict:
        """Raw measurements for an already decoded clip, without any decision (calibration uses this too)."""
        st = self.settings
        t0 = time.perf_counter()
        mask = speech_mask(wav, st)
        m: dict = {"duration_s": round(len(wav) / SAMPLE_RATE, 2), "speech_s": round(mask.sum() * st.frame_ms / 1000, 2),
                   "source_rate": source_rate, "codec": codec, "window_scores": []}
        if m["speech_s"] >= st.min_speech_s:
            windows = speech_windows(wav, mask, st)
            t1 = time.perf_counter()
            scores = self.scorer(windows)
            m["window_scores"] = [round(s, 4) for s in scores]
            m["median"] = float(statistics.median(scores))
            m["range"] = float(max(scores) - min(scores))
            m["seconds"] = {"prepare": round(t1 - t0, 2), "score": round(time.perf_counter() - t1, 2)}
        return m

    def measure(self, path: Path | str) -> dict:
        t0 = time.perf_counter()
        wav, rate, codec = decode_audio(path)
        m = self.measure_wave(wav, rate, codec)
        m["decode_s"] = round(time.perf_counter() - t0, 2) - sum((m.get("seconds") or {}).values())
        return m

    def gate(self, m: dict) -> Optional[str]:
        """Abstain gates that come before calibration; the same gates apply when thresholds are set."""
        st = self.settings
        if m.get("duration_s", 0) == 0:
            return "the recording holds no audio"
        if m.get("speech_s", 0) < st.min_speech_s:
            if m.get("speech_s", 0) == 0:
                return "no voice can be heard in the recording"
            return f"only {m['speech_s']:.1f} s of voice (needs {st.min_speech_s:.0f} s to judge)"
        if m.get("range", 0) > st.max_range:
            return "parts of the recording disagree with each other"
        return None

    def decide(self, m: dict, language: str = "hi", channel: Optional[str] = None) -> tuple[str, str, str, Optional[float], str]:
        channel = channel or channel_for(m.get("codec", ""), m.get("source_rate", 0))
        cell = cell_for(language, channel)
        reason = self.gate(m)
        if reason:
            return "abstain", "", reason, m.get("median"), cell
        cal = self.calibration.cells.get(cell)
        if cal is None and channel == LIVE_REPLAY:
            # No replay clips calibrated yet: judge it like a browser (Opus) recording, but see below.
            cal = self.calibration.cells.get(cell_for(language, "whatsapp-opus"))
        cal = cal or self.calibration.cells.get(cell_for(language, "any"))
        status, band, reason = classify(m["median"], cal)
        if channel == LIVE_REPLAY and status == "clean":
            # Played through a speaker into a microphone, a clone loses much of what gives it away (ReplayDF: one strong
            # model went from 4.7% to 18.2% EER). So "no signs" means little here; signs of cloning still count.
            status, reason = "abstain", "the voice was replayed through a speaker, which can hide signs of cloning"
        return status, band, reason, m["median"], cell

    def analyse(self, path: Path | str, language: str = "hi", channel: Optional[str] = None) -> ForensicResult:
        """`channel` overrides how the audio is taken to have arrived; pass "live-replay" for a recording made by
        playing a phone's speaker into a microphone, which hides a clone's traces and has its own thresholds."""
        path = Path(path)
        if not path.is_file():
            return ForensicResult(kind="audio", status="abstain", reason="the file was not found", model=self.model_name)
        try:
            m = self.measure(path)
        except Exception as e:                       # a detector must never crash the case; it abstains instead
            return ForensicResult(kind="audio", status="abstain", reason=f"the audio could not be read ({type(e).__name__})",
                                  model=self.model_name, extra={"sha256": sha256_of(path)})
        status, band, reason, score, cell = self.decide(m, language, channel)
        extra = dict(m)
        extra["sha256"] = sha256_of(path)
        extra["settings"] = vars(self.settings).copy()
        return ForensicResult(kind="audio", status=status, band=band, score=None if score is None else round(score, 4),
                              model=self.model_name, cell=cell, reason=reason, extra=extra)


CALIBRATION = Path(__file__).resolve().parent.parent / "calibration" / "audio.json"


def default_detector() -> DFArenaAudioForensics:
    """The detector forensics/analyse.py and the service pick up: DF Arena 500M with the committed calibration. The
    model itself loads on the first clip, not here. Without the calibration file every result abstains ("not
    calibrated"), never an uncalibrated score (docs/plan.md, fallback)."""
    cal = Calibration.load(CALIBRATION) if CALIBRATION.exists() else None
    return DFArenaAudioForensics(calibration=cal)


def analyse_windows(scores: Sequence[float]) -> tuple[float, float]:
    """(median, range) of window scores; used by tests and reports."""
    return float(statistics.median(scores)), float(max(scores) - min(scores))
