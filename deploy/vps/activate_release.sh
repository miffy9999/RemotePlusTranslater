#!/usr/bin/env sh
set -eu

if [ "$#" -lt 2 ] || [ "$#" -gt 3 ]; then
    echo "usage: activate_release.sh STAGING_DIR stable|beta [/srv/remoteplus]" >&2
    exit 64
fi

STAGING_DIR=$1
CHANNEL=$2
TARGET_ROOT=${3:-/srv/remoteplus}

case "$CHANNEL" in
    stable|beta) ;;
    *) echo "channel must be stable or beta" >&2; exit 64 ;;
esac
[ "$TARGET_ROOT" = "/srv/remoteplus" ] || [ "${REMOTEPLUS_ALLOW_TEST_ROOT:-0}" = "1" ] || {
    echo "target root must be /srv/remoteplus" >&2
    exit 64
}
[ -d "$STAGING_DIR" ] || { echo "staging directory is missing" >&2; exit 66; }
[ ! -L "$STAGING_DIR" ] || { echo "staging directory cannot be a symlink" >&2; exit 65; }
if find "$STAGING_DIR" -type l -print -quit | grep -q .; then
    echo "staging tree cannot contain symlinks" >&2
    exit 65
fi

MANIFEST="$STAGING_DIR/channels/$CHANNEL/manifest.json"
[ -f "$MANIFEST" ] || { echo "channel manifest is missing: $MANIFEST" >&2; exit 66; }
[ -f "$STAGING_DIR/site/index.html" ] || { echo "site/index.html is missing" >&2; exit 66; }
for required in deployment.json activate_release.sh rollback_channel.sh check_capacity.sh; do
    [ -f "$STAGING_DIR/ops/$required" ] || {
        echo "operations file is missing: ops/$required" >&2
        exit 66
    }
done
if grep -REq '(_HERE\b|\bREPLACE(_|[[:space:]]+WITH\b))' "$STAGING_DIR/site"; then
    echo "site still contains deployment placeholders" >&2
    exit 65
fi

PYTHON_BIN=${PYTHON_BIN:-python3}
if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
    echo "python3 is required on the VPS" >&2
    exit 69
fi

METADATA=$("$PYTHON_BIN" - "$MANIFEST" "$STAGING_DIR" "$CHANNEL" <<'PY'
import hashlib
import json
import pathlib
import re
import sys
from urllib.parse import quote, urlparse

manifest_path = pathlib.Path(sys.argv[1])
staging = pathlib.Path(sys.argv[2])
channel = sys.argv[3]
manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
deployment = json.loads((staging / "ops/deployment.json").read_text(encoding="utf-8"))
if deployment.get("schema") != 1:
    raise SystemExit("unsupported deployment metadata")
if manifest.get("schema") != 1 or manifest.get("product") != "RemotePlus Translator":
    raise SystemExit("unsupported manifest")
if manifest.get("channel") != channel:
    raise SystemExit("manifest channel mismatch")
version = str(manifest.get("version", ""))
if re.fullmatch(r"\d+\.\d+\.\d+", version) is None:
    raise SystemExit("invalid release version")
minimum = str(manifest.get("minimum_supported_version", ""))
if re.fullmatch(r"\d+\.\d+\.\d+", minimum) is None:
    raise SystemExit("invalid minimum supported version")
if tuple(map(int, minimum.split("."))) > tuple(map(int, version.split("."))):
    raise SystemExit("minimum supported version exceeds release version")
if deployment.get("version") != version:
    raise SystemExit("deployment version does not match manifest")
artifact = manifest.get("artifact")
if not isinstance(artifact, dict):
    raise SystemExit("manifest artifact is missing")
filename = str(artifact.get("filename", ""))
if pathlib.PurePath(filename).name != filename or not filename.lower().endswith(".exe"):
    raise SystemExit("invalid artifact filename")
artifact_url = urlparse(str(artifact.get("url", "")))
expected_path = f"/releases/{version}/{quote(filename)}"
if (
    artifact_url.scheme.lower() != "https"
    or artifact_url.hostname != deployment.get("download_domain")
    or artifact_url.username is not None
    or artifact_url.password is not None
    or artifact_url.path != expected_path
    or artifact_url.query
    or artifact_url.fragment
):
    raise SystemExit("artifact URL does not match deployment metadata")
if artifact.get("authenticode_required") is not True:
    raise SystemExit("release artifact must require Authenticode")
source = staging / "releases" / version / filename
if not source.is_file() or source.is_symlink():
    raise SystemExit("release artifact is missing")
if source.stat().st_size != artifact.get("size"):
    raise SystemExit("release artifact size mismatch")
hasher = hashlib.sha256()
with source.open("rb") as stream:
    while chunk := stream.read(1024 * 1024):
        hasher.update(chunk)
digest = hasher.hexdigest()
if digest != str(artifact.get("sha256", "")).lower():
    raise SystemExit("release artifact SHA-256 mismatch")
print(version)
print(filename)
PY
)
VERSION=$(printf '%s\n' "$METADATA" | sed -n '1p')
FILENAME=$(printf '%s\n' "$METADATA" | sed -n '2p')
SOURCE_RELEASE="$STAGING_DIR/releases/$VERSION"
TARGET_RELEASE="$TARGET_ROOT/releases/$VERSION"

