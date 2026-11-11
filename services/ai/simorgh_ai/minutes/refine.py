"""Post-meeting refinement: re-decode each live utterance from the stored per-speaker
audio with a wider beam (and optionally a larger model). Live captions use beam=1
to keep up in real time on CPU; the minutes deserve the most accurate text."""

from __future__ import annotations

import logging

import numpy as np

from ..audio import TARGET_RATE, read_wav_16k
from ..engines import SttEngine
from ..textnorm import normalize_persian
from .transcript import SttSession

log = logging.getLogger(__name__)


def refine_session(session: SttSession, engine: SttEngine, beam_size: int, language: str,
                   hotwords: str = "") -> int:
    """Rewrites ``session.segments[*]['text']`` in place. Returns refined count."""
    audio_cache: dict[str, np.ndarray | None] = {}
    participants = session.meta.get("participants", {})
    refined = 0
    previous: dict[str, str] = {}
    for seg in sorted(session.segments, key=lambda s: s["start_epoch_ms"]):
        pid = seg["participant_id"]
        if pid not in audio_cache:
            rel = (participants.get(pid) or {}).get("audio")
            path = session.dir / rel if rel else None
            audio_cache[pid] = read_wav_16k(path) if path and path.exists() else None
        audio = audio_cache[pid]
        if audio is None:
            continue
        start = max(0, int(seg["stream_start_ms"]) * TARGET_RATE // 1000 - TARGET_RATE // 10)
        end = min(audio.size, int(seg["stream_end_ms"]) * TARGET_RATE // 1000 + TARGET_RATE // 10)
        if end - start < TARGET_RATE // 4:
            continue
        try:
            result = engine.transcribe(audio[start:end], language=language, beam_size=beam_size,
                                       prompt=previous.get(pid, ""), hotwords=hotwords)
        except Exception:  # noqa: BLE001 - keep the live text on failure
            log.exception("refine failed for segment of %s", pid)
            continue
        text = normalize_persian(" ".join(r.text for r in result))
        if text:
            seg["live_text"] = seg["text"]
            seg["text"] = text
            previous[pid] = text
            refined += 1
    return refined
