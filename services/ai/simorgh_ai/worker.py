"""AI minutes worker.

Watches for finished meetings and produces the automatic minutes (صورت‌جلسه خودکار):

1. Jigasi final transcript JSON appears in JIGASI_TRANSCRIPTS_DIR (meeting ended)
   -> match the live STT session (per-speaker segments + audio)
   -> refine pass (wider beam) -> LLM minutes -> DB + files.
2. A Jibri recording appears in RECORDINGS_DIR without a live transcript
   -> offline transcription of the mixed audio -> LLM minutes.
3. ``background_jobs`` rows of kind ``minutes.generate`` (payload {"meeting_id"})
   -> regenerate minutes from the stored transcript (e.g. "regenerate" button).

Outputs are always written to MINUTES_DIR/<room>/<timestamp>/ so the feature works
even before the web application consumes the database tables.
"""

from __future__ import annotations

import json
import logging
import os
import re
import signal
import socket
import time
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from .config import LlmConfig, SttConfig, WorkerConfig
from .engines import SttEngine, create_engine
from .minutes.generator import MinutesGenerator, MinutesResult
from .minutes.llm import LlmClient
from .minutes.refine import refine_session
from .minutes.render import render_markdown
from .minutes.transcript import (
    UNKNOWN_SPEAKER,
    Transcript,
    Utterance,
    build_transcript,
    load_jigasi_transcript,
    load_stt_session,
    match_stt_session,
)

log = logging.getLogger("simorgh_ai.worker")

SETTLE_SECONDS = 20
_JIBRI_NAME = re.compile(r"^(?P<room>.+)_(?P<ts>\d{4}-\d{2}-\d{2}-\d{2}-\d{2}-\d{2})$")


class State:
    """Tiny JSON state file: which inputs were processed (idempotency across restarts)."""

    def __init__(self, path: Path):
        self.path = path
        self.data: dict = {"processed": {}, "failures": {}}
        if path.exists():
            try:
                self.data = json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                log.error("state file corrupt, starting fresh: %s", path)

    def done(self, key: str) -> bool:
        return key in self.data["processed"]

    def failures(self, key: str) -> int:
        return int(self.data["failures"].get(key, 0))

    def mark(self, key: str, value: str) -> None:
        self.data["processed"][key] = value
        self.data["failures"].pop(key, None)
        self._save()

    def fail(self, key: str) -> None:
        self.data["failures"][key] = self.failures(key) + 1
        self._save()

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.data, ensure_ascii=False, indent=1), encoding="utf-8")
        tmp.replace(self.path)


