# صورت‌جلسه خودکار با هوش مصنوعی و تبدیل گفتار فارسی (کرمانی) — طراحی و پژوهش

**Status:** Implemented (`services/ai`), verified end-to-end against a live Jitsi `stable-11031`
deployment with a mock STT engine and a mock LLM. Real-model accuracy must still be measured on
the organization's own audio (section 5).

---

## 1. Pipeline

```
 Jitsi conference
   │  host clicks "Start transcription"  (Jicofo invites the hidden "Transcriber")
   ▼
 Jigasi (transcriber) ── one WebSocket per meeting ──►  simorgh-ai stt-server
   - receives EVERY participant's audio separately          - per-speaker utterance segmentation
   - frame = 60-byte header "<participant>|<lang>" + PCM     - faster-whisper (CPU, int8), beam 1 live
   - 16 kHz s16le, ~1.5 s chunks, nothing during silence     - returns live captions to Jitsi
   - writes final transcript JSON (room, names, join/leave)   - stores segments.jsonl + 16 kHz WAV per speaker
   ▼                                                          ▼
 ai-worker (after the meeting ends)
   1. match Jigasi JSON ⇄ STT session by participant ids → real display names, room name
   2. refine: re-decode each utterance from the stored audio with beam 5 (optionally a larger model)
   3. resolve room → meeting (scheduled meeting, or permanent room → ad-hoc meeting record)
   4. LLM (llama.cpp, OpenAI-compatible API, JSON-schema constrained output, Persian prompt)
        short meeting: single pass; long meeting: map (notes per chunk) → reduce (final minutes)
   5. sanitize: owners snapped to real attendee names, invalid/past deadlines dropped, Jalali dates
   6. persist: transcription_sessions, transcript_segments, meeting_minutes (draft, versioned),
      action_items (linked to members when the name matches), audit_events
      + files: minutes/<room>/<time>/{minutes.md, minutes.json, transcript.txt, transcript.json}
 Fallback: a Jibri recording without a live transcript is transcribed offline (no speaker names).
 Regenerate: INSERT a background_jobs row kind='minutes.generate' (CLI: simorgh-meet minutes regenerate).
```

**Why Jigasi per-speaker streams instead of transcribing the recording:** each participant's audio
arrives separately, so "who said what" is exact without speaker diarization (which is slow on CPU
and unreliable for overlapping Persian speech). It also gives live Persian captions for free.

### Facts verified on a live deployment (they shaped the implementation)

| Observation | Consequence in code |
|---|---|
| Jigasi sends **16 kHz** PCM (a 300 Hz test tone measured exactly 300 Hz at 16 kHz) | `STT_INPUT_SAMPLE_RATE=16000` default (configurable) |
| No packets during pauses (WebRTC Opus DTX): the stream contains only voiced audio | utterances end on **arrival gaps**; wall-clock anchors map stream offsets to real time |
| Frames are 48 000 bytes ≈ 1.5 s | endpointing granularity ≈ 1.5 s (fine for minutes) |
| Jigasi's language tag follows the UI language (often `en`) | `STT_FORCE_LANGUAGE=1` decodes everything as Persian |
| Upstream `stable-11031` hard-codes `SAVE_JSON=false` | `11-simorgh-transcripts` cont-init hook appends `SAVE_JSON=true` |
| `variance` must be a JSON float (Jigasi casts to `double`) | `protocol.result_message` always emits a float |
| Jicofo's `focus` appears as a participant | filtered out of attendees |

---

## 2. Speech-to-text model selection (Persian, CPU only)

Requirement: accurate Persian (including regional accents, especially Kermani), real-time on CPU,
fully offline, permissive licence.