umask 027
mkdir -p "$TARGET_ROOT/releases" "$TARGET_ROOT/channels/$CHANNEL"
if [ -e "$TARGET_RELEASE" ]; then
    [ -f "$TARGET_RELEASE/$FILENAME" ] && \
        cmp -s "$SOURCE_RELEASE/$FILENAME" "$TARGET_RELEASE/$FILENAME" || {
        echo "immutable release path already exists with different content" >&2
        exit 73
    }
else
    RELEASE_TMP="$TARGET_ROOT/releases/.${VERSION}.new.$$"
    rm -rf "$RELEASE_TMP"
    mkdir "$RELEASE_TMP"
    cp "$SOURCE_RELEASE/$FILENAME" "$RELEASE_TMP/$FILENAME"
    chmod 0644 "$RELEASE_TMP/$FILENAME"
    mv "$RELEASE_TMP" "$TARGET_RELEASE"
fi

SITE_TMP="$TARGET_ROOT/.site.new.$$"
rm -rf "$SITE_TMP"
mkdir "$SITE_TMP"
cp -R "$STAGING_DIR/site/." "$SITE_TMP/"
find "$SITE_TMP" -type d -exec chmod 0755 {} \;
find "$SITE_TMP" -type f -exec chmod 0644 {} \;
rm -rf "$TARGET_ROOT/site.previous"
if [ -d "$TARGET_ROOT/site" ]; then
    mv "$TARGET_ROOT/site" "$TARGET_ROOT/site.previous"
fi
mv "$SITE_TMP" "$TARGET_ROOT/site"

OPS_TMP="$TARGET_ROOT/.ops.new.$$"
rm -rf "$OPS_TMP"
mkdir "$OPS_TMP"
for name in deployment.json activate_release.sh rollback_channel.sh check_capacity.sh; do
    cp "$STAGING_DIR/ops/$name" "$OPS_TMP/$name"
done
chmod 0644 "$OPS_TMP/deployment.json"
chmod 0750 "$OPS_TMP/"*.sh
rm -rf "$TARGET_ROOT/ops.previous"
if [ -d "$TARGET_ROOT/ops" ]; then
    mv "$TARGET_ROOT/ops" "$TARGET_ROOT/ops.previous"
fi
mv "$OPS_TMP" "$TARGET_ROOT/ops"

CHANNEL_ROOT="$TARGET_ROOT/channels/$CHANNEL"
MANIFEST_TMP="$CHANNEL_ROOT/.manifest.new.$$"
install -m 0644 "$MANIFEST" "$MANIFEST_TMP"
if [ -f "$CHANNEL_ROOT/manifest.json" ]; then
    cp "$CHANNEL_ROOT/manifest.json" "$CHANNEL_ROOT/manifest.previous.json"
fi
mv "$MANIFEST_TMP" "$CHANNEL_ROOT/manifest.json"

echo "activated RemotePlus $VERSION on $CHANNEL"
