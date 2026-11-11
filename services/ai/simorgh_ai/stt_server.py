"""Streaming STT server compatible with Jitsi Jigasi's WhisperTranscriptionService.

Jigasi sends each participant's audio separately, so every utterance is attributed
to the real speaker without diarization. Final utterances are returned to Jitsi as
live captions and persisted to ``<STT_DATA_DIR>/<connection-id>/`` for the
minutes worker::

    session.json        {connection_id, started_at, closed_at, engine, model, participants}
    segments.jsonl      one JSON object per final utterance
    audio/<pid>.wav     16 kHz speaker audio (when STT_KEEP_AUDIO=1) for the refine pass
"""

from __future__ import annotations

import asyncio
import bisect
import json
import logging
import re
import time
from contextlib import asynccontextmanager
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse

from . import protocol
from .audio import TARGET_RATE, UtteranceSegmenter, WavAppender, pcm16_to_float, resample
from .config import SttConfig
from .engines import SttEngine, create_engine

log = logging.getLogger("simorgh_ai.stt")

_SAFE_ID = re.compile(r"[^A-Za-z0-9_.-]")


def safe_id(value: str) -> str:
    cleaned = _SAFE_ID.sub("_", value)[:120]
    return cleaned or "unknown"


@dataclass
class ParticipantStream:
    participant_id: str
    language: str
    segmenter: UtteranceSegmenter
    stream_start_epoch_ms: int
    wav: WavAppender | None = None
    audio_rel_path: str | None = None  # kept after the WAV is closed
    received_samples: int = 0
    last_partial_at: float = 0.0
    recent_text: list[str] = field(default_factory=list)
    # WebRTC (Opus DTX) sends no packets during silence, so Jigasi's stream has no
    # silent samples: pauses only show up as gaps in arrival time. We keep anchors
    # (stream offset ms -> wall-clock ms) to map compact-stream offsets to real time.
    anchors_offset: list[int] = field(default_factory=list)
    anchors_wall: list[int] = field(default_factory=list)
    next_expected_wall_ms: float | None = None

    def note_arrival(self, offset_ms: int, wall_ms: int, duration_ms: float, gap_threshold_ms: int) -> bool:
        """Record a frame arrival. Returns True when the gap since the previous frame's
        audio ended is a pause (≥ gap_threshold_ms), i.e. an utterance boundary."""
        pause = (self.next_expected_wall_ms is not None
                 and wall_ms - self.next_expected_wall_ms >= gap_threshold_ms)
        if pause or not self.anchors_offset:
            self.anchors_offset.append(offset_ms)
            self.anchors_wall.append(wall_ms)
        # The next frame is due when this one's audio has "played out".
        base = wall_ms if (pause or self.next_expected_wall_ms is None) else max(wall_ms, self.next_expected_wall_ms)
        self.next_expected_wall_ms = base + duration_ms
        return pause

    def wall_ms_at(self, offset_ms: int) -> int:
        """Wall-clock epoch ms for a compact-stream offset."""
        if not self.anchors_offset:
            return self.stream_start_epoch_ms + offset_ms
        i = max(0, bisect.bisect_right(self.anchors_offset, offset_ms) - 1)
        return self.anchors_wall[i] + (offset_ms - self.anchors_offset[i])


