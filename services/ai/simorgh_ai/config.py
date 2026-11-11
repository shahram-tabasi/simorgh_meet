"""Runtime configuration for the Simorgh Meet AI service (environment variables)."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


def _bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    return int(raw) if raw not in (None, "") else default


def _float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    return float(raw) if raw not in (None, "") else default


def _str(name: str, default: str) -> str:
    raw = os.environ.get(name)
    return raw if raw not in (None, "") else default


@dataclass(frozen=True)
class SttConfig:
    # Engine: "faster-whisper" (default, best Persian accuracy),
    # "sherpa-onnx" (NeMo FastConformer / Zipformer ONNX, fastest on CPU) or "mock" (tests).
    engine: str = field(default_factory=lambda: _str("STT_ENGINE", "faster-whisper"))
    model_path: str = field(default_factory=lambda: _str("STT_MODEL_PATH", "/models/stt/whisper-fa"))
    # Optional second model used for the post-meeting refinement pass.
    refine_model_path: str = field(default_factory=lambda: _str("STT_REFINE_MODEL_PATH", ""))
    language: str = field(default_factory=lambda: _str("STT_LANGUAGE", "fa"))
    # Ignore the language tag Jigasi sends (it follows the user's UI language, often "en")
    # and always decode as STT_LANGUAGE. Set 0 to honour per-participant languages.
    force_language: bool = field(default_factory=lambda: _bool("STT_FORCE_LANGUAGE", True))
    compute_type: str = field(default_factory=lambda: _str("STT_COMPUTE_TYPE", "int8"))
    cpu_threads: int = field(default_factory=lambda: _int("STT_CPU_THREADS", 0))
    # Number of utterances decoded in parallel (each uses cpu_threads).
    workers: int = field(default_factory=lambda: _int("STT_WORKERS", 2))
    live_beam_size: int = field(default_factory=lambda: _int("STT_LIVE_BEAM_SIZE", 1))
    final_beam_size: int = field(default_factory=lambda: _int("STT_FINAL_BEAM_SIZE", 5))
    # Audio sent by Jigasi: 16-bit little-endian mono PCM. Skynet (the Jitsi reference
    # server) assumes 16 kHz; set 48000 if your Jigasi build forwards raw Opus-decoded audio.
    input_sample_rate: int = field(default_factory=lambda: _int("STT_INPUT_SAMPLE_RATE", 16000))
    # Utterance segmentation (energy VAD with hangover).
    vad_threshold_db: float = field(default_factory=lambda: _float("STT_VAD_THRESHOLD_DB", -45.0))
    min_silence_ms: int = field(default_factory=lambda: _int("STT_MIN_SILENCE_MS", 700))
    min_speech_ms: int = field(default_factory=lambda: _int("STT_MIN_SPEECH_MS", 300))
    max_utterance_s: float = field(default_factory=lambda: _float("STT_MAX_UTTERANCE_S", 25.0))
    # Interim (partial) captions cost CPU; disabled by default on CPU-only servers.
    partial_interval_s: float = field(default_factory=lambda: _float("STT_PARTIAL_INTERVAL_S", 0.0))
    keep_audio: bool = field(default_factory=lambda: _bool("STT_KEEP_AUDIO", True))
    data_dir: Path = field(default_factory=lambda: Path(_str("STT_DATA_DIR", "/data/stt")))
    max_connections: int = field(default_factory=lambda: _int("STT_MAX_CONNECTIONS", 20))
    # Optional ASAP (RS256) verification of Jigasi's Authorization header.
    asap_public_key_path: str = field(default_factory=lambda: _str("STT_ASAP_PUBLIC_KEY_PATH", ""))
    asap_audience: str = field(default_factory=lambda: _str("STT_ASAP_AUDIENCE", "jitsi"))
    # Comma separated hotwords (names, project terms) appended to every decode.
    hotwords: str = field(default_factory=lambda: _str("STT_HOTWORDS", ""))


@dataclass(frozen=True)
class LlmConfig:
    # Any OpenAI-compatible endpoint; the package ships llama.cpp server.
    base_url: str = field(default_factory=lambda: _str("LLM_BASE_URL", "http://llm:8080/v1"))
    model: str = field(default_factory=lambda: _str("LLM_MODEL", "minutes"))
    api_key: str = field(default_factory=lambda: _str("LLM_API_KEY", "not-needed"))
    timeout_s: float = field(default_factory=lambda: _float("LLM_TIMEOUT_S", 1800.0))
    temperature: float = field(default_factory=lambda: _float("LLM_TEMPERATURE", 0.2))
    max_output_tokens: int = field(default_factory=lambda: _int("LLM_MAX_OUTPUT_TOKENS", 3000))
    # Transcript characters per map-step chunk (Persian ≈ 2.5–3 chars/token).
    chunk_chars: int = field(default_factory=lambda: _int("LLM_CHUNK_CHARS", 12000))
    use_json_schema: bool = field(default_factory=lambda: _bool("LLM_USE_JSON_SCHEMA", True))


@dataclass(frozen=True)
class WorkerConfig:
    database_url: str = field(default_factory=lambda: _str("DATABASE_URL", ""))
    transcripts_dir: Path = field(default_factory=lambda: Path(_str("JIGASI_TRANSCRIPTS_DIR", "/data/transcripts")))
    recordings_dir: Path = field(default_factory=lambda: Path(_str("RECORDINGS_DIR", "/data/recordings")))
    minutes_dir: Path = field(default_factory=lambda: Path(_str("MINUTES_DIR", "/data/minutes")))
    poll_interval_s: float = field(default_factory=lambda: _float("WORKER_POLL_INTERVAL_S", 10.0))
    refine_enabled: bool = field(default_factory=lambda: _bool("AI_REFINE_TRANSCRIPT", True))
    transcribe_recordings: bool = field(default_factory=lambda: _bool("AI_TRANSCRIBE_RECORDINGS", True))
    # Minimum transcript words before minutes are generated (avoids empty minutes).
    min_words: int = field(default_factory=lambda: _int("AI_MINUTES_MIN_WORDS", 30))
    organization_name: str = field(default_factory=lambda: _str("ORGANIZATION_NAME", ""))
    timezone: str = field(default_factory=lambda: _str("TZ", "Asia/Tehran"))
