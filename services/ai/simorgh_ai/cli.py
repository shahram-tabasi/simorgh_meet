"""Command line entry point: ``simorgh-ai <command>``.

  stt-server                 run the Jigasi-compatible streaming STT server
  worker                     run the minutes worker
  transcribe FILE            transcribe an audio/video file (prints speaker-less transcript)
  minutes TRANSCRIPT.json    generate minutes from a Jigasi transcript JSON or worker transcript.json
  check                      verify STT model and LLM endpoint (used by the installer)
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime
from pathlib import Path

from .config import LlmConfig, SttConfig, WorkerConfig


def _cmd_transcribe(args) -> int:
    from .engines import create_engine
    from .worker import _load_media

    cfg = SttConfig()
    engine = create_engine(cfg)
    for seg in engine.transcribe(_load_media(Path(args.file)), language=cfg.language,
                                 beam_size=cfg.final_beam_size, hotwords=cfg.hotwords, vad=True):
        print(f"[{seg.start_ms / 1000:8.2f} - {seg.end_ms / 1000:8.2f}] {seg.text}")
    return 0


def _load_any_transcript(path: Path):
    from .minutes.transcript import Transcript, Utterance, build_transcript, load_jigasi_transcript

    data = json.loads(path.read_text(encoding="utf-8"))
    if "utterances" in data:  # worker transcript.json
        return Transcript(
            room_name=data["room_name"],
            started_at=datetime.fromisoformat(data["started_at"]),
            ended_at=datetime.fromisoformat(data["ended_at"]) if data.get("ended_at") else None,
            utterances=[Utterance(**u) for u in data["utterances"]],
            participants=data.get("participants", {}),
            source=data.get("source", "live"),
        )
    return build_transcript(load_jigasi_transcript(path), None)


def _cmd_minutes(args) -> int:
    from .minutes.generator import MinutesGenerator
    from .minutes.llm import LlmClient
    from .minutes.render import render_markdown

    lcfg, wcfg = LlmConfig(), WorkerConfig()
    transcript = _load_any_transcript(Path(args.transcript))
    result = MinutesGenerator(LlmClient(lcfg), lcfg, wcfg.organization_name, wcfg.timezone).generate(
        transcript, args.title or "", [t.strip() for t in (args.glossary or "").split(",") if t.strip()])
    if args.json:
        print(json.dumps(result.content, ensure_ascii=False, indent=2))
    else:
        print(render_markdown(result.content, transcript.room_name))
    return 0


def _cmd_check(_args) -> int:
    from .minutes.llm import LlmClient

    ok = True
    scfg = SttConfig()
    model = Path(scfg.model_path)
    if scfg.engine != "mock" and not model.exists():
        print(f"[FAIL] STT model not found: {model}")
        ok = False
    else:
        print(f"[ OK ] STT model: {model} ({scfg.engine})")
    if LlmClient(LlmConfig()).health():
        print("[ OK ] LLM endpoint healthy")
    else:
        print("[WARN] LLM endpoint not reachable yet (it may still be loading the model)")
    return 0 if ok else 1


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    parser = argparse.ArgumentParser(prog="simorgh-ai")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("stt-server")
    sub.add_parser("worker")
    p = sub.add_parser("transcribe")
    p.add_argument("file")
    p = sub.add_parser("minutes")
    p.add_argument("transcript")
    p.add_argument("--title")
    p.add_argument("--glossary", help="comma separated names/terms")
    p.add_argument("--json", action="store_true")
    sub.add_parser("check")
    args = parser.parse_args(argv)

    if args.command == "stt-server":
        from .stt_server import main as stt_main

        stt_main()
        return 0
    if args.command == "worker":
        from .worker import main as worker_main

        worker_main()
        return 0
    return {"transcribe": _cmd_transcribe, "minutes": _cmd_minutes, "check": _cmd_check}[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
