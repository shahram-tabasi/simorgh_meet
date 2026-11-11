"""Integration test against PostgreSQL with the API migrations applied.

Set TEST_DATABASE_URL (a disposable database!) to run it."""

import os
from datetime import datetime, timezone

import pytest

from simorgh_ai.minutes.generator import MinutesResult
from simorgh_ai.minutes.transcript import Transcript, Utterance

DB = os.environ.get("TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not DB, reason="TEST_DATABASE_URL not set")


@pytest.fixture
def seeded():
    from simorgh_ai.store import Store

    store = Store(DB)
    with store.connect() as conn:
        org = conn.execute("INSERT INTO organizations (name, slug) VALUES ('Org', 'org-' || md5(random()::text)) "
                           "RETURNING id").fetchone()["id"]
        user = conn.execute(
            "INSERT INTO users (identity_issuer, identity_subject, display_name) "
            "VALUES ('https://idp', md5(random()::text), 'علی رضایی') RETURNING id").fetchone()["id"]
        mem = conn.execute("INSERT INTO organization_memberships (organization_id, user_id, role) "
                           "VALUES (%s, %s, 'owner') RETURNING id", (org, user)).fetchone()["id"]
        room_name = "unit-" + str(org)[:8]
        conn.execute("INSERT INTO rooms (organization_id, name, room_name, created_by_membership_id) "
                     "VALUES (%s, 'اتاق واحد فنی', %s, %s)", (org, room_name, mem))
        conn.commit()
    yield store, str(org), room_name
    with store.connect() as conn:
        conn.execute("DELETE FROM organizations WHERE id = %s", (org,))
        conn.execute("DELETE FROM users WHERE id = %s", (user,))
        conn.commit()


def test_permanent_room_meeting_minutes_and_actions(seeded):
    store, org, room_name = seeded
    started = datetime(2026, 11, 11, 6, 0, tzinfo=timezone.utc)
    base = int(started.timestamp() * 1000)
    transcript = Transcript(room_name=room_name.upper(), started_at=started, ended_at=None,
                            provider_session_id="conn-" + org,
                            utterances=[Utterance("علی رضایی", base + 1000, base + 4000, "گزارش را آماده می‌کنم")])
    result = MinutesResult(
        content={"title": "t", "action_items": [
            {"title": "تهیه گزارش", "owner": "علی رضایی", "due_date": "2026-11-18", "priority": "high",
             "source_quote": "", "due_text": "هفته بعد"},
            {"title": "پیگیری", "owner": "مهمان", "due_date": "", "priority": "normal", "source_quote": "",
             "due_text": ""}]},
        model="test-model", meta={"strategy": "single"})
    with store.connect() as conn:
        meeting = store.resolve_meeting(conn, transcript.room_name, started)
        assert meeting is not None and meeting.title == "اتاق واحد فنی"
        session_id = store.save_transcript(conn, meeting, transcript)
        session_again = store.save_transcript(conn, meeting, transcript)  # idempotent upsert
        assert session_id == session_again
        m1 = store.save_minutes(conn, meeting, session_id, result, "# md")
        m2 = store.save_minutes(conn, meeting, session_id, result, "# md")
        conn.commit()
        assert m1 != m2
        versions = [r["version"] for r in conn.execute(
            "SELECT version FROM meeting_minutes WHERE meeting_id = %s ORDER BY version", (meeting.meeting_id,))]
        assert versions == [1, 2]
        items = conn.execute("SELECT title, assignee_membership_id, assignee_name, due_date::text AS due "
                             "FROM action_items WHERE minutes_id = %s ORDER BY title", (m1,)).fetchall()
        by_title = {r["title"]: r for r in items}
        assert by_title["تهیه گزارش"]["assignee_membership_id"] is not None
        assert by_title["تهیه گزارش"]["due"] == "2026-11-18"
        assert by_title["پیگیری"]["assignee_membership_id"] is None
        segs = conn.execute("SELECT start_ms, end_ms FROM transcript_segments WHERE session_id = %s",
                            (session_id,)).fetchall()
        assert [(s["start_ms"], s["end_ms"]) for s in segs] == [(1000, 4000)]
        # Same room an hour later resolves to the same ad-hoc meeting (within window).
        again = store.resolve_meeting(conn, room_name, started)
        assert again.meeting_id == meeting.meeting_id

        conn.execute("INSERT INTO background_jobs (organization_id, kind, payload) VALUES (%s, 'minutes.generate', %s)",
                     (org, '{"meeting_id": "%s"}' % meeting.meeting_id))
        conn.commit()
        job = store.claim_job(conn, ["minutes.generate"], "test")
        assert job and job["status"] == "running"
        loaded = store.load_transcript(conn, job["payload"]["meeting_id"])
        assert loaded and loaded[0].utterances[0].text == "گزارش را آماده می‌کنم"
        store.finish_job(conn, job, "boom")
        assert conn.execute("SELECT status FROM background_jobs WHERE id = %s", (job["id"],)).fetchone()["status"] == "queued"
