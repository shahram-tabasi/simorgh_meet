# Persian / Kermani STT adaptation toolkit

| Step | Tool | Where |
|---|---|---|
| 1. Export clips + machine transcripts from real meetings (with consent) | `export_dataset.py` | Simorgh server (stdlib only) |
| 2. Correct `metadata.csv` → `transcription`; set `dialect` | spreadsheet / any editor | reviewers |
| 3. Fine-tune Whisper | `finetune_whisper.py` | machine with an NVIDIA GPU (≥16 GB) |
| 4. Convert to CTranslate2 | `../package/convert-stt-model.sh` | any machine with Docker |
| 5. Compare models (WER/CER per dialect, real-time factor) | `evaluate.py` | CPU server |
| 6. Deploy | copy to `/opt/simorgh-meet/models/stt/<name>`, set `STT_MODEL_DIR`, restart `stt ai-worker` | Simorgh server |

```bash
python3 export_dataset.py --stt-dir /var/lib/simorgh-meet/stt --out ./dataset --dialect kermani
```

```bash
python3 finetune_whisper.py --data ./dataset --extra-data ./standard-persian --base vhdm/whisper-large-fa-v1 --out ./ckpt
```

```bash
../package/convert-stt-model.sh ./ckpt/final ./whisper-fa-kermani-ct2
```

```bash
python3 evaluate.py --data ./testset --model base=/opt/simorgh-meet/models/stt/whisper-fa-turbo-ct2 --model kermani=./whisper-fa-kermani-ct2
```

Ship a new model only when Kermani WER improves and standard-Persian WER does not regress.
Details and rationale: [docs/AI-MINUTES-AND-PERSIAN-STT.md](../../docs/AI-MINUTES-AND-PERSIAN-STT.md).
