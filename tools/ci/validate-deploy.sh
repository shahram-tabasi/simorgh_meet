#!/usr/bin/env bash
# Render a complete On-Premise configuration from answers.example.env into a temp dir
# (no root, no Docker daemon changes) and validate the merged compose stack.
# Used by CI; handy locally after editing installer/compose files.
# shellcheck disable=SC2034  # variables below are consumed by the sourced installer libraries
set -Eeuo pipefail
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT

BUNDLE_DIR="$ROOT/deploy/on-premise"
SIMORGH_HOME="$WORK/opt"
LOG_FILE="$WORK/install.log"
mkdir -p "$SIMORGH_HOME"
# shellcheck source=../../deploy/on-premise/installer/lib/common.sh
. "$BUNDLE_DIR/installer/lib/common.sh"
# shellcheck source=../../deploy/on-premise/installer/lib/wizard.sh
. "$BUNDLE_DIR/installer/lib/wizard.sh"
# shellcheck source=../../deploy/on-premise/installer/lib/render.sh
. "$BUNDLE_DIR/installer/lib/render.sh"
# shellcheck disable=SC2034  # consumed by the sourced libraries
NONINTERACTIVE=1
# shellcheck source=../../deploy/on-premise/answers.example.env
. "$BUNDLE_DIR/answers.example.env"
set -a
# shellcheck source=../package/versions.env
. "$ROOT/tools/package/versions.env"
set +a
DATA_DIR="$WORK/data"
BUNDLE_VERSION=$SIMORGH_VERSION
LLM_MODEL_FILE=${LLM_MODEL_FILE:-minutes-llm.gguf}
EXTERNAL_GUESTS=1 PUBLIC_IP=203.0.113.10 ENABLE_TURN=1

chown() { :; }  # not root in CI
wizard >/dev/null
ensure_secrets
render_env
render_configs
render_certificates >/dev/null
save_answers

cp -a "$BUNDLE_DIR/compose" "$SIMORGH_HOME/compose"
compose() {
  docker compose --project-directory "$SIMORGH_HOME/compose" --env-file "$SIMORGH_HOME/.env" \
    -f "$SIMORGH_HOME/compose/jitsi/docker-compose.yml" -f "$SIMORGH_HOME/compose/jitsi/jibri.yml" \
    -f "$SIMORGH_HOME/compose/jitsi/transcriber.yml" -f "$SIMORGH_HOME/compose/simorgh.yml" "$@"
}
warnings=$(compose config -q 2>&1 || true)
[ -z "$warnings" ] || { echo "$warnings" >&2; echo "compose config produced warnings/errors" >&2; exit 1; }
services=$(compose config --services | sort | tr '\n' ' ')
expected="ai-worker api coturn jibri jicofo jvb keycloak llm postgres prosody stt transcriber web "
[ "$services" = "$expected" ] || { echo "unexpected services: $services" >&2; exit 1; }
grep -q '^JIGASI_TRANSCRIBER_WHISPER_URL=ws://stt:8000/ws$' "$SIMORGH_HOME/.env"
grep -q '^COMPOSE_PROFILES=recording,ai,idp,turn$' "$SIMORGH_HOME/.env"
python3 -c "import json,sys; json.load(open(sys.argv[1]))" "$SIMORGH_HOME/config/keycloak/simorgh-realm.json"
openssl verify -CAfile "$SIMORGH_HOME/pki/ca.crt" "$SIMORGH_HOME/pki/server.crt" >/dev/null
echo "deploy configuration valid: $services"
