#!/usr/bin/env python3
"""Fine-tune a Persian Whisper checkpoint on corrected organization / Kermani audio.

Run on a machine with an NVIDIA GPU (≥16 GB VRAM for large-v3-turbo; a few hours for
~20-50 h of audio). The *result* runs on CPU in production after conversion:

  1. python3 export_dataset.py ...                 (on the Simorgh server)
  2. correct metadata.csv "transcription" column   (human review; dialect column)
  3. python3 finetune_whisper.py --data ./dataset --base vhdm/whisper-large-fa-v1 --out ./ckpt
  4. tools/package/convert-stt-model.sh ./ckpt/final ./whisper-fa-kermani-ct2
  5. python3 evaluate.py --data ./testset --model base=... --model kermani=./whisper-fa-kermani-ct2
  6. ship only if WER improves on Kermani AND does not regress on standard Persian;
     then set STT_MODEL_REPO/STT_MODEL_FORMAT in tools/package/versions.env (or copy
     the folder to /opt/simorgh-meet/models/stt/ and set STT_MODEL_DIR in .env).

Mixing in standard-Persian data (e.g. Common Voice fa) at roughly 1:1 with dialect
data prevents catastrophic forgetting. The encoder is frozen for the first epoch
by default, which is the most data-efficient setting for accent adaptation.

  pip install "transformers>=4.46" "datasets>=3" accelerate evaluate jiwer soundfile librosa
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass

import torch


@dataclass
class Collator:
    processor: object
    decoder_start_token_id: int

    def __call__(self, features):
        inputs = [{"input_features": f["input_features"]} for f in features]
        batch = self.processor.feature_extractor.pad(inputs, return_tensors="pt")
        labels = [{"input_ids": f["labels"]} for f in features]
        lab = self.processor.tokenizer.pad(labels, return_tensors="pt")
        ids = lab["input_ids"].masked_fill(lab.attention_mask.ne(1), -100)
        if (ids[:, 0] == self.decoder_start_token_id).all().cpu().item():
            ids = ids[:, 1:]
        batch["labels"] = ids
        return batch


def main() -> None:
    from datasets import Audio, load_dataset
    from transformers import (Seq2SeqTrainer, Seq2SeqTrainingArguments, TrainerCallback,
                              WhisperForConditionalGeneration, WhisperProcessor)
    import evaluate

    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True, help="audiofolder with corrected metadata.csv")
    ap.add_argument("--extra-data", action="append", default=[],
                    help="additional audiofolders (e.g. standard Persian) mixed into training")
    ap.add_argument("--base", default="vhdm/whisper-large-fa-v1")
    ap.add_argument("--out", required=True)
    ap.add_argument("--epochs", type=float, default=3)
    ap.add_argument("--lr", type=float, default=1e-5)
    ap.add_argument("--batch", type=int, default=8)
    ap.add_argument("--grad-accum", type=int, default=2)
    ap.add_argument("--freeze-encoder-epochs", type=float, default=1.0)
    ap.add_argument("--test-size", type=float, default=0.1)
    args = ap.parse_args()

    processor = WhisperProcessor.from_pretrained(args.base, language="persian", task="transcribe")
    model = WhisperForConditionalGeneration.from_pretrained(args.base)
    model.generation_config.language = "persian"
    model.generation_config.task = "transcribe"
    model.generation_config.forced_decoder_ids = None

    from datasets import concatenate_datasets

    parts = [load_dataset("audiofolder", data_dir=d, split="train") for d in [args.data, *args.extra_data]]
    keep = ["audio", "transcription"]
    ds = concatenate_datasets([p.remove_columns([c for c in p.column_names if c not in keep]) for p in parts])
    ds = ds.cast_column("audio", Audio(sampling_rate=16000)).filter(lambda r: bool(r["transcription"].strip()))
    split = ds.train_test_split(test_size=args.test_size, seed=42)

    def prepare(row):
        audio = row["audio"]
        row["input_features"] = processor.feature_extractor(audio["array"], sampling_rate=16000).input_features[0]
        row["labels"] = processor.tokenizer(row["transcription"]).input_ids
        return row

    split = split.map(prepare, remove_columns=split["train"].column_names, num_proc=4)
    wer_metric = evaluate.load("wer")

    def compute_metrics(pred):
        ids = pred.label_ids
        ids[ids == -100] = processor.tokenizer.pad_token_id
        pred_str = processor.batch_decode(pred.predictions, skip_special_tokens=True)
        label_str = processor.batch_decode(ids, skip_special_tokens=True)
        return {"wer": wer_metric.compute(predictions=pred_str, references=label_str)}

    class UnfreezeEncoder(TrainerCallback):
        def on_epoch_begin(self, _args, state, _control, **_kw):
            frozen = state.epoch is not None and state.epoch < args.freeze_encoder_epochs
            for p in model.model.encoder.parameters():
                p.requires_grad = not frozen

    training_args = Seq2SeqTrainingArguments(
        output_dir=args.out,
        per_device_train_batch_size=args.batch,
        per_device_eval_batch_size=args.batch,
        gradient_accumulation_steps=args.grad_accum,
        learning_rate=args.lr,
        warmup_ratio=0.1,
        num_train_epochs=args.epochs,
        gradient_checkpointing=True,
        fp16=torch.cuda.is_available(),
        eval_strategy="epoch",
        save_strategy="epoch",
        save_total_limit=2,
        load_best_model_at_end=True,
        metric_for_best_model="wer",
        greater_is_better=False,
        predict_with_generate=True,
        generation_max_length=225,
        logging_steps=25,
        report_to=[],
    )
    trainer = Seq2SeqTrainer(
        model=model,
        args=training_args,
        train_dataset=split["train"],
        eval_dataset=split["test"],
        data_collator=Collator(processor, model.config.decoder_start_token_id),
        compute_metrics=compute_metrics,
        processing_class=processor.feature_extractor,
        callbacks=[UnfreezeEncoder()],
    )
    trainer.train()
    final = f"{args.out}/final"
    trainer.save_model(final)
    processor.save_pretrained(final)
    print(f"saved {final}; next: tools/package/convert-stt-model.sh {final} <ct2-out-dir>")


if __name__ == "__main__":
    main()
