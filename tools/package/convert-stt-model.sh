#!/usr/bin/env bash
# Convert a Hugging Face Whisper checkpoint (e.g. your Kermani fine-tune) to CTranslate2
# for faster-whisper. Runs in a throw-away container so the build host needs only Docker.
#   tools/package/convert-stt-model.sh <hf-checkpoint-dir> <output-dir> [quantization]
# quantization: float16 (default; loaded as int8 at runtime) | int8
set -Eeuo pipefail
SRC=$(cd "$1" && pwd); OUT=$2; Q=${3:-float16}
mkdir -p "$OUT"; OUT=$(cd "$OUT" && pwd)
docker run --rm -v "$SRC:/in:ro" -v "$OUT:/out" python:3.12-slim-bookworm bash -ec "
  pip install --no-cache-dir -q ctranslate2==4.9.0 'transformers[torch]' --extra-index-url https://download.pytorch.org/whl/cpu
  extra=''
  for f in tokenizer.json preprocessor_config.json; do [ -f /in/\$f ] && extra=\"\$extra \$f\"; done
  ct2-transformers-converter --model /in --output_dir /out --force --quantization $Q \${extra:+--copy_files \$extra}
"
[ -f "$OUT/model.bin" ] || { echo "conversion failed" >&2; exit 1; }
echo "CTranslate2 model written to $OUT"
