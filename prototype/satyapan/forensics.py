"""F3 media forensics. Corroboration only: these signals are soft, so they can never anchor a RED, and each
detector abstains outside the conditions it was calibrated for.

- NullAudioForensics abstains ("no calibrated detector loaded").
- AASISTAudioForensics loads an AASIST-L checkpoint (MIT, clovaai/aasist) when torch is installed and a per-cell
  calibration file exists.
- DocumentForensics: error-level analysis plus creator metadata; abstains on small or recompressed images.
- SimulatedForensics: rehearsal only; its results are labelled SIMULATED wherever they appear.
- RemoteForensics: the finale detectors (satyapan-finale: GenD face check + audio deepfake check) through their local
  service, which keeps the models loaded. A video gets a face result and a voice result. If the service is not
  running, the file gets one abstaining result that says so; a case never fails because of forensics.
"""
from __future__ import annotations

import io
import os
import json
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Optional, Protocol

from .adapters import Label
from .media import SAMPLE_RATE, decode_audio  # noqa: F401 - re-exported: calibrate.py and the tests import it from here

BAND_HI = {"low": "कम", "moderate": "मध्यम", "high": "अधिक"}
ROOT = Path(__file__).resolve().parent.parent
AASIST_DIR = ROOT / "vendor" / "aasist"                      # clovaai/aasist code + AASIST-L weights (MIT), via setup-models
AASIST_CALIBRATION = ROOT / "data" / "forensics" / "aasist_calibration.json"   # written by `satyapan calibrate-audio`


@dataclass
class ForensicResult:
    kind: str                      # audio | document | video
    status: str                    # synthetic | edited | clean | abstain
    band: str = ""                 # low | moderate | high
    score: Optional[float] = None
    reason: str = ""
    model: str = ""
    cell: str = ""                 # calibration cell, e.g. "hi/whatsapp-opus"
    simulated: bool = False
    extra: dict = field(default_factory=dict)


class AudioForensics(Protocol):
    label: Label
    def analyse(self, path: Path, language: str = "hi") -> ForensicResult: ...


class NullAudioForensics:
    label = Label("Audio forensics", "No voice detector loaded in this process", "Model risk",
                  "abstains here; when the local forensics service runs, voice notes are checked there", mock=False)

    def analyse(self, path: Path, language: str = "hi") -> ForensicResult:
        return ForensicResult(kind="audio", status="abstain", reason="no calibrated audio detector loaded", model="none")


class SimulatedForensics:
    """Rehearsal stand-in that returns whatever the scenario scripted. Never used on a real customer."""
    label = Label("Audio forensics (SIMULATED)", "AASIST-L anti-spoofing (CPU)", "Model risk", "scenario-scripted result for rehearsal")

    def __init__(self, result: dict):
        self.result = result

    def analyse(self, path: Path, language: str = "hi") -> ForensicResult:
        r = self.result
        return ForensicResult(kind=r.get("kind", "audio"), status=r.get("status", "abstain"), band=r.get("band", ""), score=r.get("score"),
                              reason="SIMULATED result for rehearsal (no model loaded)", model="simulated", cell=r.get("cell", ""), simulated=True)


