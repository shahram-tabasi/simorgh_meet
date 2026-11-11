#!/usr/bin/env bash
# Build Simorgh images and pull pinned third-party images, then export every image to
# cache/images/<name>.tar.gz for offline `docker load`. Needs Docker + internet (once).
#   tools/package/build-images.sh [--skip-pull]
set -Eeuo pipefail
HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
ROOT=$(cd "$HERE/../.." && pwd)
CACHE=${CACHE:-$HERE/cache}
SKIP_PULL=0; [ "${1:-}" = --skip-pull ] && SKIP_PULL=1
# shellcheck source=versions.env
set -a; . "$HERE/versions.env"; set +a
PLATFORM=linux/amd64
mkdir -p "$CACHE/images"
log() { printf '[images] %s\n' "$*" >&2; }

images_list() {
  local j
  for j in web prosody jicofo jvb jibri jigasi; do echo "jitsi/$j:${JITSI_IMAGE_VERSION}"; done
  echo "postgres:${POSTGRES_IMAGE_TAG}"
  echo "keycloak/keycloak:${KEYCLOAK_IMAGE_TAG}"
  echo "ghcr.io/ggml-org/llama.cpp:${LLAMACPP_IMAGE_TAG}"
  echo "coturn/coturn:${COTURN_IMAGE_TAG}"
  echo "simorgh-meet/api:${SIMORGH_VERSION}"
  echo "simorgh-meet/ai:${SIMORGH_VERSION}"
}

log "building simorgh-meet/api:${SIMORGH_VERSION}"
docker build --platform "$PLATFORM" -t "simorgh-meet/api:${SIMORGH_VERSION}" -f "$ROOT/apps/api/Dockerfile" "$ROOT"
log "building simorgh-meet/ai:${SIMORGH_VERSION}"
docker build --platform "$PLATFORM" -t "simorgh-meet/ai:${SIMORGH_VERSION}" "$ROOT/services/ai"

: >"$CACHE/images.lock"
while read -r image; do
  case $image in simorgh-meet/*) ;; *)
    if [ "$SKIP_PULL" = 0 ] || ! docker image inspect "$image" >/dev/null 2>&1; then
      log "pulling $image"; docker pull --platform "$PLATFORM" "$image" >/dev/null
    fi ;;
  esac
  name=$(echo "$image" | tr '/:' '__')
  out="$CACHE/images/$name.tar.gz"
  id=$(docker image inspect --format '{{.Id}}' "$image")
  if [ -f "$out" ] && [ -f "$out.id" ] && [ "$(cat "$out.id")" = "$id" ]; then
    log "cached export: $name"
  else
    log "exporting $image"
    docker save --platform "$PLATFORM" "$image" | gzip -6 >"$out.part" && mv "$out.part" "$out"
    echo "$id" >"$out.id"
  fi
  digest=$(docker image inspect --format '{{join .RepoDigests ","}}' "$image")
  printf '%s id=%s digests=%s\n' "$image" "$id" "${digest:-local-build}" >>"$CACHE/images.lock"
done < <(images_list)
# Remove exports of images no longer in the list.
for f in "$CACHE"/images/*.tar.gz; do
  base=$(basename "$f" .tar.gz)
  images_list | tr '/:' '__' | grep -qx "$base" || { log "removing stale $base"; rm -f "$f" "$f.id"; }
done
log "done: $(du -sh "$CACHE/images" | cut -f1) in $CACHE/images"
