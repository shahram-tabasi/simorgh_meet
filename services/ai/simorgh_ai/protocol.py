"""Wire protocol of Jigasi's ``WhisperTranscriptionService`` (Jitsi transcriber).

Reverse-engineered from jigasi ``WhisperWebsocket.java`` and the Jitsi reference
server (jitsi/skynet ``streaming_whisper``):

* Jigasi connects to ``<websocket_url>/<connection-uuid>`` — one connection per
  conference. An optional ``Authorization: Bearer <ASAP RS256 JWT>`` header is sent.
* Every binary frame = 60-byte header + raw audio. The header is
  ``"<participant_id>|<language-tag>"`` encoded in UTF-8 and NUL padded.
  Audio is 16-bit little-endian mono PCM.
* A single-byte binary frame (``b"\\x00"``) means "all participants left" (EOF).
* The server answers with JSON text frames::

      {"id": "...", "participant_id": "...", "ts": 1700000000000,
       "text": "...", "audio": "", "type": "partial"|"final", "variance": 1.0}

  ``variance`` MUST be serialized as a floating point number: Jigasi casts it to
  ``double`` and a JSON integer would raise ClassCastException.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass

HEADER_SIZE = 60
EOF_FRAME_MAX = 1


class ProtocolError(ValueError):
    pass


@dataclass(frozen=True)
class AudioFrame:
    participant_id: str
    language: str
    pcm: bytes


def is_eof(frame: bytes) -> bool:
    return len(frame) <= EOF_FRAME_MAX


def parse_frame(frame: bytes) -> AudioFrame:
    if len(frame) < HEADER_SIZE:
        raise ProtocolError(f"frame too short: {len(frame)} bytes")
    header = frame[:HEADER_SIZE].split(b"\x00", 1)[0].decode("utf-8", errors="replace").strip()
    participant_id, _, language = header.partition("|")
    participant_id = participant_id.strip()
    if not participant_id:
        raise ProtocolError("missing participant id in header")
    pcm = frame[HEADER_SIZE:]
    if len(pcm) % 2:
        pcm = pcm[:-1]
    return AudioFrame(participant_id=participant_id, language=normalize_language(language), pcm=pcm)


def build_frame(participant_id: str, language: str, pcm: bytes) -> bytes:
    """Build a frame exactly like Jigasi does (used by tests and the load tool)."""
    header = f"{participant_id}|{language}".encode("utf-8")
    if len(header) > HEADER_SIZE:
        raise ProtocolError("header longer than 60 bytes")
    return header.ljust(HEADER_SIZE, b"\x00") + pcm


def normalize_language(tag: str) -> str:
    """'fa-IR' -> 'fa'; empty/'null' -> ''."""
    tag = (tag or "").strip()
    if tag.lower() in {"", "null", "none", "auto"}:
        return ""
    return tag.split("-")[0].split("_")[0].lower()


def result_message(
    participant_id: str,
    text: str,
    final: bool,
    ts_ms: int,
    result_id: str | None = None,
    variance: float = 1.0,
) -> str:
    return json.dumps(
        {
            "id": result_id or str(uuid.uuid4()),
            "participant_id": participant_id,
            "ts": int(ts_ms),
            "text": text,
            "audio": "",
            "type": "final" if final else "partial",
            "variance": float(variance),
        },
        ensure_ascii=False,
    )
