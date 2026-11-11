"""Meeting transcript model and loaders.

Sources (best first):
1. Live STT session written by ``stt_server`` (per-speaker audio + segments), joined
   with Jigasi's final transcript JSON for real display names and the room name.
2. Jigasi final transcript JSON alone (``SPEECH`` events) — when no STT session matches.
3. A recording (mixed audio) transcribed offline — speakers unknown.
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from ..textnorm import normalize_persian, word_count

log = logging.getLogger(__name__)

UNKNOWN_SPEAKER = "سخنران نامشخص"
# Jitsi service participants that appear in Jigasi transcripts but are not people.
_SERVICE_PARTICIPANTS = {"focus"}


@dataclass
class Utterance:
    speaker: str
    start_ms: int  # epoch milliseconds
    end_ms: int
    text: str
    participant_id: str | None = None
    confidence: float | None = None


@dataclass
class Transcript:
    room_name: str
    started_at: datetime
    ended_at: datetime | None
    utterances: list[Utterance] = field(default_factory=list)
    participants: dict[str, str] = field(default_factory=dict)  # provider id -> display name
    source: str = "live"
    provider_session_id: str | None = None
    engine: str = "unknown"
    model: str = "unknown"
    language: str = "fa"

    @property
    def speakers(self) -> list[str]:
        seen: list[str] = []
        for u in self.utterances:
            if u.speaker not in seen:
                seen.append(u.speaker)
        return seen

    def word_count(self) -> int:
        return sum(word_count(u.text) for u in self.utterances)

    def to_lines(self) -> list[str]:
        """Compact speaker-attributed lines: '[mm:ss] Name: text' (consecutive merged)."""
        lines: list[str] = []
        base = int(self.started_at.timestamp() * 1000)
        last_speaker = None
        for u in sorted(self.utterances, key=lambda x: x.start_ms):
            offset = max(0, (u.start_ms - base) // 1000)
            stamp = f"{offset // 3600:02d}:{(offset % 3600) // 60:02d}:{offset % 60:02d}"
            if u.speaker == last_speaker and lines:
                lines[-1] += " " + u.text
            else:
                lines.append(f"[{stamp}] {u.speaker}: {u.text}")
                last_speaker = u.speaker
        return lines

    def to_json(self) -> dict:
        data = asdict(self)
        data["started_at"] = self.started_at.isoformat()
        data["ended_at"] = self.ended_at.isoformat() if self.ended_at else None
        return data


def _parse_time(value) -> datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value / 1000, tz=timezone.utc)
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


@dataclass
class JigasiTranscript:
    path: Path
    room_name: str
    started_at: datetime | None
    ended_at: datetime | None
    participants: dict[str, str]
    speech: list[Utterance]
    joins: list[tuple[str, int]]
    leaves: list[tuple[str, int]]


def load_jigasi_transcript(path: Path) -> JigasiTranscript:
    data = json.loads(path.read_text(encoding="utf-8"))
    participants: dict[str, str] = {}

    def remember(p: dict | None) -> str:
        if not p:
            return UNKNOWN_SPEAKER
        pid = str(p.get("id") or "")
        if pid in _SERVICE_PARTICIPANTS:
            return ""
        name = (p.get("name") or p.get("identity_name") or "").strip() or pid or UNKNOWN_SPEAKER
        if pid:
            participants[pid] = name
        return name

    for p in data.get("initial_participants") or []:
        remember(p)

    speech, joins, leaves = [], [], []
    for ev in data.get("events") or []:
        kind = str(ev.get("event", "")).upper()
        ts = int(ev.get("timestamp") or 0)
        participant = ev.get("participant")
        name = remember(participant)
        if not name:
            continue
        pid = str((participant or {}).get("id") or "") or None
        if kind == "SPEECH":
            if ev.get("is_interim"):
                continue
            alts = ev.get("transcript") or []
            text = normalize_persian(alts[0].get("text", "")) if alts else ""
            if text:
                speech.append(Utterance(name, ts, ts, text, pid, alts[0].get("confidence")))
        elif kind == "JOIN":
            joins.append((name, ts))
        elif kind == "LEAVE":
            leaves.append((name, ts))

    return JigasiTranscript(
        path=path,
        room_name=str(data.get("room_name") or path.stem).split("@")[0],
        started_at=_parse_time(data.get("start_time")),
        ended_at=_parse_time(data.get("end_time")),
        participants=participants,
        speech=speech,
        joins=joins,
        leaves=leaves,
    )


@dataclass
class SttSession:
    dir: Path
    meta: dict
    segments: list[dict]

    @property
    def participant_ids(self) -> set[str]:
        ids = set(self.meta.get("participants", {}).keys())
        ids.update(s["participant_id"] for s in self.segments)
        return ids

    @property
    def closed(self) -> bool:
        return bool(self.meta.get("closed_at_ms"))


def load_stt_session(directory: Path) -> SttSession | None:
    meta_path = directory / "session.json"
    if not meta_path.exists():
        return None
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    segments = []
    seg_path = directory / "segments.jsonl"
    if seg_path.exists():
        for line in seg_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                try:
                    segments.append(json.loads(line))
                except json.JSONDecodeError:
                    log.warning("skipping corrupt segment line in %s", seg_path)
    return SttSession(directory, meta, segments)


def match_stt_session(jt: JigasiTranscript, stt_root: Path) -> SttSession | None:
    """Pick the STT session sharing the most participant ids with the Jigasi transcript,
    falling back to the closest start time within 10 minutes."""
    if not stt_root.exists():
        return None
    ids = set(jt.participants.keys()) | {u.participant_id for u in jt.speech if u.participant_id}
    start_ms = int(jt.started_at.timestamp() * 1000) if jt.started_at else None
    best, best_score = None, 0.0
    for child in stt_root.iterdir():
        if not child.is_dir():
            continue
        session = load_stt_session(child)
        if session is None:
            continue
        overlap = len(ids & session.participant_ids)
        score = float(overlap)
        if start_ms is not None:
            delta = abs(int(session.meta.get("started_at_ms") or 0) - start_ms)
            if overlap == 0 and delta > 10 * 60 * 1000:
                continue
            score += max(0.0, 1.0 - delta / (10 * 60 * 1000)) * 0.5
        if score > best_score:
            best, best_score = session, score
    return best


def build_transcript(jt: JigasiTranscript | None, session: SttSession | None) -> Transcript:
    if jt is None and session is None:
        raise ValueError("no transcript source")
    names = dict(jt.participants) if jt else {}
    utterances: list[Utterance] = []
    if session and session.segments:
        for s in session.segments:
            pid = s["participant_id"]
            utterances.append(Utterance(
                speaker=names.get(pid) or _guess_name(pid, names),
                start_ms=int(s["start_epoch_ms"]),
                end_ms=int(s["end_epoch_ms"]),
                text=normalize_persian(s["text"]),
                participant_id=pid,
                confidence=s.get("confidence"),
            ))
        source = "live"
    elif jt:
        utterances = list(jt.speech)
        source = "live"
    utterances.sort(key=lambda u: u.start_ms)

    started = (jt.started_at if jt and jt.started_at else None) or (
        datetime.fromtimestamp(session.meta["started_at_ms"] / 1000, tz=timezone.utc) if session
        else datetime.now(timezone.utc))
    if utterances:
        started = min(started, datetime.fromtimestamp(utterances[0].start_ms / 1000, tz=timezone.utc))
    ended = jt.ended_at if jt else None
    if ended is None and session and session.meta.get("closed_at_ms"):
        ended = datetime.fromtimestamp(session.meta["closed_at_ms"] / 1000, tz=timezone.utc)

    return Transcript(
        room_name=jt.room_name if jt else session.dir.name,
        started_at=started,
        ended_at=ended,
        utterances=utterances,
        participants=names,
        source=source,
        provider_session_id=session.meta.get("connection_id") if session else (jt.path.name if jt else None),
        engine=session.meta.get("engine", "jigasi") if session else "jigasi",
        model=session.meta.get("model", "unknown") if session else "unknown",
    )


def _guess_name(pid: str, names: dict[str, str]) -> str:
    # Jigasi ids may be "<room>@muc/<resource>" in one place and "<resource>" in another.
    for key, name in names.items():
        if key.endswith("/" + pid) or pid.endswith("/" + key):
            return name
    return f"شرکت‌کننده {pid[:6]}"
