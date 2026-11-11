import json
from datetime import date, timedelta

import numpy as np
import pytest
from conftest import silence, tone

from simorgh_ai import protocol
from simorgh_ai.audio import UtteranceSegmenter, pcm16_to_float, float_to_pcm16, resample
from simorgh_ai.jalali import format_jalali, gregorian_to_jalali, jalali_to_gregorian
from simorgh_ai.minutes.generator import chunk_lines
from simorgh_ai.minutes.llm import parse_json_object
from simorgh_ai.textnorm import normalize_persian


def test_frame_roundtrip_matches_jigasi_layout():
    pcm = float_to_pcm16(tone(0.02))
    frame = protocol.build_frame("a1b2c3d4", "fa-IR", pcm)
    assert len(frame) == 60 + len(pcm)
    parsed = protocol.parse_frame(frame)
    assert parsed.participant_id == "a1b2c3d4"
    assert parsed.language == "fa"
    assert parsed.pcm == pcm
    assert protocol.is_eof(b"\x00")
    assert not protocol.is_eof(frame)


def test_frame_without_participant_rejected():
    with pytest.raises(protocol.ProtocolError):
        protocol.parse_frame(b"|fa".ljust(60, b"\x00") + b"\x00\x00")


def test_result_message_variance_is_float():
    msg = protocol.result_message("p1", "سلام", True, 123, variance=1)
    raw = json.loads(msg)
    assert raw["type"] == "final" and raw["participant_id"] == "p1"
    assert '"variance": 1.0' in msg  # Jigasi casts to double


def test_resample_48k_to_16k_preserves_duration():
    x = tone(1.0)
    x48 = np.interp(np.linspace(0, 1, 48000, endpoint=False), np.linspace(0, 1, 16000, endpoint=False), x)
    assert resample(x48.astype(np.float32), 48000).size == 16000
    assert resample(x, 16000) is x


def test_segmenter_splits_on_silence():
    seg = UtteranceSegmenter(min_silence_ms=500)
    audio = np.concatenate([silence(0.5), tone(1.0), silence(1.0), tone(2.0), silence(1.0)])
    utts = []
    for i in range(0, audio.size, 320):  # 20 ms packets like WebRTC
        utts += seg.push(audio[i : i + 320])
    utts += seg.flush()
    assert len(utts) == 2
    assert abs(utts[0].start_ms - 500) <= 350
    assert 900 <= utts[0].end_ms - utts[0].start_ms <= 1900
    assert abs(utts[1].start_ms - 2500) <= 350


def test_segmenter_caps_long_utterances():
    seg = UtteranceSegmenter(max_utterance_s=3.0)
    utts = seg.push(tone(7.0)) + seg.flush()
    assert len(utts) == 3
    assert all(u.samples.size <= 3 * 16000 + 480 for u in utts)


def test_segmenter_ignores_short_clicks():
    seg = UtteranceSegmenter(min_speech_ms=300)
    utts = seg.push(np.concatenate([tone(0.06), silence(1.5)])) + seg.flush()
    assert utts == []


def test_pcm_conversion_roundtrip():
    x = tone(0.1)
    assert np.allclose(pcm16_to_float(float_to_pcm16(x)), x, atol=1e-4)


def test_persian_normalization():
    assert normalize_persian("علي مي روم به كتابخانه ها") == "علی می‌روم به کتابخانه‌ها"
    assert normalize_persian("  سلام  ،  خوبی ؟ ") == "سلام، خوبی؟"
    assert normalize_persian("") == ""


def test_jalali_known_dates_and_roundtrip():
    assert gregorian_to_jalali(2025, 3, 21) == (1404, 1, 1)
    assert gregorian_to_jalali(2026, 11, 11) == (1405, 8, 20)
    d = date(2020, 1, 1)
    for _ in range(0, 3000, 7):
        assert date(*jalali_to_gregorian(*gregorian_to_jalali(d.year, d.month, d.day))) == d
        d += timedelta(days=7)
    assert format_jalali(date(2026, 11, 11)) == "چهارشنبه ۲۰ آبان ۱۴۰۵"


def test_parse_json_object_tolerates_wrappers():
    assert parse_json_object('<think>hm</think>```json\n{"a": 1}\n```') == {"a": 1}
    assert parse_json_object('Sure! {"a": {"b": 2}} done') == {"a": {"b": 2}}
    with pytest.raises(ValueError):
        parse_json_object("no json here")


def test_chunk_lines():
    lines = [f"line {i} " + "x" * 50 for i in range(100)]
    chunks = chunk_lines(lines, 600)
    assert len(chunks) > 5
    assert all(len(c) <= 600 for c in chunks)
    assert "\n".join(chunks).count("line") == 100
