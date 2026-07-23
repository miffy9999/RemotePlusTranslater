from __future__ import annotations

import argparse
import json
import tempfile
import urllib.request
from pathlib import Path

from translator_app.app_updates import (
    MAX_MANIFEST_BYTES,
    _require_https_url,
    _verify_https_response,
    download_verified_installer,
    parse_manifest,
)


def validate_manifest_headers(headers) -> None:
    content_type = str(headers.get("Content-Type", "")).casefold()
    cache_control = str(headers.get("Cache-Control", "")).casefold()
    hsts = str(headers.get("Strict-Transport-Security", "")).casefold()
    nosniff = str(headers.get("X-Content-Type-Options", "")).casefold()
    if "application/json" not in content_type:
        raise ValueError("Manifest response must use application/json")
    if "no-store" not in cache_control:
        raise ValueError("Manifest response must disable caching with no-store")
    if "max-age=" not in hsts:
        raise ValueError("Manifest response must enable HSTS")
    if nosniff != "nosniff":
        raise ValueError("Manifest response must enable X-Content-Type-Options: nosniff")


def verify_live_release(
    manifest_url: str,
    channel: str,
    thumbprints: list[str],
    *,
    manifest_only: bool,
    timeout_seconds: float,
) -> dict:
    _require_https_url(manifest_url, "Manifest URL")
    request = urllib.request.Request(
        manifest_url,
        headers={"User-Agent": "RemotePlus-VPS-Verifier/1"},
    )
    with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
        _verify_https_response(response, manifest_url)
        validate_manifest_headers(response.headers)
        payload = response.read(MAX_MANIFEST_BYTES + 1)
    update = parse_manifest(payload, channel)
    downloaded = False
    if not manifest_only:
        if not thumbprints:
            raise ValueError("At least one trusted publisher thumbprint is required")
        with tempfile.TemporaryDirectory(prefix="remoteplus-verify-") as temporary:
            download_verified_installer(
                update,
                Path(temporary),
                thumbprints,
                timeout_seconds,
            )
        downloaded = True
    return {
        "channel": channel,
        "version": update.version,
        "manifest_url": manifest_url,
        "artifact_url": update.url,
        "artifact_verified": downloaded,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify a live RemotePlus VPS release")
    parser.add_argument("--manifest-url", required=True)
    parser.add_argument("--channel", choices=("stable", "beta"), default="stable")
    parser.add_argument("--trusted-thumbprint", action="append", default=[])
    parser.add_argument("--manifest-only", action="store_true")
    parser.add_argument("--timeout-seconds", type=float, default=60)
    args = parser.parse_args()
    result = verify_live_release(
        args.manifest_url,
        args.channel,
        args.trusted_thumbprint,
        manifest_only=args.manifest_only,
        timeout_seconds=args.timeout_seconds,
    )
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
