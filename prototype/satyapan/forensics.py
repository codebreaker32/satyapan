"""F3 media forensics. Corroboration only: these signals are soft, so they can never anchor a RED, and each
detector abstains outside the conditions it was calibrated for.

- NullAudioForensics abstains ("no calibrated detector loaded").
- AASISTAudioForensics loads an AASIST-L checkpoint (MIT, clovaai/aasist) when torch is installed and a per-cell
  calibration file exists.
- DocumentForensics: error-level analysis plus creator metadata; abstains on small or recompressed images.
- SimulatedForensics: rehearsal only; its results are labelled SIMULATED wherever they appear.
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
    label = Label("Audio forensics", "AASIST-L anti-spoofing (CPU), calibrated per language × codec", "Model risk",
                  "in-process model; abstains when no calibrated detector is loaded", mock=False)

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
    catches a modern Indian-language voice clone is not measured here, which is why F3 stays corroboration only.
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


def _from_team(r) -> ForensicResult:
    """A team-repository result (object or its JSON dict from the forensics service) as this engine's ForensicResult."""
    g = r.get if isinstance(r, dict) else (lambda k, d=None: getattr(r, k, d))
    extra = g("extra") or {}
    keep = ("speech_s", "duration_s", "window_scores", "codec", "source_rate", "seconds", "from_video", "faces_scored",
            "frames_tried", "spread", "short_side")
    return ForensicResult(kind=g("kind"), status=g("status"), band=g("band") or "", score=g("score"), reason=g("reason") or "",
                          model=g("model") or "", cell=g("cell") or "", extra={k: extra[k] for k in keep if extra.get(k) is not None})


class _FaceCheckMissing:
    """Stands in for the face check when it cannot load here (no OpenCV, no GenD weights): it abstains with the reason,
    and the voice check on the same video still runs."""
    def __init__(self, reason: str):
        self.reason = reason

    def analyse(self, path):
        from forensics.common import ForensicResult as TeamResult
        return TeamResult(kind="video", status="abstain", reason=self.reason, model="none")


class TeamVideoForensics:
    """A video gets both checks of the team repository's joined entry point (forensics/analyse.py): the face check
    (GenD CLIP-L/14, Aman's, on YuNet faces) on its frames, and the voice check (DF Arena) on its sound track, judged
    by the sound's own codec. An audio file never comes here; it goes to the voice check alone.

    With SATYAPAN_FORENSICS_URL set, it asks the team's forensics service (scripts/demo_up.sh), which keeps both models
    loaded in their own process. Otherwise it runs the same entry point in this process, loading GenD on the first
    video (about 25 s on the team laptop) and sharing the voice model with the audio check."""
    label = Label("Video forensics", "GenD CLIP-L/14 face check (yermandy/GenD, MIT) on YuNet faces, plus the DF Arena "
                  "voice check on the sound track; both calibrated", "Model risk",
                  "in-process models, or the team's forensics service", mock=False)

    def __init__(self, repo: Path, audio, url: Optional[str] = None):
        import sys
        if str(repo) not in sys.path:
            sys.path.insert(0, str(repo))
        self.repo, self.url = repo, (url or "").rstrip("/")
        # the voice half: the team detector inside the DF Arena adapter, else whatever audio check this engine has
        self.audio = getattr(audio, "detector", audio)
        self._video = None

    @property
    def video(self):
        if self._video is None:
            try:
                from forensics.common import Calibration
                from forensics.video import GenDVideoForensics
                cal = self.repo / "calibration" / "video.json"
                self._video = GenDVideoForensics(calibration=Calibration.load(cal) if cal.exists() else None)
                _ = self._video.detector, self._video.scorer             # load now, so a failure is caught here
            except Exception as e:  # noqa: BLE001 - no OpenCV or no weights: the face half abstains, the voice half runs
                self._video = _FaceCheckMissing(f"the face check is not installed on this machine ({type(e).__name__})")
        return self._video

    def analyse(self, path: Path, language: str = "hi", channel: Optional[str] = None) -> list[ForensicResult]:
        language = language if language in ("hi", "en") else "hi"
        if self.url:
            import json
            import urllib.request
            body = json.dumps({"path": str(Path(path).resolve()), "language": language, "channel": channel}).encode()
            req = urllib.request.Request(self.url + "/analyse", data=body, headers={"Content-Type": "application/json"})
            try:
                with urllib.request.urlopen(req, timeout=600) as r:
                    return [_from_team(x) for x in json.load(r)["results"]]
            except Exception as e:  # noqa: BLE001 - the service is down: say so, never crash the case
                why = f"the forensics service could not be reached ({type(e).__name__})"
                return [ForensicResult(kind=k, status="abstain", reason=why, model="service") for k in ("video", "audio")]
        from forensics.analyse import analyse as joined
        return [_from_team(r) for r in joined(path, video=self.video, audio=self.audio, language=language, channel=channel)]