class AASISTAudioForensics:
    """Real detector: AASIST-L (clovaai/aasist, MIT), trained on ASVspoof 2019 LA, run on CPU.

    Needs torch, PyAV, the vendored AASIST code and weights, and a calibration JSON giving, per cell "lang/codec",
    the score thresholds at 20%, 5% and 1% false-synthetic rate measured on GENUINE speech (`satyapan
    calibrate-audio`). score >= t_fpr5 -> synthetic; t_fpr20 <= score < t_fpr5 -> abstain (grey band); below ->
    clean. Clips under 3 s, audio that will not decode, and cells without calibration abstain, with the reason and,
    where the model did run, its score, so the officer sees a real model ran and why it said nothing.

    What the calibration measures is false alarms on real speech re-encoded through each channel. How often the model
    catches a modern Indian-language voice clone is not measured here, which is why it counts only through these
    calibrated bands.
    """
    label = Label("Audio forensics", "AASIST-L (clovaai/aasist, MIT) on CPU", "Model risk", "in-process model with per-cell calibration", mock=False)
    WINDOW = 64600  # ~4 s at 16 kHz, as in the AASIST recipe; the score is the mean over windows

    def __init__(self, checkpoint: Path, calibration: Optional[Path], vendor_dir: Path):
        import sys
        import torch
        if str(vendor_dir) not in sys.path:
            sys.path.insert(0, str(vendor_dir))
        from models.AASIST import Model  # type: ignore  # clovaai/aasist
        cfg = json.loads((vendor_dir / "config" / "AASIST-L.conf").read_text())["model_config"]
        self.torch = torch
        self.model = Model(cfg)
        self.model.load_state_dict(torch.load(checkpoint, map_location="cpu", weights_only=True))
        self.model.eval()
        self.calib = json.loads(Path(calibration).read_text()) if calibration and Path(calibration).exists() else {}

    @staticmethod
    def _cell(sample_rate: int, language: str) -> str:
        codec = "amr-8k" if sample_rate <= 8000 else ("clean-16k" if sample_rate <= 16000 else "whatsapp-opus")
        return f"{language}/{codec}"

    def score(self, wav16) -> float:
        """Mean spoof-minus-bona-fide logit over ~4 s windows of 16 kHz mono audio. Higher means more synthetic."""
        x = self.torch.from_numpy(wav16)
        n = self.WINDOW
        chunks = [x[i:i + n] for i in range(0, max(1, len(x) - n + 1), n)] or [x]
        scores = []
        with self.torch.no_grad():
            for c in chunks:
                if len(c) < n:
                    c = self.torch.nn.functional.pad(c, (0, n - len(c)))
                _, out = self.model(c.unsqueeze(0))
                scores.append(float(out[0, 0] - out[0, 1]))  # spoof logit minus bona fide logit
        return float(sum(scores) / len(scores))

    def analyse(self, path: Path, language: str = "hi") -> ForensicResult:
        language = language if language in ("hi", "en") else "hi"
        try:
            wav, source_rate, codec = decode_audio(path)
        except Exception as e:  # noqa: BLE001 - an unreadable file is an abstain, never a crash or a verdict
            return ForensicResult("audio", "abstain", reason=f"could not decode the audio ({type(e).__name__})", model="AASIST-L")
        dur = len(wav) / SAMPLE_RATE
        cell = self._cell(source_rate, language)
        if dur < 3.0:
            return ForensicResult("audio", "abstain", reason=f"only {dur:.1f} s of audio (< 3 s)", model="AASIST-L", cell=cell)
        score = round(self.score(wav), 3)
        th = self.calib.get(cell)
        if not isinstance(th, dict) or "t_fpr5" not in th:
            return ForensicResult("audio", "abstain", score=score, reason=f"the model ran, but it has no calibration for {cell} audio",
                                  model="AASIST-L", cell=cell, extra={"codec": codec})
        if score >= th["t_fpr5"]:
            band = "high" if score >= th.get("t_fpr1", th["t_fpr5"] + 1.0) else "moderate"
            return ForensicResult("audio", "synthetic", band=band, score=score, model="AASIST-L", cell=cell, extra={"codec": codec})
        if score >= th["t_fpr20"]:
            return ForensicResult("audio", "abstain", score=score, reason="score in the grey band between 5% and 20% FPR",
                                  model="AASIST-L", cell=cell, extra={"codec": codec})
        return ForensicResult("audio", "clean", score=score, model="AASIST-L", cell=cell, extra={"codec": codec})