class Session:
    def __init__(self, connection_id: str, cfg: SttConfig, engine: SttEngine):
        self.connection_id = safe_id(connection_id)
        self.cfg = cfg
        self.engine = engine
        self.dir = cfg.data_dir / self.connection_id
        self.dir.mkdir(parents=True, exist_ok=True)
        self.started_at_ms = int(time.time() * 1000)
        self.participants: dict[str, ParticipantStream] = {}
        self._segments = (self.dir / "segments.jsonl").open("a", encoding="utf-8")
        self._write_meta(closed=False)

    def _write_meta(self, closed: bool) -> None:
        meta = {
            "connection_id": self.connection_id,
            "started_at_ms": self.started_at_ms,
            "closed_at_ms": int(time.time() * 1000) if closed else None,
            "engine": self.engine.name,
            "model": self.engine.model,
            "sample_rate": TARGET_RATE,
            "participants": {
                pid: {"language": p.language, "stream_start_epoch_ms": p.stream_start_epoch_ms,
                      "audio": p.audio_rel_path}
                for pid, p in self.participants.items()
            },
        }
        tmp = self.dir / "session.json.tmp"
        tmp.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(self.dir / "session.json")

    def participant(self, pid: str, language: str) -> ParticipantStream:
        stream = self.participants.get(pid)
        if stream is None:
            cfg = self.cfg
            stream = ParticipantStream(
                participant_id=pid,
                language=cfg.language if cfg.force_language else (language or cfg.language),
                segmenter=UtteranceSegmenter(
                    threshold_db=cfg.vad_threshold_db,
                    min_silence_ms=cfg.min_silence_ms,
                    min_speech_ms=cfg.min_speech_ms,
                    max_utterance_s=cfg.max_utterance_s,
                ),
                stream_start_epoch_ms=int(time.time() * 1000),
                wav=WavAppender(self.dir / "audio" / f"{safe_id(pid)}.wav") if cfg.keep_audio else None,
                audio_rel_path=f"audio/{safe_id(pid)}.wav" if cfg.keep_audio else None,
            )
            self.participants[pid] = stream
            self._write_meta(closed=False)
        return stream

    def record_segment(self, stream: ParticipantStream, start_ms: int, end_ms: int, text: str,
                       confidence: float | None) -> dict:
        row = {
            "participant_id": stream.participant_id,
            "start_epoch_ms": stream.wall_ms_at(start_ms),
            "end_epoch_ms": stream.wall_ms_at(start_ms) + (end_ms - start_ms),
            "stream_start_ms": start_ms,
            "stream_end_ms": end_ms,
            "text": text,
            "confidence": confidence,
            "language": stream.language,
        }
        self._segments.write(json.dumps(row, ensure_ascii=False) + "\n")
        self._segments.flush()
        return row

    def close(self) -> None:
        for p in self.participants.values():
            if p.wav:
                p.wav.close()
                p.wav = None
        self._segments.close()
        self._write_meta(closed=True)


class SttService:
    def __init__(self, cfg: SttConfig, engine: SttEngine | None = None):
        self.cfg = cfg
        self.engine = engine or create_engine(cfg)
        self.executor = ThreadPoolExecutor(max_workers=max(1, cfg.workers), thread_name_prefix="stt")
        self.active = 0

    async def decode(self, audio: np.ndarray, language: str, beam: int, prompt: str):
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            self.executor,
            lambda: self.engine.transcribe(
                audio, language=language, beam_size=beam, prompt=prompt, hotwords=self.cfg.hotwords
            ),
        )


def _authorized(websocket: WebSocket, cfg: SttConfig) -> bool:
    if not cfg.asap_public_key_path:
        return True
    import jwt  # PyJWT

    header = websocket.headers.get("authorization", "")
    token = header.split(" ")[-1] if header else websocket.query_params.get("auth_token", "")
    if not token:
        return False
    try:
        key = Path(cfg.asap_public_key_path).read_text()
        jwt.decode(token, key, algorithms=["RS256"], audience=cfg.asap_audience)
        return True
    except Exception as exc:  # noqa: BLE001 - any validation failure means unauthorized
        log.warning("rejected transcriber connection: %s", exc)
        return False