class AudioOnlyVideoForensics:
    """No team repository here: a video's sound still gets the engine's voice check; the face check says it is absent."""
    label = Label("Video forensics", "voice check on the sound track only; no face check installed", "Model risk",
                  "the audio check, run on the video's sound", mock=False)

    def __init__(self, audio):
        self.audio = audio

    def analyse(self, path: Path, language: str = "hi", channel: Optional[str] = None) -> list[ForensicResult]:
        voice = (self.audio.analyse(path, language, channel=channel) if channel and getattr(self.audio, "accepts_channel", False)
                 else self.audio.analyse(path, language))
        return [ForensicResult(kind="video", status="abstain", reason="no face check is installed", model="none"), voice]


def default_video_forensics(audio):
    """Both checks for a video when the team repository has the face check, else the voice check alone."""
    if (TEAM_REPO / "forensics" / "analyse.py").exists() and os.environ.get("SATYAPAN_VIDEO", "").lower() != "none":
        try:
            return TeamVideoForensics(TEAM_REPO, audio, url=os.environ.get("SATYAPAN_FORENSICS_URL"))
        except Exception:  # noqa: BLE001
            pass
    return AudioOnlyVideoForensics(audio)


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
    if choice in ("", "dfarena") and (TEAM_REPO / "calibration" / "audio.json").exists():
        try:
            return DFArenaAudioForensics(TEAM_REPO)
        except Exception:  # noqa: BLE001 - a broken checkout falls back to AASIST-L, never a crash
            pass
    if choice == "none":
        return NullAudioForensics()
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
        try:
            img = Image.open(path)
        except Exception as e:  # noqa: BLE001
            return ForensicResult("document", "abstain", reason=f"cannot open image: {e}", model="ELA")
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
    rule_id = {"audio": "R-AUDIO-SYNTH", "video": "R-VIDEO-SYNTH"}.get(res.kind) or ("R-DOC-AI" if res.status == "synthetic" else "R-DOC-TAMPER")
    if res.status in ("synthetic", "edited"):
        return make_signal(book, rule_id, {"evidence_key": f"media:{res.kind}", "band": res.band + tag, "band_hi": BAND_HI.get(res.band, res.band) + tag,
                                           "score": res.score, "model": res.model, "cell": res.cell, "simulated": res.simulated,
                                           "status": res.status, "deepfake_pct": deepfake_pct(res),
                                           "tool": res.extra.get("ai_tool", "")})
    reason = res.reason or ("no signs found" if res.status == "clean" else "abstained")
    return Signal(rule_id=rule_id, family=Family.F3, severity=Severity.ABSTAIN if res.status == "abstain" else Severity.INFO,
                  evidence_key=f"media:{res.kind}", reason_en=f"Forensics ({res.kind}): {res.status}{tag}. {reason}",
                  reason_hi=f"फ़ोरेंसिक ({res.kind}): {res.status}{tag}", citation="corroboration only", citation_verified=True,
                  rule_version="forensics-1.0",
                  detail={"can_be_second": False, "status": res.status, "score": res.score, "model": res.model, "cell": res.cell, "simulated": res.simulated,
                          "deepfake_pct": deepfake_pct(res)})