| Candidate | Type | Reported accuracy | CPU fit | Notes |
|---|---|---|---|---|
| **vhdm/whisper-large-fa-v1** (CT2 conversion: **parseh/whisper-fa-fast-ct2**) | Whisper large-v3-turbo fine-tuned on Persian | ~14 % WER on clean Persian (model card) | Good: turbo has a 4-layer decoder; int8 via CTranslate2 | **Default.** Card warns accented/dialectal speech is less reliable → fine-tune (section 4). Verify licence before commercial use. |
| givia/whisper-large-v3-turbo-persian | Whisper turbo, full fine-tune, ~236 h openly licensed Persian | — | Same as above; ships whisper.cpp/GGML too | Good alternative base for fine-tuning. |
| MohammadGholizadeh/whisper-large-v3-turbo-persian | Whisper turbo fine-tune | Common Voice 17 fa: 50.2 % → 19.4 % WER | Needs CT2 conversion (`convert-stt-model.sh`) | Alternative. |
| nvidia/stt_fa_fastconformer_hybrid_large | NeMo FastConformer (RNNT/CTC), Common Voice fa | ~13–15 % WER on NVIDIA's CV-15 split | **Fastest** on CPU via sherpa-onnx (needs ONNX export) | Engine supported (`STT_ENGINE=sherpa-onnx`); weaker on spontaneous/meeting speech (read-speech training data). |
| Shenava (PersianML/Reza2kn) | FastConformer derivatives, sherpa-onnx bundles | self-reported 7.5 % WER (golden set), 10.6 % FLEURS-fa | Very small/fast | Promising for live captions; numbers not independently verified. |
| Vosk fa | Kaldi | weakest in PSRB accent tests | Very fast | Not recommended. |

**Benchmark evidence for accents.** The PSRB benchmark (PartAI, 2025) evaluates ten ASR systems on
12 Persian accents **including Kermani**. It reports that all models do well on standard Persian but
degrade on regional accents; Kermani error rates in its accent table range from ~18 % (best commercial
system) to ~55 % (Vosk), mean ~32 %. A public subset is available as `PartAI/PSRB` on Hugging Face and
is the recommended **Kermani evaluation set**. **There is no public Kermani-specific model or training
corpus**, so Kermani accuracy has to come from adapting a strong Persian model on in-house data.

**Why faster-whisper by default:** best open Persian accuracy on conversational speech today, punctuation
and casing for free, int8 CTranslate2 runs ~real-time on 2–4 cores per active speaker, and the same model
serves live captions (beam 1) and the higher-quality refine pass (beam 5).

Configuration (in `/opt/simorgh-meet/.env`):

| Variable | Default | Purpose |
|---|---|---|
| `STT_ENGINE` | `faster-whisper` | or `sherpa-onnx` |
| `STT_MODEL_DIR` / `STT_REFINE_MODEL_PATH` | bundled model / empty | live model; optional bigger model for the refine pass |
| `STT_WORKERS`, `STT_CPU_THREADS`, `STT_CPU_LIMIT` | sized by installer | concurrency vs. CPU |
| `STT_LIVE_BEAM_SIZE` / `STT_FINAL_BEAM_SIZE` | 1 / 5 | speed vs. accuracy |
| `STT_HOTWORDS` | empty | names/terms biased during decoding (comma separated) |
| `STT_PARTIAL_INTERVAL_S` | 0 | >0 enables interim captions (costs CPU) |
| `STT_MIN_SILENCE_MS` | 700 | pause that ends an utterance |

---

## 3. Minutes LLM (CPU)

**Default: Qwen3.5-9B (Apache-2.0), GGUF Q4_K_M, llama.cpp server.** Community Persian evaluations in
2026 rank Qwen3.5-9B and Gemma 3 12B as the strongest local models for Persian writing/summarization;
Dorna2-8B is the main Persian-specific option. These rankings come from blog benchmarks, not peer-review,
so the choice is configurable (`LLM_GGUF_REPO`, `LLM_GGUF_PATTERN` in `tools/package/versions.env`):

| Model | Licence | RAM (Q4) | Comment |
|---|---|---|---|
| **Qwen3.5-9B** | Apache-2.0 | ~6–7 GB | default; good Persian, JSON-schema friendly, thinking disabled via `chat_template_kwargs` |
| Gemma 3 12B | Gemma terms | ~8–9 GB | strong Persian knowledge; check licence terms |
| Dorna2 8B (PartAI) | check card | ~6 GB | Persian-optimized |

Quality controls built into the pipeline:
- System prompt in Persian: formal standard Persian output, **never invent** facts/owners/dates,
  convert dialect/colloquial speech to formal Persian, decisions ≠ suggestions, ISO + verbatim deadlines.
- Output constrained by **JSON schema** (llama.cpp grammar) with a tolerant parser and one retry.
- Map-reduce for long meetings (`LLM_CHUNK_CHARS`), so a 2-hour meeting fits an 8–16 k context.
- Post-validation: owners snapped to real attendee names, deadlines before the meeting dropped,
  priorities normalized, `review_required: true` — minutes are **drafts** until a human approves.
