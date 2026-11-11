#!/usr/bin/env bash
# Download every binary artifact the offline bundle needs, ONCE, into a local cache:
#   cache/vendor/docker/   docker-<ver>.tgz, docker-compose-linux-x86_64
#   cache/models/stt/<dir> CTranslate2 Whisper model (Persian)
#   cache/models/llm/      GGUF model for the minutes LLM
#   cache/artifacts.lock   exact URLs, revisions and SHA-256 of what was fetched
#
# Re-running is cheap: files already present with the recorded checksum are skipped.
# Usage: tools/package/fetch-artifacts.sh [--only docker|stt|llm] [--cache DIR]
# Env:   HF_TOKEN (optional, for gated/rate-limited downloads), HF_ENDPOINT (mirror)
set -Eeuo pipefail

HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
CACHE=${CACHE:-$HERE/cache}
ONLY=''
while [ $# -gt 0 ]; do
  case $1 in
    --only) ONLY=$2; shift 2 ;;
    --cache) CACHE=$2; shift 2 ;;
    *) echo "unknown option $1" >&2; exit 2 ;;
  esac
done

# shellcheck source=versions.env
set -a; . "$HERE/versions.env"; set +a
HF_ENDPOINT=${HF_ENDPOINT:-https://huggingface.co}
LOCK="$CACHE/artifacts.lock"
mkdir -p "$CACHE/vendor/docker" "$CACHE/models/stt" "$CACHE/models/llm"
touch "$LOCK"

log() { printf '[fetch] %s\n' "$*" >&2; }
die() { printf '[fetch] ERROR: %s\n' "$*" >&2; exit 1; }

lock_set() { # key value
  grep -v "^$1=" "$LOCK" >"$LOCK.tmp" || true
  printf '%s=%s\n' "$1" "$2" >>"$LOCK.tmp"
  sort "$LOCK.tmp" >"$LOCK"; rm -f "$LOCK.tmp"
}
lock_get() { grep -E "^$1=" "$LOCK" | tail -n1 | cut -d= -f2- || true; }

sha() { sha256sum "$1" | awk '{print $1}'; }

curl_auth=()
[ -n "${HF_TOKEN:-}" ] && curl_auth=(-H "Authorization: Bearer ${HF_TOKEN}")

download() { # url dest [expected_sha256] [hf]
  local url=$1 dest=$2 expected=${3:-} hf=${4:-}
  if [ -f "$dest" ] && [ -n "$expected" ] && [ "$(sha "$dest")" = "$expected" ]; then
    log "cached: $(basename "$dest")"; return 0
  fi
  log "downloading $url"
  local extra=(); [ -n "$hf" ] && extra=("${curl_auth[@]}")
  curl -fL --progress-bar --retry 5 --retry-delay 3 --retry-all-errors -C - "${extra[@]}" -o "$dest.part" "$url" \
    || die "download failed: $url"
  mv "$dest.part" "$dest"
  if [ -n "$expected" ]; then
    [ "$(sha "$dest")" = "$expected" ] || die "checksum mismatch for $dest"
  fi
}

fetch_docker() {
  local tgz="$CACHE/vendor/docker/docker-${DOCKER_VERSION}.tgz"
  download "$DOCKER_STATIC_URL" "$tgz" "$(lock_get "docker.tgz.sha256")"
  tar -tzf "$tgz" docker/dockerd >/dev/null || die "invalid docker archive"
  lock_set docker.url "$DOCKER_STATIC_URL"
  lock_set docker.tgz.sha256 "$(sha "$tgz")"

  local bin="$CACHE/vendor/docker/docker-compose-linux-x86_64"
  local expected
  expected=$(curl -fsSL --retry 3 "${COMPOSE_URL}.sha256" | awk '{print $1}') || die "cannot fetch compose checksum"
  download "$COMPOSE_URL" "$bin" "$expected"
  chmod +x "$bin"
  lock_set compose.url "$COMPOSE_URL"
  lock_set compose.sha256 "$expected"
  log "docker ${DOCKER_VERSION} + compose ${COMPOSE_VERSION} ready"
}

# hf_files REPO REVISION -> lines "path<TAB>size<TAB>sha256-or-empty" (sha256 for LFS files)
hf_files() {
  curl -fsSL "${curl_auth[@]}" "${HF_ENDPOINT}/api/models/$1/tree/$2?recursive=true" \
    | python3 -c '
import json, sys
for f in json.load(sys.stdin):
    if f.get("type") != "file":
        continue
    lfs = f.get("lfs") or {}
    print(f.get("path"), f.get("size", 0), lfs.get("oid", ""), sep="\t")
'
}

hf_commit() {
  curl -fsSL "${curl_auth[@]}" "${HF_ENDPOINT}/api/models/$1/revision/$2" \
    | python3 -c 'import json,sys; print(json.load(sys.stdin)["sha"])'
}

fetch_hf_snapshot() { # repo revision dest_dir
  local repo=$1 rev=$2 dest=$3 commit path size oid
  commit=$(hf_commit "$repo" "$rev") || die "cannot resolve $repo@$rev (network/HF_TOKEN/HF_ENDPOINT?)"
  log "$repo @ $commit"
  mkdir -p "$dest"
  while IFS=$'\t' read -r path size oid; do
    case $path in .gitattributes|*.md|*.png|*.jpg) continue ;; esac
    mkdir -p "$dest/$(dirname "$path")"
    download "${HF_ENDPOINT}/$repo/resolve/$commit/$path" "$dest/$path" "$oid" hf
  done < <(hf_files "$repo" "$commit")
  printf '%s\n' "$commit"
}

