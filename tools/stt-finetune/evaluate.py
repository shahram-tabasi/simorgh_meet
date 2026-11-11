#!/usr/bin/env python3
"""Measure WER/CER of one or more CTranslate2 Whisper models on a labelled test set,
overall and per dialect — the acceptance gate before shipping a new STT model.

Test set = an audiofolder with metadata.csv (file_name, transcription[, dialect]),
e.g. a held-out part of export_dataset.py output, or the public PSRB benchmark
(PartAI/PSRB on Hugging Face, which includes a Kermani-accent subset).

  pip install faster-whisper==1.2.1 jiwer==4.0.0
  python3 evaluate.py --data ./testset --model base=/models/whisper-fa-turbo-ct2 \
                      --model kermani=/models/whisper-fa-kermani-ct2 [--beam 5] [--threads 8]

Both texts are normalized identically (Arabic→Persian letters, ZWNJ, punctuation)
so that only recognition errors are counted.
"""

from __future__ import annotations

import argparse
import csv
import re
import time
from collections import defaultdict
from pathlib import Path

_MAP = str.maketrans({"ي": "ی", "ى": "ی", "ك": "ک", "ۀ": "ه", "ة": "ه", "‌": " ",
                      "۰": "0", "۱": "1", "۲": "2", "۳": "3", "۴": "4",
                      "۵": "5", "۶": "6", "۷": "7", "۸": "8", "۹": "9"})
_DROP = re.compile(r"[ً-ْٰ.,،؛:!?؟«»\"'()\[\]\-–—…]")


def norm(text: str) -> str:
    return " ".join(_DROP.sub(" ", text.translate(_MAP)).split())


def main() -> None:
    import jiwer
    from faster_whisper import WhisperModel

    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True, type=Path)
    ap.add_argument("--model", action="append", required=True, help="name=path (repeatable)")
    ap.add_argument("--beam", type=int, default=5)
    ap.add_argument("--threads", type=int, default=0)
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    rows = list(csv.DictReader((args.data / "metadata.csv").open(encoding="utf-8")))
    if args.limit:
        rows = rows[: args.limit]
    print(f"{len(rows)} utterances")
    for spec in args.model:
        name, _, path = spec.partition("=")
        model = WhisperModel(path, device="cpu", compute_type="int8", cpu_threads=args.threads)
        refs, hyps, groups = [], [], defaultdict(lambda: ([], []))
        audio_seconds, started = 0.0, time.monotonic()
        for row in rows:
            segments, info = model.transcribe(str(args.data / row["file_name"]), language="fa",
                                              beam_size=args.beam, condition_on_previous_text=False)
            hyp = norm(" ".join(s.text for s in segments))
            ref = norm(row["transcription"])
            audio_seconds += info.duration
            if not ref:
                continue
            refs.append(ref)
            hyps.append(hyp)
            g = groups[row.get("dialect") or "unlabelled"]
            g[0].append(ref)
            g[1].append(hyp)
        elapsed = time.monotonic() - started
        print(f"\n== {name} ({path})")
        print(f"   WER {jiwer.wer(refs, hyps):.3f}  CER {jiwer.cer(refs, hyps):.3f}  "
              f"RTF {elapsed / max(audio_seconds, 1e-6):.3f}")
        for dialect, (r, h) in sorted(groups.items()):
            print(f"   [{dialect:>12}] n={len(r):5d}  WER {jiwer.wer(r, h):.3f}  CER {jiwer.cer(r, h):.3f}")


if __name__ == "__main__":
    main()