class DFArenaAudioForensics:
    """The team repository's voice detector (codebreaker32/satyapan: forensics/audio.py, calibration/audio.json),
    behind this engine's ForensicResult. DF Arena 500M (Speech-Arena-2025, non-commercial licence), calibrated per
    language and channel on public real speech (In-the-Wild, Gram Vaani, FLEURS) and checked on real circulated fakes.

    It replaces AASIST-L, which is near chance on real circulated fakes (full AASIST: 43% EER on In-the-Wild). The model
    loads on the first voice note (about a minute on the team laptop), not at start-up. `channel="live-replay"` marks
    a recording made by playing the customer's phone into the console's microphone: there "no signs" becomes "unsure",
    because replay hides a clone's traces."""
    label = Label("Audio forensics", "DF Arena 500M (Speech-Arena-2025, Idiap; non-commercial licence) on CPU, "
                  "calibrated per language and channel", "Model risk", "in-process model with per-channel calibration",
                  mock=False)
    accepts_channel = True

    def __init__(self, repo: Path):
        import sys
        if str(repo) not in sys.path:
            sys.path.insert(0, str(repo))
        from forensics.audio import DFArenaAudioForensics as TeamDetector   # the team repo's top-level package
        from forensics.common import Calibration
        self.repo = repo
        self.detector = TeamDetector(calibration=Calibration.load(repo / "calibration" / "audio.json"))

    def analyse(self, path: Path, language: str = "hi", channel: Optional[str] = None) -> ForensicResult:
        r = self.detector.analyse(path, language=language if language in ("hi", "en") else "hi", channel=channel)
        keep = {k: r.extra.get(k) for k in ("speech_s", "duration_s", "window_scores", "codec", "source_rate", "seconds")}
        return ForensicResult(kind="audio", status=r.status, band=r.band, score=r.score, reason=r.reason, model=r.model,
                              cell=r.cell, extra={k: v for k, v in keep.items() if v is not None})


# The voice detector's repository: this engine's parent when it sits in prototype/ of the team repository, else a
# sibling checkout named satyapan-team (the laptop layout). SATYAPAN_TEAM_REPO overrides both.
TEAM_REPO = Path(os.environ.get("SATYAPAN_TEAM_REPO")
                 or (ROOT.parent if (ROOT.parent / "forensics" / "audio.py").exists() else ROOT.parent.parent / "satyapan-team"))


@lru_cache(maxsize=1)
def default_audio_forensics():
    """The best real detector that is installed and calibrated, else the abstaining stand-in. Loaded once per
    process, because every engine (and every test) would otherwise load torch and the weights again.

    SATYAPAN_AUDIO picks one: "dfarena" (the default when the team repository and its calibration are present),
    "aasist", or "none". The test suite pins "aasist" so its results do not depend on a 1.7 GB download."""
    choice = os.environ.get("SATYAPAN_AUDIO", "").lower()
    if choice == "none":
        return NullAudioForensics()
    # Both real detectors need torch. Without it (the engine's own environment on the demo laptop, where the voice check
    # runs in the forensics service instead) the label must not name a model that cannot run in this process.
    import importlib.util
    if importlib.util.find_spec("torch") is None:
        return NullAudioForensics()
    if choice in ("", "dfarena") and (TEAM_REPO / "calibration" / "audio.json").exists():
        try:
            return DFArenaAudioForensics(TEAM_REPO)
        except Exception:  # noqa: BLE001 - a broken checkout falls back to AASIST-L, never a crash
            pass
    ckpt = AASIST_DIR / "models" / "weights" / "AASIST-L.pth"
    if not (ckpt.exists() and AASIST_CALIBRATION.exists()):
        return NullAudioForensics()
    try:
        return AASISTAudioForensics(ckpt, AASIST_CALIBRATION, AASIST_DIR)
    except Exception:  # noqa: BLE001 - torch missing or a broken download: the abstaining stand-in, never a crash
        return NullAudioForensics()


# AI image tools that name themselves in a file's metadata (EXIF Software, PNG text, XMP). Matched only inside
# metadata text, never in the pixel data, so a random run of bytes cannot match.
AI_TOOLS = {"dall-e": "DALL·E", "dall·e": "DALL·E", "midjourney": "Midjourney", "stable diffusion": "Stable Diffusion",
            "stablediffusion": "Stable Diffusion", "comfyui": "Stable Diffusion (ComfyUI)", "firefly": "Adobe Firefly",
            "imagen": "Google Imagen", "gemini": "Google Gemini", "chatgpt": "ChatGPT", "openai": "OpenAI",
            "ideogram": "Ideogram", "leonardo.ai": "Leonardo.Ai"}


