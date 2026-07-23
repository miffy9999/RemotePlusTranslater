from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import urllib.request
from dataclasses import dataclass, replace
from pathlib import Path, PurePath
from urllib.parse import urlparse

from .process_cleanup import hidden_subprocess_options

MAX_MANIFEST_BYTES = 256 * 1024
MAX_INSTALLER_BYTES = 4 * 1024 * 1024 * 1024
VERSION = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True, slots=True)
class AvailableUpdate:
    version: str
    mandatory: bool
    minimum_supported_version: str
    filename: str
    url: str
    size: int
    sha256: str


def _require_https_url(value: str, label: str) -> None:
    if value != value.strip() or any(ord(char) < 32 for char in value):
        raise ValueError(f"{label} must be a clean HTTPS URL")
    parsed = urlparse(value)
    try:
        parsed.port
    except ValueError as exc:
        raise ValueError(f"{label} has an invalid port") from exc
    if (
        parsed.scheme.casefold() != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.fragment
    ):
        raise ValueError(f"{label} must use HTTPS without credentials or a fragment")


def _verify_https_response(response, requested_url: str, expected_size: int | None = None) -> None:
    final_url = response.geturl() if hasattr(response, "geturl") else requested_url
    _require_https_url(str(final_url), "Final response URL")
    status = getattr(response, "status", 200)
    if status != 200:
        raise ValueError(f"Update server returned HTTP {status}")
    headers = getattr(response, "headers", None)
    content_length = headers.get("Content-Length") if headers is not None else None
    if content_length is None:
        return
    try:
        declared_size = int(content_length)
    except (TypeError, ValueError) as exc:
        raise ValueError("Update server returned an invalid Content-Length") from exc
    if declared_size < 0 or declared_size > MAX_INSTALLER_BYTES:
        raise ValueError("Update server returned an unsafe Content-Length")
    if expected_size is not None and declared_size != expected_size:
        raise ValueError("Update server Content-Length does not match the manifest")


def _version_tuple(value: str) -> tuple[int, int, int]:
    match = VERSION.fullmatch(value)
    if match is None:
        raise ValueError(f"Invalid release version: {value}")
    return tuple(int(part) for part in match.groups())


def parse_manifest(payload: bytes, expected_channel: str) -> AvailableUpdate:
    if len(payload) > MAX_MANIFEST_BYTES:
        raise ValueError("Update manifest is too large")
    try:
        manifest = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("Update manifest is not valid UTF-8 JSON") from exc
    if manifest.get("schema") != 1 or manifest.get("product") != "RemotePlus Translator":
        raise ValueError("Unsupported update manifest")
    if manifest.get("channel") != expected_channel:
        raise ValueError("Update channel does not match configuration")
    artifact = manifest.get("artifact")
    if not isinstance(artifact, dict):
        raise ValueError("Update manifest has no artifact")
    version = str(manifest.get("version", ""))
    _version_tuple(version)
    minimum_supported_version = str(manifest.get("minimum_supported_version", ""))
    _version_tuple(minimum_supported_version)
    if _version_tuple(minimum_supported_version) > _version_tuple(version):
        raise ValueError("Minimum supported version exceeds the release version")
    filename = str(artifact.get("filename", ""))
    if not filename or PurePath(filename).name != filename or not filename.casefold().endswith(".exe"):
        raise ValueError("Update filename must be a plain EXE name")
    url = str(artifact.get("url", ""))
    _require_https_url(url, "Update artifact URL")
    size = artifact.get("size")
    if isinstance(size, bool) or not isinstance(size, int) or not 0 < size <= MAX_INSTALLER_BYTES:
        raise ValueError("Update artifact size is invalid")
    checksum = str(artifact.get("sha256", "")).casefold()
    if SHA256.fullmatch(checksum) is None:
        raise ValueError("Update artifact SHA-256 is invalid")
    if artifact.get("authenticode_required") is not True:
        raise ValueError("Update artifact must require Authenticode")
    return AvailableUpdate(
        version=version,
        mandatory=manifest.get("mandatory") is True,
        minimum_supported_version=minimum_supported_version,
        filename=filename,
        url=url,
        size=size,
        sha256=checksum,
    )


def check_for_update(
    manifest_url: str,
    current_version: str,
    channel: str,
    timeout_seconds: float,
) -> AvailableUpdate | None:
    _require_https_url(manifest_url, "Update manifest URL")
    request = urllib.request.Request(
        manifest_url,
        headers={"User-Agent": f"RemotePlus-Launcher/{current_version}"},
    )
    with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
        _verify_https_response(response, manifest_url)
        payload = response.read(MAX_MANIFEST_BYTES + 1)
    update = parse_manifest(payload, channel)
    if _version_tuple(update.version) <= _version_tuple(current_version):
        return None
    if _version_tuple(current_version) < _version_tuple(update.minimum_supported_version):
        return replace(update, mandatory=True)
    return update


def _authenticode_identity(path: Path) -> tuple[str, str]:
    powershell = (
        Path(os.environ.get("SystemRoot", r"C:\Windows"))
        / "System32"
        / "WindowsPowerShell"
        / "v1.0"
        / "powershell.exe"
    )
    if os.name != "nt" or not powershell.is_file():
        raise RuntimeError("Authenticode verification is unavailable")
    script = (
        "$s=Get-AuthenticodeSignature -LiteralPath $args[0];"
        "[pscustomobject]@{status=$s.Status.ToString();"
        "thumbprint=$s.SignerCertificate.Thumbprint}|ConvertTo-Json -Compress"
    )
    completed = subprocess.run(
        [str(powershell), "-NoProfile", "-NonInteractive", "-Command", script, str(path)],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
        **hidden_subprocess_options(),
    )
    if completed.returncode != 0:
        raise RuntimeError("Authenticode verification failed to run")
    try:
        result = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError("Authenticode verification returned invalid data") from exc
    return str(result.get("status", "")), str(result.get("thumbprint", ""))


def download_verified_installer(
    update: AvailableUpdate,
    destination_root: Path,
    trusted_thumbprints: list[str],
    timeout_seconds: float,
) -> Path:
    trusted = {value.replace(" ", "").casefold() for value in trusted_thumbprints}
    if not trusted:
        raise ValueError("No trusted update publisher certificate is configured")
    destination_root.mkdir(parents=True, exist_ok=True)
    final = destination_root / update.filename
    temporary = final.with_suffix(final.suffix + ".part")
    temporary.unlink(missing_ok=True)
    digest = hashlib.sha256()
    received = 0
    try:
        request = urllib.request.Request(
            update.url,
            headers={"User-Agent": "RemotePlus-Launcher"},
        )
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            _verify_https_response(response, update.url, update.size)
            with temporary.open("wb") as output:
                while chunk := response.read(1024 * 1024):
                    received += len(chunk)
                    if received > update.size or received > MAX_INSTALLER_BYTES:
                        raise ValueError("Downloaded installer is larger than the manifest")
                    digest.update(chunk)
                    output.write(chunk)
        if received != update.size:
            raise ValueError("Downloaded installer size does not match the manifest")
        if digest.hexdigest() != update.sha256:
            raise ValueError("Downloaded installer SHA-256 does not match the manifest")
        status, thumbprint = _authenticode_identity(temporary)
        if status != "Valid":
            raise ValueError(f"Downloaded installer Authenticode status is {status}")
        if thumbprint.replace(" ", "").casefold() not in trusted:
            raise ValueError("Downloaded installer publisher certificate is not trusted")
        temporary.replace(final)
        return final
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
