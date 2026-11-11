#!/usr/bin/env bash
# Assemble the offline installer from the fetched/built cache:
#   out/simorgh-meet-<ver>.run          single self-extracting installer
#   out/simorgh-meet-<ver>.run.sha256
#   out/simorgh-meet-<ver>.tar.gz       (with --tar) plain archive alternative
# Prerequisites: fetch-artifacts.sh and build-images.sh have been run.
#   tools/package/build-bundle.sh [--no-ai-models] [--tar] [--split 4G]
set -Eeuo pipefail
HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
ROOT=$(cd "$HERE/../.." && pwd)
CACHE=${CACHE:-$HERE/cache}
OUT=${OUT:-$HERE/out}
WITH_MODELS=1; MAKE_TAR=0; SPLIT=''
while [ $# -gt 0 ]; do
  case $1 in
    --no-ai-models) WITH_MODELS=0 ;;
    --tar) MAKE_TAR=1 ;;
    --split) SPLIT=$2; shift ;;
    *) echo "unknown option $1" >&2; exit 2 ;;
  esac; shift
done
# shellcheck source=versions.env
set -a; . "$HERE/versions.env"; set +a
log() { printf '[bundle] %s\n' "$*" >&2; }
die() { printf '[bundle] ERROR: %s\n' "$*" >&2; exit 1; }

NAME="simorgh-meet-${SIMORGH_VERSION}"
STAGE="$OUT/stage/$NAME"
rm -rf "$OUT/stage"; mkdir -p "$STAGE"

# ---- check inputs
[ -f "$CACHE/vendor/docker/docker-${DOCKER_VERSION}.tgz" ] || die "run fetch-artifacts.sh first (docker)"
[ -f "$CACHE/vendor/docker/docker-compose-linux-x86_64" ] || die "run fetch-artifacts.sh first (compose)"
ls "$CACHE"/images/*.tar.gz >/dev/null 2>&1 || die "run build-images.sh first"
for img in simorgh-meet_api_${SIMORGH_VERSION} simorgh-meet_ai_${SIMORGH_VERSION} jitsi_web_${JITSI_IMAGE_VERSION}; do
  [ -f "$CACHE/images/$img.tar.gz" ] || die "missing image export: $img"
done
if [ "$WITH_MODELS" = 1 ]; then
  [ -f "$CACHE/models/stt/$STT_MODEL_DIR/model.bin" ] || [ "$STT_ENGINE" != faster-whisper ] || die "STT model missing (fetch-artifacts.sh --only stt)"
  [ -f "$CACHE/models/llm/$LLM_MODEL_FILE" ] || die "LLM model missing (fetch-artifacts.sh --only llm)"
fi

# ---- payload
log "staging $NAME"
D="$ROOT/deploy/on-premise"
cp -a "$D/install.sh" "$D/answers.example.env" "$D/installer" "$D/compose" "$D/templates" "$D/bin" "$D/systemd" "$STAGE/"
cp -a "$ROOT/docs/ON-PREMISE-INSTALL.md" "$STAGE/README.md"
mkdir -p "$STAGE/vendor/docker" "$STAGE/images"
cp -a "$CACHE/vendor/docker/docker-${DOCKER_VERSION}.tgz" "$CACHE/vendor/docker/docker-compose-linux-x86_64" "$STAGE/vendor/docker/"
cp -a "$CACHE"/images/*.tar.gz "$STAGE/images/"
if [ "$WITH_MODELS" = 1 ]; then
  mkdir -p "$STAGE/models/stt" "$STAGE/models/llm"
  cp -a "$CACHE/models/stt/$STT_MODEL_DIR" "$STAGE/models/stt/"
  cp -a "$CACHE/models/llm/$LLM_MODEL_FILE" "$STAGE/models/llm/"
fi

cat >"$STAGE/manifest.env" <<MANIFEST
BUNDLE_VERSION=${SIMORGH_VERSION}
BUILD_DATE=$(date -u +%FT%TZ)
GIT_COMMIT=$(git -C "$ROOT" rev-parse --short HEAD 2>/dev/null || echo unknown)
DOCKER_VERSION=${DOCKER_VERSION}
COMPOSE_VERSION=${COMPOSE_VERSION}
JITSI_IMAGE_VERSION=${JITSI_IMAGE_VERSION}
POSTGRES_IMAGE_TAG=${POSTGRES_IMAGE_TAG}
KEYCLOAK_IMAGE_TAG=${KEYCLOAK_IMAGE_TAG}
LLAMACPP_IMAGE_TAG=${LLAMACPP_IMAGE_TAG}
COTURN_IMAGE_TAG=${COTURN_IMAGE_TAG}
STT_ENGINE=${STT_ENGINE}
STT_MODEL_DIR=$( [ "$WITH_MODELS" = 1 ] && echo "$STT_MODEL_DIR")
LLM_MODEL_FILE=$( [ "$WITH_MODELS" = 1 ] && echo "$LLM_MODEL_FILE")
MANIFEST
cp "$CACHE/artifacts.lock" "$STAGE/artifacts.lock" 2>/dev/null || true
cp "$CACHE/images.lock" "$STAGE/images.lock" 2>/dev/null || true
chmod +x "$STAGE/install.sh" "$STAGE/bin/simorgh-meet"

log "checksumming payload"
(cd "$STAGE" && find . -type f ! -name SHA256SUMS -print0 | sort -z | xargs -0 sha256sum >SHA256SUMS)

# ---- archive + self-extracting installer
log "compressing (this takes a while for multi-GB models)…"
TARBALL="$OUT/$NAME.tar.gz"
tar -C "$OUT/stage" -cf - "$NAME" | gzip -1 >"$TARBALL"
payload_sha=$(sha256sum "$TARBALL" | cut -d' ' -f1)
size_gb=$(( $(du -sm "$OUT/stage" | cut -f1) / 1024 + 2 ))
header=$(mktemp)
sed -e "s/@@VERSION@@/${SIMORGH_VERSION}/g" -e "s/@@PAYLOAD_SHA256@@/${payload_sha}/" \
    -e "s/@@SIZE_GB@@/${size_gb}/g" "$HERE/run-header.sh" >"$header"
lines=$(( $(wc -l <"$header") + 1 ))
sed -i "s/@@HEADER_LINES@@/${lines}/" "$header"
RUN="$OUT/$NAME.run"
cat "$header" "$TARBALL" >"$RUN"; chmod +x "$RUN"; rm -f "$header"
(cd "$OUT" && sha256sum "$NAME.run" >"$NAME.run.sha256")
[ "$MAKE_TAR" = 1 ] || rm -f "$TARBALL"
if [ -n "$SPLIT" ]; then
  (cd "$OUT" && split -b "$SPLIT" -d -a 2 "$NAME.run" "$NAME.run.part-" && sha256sum "$NAME".run.part-* >"$NAME.parts.sha256")
  log "split into parts; reassemble with: cat $NAME.run.part-* > $NAME.run"
fi
rm -rf "$OUT/stage"
log "done: $RUN ($(du -h "$RUN" | cut -f1))"
