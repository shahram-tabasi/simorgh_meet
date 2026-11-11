#!/bin/sh
# Simorgh Meet self-extracting offline installer.
#   sudo sh simorgh-meet-@@VERSION@@.run                     extract + run installer (interactive)
#   sudo sh simorgh-meet-@@VERSION@@.run --answers FILE      unattended
#   sh simorgh-meet-@@VERSION@@.run --extract-only DIR       just unpack
#   sh simorgh-meet-@@VERSION@@.run --verify                 check payload checksum
set -eu
PAYLOAD_SHA256=@@PAYLOAD_SHA256@@
SKIP=@@HEADER_LINES@@
SELF=$0
payload() { tail -n +"$SKIP" "$SELF"; }

case "${1:-}" in
  --verify)
    echo "Verifying payload…"
    [ "$(payload | sha256sum | cut -d' ' -f1)" = "$PAYLOAD_SHA256" ] && { echo OK; exit 0; } || { echo "CORRUPTED"; exit 1; } ;;
  --extract-only)
    DEST=${2:?destination directory required}; mkdir -p "$DEST"
    payload | tar -xzf - -C "$DEST"; echo "Extracted to $DEST"; exit 0 ;;
esac

[ "$(id -u)" -eq 0 ] || { echo "Run as root: sudo sh $SELF" >&2; exit 1; }
BASE=${TMPDIR:-/var/tmp}
FREE=$(df -Pk "$BASE" | awk 'NR==2 {print int($4/1024/1024)}')
echo "Extracting installer to $BASE (needs ~@@SIZE_GB@@ GB, free ${FREE} GB)…"
[ "$FREE" -ge @@SIZE_GB@@ ] || { echo "Not enough space in $BASE; set TMPDIR=/path/with/space" >&2; exit 1; }
WORK=$(mktemp -d "$BASE/simorgh-meet-install.XXXXXX")
trap 'rm -rf "$WORK"' EXIT INT TERM
payload | tar -xzf - -C "$WORK"
cd "$WORK/simorgh-meet-@@VERSION@@"
bash ./install.sh "$@"
exit $?
__PAYLOAD_BELOW__