def create_app(cfg: SttConfig | None = None, engine: SttEngine | None = None) -> FastAPI:
    cfg = cfg or SttConfig()
    service: dict[str, SttService] = {}

    def get_service() -> SttService:
        if "svc" not in service:
            service["svc"] = SttService(cfg, engine)
        return service["svc"]

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        get_service()  # load the model before the first meeting starts
        yield

    app = FastAPI(title="Simorgh Meet STT", docs_url=None, redoc_url=None, lifespan=lifespan)

    @app.get("/health")
    async def health():
        svc = get_service()
        return JSONResponse({"status": "ok", "engine": svc.engine.name, "model": svc.engine.model,
                             "active_connections": svc.active})

    async def handle(websocket: WebSocket, connection_id: str) -> None:
        svc = get_service()
        if not _authorized(websocket, cfg):
            await websocket.close(code=4401)
            return
        if svc.active >= cfg.max_connections:
            await websocket.close(code=1013)
            return
        await websocket.accept()
        svc.active += 1
        session = Session(connection_id, cfg, svc.engine)
        log.info("transcriber connected: %s", session.connection_id)
        pending: set[asyncio.Task] = set()
        send_lock = asyncio.Lock()

        async def send(msg: str) -> None:
            async with send_lock:
                try:
                    await websocket.send_text(msg)
                except Exception:  # noqa: BLE001 - client may be gone during EOF flush
                    pass

        async def finalize(stream: ParticipantStream, utt) -> None:
            prompt = " ".join(stream.recent_text[-2:])
            segments = await svc.decode(utt.samples, stream.language, cfg.live_beam_size, prompt)
            text = " ".join(s.text for s in segments).strip()
            if not text:
                return
            conf = [s.confidence for s in segments if s.confidence is not None]
            session.record_segment(stream, utt.start_ms, utt.end_ms, text,
                                   float(np.mean(conf)) if conf else None)
            stream.recent_text.append(text)
            del stream.recent_text[:-4]
            await send(protocol.result_message(stream.participant_id, text, True,
                                               stream.wall_ms_at(utt.start_ms)))

        async def partial(stream: ParticipantStream) -> None:
            utt = stream.segmenter.current_partial()
            if utt is None or utt.samples.size < TARGET_RATE:
                return
            segments = await svc.decode(utt.samples, stream.language, 1, "")
            text = " ".join(s.text for s in segments).strip()
            if text:
                await send(protocol.result_message(stream.participant_id, text, False,
                                                   stream.wall_ms_at(utt.start_ms),
                                                   variance=0.5))

        def spawn(coro) -> None:
            task = asyncio.create_task(coro)
            pending.add(task)
            task.add_done_callback(pending.discard)

        def flush_all() -> None:
            for stream in session.participants.values():
                for utt in stream.segmenter.flush():
                    spawn(finalize(stream, utt))

        try:
            while True:
                message = await websocket.receive()
                if message.get("type") == "websocket.disconnect":
                    break
                frame = message.get("bytes")
                if frame is None:
                    continue  # Jigasi does not send text frames; ignore
                if protocol.is_eof(frame):
                    flush_all()
                    continue
                try:
                    parsed = protocol.parse_frame(frame)
                except protocol.ProtocolError as exc:
                    log.debug("bad frame: %s", exc)
                    continue
                stream = session.participant(parsed.participant_id, parsed.language)
                samples = resample(pcm16_to_float(parsed.pcm), cfg.input_sample_rate, TARGET_RATE)
                offset_ms = stream.received_samples * 1000 // TARGET_RATE
                if stream.note_arrival(offset_ms, int(time.time() * 1000), samples.size * 1000 / TARGET_RATE,
                                       cfg.min_silence_ms):
                    for utt in stream.segmenter.flush():  # a pause ends the current utterance
                        spawn(finalize(stream, utt))
                stream.received_samples += samples.size
                if stream.wav:
                    stream.wav.write(samples)
                for utt in stream.segmenter.push(samples):
                    spawn(finalize(stream, utt))
                if cfg.partial_interval_s > 0:
                    now = time.monotonic()
                    if now - stream.last_partial_at >= cfg.partial_interval_s:
                        stream.last_partial_at = now
                        spawn(partial(stream))
        except WebSocketDisconnect:
            pass
        finally:
            flush_all()
            if pending:
                await asyncio.gather(*pending, return_exceptions=True)
            session.close()
            svc.active -= 1
            log.info("transcriber disconnected: %s", session.connection_id)

    # Jigasi appends "/<uuid>" to the configured URL. Accept the Skynet path too.
    @app.websocket("/ws/{connection_id}")
    async def ws(websocket: WebSocket, connection_id: str):
        await handle(websocket, connection_id)

    @app.websocket("/streaming-whisper/ws/{connection_id}")
    async def ws_skynet(websocket: WebSocket, connection_id: str):
        await handle(websocket, connection_id)

    return app


def main() -> None:
    import uvicorn

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    uvicorn.run(create_app(), host="0.0.0.0", port=8000, ws_max_size=4 * 1024 * 1024, log_level="info")


if __name__ == "__main__":
    main()
