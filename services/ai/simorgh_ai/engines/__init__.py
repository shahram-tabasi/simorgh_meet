"""Speech-to-text engines. All engines take float32 mono audio at 16 kHz."""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from typing import Protocol

import numpy as np

from ..config import SttConfig
from ..textnorm import normalize_persian

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Segment:
    start_ms: int
    end_ms: int
    text: str
    confidence: float | None = None


class SttEngine(Protocol):
    name: str
    model: str

    def transcribe(
        self,
        audio: np.ndarray,
        *,
        language: str,
        beam_size: int,
        prompt: str = "",
        hotwords: str = "",
        vad: bool = False,
    ) -> list[Segment]: ...


class MockEngine:
    """Deterministic engine for tests: reports the audio duration as text."""

    name = "mock"
    model = "mock"

    def transcribe(self, audio, *, language, beam_size, prompt="", hotwords="", vad=False):
        seconds = audio.size / 16000
        return [Segment(0, int(seconds * 1000), f"گفتار {seconds:.1f} ثانیه", 1.0)]


class FasterWhisperEngine:
    """CTranslate2 Whisper (int8 on CPU). Works with any Whisper checkpoint converted
    with ``ct2-transformers-converter`` — e.g. a Persian fine-tuned large-v3-turbo."""

    name = "faster-whisper"

    def __init__(self, model_path: str, cfg: SttConfig):
        from faster_whisper import WhisperModel  # heavy import, lazily

        self.model = model_path
        self._model = WhisperModel(
            model_path,
            device="cpu",
            compute_type=cfg.compute_type,
            cpu_threads=cfg.cpu_threads,
            num_workers=max(1, cfg.workers),
        )
        log.info("loaded faster-whisper model %s (%s)", model_path, cfg.compute_type)

    def transcribe(self, audio, *, language, beam_size, prompt="", hotwords="", vad=False):
        segments, _info = self._model.transcribe(
            audio,
            language=language or None,
            task="transcribe",
            beam_size=max(1, beam_size),
            best_of=max(1, beam_size),
            temperature=[0.0, 0.2, 0.4],
            condition_on_previous_text=False,
            initial_prompt=prompt or None,
            hotwords=hotwords or None,
            vad_filter=vad,
            vad_parameters={"min_silence_duration_ms": 500} if vad else None,
            no_speech_threshold=0.6,
            log_prob_threshold=-1.0,
            compression_ratio_threshold=2.4,
            without_timestamps=False,
        )
        out: list[Segment] = []
        for seg in segments:
            text = normalize_persian(seg.text)
            if not text or _is_hallucination(text):
                continue
            conf = float(np.exp(seg.avg_logprob)) if seg.avg_logprob is not None else None
            out.append(Segment(int(seg.start * 1000), int(seg.end * 1000), text, conf))
        return out


class SherpaOnnxEngine:
    """sherpa-onnx offline recognizer (NeMo FastConformer CTC/transducer or Zipformer).

    Expected model directory layout:
      * NeMo CTC:        model.onnx (or model.int8.onnx) + tokens.txt
      * Transducer:      encoder*.onnx, decoder*.onnx, joiner*.onnx + tokens.txt
    """

    name = "sherpa-onnx"

    def __init__(self, model_path: str, cfg: SttConfig):
        import glob
        import os

        import sherpa_onnx

        self.model = model_path
        threads = cfg.cpu_threads or max(1, (os.cpu_count() or 2) // 2)

        def pick(pattern: str) -> str | None:
            found = sorted(glob.glob(os.path.join(model_path, pattern)))
            int8 = [f for f in found if "int8" in f]
            return (int8 or found or [None])[0]

        tokens = os.path.join(model_path, "tokens.txt")
        encoder, decoder, joiner = pick("encoder*.onnx"), pick("decoder*.onnx"), pick("joiner*.onnx")
        if encoder and decoder and joiner:
            self._rec = sherpa_onnx.OfflineRecognizer.from_transducer(
                encoder=encoder, decoder=decoder, joiner=joiner, tokens=tokens,
                num_threads=threads, decoding_method="modified_beam_search",
                model_type=os.environ.get("STT_SHERPA_MODEL_TYPE", "nemo_transducer"),
            )
        else:
            model = pick("model*.onnx")
            if not model:
                raise FileNotFoundError(f"no ONNX model found in {model_path}")
            self._rec = sherpa_onnx.OfflineRecognizer.from_nemo_ctc(
                model=model, tokens=tokens, num_threads=threads
            )
        self._lock = threading.Semaphore(max(1, cfg.workers))
        log.info("loaded sherpa-onnx model %s", model_path)

    def transcribe(self, audio, *, language, beam_size, prompt="", hotwords="", vad=False):
        with self._lock:
            stream = self._rec.create_stream()
            stream.accept_waveform(16000, audio)
            self._rec.decode_stream(stream)
            text = normalize_persian(stream.result.text)
        if not text:
            return []
        return [Segment(0, int(audio.size / 16), text, None)]


# Whisper is known to hallucinate stock phrases on silence/noise (subtitle credits etc.).
_HALLUCINATIONS = (
    "زیرنویس",
    "ترجمه و زیرنویس",
    "مشترک شوید",
    "سابسکرایب",
    "ممنون که تماشا کردید",
    "amara.org",
)


def _is_hallucination(text: str) -> bool:
    lowered = text.lower()
    return any(marker in lowered for marker in _HALLUCINATIONS) and len(text) < 80


def create_engine(cfg: SttConfig, model_path: str | None = None) -> SttEngine:
    path = model_path or cfg.model_path
    if cfg.engine == "mock":
        return MockEngine()
    if cfg.engine == "faster-whisper":
        return FasterWhisperEngine(path, cfg)
    if cfg.engine == "sherpa-onnx":
        return SherpaOnnxEngine(path, cfg)
    raise ValueError(f"unknown STT_ENGINE: {cfg.engine}")
