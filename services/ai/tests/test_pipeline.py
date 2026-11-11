import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pytest
from conftest import silence, tone
from fastapi.testclient import TestClient

from simorgh_ai import protocol
from simorgh_ai.audio import float_to_pcm16
from simorgh_ai.config import LlmConfig, SttConfig, WorkerConfig
from simorgh_ai.engines import MockEngine
from simorgh_ai.minutes.generator import MinutesGenerator
from simorgh_ai.minutes.render import render_markdown
from simorgh_ai.minutes.transcript import build_transcript, load_jigasi_transcript, match_stt_session
from simorgh_ai.stt_server import create_app
from simorgh_ai.worker import Worker, _parse_recording_name


def stt_cfg(tmp_path: Path, **kw) -> SttConfig:
    return SttConfig(engine="mock", data_dir=tmp_path / "stt", min_silence_ms=400, **kw)


def send_speech(ws, pid: str, audio: np.ndarray, lang: str = "fa-IR", realtime: bool = False) -> None:
    pcm = float_to_pcm16(audio)
    step = 640 * 25  # ~500 ms frames, like Jigasi's local buffer
    for i in range(0, len(pcm), step):
        chunk = pcm[i : i + step]
        ws.send_bytes(protocol.build_frame(pid, lang, chunk))
        if realtime:
            time.sleep(len(chunk) / 2 / 16000)


def run_meeting(tmp_path: Path) -> tuple[list[dict], Path]:
    app = create_app(stt_cfg(tmp_path), MockEngine())
    messages = []
    with TestClient(app) as client:
        assert client.get("/health").json()["engine"] == "mock"
        with client.websocket_connect("/ws/conn-1234") as ws:
            send_speech(ws, "ep-ali", np.concatenate([tone(1.5), silence(0.8)]))
            send_speech(ws, "ep-sara", np.concatenate([tone(2.0), silence(0.8)]), lang="en-US")
            send_speech(ws, "ep-ali", tone(1.0))  # unterminated: must be flushed at EOF
            ws.send_bytes(b"\x00")
            deadline = time.time() + 10
            while len(messages) < 3 and time.time() < deadline:
                messages.append(json.loads(ws.receive_text()))
    return messages, tmp_path / "stt" / "conn-1234"


def test_websocket_end_to_end(tmp_path):
    messages, session_dir = run_meeting(tmp_path)
    assert len(messages) == 3
    assert {m["participant_id"] for m in messages} == {"ep-ali", "ep-sara"}
    assert all(m["type"] == "final" and isinstance(m["variance"], float) for m in messages)
    meta = json.loads((session_dir / "session.json").read_text())
    assert meta["closed_at_ms"] and set(meta["participants"]) == {"ep-ali", "ep-sara"}
    segments = [json.loads(l) for l in (session_dir / "segments.jsonl").read_text().splitlines()]
    assert len(segments) == 3
    assert {s["language"] for s in segments} == {"fa"}  # forced even though Jigasi may send "en"
    assert (session_dir / "audio" / "ep-ali.wav").stat().st_size > 16000 * 2 * 2
    # The audio path must survive close(): the refine pass and dataset export depend on it.
    assert meta["participants"]["ep-ali"]["audio"] == "audio/ep-ali.wav"


def test_asap_auth_rejects_missing_token(tmp_path):
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pub = tmp_path / "pub.pem"
    pub.write_bytes(key.public_key().public_bytes(serialization.Encoding.PEM,
                                                  serialization.PublicFormat.SubjectPublicKeyInfo))
    app = create_app(stt_cfg(tmp_path, asap_public_key_path=str(pub)), MockEngine())
    from starlette.websockets import WebSocketDisconnect

    with TestClient(app) as client:
        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect("/ws/x") as ws:
                ws.receive_text()
        import jwt

        token = jwt.encode({"aud": "jitsi", "iss": "jigasi"}, key, algorithm="RS256")
        with client.websocket_connect("/ws/y", headers={"Authorization": f"Bearer {token}"}) as ws:
            ws.send_bytes(b"\x00")