class Worker:
    def __init__(self, wcfg: WorkerConfig | None = None, scfg: SttConfig | None = None,
                 lcfg: LlmConfig | None = None, llm: LlmClient | None = None, engine: SttEngine | None = None):
        self.wcfg = wcfg or WorkerConfig()
        self.scfg = scfg or SttConfig()
        self.lcfg = lcfg or LlmConfig()
        self.llm = llm or LlmClient(self.lcfg)
        self._engine = engine
        self.generator = MinutesGenerator(self.llm, self.lcfg, self.wcfg.organization_name, self.wcfg.timezone)
        self.state = State(self.wcfg.minutes_dir / ".worker-state.json")
        self.store = None
        if self.wcfg.database_url:
            from .store import Store

            self.store = Store(self.wcfg.database_url)
        self.worker_id = f"{socket.gethostname()}:{os.getpid()}"
        self._stop = False

    @property
    def engine(self) -> SttEngine:
        if self._engine is None:
            self._engine = create_engine(self.scfg, self.scfg.refine_model_path or None)
        return self._engine

    # ------------------------------------------------------------------ loop
    def run_forever(self) -> None:
        signal.signal(signal.SIGTERM, lambda *_: setattr(self, "_stop", True))
        log.info("worker started (transcripts=%s, recordings=%s, db=%s)", self.wcfg.transcripts_dir,
                 self.wcfg.recordings_dir, "yes" if self.store else "no")
        while not self._stop:
            try:
                self.tick()
            except Exception:  # noqa: BLE001 - keep the daemon alive
                log.exception("worker tick failed")
            for _ in range(int(self.wcfg.poll_interval_s * 10)):
                if self._stop:
                    break
                time.sleep(0.1)

    def tick(self) -> None:
        for path in self._settled_files(self.wcfg.transcripts_dir, ("*.json",)):
            self._guarded(f"jigasi:{path.name}", lambda p=path: self.process_jigasi_file(p))
        if self.wcfg.transcribe_recordings:
            for path in self._settled_files(self.wcfg.recordings_dir, ("*.mp4", "*.webm", "*.mkv", "*.wav")):
                self._guarded(f"recording:{path.relative_to(self.wcfg.recordings_dir)}",
                              lambda p=path: self.process_recording(p))
        if self.store:
            self._process_db_jobs()

    def _settled_files(self, root: Path, patterns: tuple[str, ...]) -> list[Path]:
        if not root.exists():
            return []
        now = time.time()
        files = [p for pat in patterns for p in root.rglob(pat)]
        return sorted(p for p in files if p.is_file() and now - p.stat().st_mtime > SETTLE_SECONDS)

    def _guarded(self, key: str, fn) -> None:
        if self.state.done(key) or self.state.failures(key) >= 3:
            return
        try:
            result = fn()
            self.state.mark(key, result or "skipped")
        except Exception:  # noqa: BLE001
            log.exception("processing failed: %s", key)
            self.state.fail(key)

    # -------------------------------------------------------------- sources
    def process_jigasi_file(self, path: Path) -> str:
        jt = load_jigasi_transcript(path)
        session = match_stt_session(jt, self.scfg.data_dir)
        if session and self.wcfg.refine_enabled and session.segments:
            count = refine_session(session, self.engine, self.scfg.final_beam_size, self.scfg.language,
                                   self.scfg.hotwords)
            log.info("refined %d/%d segments for %s", count, len(session.segments), jt.room_name)
        transcript = build_transcript(jt, session)
        if session:
            self.state.mark(f"stt:{session.dir.name}", jt.room_name)
        return self.produce(transcript)

    def process_recording(self, path: Path) -> str:
        room, started = _parse_recording_name(path, self.wcfg.timezone)
        if self._covered_by_live(room, started):
            return "covered-by-live-transcript"
        segments = self.engine.transcribe(_load_media(path), language=self.scfg.language,
                                          beam_size=self.scfg.final_beam_size, hotwords=self.scfg.hotwords, vad=True)
        base = int(started.timestamp() * 1000)
        transcript = Transcript(
            room_name=room, started_at=started, ended_at=None, source="recording",
            provider_session_id=f"recording:{path.name}", engine=self.engine.name, model=self.engine.model,
            utterances=[Utterance(UNKNOWN_SPEAKER, base + s.start_ms, base + s.end_ms, s.text, None, s.confidence)
                        for s in segments],
        )
        return self.produce(transcript)

    def _covered_by_live(self, room: str, started: datetime) -> bool:
        """True when a live transcript of the same room started within 3 hours of the recording."""
        for key, value in self.state.data["processed"].items():
            if not key.startswith("jigasi:") or not isinstance(value, str) or "|" not in value:
                continue
            live_room, _, live_start = value.partition("|")
            if live_room != room.lower():
                continue
            try:
                if abs((datetime.fromisoformat(live_start) - started).total_seconds()) < 3 * 3600:
                    return True
            except ValueError:
                continue
        return False

    def _process_db_jobs(self) -> None:
        with self.store.connect() as conn:
            job = self.store.claim_job(conn, ["minutes.generate"], self.worker_id)
            if not job:
                return
            try:
                loaded = self.store.load_transcript(conn, job["payload"]["meeting_id"])
                if not loaded:
                    raise RuntimeError("no completed transcript for meeting")
                transcript, session_id, meeting = loaded
                glossary = self.store.glossary(conn, meeting.organization_id)
                result = self.generator.generate(transcript, meeting.title, glossary)
                markdown = render_markdown(result.content, transcript.room_name)
                self.store.save_minutes(conn, meeting, session_id, result, markdown)
                conn.commit()
                self.store.finish_job(conn, job, None)
            except Exception as exc:  # noqa: BLE001
                conn.rollback()
                log.exception("job %s failed", job["id"])
                self.store.finish_job(conn, job, str(exc))

    # ----------------------------------------------------------- produce
    def produce(self, transcript: Transcript) -> str:
        room_key = f"{transcript.room_name.lower()}|{transcript.started_at.isoformat()}"
        out_dir = self._output_dir(transcript)
        _write_transcript_files(out_dir, transcript)
        words = transcript.word_count()
        if words < self.wcfg.min_words:
            log.info("transcript for %s too short (%d words); minutes skipped", transcript.room_name, words)
            return room_key

        meeting, glossary, title = None, [], ""
        if self.store:
            with self.store.connect() as conn:
                meeting = self.store.resolve_meeting(conn, transcript.room_name, transcript.started_at)
                if meeting:
                    glossary, title = self.store.glossary(conn, meeting.organization_id), meeting.title
                conn.commit()
            if meeting and not meeting.ai_minutes_enabled:
                log.info("AI minutes disabled for meeting %s", meeting.meeting_id)
                return room_key

        result: MinutesResult = self.generator.generate(transcript, title, glossary)
        markdown = render_markdown(result.content, transcript.room_name)
        (out_dir / "minutes.json").write_text(
            json.dumps({"content": result.content, "model": result.model, "meta": result.meta},
                       ensure_ascii=False, indent=2), encoding="utf-8")
        (out_dir / "minutes.md").write_text(markdown, encoding="utf-8")

        if self.store and meeting:
            with self.store.connect() as conn:
                session_id = self.store.save_transcript(conn, meeting, transcript)
                self.store.save_minutes(conn, meeting, session_id, result, markdown)
                conn.commit()
            log.info("minutes stored for meeting %s", meeting.meeting_id)
        elif self.store:
            log.warning("no meeting/room record for Jitsi room %r; minutes saved to %s only",
                        transcript.room_name, out_dir)
        return room_key

    def _output_dir(self, transcript: Transcript) -> Path:
        safe_room = re.sub(r"[^\w.-]", "_", transcript.room_name)[:100] or "room"
        stamp = transcript.started_at.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        path = self.wcfg.minutes_dir / safe_room / stamp
        path.mkdir(parents=True, exist_ok=True)
        return path


def _write_transcript_files(out_dir: Path, transcript: Transcript) -> None:
    (out_dir / "transcript.json").write_text(json.dumps(transcript.to_json(), ensure_ascii=False, indent=1),
                                             encoding="utf-8")
    (out_dir / "transcript.txt").write_text("\n".join(transcript.to_lines()) + "\n", encoding="utf-8")


def _parse_recording_name(path: Path, tz: str = "UTC") -> tuple[str, datetime]:
    """Jibri names files '<room>_<YYYY-MM-DD-HH-MM-SS>.mp4' using its local clock (TZ)."""
    match = _JIBRI_NAME.match(path.stem)
    if match:
        started = datetime.strptime(match["ts"], "%Y-%m-%d-%H-%M-%S").replace(tzinfo=ZoneInfo(tz))
        return match["room"], started
    return path.stem, datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)


def _load_media(path: Path):
    from faster_whisper.audio import decode_audio  # PyAV based, no ffmpeg binary needed

    return decode_audio(str(path), sampling_rate=16000)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    Worker().run_forever()


if __name__ == "__main__":
    main()