- Organization glossary (`simorgh-meet glossary add …`) is injected into the prompt so names and
  local terms are spelled correctly.

Expected latency (planning estimate for 16 cores/AVX2, to be measured): a 1-hour meeting (~8–10 k words)
→ minutes ready roughly 5–15 minutes after the meeting ends.

---

## 4. Kermani dialect plan (برنامه گویش کرمانی)

1. **Baseline (day 1):** bundled Persian Whisper-turbo + glossary + LLM instructed to normalize dialect.
2. **Measure:** `tools/stt-finetune/evaluate.py` on (a) PSRB Kermani subset, (b) 1–2 hours of the
   organization's own recorded meetings, transcribed by staff. Track WER/CER per dialect.
3. **Data flywheel (with consent):** every meeting already stores per-speaker 16 kHz audio and
   time-aligned text. `export_dataset.py` cuts clips + machine text → staff correct `metadata.csv`
   (mark `dialect=kermani`). Correcting machine text is ~3–5× faster than transcribing from scratch.
4. **Fine-tune** (`finetune_whisper.py`, on any machine with a 16 GB+ GPU; hours, not days):
   start from the Persian checkpoint, mix Kermani and standard Persian ~1:1 to avoid forgetting,
   freeze the encoder for the first epoch. Target 20–50 h of corrected Kermani speech for a
   substantial gain; even 5–10 h usually helps accent adaptation.
5. **Convert & gate:** `tools/package/convert-stt-model.sh` → CT2; ship only if Kermani WER improves
   **and** standard Persian does not regress (`evaluate.py --model base=… --model kermani=…`).
6. **Deploy offline:** copy the model folder to `/opt/simorgh-meet/models/stt/<name>/`, set
   `STT_MODEL_DIR=<name>` in `.env`, `simorgh-meet restart stt ai-worker` — or rebuild the bundle with
   `STT_MODEL_REPO`/`STT_MODEL_FORMAT` pointing to it.

---

## 5. Acceptance checklist before production use

- [ ] WER/CER of the bundled model on ≥1 h of the organization's real meetings (standard + Kermani).
- [ ] Minutes reviewed by 2–3 meeting secretaries on ≥10 real meetings (precision of decisions/actions).
- [ ] CPU load measured with the expected number of simultaneous speakers and meetings.
- [ ] Licences of the selected STT and LLM checkpoints confirmed for the intended use.

## 6. Privacy

- Everything runs on the customer's server; models load with `HF_HUB_OFFLINE=1`; no network egress needed.
- Transcription starts only when a host requests it (visible to all participants in Jitsi).
- Per-speaker audio is kept 30 days for the refine pass/dataset export, then deleted by the daily timer.
- Jigasi transcript files are not served over HTTP (`/transcripts/` is blocked in nginx).
- Use audio for model training only with documented participant consent.

## Sources

- Jigasi `WhisperWebsocket.java` / `LocalJsonTranscriptHandler.java` (github.com/jitsi/jigasi), jitsi/skynet streaming_whisper, docker-jitsi-meet `stable-11031`.
- [vhdm/whisper-large-fa-v1](https://huggingface.co/vhdm/whisper-large-fa-v1), [parseh/whisper-fa-fast-ct2](https://huggingface.co/parseh/whisper-fa-fast-ct2), [givia/whisper-large-v3-turbo-persian](https://huggingface.co/givia/whisper-large-v3-turbo-persian), [MohammadGholizadeh/whisper-large-v3-turbo-persian](https://huggingface.co/MohammadGholizadeh/whisper-large-v3-turbo-persian)
- [nvidia/stt_fa_fastconformer_hybrid_large](https://huggingface.co/nvidia/stt_fa_fastconformer_hybrid_large), [PersianML/Shenava-Koochik-v1.0](https://huggingface.co/PersianML/Shenava-Koochik-v1.0)
- [PSRB: A Comprehensive Benchmark for Evaluating Persian ASR Systems (arXiv 2505.21230)](https://arxiv.org/abs/2505.21230)
- [Qwen/Qwen3.5-9B](https://huggingface.co/Qwen/Qwen3.5-9B), [Persian AI in 2026: local models](https://hussain-nazary.github.io/persian-ai-2026-local-models.html)