fetch_stt() {
  local dest="$CACHE/models/stt/$STT_MODEL_DIR" commit
  if [ "$STT_MODEL_FORMAT" = ct2 ]; then
    commit=$(fetch_hf_snapshot "$STT_MODEL_REPO" "$STT_MODEL_REVISION" "$dest" | tail -n1)
    [ -f "$dest/model.bin" ] || die "$STT_MODEL_REPO is not a CTranslate2 model (model.bin missing); set STT_MODEL_FORMAT=transformers"
  else
    local raw="$CACHE/models/_hf/${STT_MODEL_REPO//\//__}"
    commit=$(fetch_hf_snapshot "$STT_MODEL_REPO" "$STT_MODEL_REVISION" "$raw" | tail -n1)
    "$HERE/convert-stt-model.sh" "$raw" "$dest"
  fi
  lock_set stt.repo "$STT_MODEL_REPO"
  lock_set stt.commit "$commit"
  lock_set stt.dir "$STT_MODEL_DIR"
  log "STT model ready: $dest ($(du -sh "$dest" | cut -f1))"
}

fetch_llm() {
  local commit file size oid dest="$CACHE/models/llm/$LLM_MODEL_FILE"
  commit=$(hf_commit "$LLM_GGUF_REPO" "$LLM_GGUF_REVISION") || die "cannot resolve $LLM_GGUF_REPO"
  # shellcheck disable=SC2254
  while IFS=$'\t' read -r file size oid; do
    case $(basename "$file") in $LLM_GGUF_PATTERN) break ;; esac
    file=''
  done < <(hf_files "$LLM_GGUF_REPO" "$commit")
  [ -n "$file" ] || die "no file matching '$LLM_GGUF_PATTERN' in $LLM_GGUF_REPO (split GGUFs are not supported; pick a single-file quant)"
  log "LLM: $LLM_GGUF_REPO/$file ($((size / 1024 / 1024)) MiB) @ $commit"
  download "${HF_ENDPOINT}/$LLM_GGUF_REPO/resolve/$commit/$file" "$dest" "$oid" hf
  lock_set llm.repo "$LLM_GGUF_REPO"
  lock_set llm.commit "$commit"
  lock_set llm.source_file "$file"
  lock_set llm.sha256 "$oid"
  log "LLM model ready: $dest"
}

case $ONLY in
  '') fetch_docker; fetch_stt; fetch_llm ;;
  docker) fetch_docker ;;
  stt) fetch_stt ;;
  llm) fetch_llm ;;
  *) die "--only must be docker|stt|llm" ;;
esac
log "artifacts lock: $LOCK"
