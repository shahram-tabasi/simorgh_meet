"""PostgreSQL persistence for transcripts, AI minutes and action items."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone

import psycopg
from psycopg.rows import dict_row

from .minutes.generator import MinutesResult
from .minutes.transcript import Transcript, Utterance

log = logging.getLogger(__name__)


@dataclass
class MeetingRef:
    meeting_id: str
    organization_id: str
    title: str
    ai_minutes_enabled: bool


class Store:
    def __init__(self, database_url: str):
        self.database_url = database_url

    def connect(self) -> psycopg.Connection:
        return psycopg.connect(self.database_url, row_factory=dict_row, application_name="simorgh-meet-ai")

    # ------------------------------------------------------------------ lookup
    def resolve_meeting(self, conn: psycopg.Connection, room_name: str, started_at: datetime) -> MeetingRef | None:
        room_name = room_name.strip().lower()
        row = conn.execute(
            """SELECT id, organization_id, title, ai_minutes_enabled FROM meetings
                WHERE lower(room_name) = %s AND status <> 'cancelled'
                ORDER BY (status = 'active') DESC,
                         abs(extract(epoch FROM coalesce(actual_started_at, scheduled_start_at, created_at) - %s))
                LIMIT 1""",
            (room_name, started_at),
        ).fetchone()
        if row:
            return MeetingRef(str(row["id"]), str(row["organization_id"]), row["title"], row["ai_minutes_enabled"])

        room = conn.execute(
            """SELECT id, organization_id, name, created_by_membership_id, default_ai_minutes, visibility
                 FROM rooms WHERE lower(room_name) = %s AND status = 'active' LIMIT 1""",
            (room_name,),
        ).fetchone()
        if not room:
            return None
        window = timedelta(hours=12)
        row = conn.execute(
            """SELECT id, organization_id, title, ai_minutes_enabled FROM meetings
                WHERE room_id = %s AND status <> 'cancelled'
                  AND coalesce(actual_started_at, scheduled_start_at) BETWEEN %s AND %s
                ORDER BY abs(extract(epoch FROM coalesce(actual_started_at, scheduled_start_at) - %s))
                LIMIT 1""",
            (room["id"], started_at - window, started_at + window, started_at),
        ).fetchone()
        if row:
            return MeetingRef(str(row["id"]), str(row["organization_id"]), row["title"], row["ai_minutes_enabled"])

        # Ad-hoc session in a permanent room: create a meeting record to hang minutes on.
        stamp = started_at.astimezone(timezone.utc).strftime("%Y%m%d%H%M%S")
        row = conn.execute(
            """INSERT INTO meetings (organization_id, created_by_membership_id, title, status, room_id,
                                     room_name, visibility, actual_started_at, ai_minutes_enabled)
               VALUES (%s, %s, %s, 'ended', %s, %s, %s, %s, %s)
               RETURNING id, organization_id, title, ai_minutes_enabled""",
            (room["organization_id"], room["created_by_membership_id"], room["name"], room["id"],
             f"{room_name}~{stamp}", room["visibility"], started_at, room["default_ai_minutes"]),
        ).fetchone()
        return MeetingRef(str(row["id"]), str(row["organization_id"]), row["title"], row["ai_minutes_enabled"])

    def glossary(self, conn: psycopg.Connection, organization_id: str) -> list[str]:
        rows = conn.execute(
            "SELECT term, normalized FROM organization_glossary_terms WHERE organization_id = %s ORDER BY term LIMIT 300",
            (organization_id,),
        ).fetchall()
        return [f"{r['term']} ({r['normalized']})" if r["normalized"] else r["term"] for r in rows]

    # ----------------------------------------------------------------- persist
    def save_transcript(self, conn: psycopg.Connection, meeting: MeetingRef, transcript: Transcript) -> str:
        provider_id = transcript.provider_session_id or f"{transcript.room_name}:{transcript.started_at.isoformat()}"
        row = conn.execute(
            """INSERT INTO transcription_sessions
                 (organization_id, meeting_id, source, provider_session_id, engine, model, language,
                  status, started_at, completed_at)
               VALUES (%s, %s, %s, %s, %s, %s, %s, 'completed', %s, %s)
               ON CONFLICT (source, provider_session_id) DO UPDATE
                 SET engine = EXCLUDED.engine, model = EXCLUDED.model, status = 'completed',
                     completed_at = EXCLUDED.completed_at
               RETURNING id""",
            (meeting.organization_id, meeting.meeting_id, transcript.source, provider_id, transcript.engine,
             transcript.model, transcript.language, transcript.started_at,
             transcript.ended_at or datetime.now(timezone.utc)),
        ).fetchone()
        session_id = str(row["id"])
        conn.execute("DELETE FROM transcript_segments WHERE session_id = %s", (session_id,))
        base = int(transcript.started_at.timestamp() * 1000)
        participant_ids = self._participant_map(conn, meeting)
        with conn.cursor() as cur:
            cur.executemany(
                """INSERT INTO transcript_segments
                     (organization_id, session_id, participant_id, speaker_label, provider_participant_id,
                      start_ms, end_ms, text, confidence)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                [
                    (meeting.organization_id, session_id, participant_ids.get(u.speaker), u.speaker[:160],
                     u.participant_id, max(0, u.start_ms - base), max(0, u.end_ms - base), u.text, u.confidence)
                    for u in transcript.utterances
                ],
            )
        return session_id

    def _participant_map(self, conn: psycopg.Connection, meeting: MeetingRef) -> dict[str, str]:
        rows = conn.execute(
            """SELECT p.id, coalesce(u.display_name, p.display_name) AS name
                 FROM meeting_participants p
                 LEFT JOIN organization_memberships m ON m.id = p.membership_id
                 LEFT JOIN users u ON u.id = m.user_id
                WHERE p.meeting_id = %s AND p.organization_id = %s""",
            (meeting.meeting_id, meeting.organization_id),
        ).fetchall()
        return {r["name"]: str(r["id"]) for r in rows if r["name"]}

    def save_minutes(self, conn: psycopg.Connection, meeting: MeetingRef, session_id: str | None,
                     result: MinutesResult, markdown: str) -> str:
        # Serialize version allocation per meeting (UNIQUE(meeting_id, version) is the backstop).
        conn.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (f"minutes:{meeting.meeting_id}",))
        version = conn.execute(
            "SELECT coalesce(max(version), 0) + 1 AS v FROM meeting_minutes WHERE meeting_id = %s",
            (meeting.meeting_id,),
        ).fetchone()["v"]
        row = conn.execute(
            """INSERT INTO meeting_minutes
                 (organization_id, meeting_id, version, status, origin, language, content, rendered_markdown,
                  transcription_session_id, generator_model, generator_meta)
               VALUES (%s, %s, %s, 'draft', 'ai', 'fa', %s, %s, %s, %s, %s)
               RETURNING id""",
            (meeting.organization_id, meeting.meeting_id, version, json.dumps(result.content, ensure_ascii=False),
             markdown, session_id, result.model, json.dumps(result.meta, ensure_ascii=False)),
        ).fetchone()
        minutes_id = str(row["id"])
        members = {
            r["name"]: str(r["id"])
            for r in conn.execute(
                """SELECT m.id, u.display_name AS name FROM organization_memberships m
                     JOIN users u ON u.id = m.user_id
                    WHERE m.organization_id = %s AND m.status = 'active' AND u.display_name IS NOT NULL""",
                (meeting.organization_id,),
            ).fetchall()
        }
        for item in result.content.get("action_items", []):
            owner = item.get("owner") or None
            due = date.fromisoformat(item["due_date"]) if item.get("due_date") else None
            conn.execute(
                """INSERT INTO action_items
                     (organization_id, meeting_id, minutes_id, title, assignee_membership_id, assignee_name,
                      due_date, priority, origin, source_quote, description)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'ai', %s, %s)""",
                (meeting.organization_id, meeting.meeting_id, minutes_id, item["title"][:500],
                 members.get(owner) if owner else None, owner, due, item.get("priority", "normal"),
                 item.get("source_quote") or None, item.get("due_text") or None),
            )
        conn.execute(
            """INSERT INTO audit_events (organization_id, actor_kind, action, target_type, target_id, metadata)
               VALUES (%s, 'service', 'minutes.ai_generated', 'meeting_minutes', %s, %s)""",
            (meeting.organization_id, minutes_id,
             json.dumps({"meeting_id": meeting.meeting_id, "version": version, **result.meta})),
        )
        return minutes_id

    # -------------------------------------------------------------------- jobs
    def claim_job(self, conn: psycopg.Connection, kinds: list[str], worker_id: str) -> dict | None:
        row = conn.execute(
            """UPDATE background_jobs SET status = 'running', attempts = attempts + 1, locked_at = now(),
                      locked_by = %s, updated_at = now()
                WHERE id = (SELECT id FROM background_jobs
                             WHERE status = 'queued' AND kind = ANY(%s) AND run_after <= now()
                             ORDER BY run_after, id FOR UPDATE SKIP LOCKED LIMIT 1)
                RETURNING *""",
            (worker_id, kinds),
        ).fetchone()
        conn.commit()
        return row

    def finish_job(self, conn: psycopg.Connection, job: dict, error: str | None) -> None:
        if error is None:
            conn.execute("UPDATE background_jobs SET status='succeeded', last_error=NULL, updated_at=now() WHERE id=%s",
                         (job["id"],))
        else:
            retry = job["attempts"] < job["max_attempts"]
            conn.execute(
                """UPDATE background_jobs SET status = %s, last_error = %s, locked_at = NULL, updated_at = now(),
                          run_after = now() + make_interval(secs => 60 * attempts * attempts)
                    WHERE id = %s""",
                ("queued" if retry else "failed", error[:4000], job["id"]),
            )
        conn.commit()

    def load_transcript(self, conn: psycopg.Connection, meeting_id: str) -> tuple[Transcript, str, MeetingRef] | None:
        m = conn.execute(
            "SELECT id, organization_id, title, room_name, ai_minutes_enabled FROM meetings WHERE id = %s",
            (meeting_id,),
        ).fetchone()
        if not m:
            return None
        s = conn.execute(
            """SELECT * FROM transcription_sessions WHERE meeting_id = %s AND status = 'completed'
                ORDER BY completed_at DESC NULLS LAST LIMIT 1""",
            (meeting_id,),
        ).fetchone()
        if not s:
            return None
        base = int(s["started_at"].timestamp() * 1000)
        segs = conn.execute(
            "SELECT * FROM transcript_segments WHERE session_id = %s ORDER BY start_ms, id", (s["id"],)
        ).fetchall()
        transcript = Transcript(
            room_name=m["room_name"], started_at=s["started_at"], ended_at=s["completed_at"],
            utterances=[Utterance(r["speaker_label"], base + r["start_ms"], base + r["end_ms"], r["text"],
                                  r["provider_participant_id"], r["confidence"]) for r in segs],
            source=s["source"], provider_session_id=s["provider_session_id"], engine=s["engine"], model=s["model"],
        )
        ref = MeetingRef(str(m["id"]), str(m["organization_id"]), m["title"], m["ai_minutes_enabled"])
        return transcript, str(s["id"]), ref
