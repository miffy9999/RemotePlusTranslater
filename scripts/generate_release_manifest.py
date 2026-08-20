from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote, urljoin, urlparse

from translator_app import __version__


VERSION = re.compile(r"^\d+\.\d+\.\d+$")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def authenticode_status(path: Path) -> str:
    powershell = (
        Path(os.environ.get("SystemRoot", r"C:\Windows"))
        / "System32"
        / "WindowsPowerShell"
        / "v1.0"
        / "powershell.exe"
    )
    if os.name != "nt" or not powershell.is_file():
        return "Unavailable"
    completed = subprocess.run(
        [
            str(powershell),
            "-NoProfile",
            "-NonInteractive",
            "-Command",
            "(Get-AuthenticodeSignature -LiteralPath $args[0]).Status.ToString()",
            str(path.resolve()),
        ],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    if completed.returncode != 0:
        return "Error"
    return completed.stdout.strip() or "UnknownError"


def generate_manifest(
    artifact: Path,
    base_url: str,
    channel: str,
    *,
    version: str = __version__,
    mandatory: bool = False,
    minimum_supported_version: str = "0.7.0",
    require_signature: bool = True,
) -> dict:
    artifact = artifact.resolve()
    if not artifact.is_file():
        raise ValueError(f"Release artifact does not exist: {artifact}")
    if artifact.suffix.casefold() != ".exe":
        raise ValueError("The release artifact must be an Authenticode-signed EXE installer")
    parsed = urlparse(base_url)
    try:
        parsed.port
    except ValueError as exc:
        raise ValueError("base_url has an invalid port") from exc
    if (
        parsed.scheme.casefold() != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.fragment
    ):
        raise ValueError(
            "base_url must be an absolute HTTPS URL without credentials or a fragment"
        )
    if channel not in {"stable", "beta"}:
        raise ValueError("channel must be stable or beta")
    if VERSION.fullmatch(version) is None or VERSION.fullmatch(minimum_supported_version) is None:
        raise ValueError("release versions must use MAJOR.MINOR.PATCH")
    if tuple(map(int, minimum_supported_version.split("."))) > tuple(
        map(int, version.split("."))
    ):
        raise ValueError("minimum_supported_version cannot exceed the release version")
    signature_status = authenticode_status(artifact)
    if require_signature and signature_status != "Valid":
        raise ValueError(f"Authenticode signature is not valid: {signature_status}")
    artifact_url = urljoin(base_url.rstrip("/") + "/", quote(artifact.name))
    return {
        "schema": 1,
        "product": "RemotePlus Translator",
        "channel": channel,
        "version": version,
        "published_at": datetime.now(timezone.utc).isoformat(),
        "mandatory": mandatory,
        "minimum_supported_version": minimum_supported_version,
        "artifact": {
            "filename": artifact.name,
            "url": artifact_url,
            "size": artifact.stat().st_size,
            "sha256": sha256_file(artifact),
            "authenticode_required": True,
            "authenticode_build_status": signature_status,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Create a VPS release manifest")
    parser.add_argument("--artifact", required=True, type=Path)
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--channel", choices=("stable", "beta"), default="stable")
    parser.add_argument("--version", default=__version__)
    parser.add_argument("--minimum-supported-version", default="0.7.0")
    parser.add_argument("--mandatory", action="store_true")
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument(
        "--allow-unsigned-development-build",
        action="store_true",
        help="Only for local tests. Never publish this output as a commercial stable release.",
    )
    args = parser.parse_args()
    manifest = generate_manifest(
        args.artifact,
        args.base_url,
        args.channel,
        version=args.version,
        mandatory=args.mandatory,
        minimum_supported_version=args.minimum_supported_version,
        require_signature=not args.allow_unsigned_development_build,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_suffix(args.output.suffix + ".tmp")
    temporary.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(args.output)
    print(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
