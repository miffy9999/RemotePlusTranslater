#!/usr/bin/env sh
set -eu

CHANNEL=${1:-}
TARGET_ROOT=${2:-/srv/remoteplus}
case "$CHANNEL" in
    stable|beta) ;;
    *) echo "usage: rollback_channel.sh stable|beta [/srv/remoteplus]" >&2; exit 64 ;;
esac
[ "$TARGET_ROOT" = "/srv/remoteplus" ] || [ "${REMOTEPLUS_ALLOW_TEST_ROOT:-0}" = "1" ] || {
    echo "target root must be /srv/remoteplus" >&2
    exit 64
}
CHANNEL_ROOT="$TARGET_ROOT/channels/$CHANNEL"
CURRENT="$CHANNEL_ROOT/manifest.json"
PREVIOUS="$CHANNEL_ROOT/manifest.previous.json"
[ -f "$PREVIOUS" ] || { echo "previous manifest is unavailable" >&2; exit 66; }

PYTHON_BIN=${PYTHON_BIN:-python3}
if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
    echo "python3 is required on the VPS" >&2
    exit 69
fi

"$PYTHON_BIN" - "$PREVIOUS" "$TARGET_ROOT" "$CHANNEL" <<'PY'
import json
import hashlib
import pathlib
import re
import sys

value = json.loads(pathlib.Path(sys.argv[1]).read_text(encoding="utf-8"))
if value.get("schema") != 1 or value.get("product") != "RemotePlus Translator":
    raise SystemExit("previous manifest is invalid")
if value.get("channel") != sys.argv[3]:
    raise SystemExit("previous manifest channel is invalid")
version = str(value.get("version", ""))
if re.fullmatch(r"\d+\.\d+\.\d+", version) is None:
    raise SystemExit("previous manifest version is invalid")
artifact = value.get("artifact")
if not isinstance(artifact, dict):
    raise SystemExit("previous manifest artifact is invalid")
filename = str(artifact.get("filename", ""))
if pathlib.PurePath(filename).name != filename or not filename.lower().endswith(".exe"):
    raise SystemExit("previous manifest artifact filename is invalid")
release = pathlib.Path(sys.argv[2]) / "releases" / version / filename
if not release.is_file() or release.is_symlink():
    raise SystemExit("previous release artifact is unavailable")
if release.stat().st_size != artifact.get("size"):
    raise SystemExit("previous release artifact size is invalid")
hasher = hashlib.sha256()
with release.open("rb") as stream:
    while chunk := stream.read(1024 * 1024):
        hasher.update(chunk)
if hasher.hexdigest() != str(artifact.get("sha256", "")).lower():
    raise SystemExit("previous release artifact hash is invalid")
PY

ROLLBACK_TMP="$CHANNEL_ROOT/.manifest.rollback.$$"
install -m 0644 "$PREVIOUS" "$ROLLBACK_TMP"
if [ -f "$CURRENT" ]; then
    cp "$CURRENT" "$CHANNEL_ROOT/manifest.rolled-back.json"
fi
mv "$ROLLBACK_TMP" "$CURRENT"
echo "rolled back channel $CHANNEL"