def ai_tool_label(path: Path, img) -> str:
    """The AI tool a document's own file label names, or "" when it names none. A missing label proves nothing:
    labels are easy to strip, and WhatsApp strips them. This only reads what the file says about itself."""
    try:
        head = path.read_bytes()[: 32 << 20]
    except OSError:
        head = b""
    # IPTC digital source type, written into XMP and C2PA content credentials by OpenAI, Adobe, Google and others
    if b"trainedAlgorithmicMedia" in head:
        return "content credentials: made by a trained algorithm"
    texts = [v.decode("utf-8", "ignore") if isinstance(v, bytes) else v for v in img.info.values() if isinstance(v, (str, bytes))]
    try:
        texts += [str(v) for v in img.getexif().values() if isinstance(v, (str, bytes))]
    except Exception:  # noqa: BLE001 - unreadable EXIF is no label
        pass
    blob = " ".join(texts).lower()
    if "steps:" in blob and "sampler:" in blob:          # the generation settings Stable Diffusion web UIs write
        return "Stable Diffusion (generation settings in the file)"
    return next((name for key, name in AI_TOOLS.items() if key in blob), "")


class DocumentForensics:
    label = Label("Document forensics", "Error-level analysis + creator metadata; seal and font checks are stretch", "Model risk",
                  "in-process; abstains on small or recompressed images", mock=False)

    def analyse(self, path: Path) -> ForensicResult:
        from PIL import Image, ImageChops
        # The reason is shown to the officer and signed into the pack, so it is a plain sentence: never an exception's
        # text, which carried the laptop's absolute upload path, and never "cannot open" for a PDF whose text was read.
        if Path(path).suffix.lower() == ".pdf":
            return ForensicResult("document", "abstain", reason="the document check reads photos and scans; a PDF's "
                                  "pages are not checked", model="ELA")
        try:
            img = Image.open(path)
        except Exception:  # noqa: BLE001
            return ForensicResult("document", "abstain", reason="the file did not open as an image", model="ELA")
        tool = ai_tool_label(Path(path), img)
        if tool:
            return ForensicResult("document", "synthetic", band="high", model="file label", extra={"ai_tool": tool})
        software = ""
        try:
            software = str(img.getexif().get(305, "")) or str(img.info.get("Software", ""))  # EXIF 305 = Software
        except Exception:  # noqa: BLE001
            pass
        rgb = img.convert("RGB")
        if min(rgb.size) < 600:
            return ForensicResult("document", "abstain", reason=f"image too small for ELA ({rgb.size[0]}x{rgb.size[1]})", model="ELA")
        if img.format == "JPEG" and getattr(img, "quantization", None):
            tbl = img.quantization.get(0) or []
            q = sum(tbl) / len(tbl) if tbl else 0
            if q > 12:   # WhatsApp-style recompression: ELA would mostly measure the recompression itself
                return ForensicResult("document", "abstain", reason=f"recompressed JPEG (mean quant {q:.0f}); ELA unreliable", model="ELA")
        buf = io.BytesIO()
        rgb.save(buf, "JPEG", quality=90)
        buf.seek(0)
        diff = ImageChops.difference(rgb, Image.open(buf))
        px = list(diff.getdata())
        mean = sum(sum(p) for p in px) / (3 * len(px))
        mx = max(max(p) for p in px)
        suspicious = mean > 6.0 or mx > 180
        band = "moderate" if (mean > 10 or mx > 220) else "low"
        if software and any(k in software.lower() for k in ("photoshop", "gimp", "canva", "pixlr", "snapseed")):
            suspicious, band = True, "moderate"
        return ForensicResult("document", "edited" if suspicious else "clean", band=band if suspicious else "", score=round(mean, 2),
                              model="ELA", extra={"ela_mean": round(mean, 2), "ela_max": mx, "software": software})