def write_jigasi_transcript(path: Path, started: datetime) -> Path:
    ms = int(started.timestamp() * 1000)
    data = {
        "room_name": "projectx@muc.meet.jitsi",
        "start_time": started.isoformat(),
        "end_time": None,
        "initial_participants": [{"name": "Fellow Jitser", "id": "focus"}, {"name": "علی رضایی", "id": "ep-ali"}],
        "events": [
            {"event": "JOIN", "timestamp": ms, "participant": {"name": "سارا احمدی", "id": "ep-sara"}},
            {"event": "SPEECH", "timestamp": ms + 1000, "participant": {"name": "علی رضایی", "id": "ep-ali"},
             "transcript": [{"text": "سلام دوستان", "confidence": 0.9}], "is_interim": False},
            {"event": "SPEECH", "timestamp": ms + 1500, "participant": {"name": "علی رضایی", "id": "ep-ali"},
             "transcript": [{"text": "سلام دوس", "confidence": 0.5}], "is_interim": True},
        ],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return path


def test_transcript_merge_uses_real_names(tmp_path):
    _, session_dir = run_meeting(tmp_path)
    jt = load_jigasi_transcript(write_jigasi_transcript(tmp_path / "t" / "a.json", datetime.now(timezone.utc)))
    assert jt.room_name == "projectx" and len(jt.speech) == 1  # interim dropped
    assert "focus" not in jt.participants  # Jicofo is not a person
    session = match_stt_session(jt, tmp_path / "stt")
    assert session is not None and session.dir == session_dir
    transcript = build_transcript(jt, session)
    assert set(transcript.speakers) == {"علی رضایی", "سارا احمدی"}
    assert len(transcript.utterances) == 3
    assert transcript.to_lines()[0].startswith("[00:00:")


def test_minutes_generation_single_and_map_reduce(tmp_path, llm_client, fake_llm):
    _, _ = run_meeting(tmp_path)
    jt = load_jigasi_transcript(write_jigasi_transcript(tmp_path / "t" / "a.json", datetime.now(timezone.utc)))
    transcript = build_transcript(jt, match_stt_session(jt, tmp_path / "stt"))

    gen = MinutesGenerator(llm_client, LlmConfig(base_url="http://llm/v1"), "شرکت نمونه")
    result = gen.generate(transcript, "جلسه هفتگی", ["سیمرغ"])
    assert result.meta["strategy"] == "single"
    content = result.content
    assert content["title"] == "جلسه هماهنگی پروژه"
    titles = [a["title"] for a in content["action_items"]]
    assert titles == ["تهیه گزارش نهایی", "اقدام با تاریخ غلط"]  # empty title dropped
    first, second = content["action_items"]
    assert first["owner"] == "علی رضایی"  # snapped to participant spelling
    assert second["due_date"] == "" and second["priority"] == "normal"
    assert content["review_required"] is True
    prompt = fake_llm.requests[0]["messages"][1]["content"]
    assert "سیمرغ" in prompt and "شرکت نمونه" in prompt and "علی رضایی" in prompt
    assert fake_llm.requests[0]["response_format"]["type"] == "json_schema"

    md = render_markdown(content, transcript.room_name)
    assert "## اقدامات و پیگیری‌ها" in md and "| ۱ | تهیه گزارش نهایی | علی رضایی |" in md

    fake_llm.requests.clear()
    small = MinutesGenerator(llm_client, LlmConfig(base_url="http://llm/v1", chunk_chars=60))
    result = small.generate(transcript)
    assert result.meta["strategy"].startswith("map-reduce/")
    assert len(fake_llm.requests) == int(result.meta["strategy"].split("/")[1]) + 1


def test_worker_processes_finished_meeting(tmp_path, llm_client, monkeypatch):
    run_meeting(tmp_path)
    transcripts = tmp_path / "transcripts"
    f = write_jigasi_transcript(transcripts / "projectx.json", datetime.now(timezone.utc))
    old = time.time() - 120
    os.utime(f, (old, old))
    wcfg = WorkerConfig(database_url="", transcripts_dir=transcripts, recordings_dir=tmp_path / "rec",
                        minutes_dir=tmp_path / "minutes", min_words=1, refine_enabled=True)
    worker = Worker(wcfg, stt_cfg(tmp_path), LlmConfig(base_url="http://llm/v1"), llm=llm_client,
                    engine=MockEngine())
    calls = []
    original = MockEngine.transcribe
    MockEngine.transcribe = lambda self, audio, **kw: calls.append(kw["beam_size"]) or original(self, audio, **kw)
    try:
        worker.tick()
    finally:
        MockEngine.transcribe = original
    assert calls and set(calls) == {5}  # refine pass re-decoded every utterance with the final beam
    outputs = list((tmp_path / "minutes" / "projectx").glob("*/minutes.md"))
    assert len(outputs) == 1
    assert "تهیه گزارش نهایی" in outputs[0].read_text()
    transcript = json.loads((outputs[0].parent / "transcript.json").read_text())
    worker.tick()  # idempotent
    assert len(list((tmp_path / "minutes" / "projectx").glob("*/minutes.md"))) == 1


def test_parse_jibri_recording_name(tmp_path):
    p = tmp_path / "abc" / "projectx_2026-11-11-09-30-00.mp4"
    p.parent.mkdir()
    p.write_bytes(b"")
    room, started = _parse_recording_name(p, "Asia/Tehran")
    assert room == "projectx" and started.hour == 9 and started.utcoffset().total_seconds() == 3.5 * 3600


def test_dtx_pause_without_silent_samples_ends_utterance(tmp_path):
    """Real Jigasi traffic: WebRTC sends no packets while a speaker pauses (Opus DTX), so
    the stream contains only voiced audio and pauses are visible only as arrival gaps.
    Verified against a live Jitsi stable-11031 deployment."""
    app = create_app(stt_cfg(tmp_path), MockEngine())
    with TestClient(app) as client:
        with client.websocket_connect("/ws/dtx") as ws:
            send_speech(ws, "ep-ali", tone(1.5), realtime=True)  # no trailing silence samples
            time.sleep(1.2)                                        # speaker pauses: nothing is sent
            send_speech(ws, "ep-ali", tone(1.0), realtime=True)
            ws.send_bytes(b"\x00")
            msgs = [json.loads(ws.receive_text()) for _ in range(2)]
    assert len(msgs) == 2
    segs = [json.loads(l) for l in (tmp_path / "stt" / "dtx" / "segments.jsonl").read_text().splitlines()]
    segs.sort(key=lambda r: r["stream_start_ms"])
    assert len(segs) == 2
    # Compact stream offsets stay contiguous (used to cut the WAV) ...
    assert segs[1]["stream_start_ms"] - segs[0]["stream_end_ms"] < 400
    # ... while wall-clock times include the real pause.
    assert segs[1]["start_epoch_ms"] - segs[0]["end_epoch_ms"] >= 900


def test_wall_clock_anchor_mapping():
    from simorgh_ai.stt_server import ParticipantStream
    from simorgh_ai.audio import UtteranceSegmenter

    p = ParticipantStream("p", "fa", UtteranceSegmenter(), stream_start_epoch_ms=1_000)
    assert p.note_arrival(0, 10_000, 500, 700) is False      # first frame anchors
    assert p.note_arrival(500, 10_510, 500, 700) is False    # on time
    assert p.note_arrival(1000, 11_020, 500, 700) is False   # jitter is not a pause
    assert p.note_arrival(1500, 13_000, 500, 700) is True    # ~1.5 s gap -> pause
    assert p.wall_ms_at(200) == 10_200
    assert p.wall_ms_at(1500) == 13_000
    assert p.wall_ms_at(1700) == 13_200
