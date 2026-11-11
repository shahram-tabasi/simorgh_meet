#!/usr/bin/env python3
"""Export utterance clips + machine transcripts from Simorgh STT sessions for human
correction — the first step of the Kermani (and organization-specific) data flywheel.

Every live meeting already stores per-speaker 16 kHz audio and time-aligned segments
(``/var/lib/simorgh-meet/stt/<session>/``). This tool cuts each segment into its own
WAV file and writes ``metadata.csv`` (Hugging Face "audiofolder" layout)::

    file_name,transcription,machine_transcription,speaker,session,duration_s,dialect
    clips/<session>/<n>.wav,<text to correct>,<original STT text>,<participant>,...

Reviewers correct the ``transcription`` column (keep ``machine_transcription`` as is)
and set ``dialect`` (e.g. ``kermani`` / ``standard``). The corrected folder is the
input of ``finetune_whisper.py``.

Only export meetings whose participants consented to their voice being used for
model improvement (see docs/AI-MINUTES-AND-PERSIAN-STT.md, "Privacy").

Usage:
  python3 export_dataset.py --stt-dir /var/lib/simorgh-meet/stt --out ./dataset \
      [--session <id> ...] [--min-seconds 1.0] [--max-seconds 30] [--dialect kermani]
"""

from __future__ import annotations

import argparse
import csv
import json
import wave
from pathlib import Path

RATE = 16000


def read_pcm(path: Path) -> bytes:
    with wave.open(str(path), "rb") as wav:
        if wav.getframerate() != RATE or wav.getnchannels() != 1 or wav.getsampwidth() != 2:
            raise ValueError(f"{path}: expected 16 kHz mono 16-bit WAV")
        return wav.readframes(wav.getnframes())


def write_wav(path: Path, pcm: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(RATE)
        wav.writeframes(pcm)


def export_session(session_dir: Path, out: Path, writer: csv.DictWriter, min_s: float, max_s: float,
                   dialect: str) -> int:
    meta = json.loads((session_dir / "session.json").read_text(encoding="utf-8"))
    seg_file = session_dir / "segments.jsonl"
    if not seg_file.exists():
        return 0
    audio_cache: dict[str, bytes] = {}
    count = 0
    for n, line in enumerate(seg_file.read_text(encoding="utf-8").splitlines()):
        if not line.strip():
            continue
        seg = json.loads(line)
        pid = seg["participant_id"]
        rel = (meta.get("participants", {}).get(pid) or {}).get("audio")
        if not rel or not (session_dir / rel).exists():
            continue
        if pid not in audio_cache:
            audio_cache[pid] = read_pcm(session_dir / rel)
        pcm = audio_cache[pid]
        start = int(seg["stream_start_ms"]) * RATE // 1000 * 2
        end = int(seg["stream_end_ms"]) * RATE // 1000 * 2
        clip = pcm[max(0, start - 3200) : min(len(pcm), end + 3200)]  # ±100 ms context
        duration = len(clip) / 2 / RATE
        if not (min_s <= duration <= max_s):
            continue
        rel_clip = Path("clips") / session_dir.name / f"{n:05d}.wav"
        write_wav(out / rel_clip, clip)
        writer.writerow({
            "file_name": rel_clip.as_posix(),
            "transcription": seg["text"],
            "machine_transcription": seg.get("live_text", seg["text"]),
            "speaker": pid,
            "session": session_dir.name,
            "duration_s": f"{duration:.2f}",
            "dialect": dialect,
        })
        count += 1
    return count


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--stt-dir", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--session", action="append", help="limit to these session ids (repeatable)")
    ap.add_argument("--min-seconds", type=float, default=1.0)
    ap.add_argument("--max-seconds", type=float, default=30.0)
    ap.add_argument("--dialect", default="", help="default value for the dialect column")
    args = ap.parse_args()

    args.out.mkdir(parents=True, exist_ok=True)
    meta_path = args.out / "metadata.csv"
    new_file = not meta_path.exists()
    total = 0
    with meta_path.open("a", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=["file_name", "transcription", "machine_transcription", "speaker",
                                                "session", "duration_s", "dialect"])
        if new_file:
            writer.writeheader()
        for session_dir in sorted(p for p in args.stt_dir.iterdir() if (p / "session.json").exists()):
            if args.session and session_dir.name not in args.session:
                continue
            n = export_session(session_dir, args.out, writer, args.min_seconds, args.max_seconds, args.dialect)
            print(f"{session_dir.name}: {n} clips")
            total += n
    print(f"exported {total} clips -> {meta_path}")


if __name__ == "__main__":
    main()