class RemoteForensics:
    """Client for the satyapan-finale forensics service (`python -m forensics.service`, http://127.0.0.1:8765)."""

    def __init__(self, url: str, timeout: float = 900.0):
        self.url = url.rstrip("/")
        # How long a check may take. A one-minute 1080p video takes about 2.5 minutes on this laptop's CPU and the
        # upload cap allows longer clips; a shorter wait ended with "the forensics service is not running" while the
        # service was still working, and a second request queued behind the first.
        self.timeout = timeout
        # Prefetch: forensics start when a file is uploaded (alongside speech-to-text), and run() picks up the result
        # by content hash, so the officer is not waiting for the face check after clicking Run.
        import threading
        self._lock = threading.Lock()
        self._pending: dict = {}
        self.label = Label("Video and audio forensics", "GenD CLIP-L/14 face check (MIT) and DF Arena 500M voice check "
                           "(non-commercial licence), calibrated per kind of input", "Model risk",
                           f"local service at {self.url}; abstains when unsure, uncalibrated or not running", mock=False)

    def _call(self, method: str, route: str, body: Optional[dict] = None, timeout: Optional[float] = None) -> dict:
        import urllib.request
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(self.url + route, data=data, method=method, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout or self.timeout) as r:
            return json.load(r)

    def health(self) -> Optional[dict]:
        try:
            return self._call("GET", "/health", timeout=10)   # answered at once even while a check runs
        except Exception:  # noqa: BLE001 - any failure means "not running"
            return None

    @staticmethod
    def _sha(path: Path) -> str:
        import hashlib
        h = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
        return h.hexdigest()

    @staticmethod
    def _key(sha: str, language: str, channel: Optional[str]) -> str:
        return f"{sha}|{language}|{channel or ''}"      # the voice check is calibrated per language and channel

    def prefetch(self, path: Path, kind: str, language: str = "hi", channel: Optional[str] = None) -> None:
        """Start the analysis of a private copy of `path` in the background (the upload is moved after decoding)."""
        import shutil
        import tempfile
        import threading
        try:
            sha = self._sha(path)
        except OSError:
            return
        sha = self._key(sha, language, channel)
        with self._lock:
            e = self._pending.get(sha)
            if e is not None and not (e["done"].is_set() and _unreachable(e["results"] or [])):
                return                                   # already running, or a real answer is cached
            done = threading.Event()
            self._pending[sha] = {"done": done, "results": None}
        tmp = Path(tempfile.mkdtemp(prefix="satyapan-forensics-"))
        copy = tmp / Path(path).name
        shutil.copyfile(path, copy)

        def work():
            try:
                self._pending[sha]["results"] = self._fetch(copy, kind, language, channel)
            finally:
                shutil.rmtree(tmp, ignore_errors=True)
                done.set()
        threading.Thread(target=work, daemon=True).start()

    def analyse_all(self, path: Path, kind: str, language: str = "hi", channel: Optional[str] = None) -> list[ForensicResult]:
        try:
            sha = self._key(self._sha(path), language, channel)
        except OSError:
            sha = None
        entry = self._pending.get(sha) if sha else None
        if entry is not None and entry["done"].wait(self.timeout) and entry["results"] is not None:
            # Reuse any real answer from the service, including its own abstains ("audio detector not installed yet").
            # Only a client-side failure (service unreachable at upload time) is retried now.
            if not _unreachable(entry["results"]):
                return entry["results"]
        results = self._fetch(path, kind, language, channel)
        if sha and not _unreachable(results):          # keep it, so a re-run (strike a field) does not re-analyse
            import threading
            done = threading.Event()
            done.set()
            with self._lock:
                self._pending[sha] = {"done": done, "results": results}
        return results

    def _fetch(self, path: Path, kind: str, language: str = "hi", channel: Optional[str] = None) -> list[ForensicResult]:
        body = {"path": str(Path(path).resolve()), "language": language if language in ("hi", "en") else "hi"}
        if channel:
            body["channel"] = channel
        if kind in ("audio", "video"):
            body["kind"] = kind      # a browser voice recording is WebM: without this the service would face-check it
        try:
            out = self._call("POST", "/analyse", body)
        except Exception as e:  # noqa: BLE001 - not running, timed out, or bad reply: abstain, never fail the case
            if isinstance(e, TimeoutError) or isinstance(getattr(e, "reason", None), TimeoutError):
                # still working on it, so not "not running"; and not retried, which would queue a second copy behind it
                return [ForensicResult(kind=kind, status="abstain", model="none",
                                       reason=f"the media checks did not finish within {int(self.timeout // 60)} minutes")]
            return [ForensicResult(kind=kind, status="abstain", reason="the forensics service is not running", model="none",
                                   extra={"unreachable": True})]
        results = []
        for d in out.get("results", []):
            if d.get("status") not in ("synthetic", "clean", "abstain") or d.get("kind") not in ("audio", "video"):
                continue
            if kind == "audio" and d.get("kind") == "video":
                continue             # a voice note has no face to check, whatever an older service answered
            results.append(ForensicResult(kind=d["kind"], status=d["status"], band=d.get("band", ""), score=d.get("score"),
                                          reason=d.get("reason", ""), model=d.get("model", ""), cell=d.get("cell", ""),
                                          extra={"sha256": (d.get("extra") or {}).get("sha256"), "service_seconds": out.get("seconds")}))
        return results or [ForensicResult(kind=kind, status="abstain", reason="the forensics service returned no result", model="none",
                                          extra={"unreachable": True})]


def _unreachable(results: list) -> bool:
    return any((r.extra or {}).get("unreachable") for r in results)


CHECK_EN = {"audio": "Voice check", "video": "Face check", "document": "Document check"}
CHECK_HI = {"audio": "आवाज़ की जाँच", "video": "चेहरे की जाँच", "document": "दस्तावेज़ की जाँच"}

RULE_FOR_KIND = {"audio": "R-AUDIO-SYNTH", "video": "R-VIDEO-SYNTH", "document": "R-DOC-TAMPER"}


def rule_for(res: "ForensicResult") -> str:
    """Voice -> R-AUDIO-SYNTH, face -> R-VIDEO-SYNTH; a document whose own label names an AI tool -> R-DOC-AI."""
    if res.kind == "document" and res.status == "synthetic":
        return "R-DOC-AI"
    return RULE_FOR_KIND.get(res.kind, "R-DOC-TAMPER")


DEEPFAKE_PCT = {"high": 100, "moderate": 70, "low": 30}   # calibrated band -> deepfake % (fusion's combined score)


def deepfake_pct(res: ForensicResult) -> Optional[int]:
    """How fake the media looks, 0-100, from the calibrated result and never from the raw score; None when the
    detector could not judge it, which fusion treats as no media at all."""
    if res.status in ("synthetic", "edited"):
        return DEEPFAKE_PCT.get(res.band, DEEPFAKE_PCT["moderate"])
    return 0 if res.status == "clean" else None


def to_signal(book, res: ForensicResult):
    """Turn a ForensicResult into a Signal: soft when it fires, abstain/info otherwise. F3 can never be hard; it
    reaches a verdict only through fusion's combined score."""
    from .models import Family, Severity, Signal
    from .rulebook import make_signal
    tag = " (SIMULATED)" if res.simulated else ""
    rule_id = rule_for(res)
    if res.status in ("synthetic", "edited"):
        return make_signal(book, rule_id, {"evidence_key": f"media:{res.kind}", "band": res.band + tag, "band_hi": BAND_HI.get(res.band, res.band) + tag,
                                           "score": res.score, "model": res.model, "cell": res.cell, "simulated": res.simulated,
                                           "status": res.status, "deepfake_pct": deepfake_pct(res),
                                           "tool": res.extra.get("ai_tool", "")})
    check_en = CHECK_EN.get(res.kind, "Media check")
    check_hi = CHECK_HI.get(res.kind, "मीडिया की जाँच")
    if res.status == "clean":
        reason_en = f"{check_en}{tag}: no signs found. That does not confirm the media is genuine."
        reason_hi = f"{check_hi}{tag}: कोई संकेत नहीं मिला। इससे यह पक्का नहीं होता कि मीडिया असली है।"
    else:
        reason_en = f"{check_en}{tag}: unsure: {res.reason or 'it could not judge this file'}."
        reason_hi = f"{check_hi}{tag}: अनिश्चित।"
    return Signal(rule_id=rule_id, family=Family.F3, severity=Severity.ABSTAIN if res.status == "abstain" else Severity.INFO,
                  evidence_key=f"media:{res.kind}", reason_en=reason_en,
                  reason_hi=reason_hi, citation="media check; counts in the combined score only when it can judge the media", citation_verified=True,
                  rule_version="forensics-1.0",
                  detail={"can_be_second": False, "status": res.status, "score": res.score, "model": res.model, "cell": res.cell, "simulated": res.simulated,
                          "deepfake_pct": deepfake_pct(res)})
