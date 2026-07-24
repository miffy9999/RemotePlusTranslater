from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.prepare_vps_deployment import render_deployment
from scripts.verify_vps_release import validate_manifest_headers


ROOT = Path(__file__).resolve().parent.parent


def deployment_profile() -> dict:
    return {
        "site_domain": "remoteplus.hotel-co.jp",
        "download_domain": "download.hotel-co.jp",
        "admin_email": "admin@hotel-co.jp",
        "allowed_cidrs": ["203.0.113.12/32", "10.8.0.1/24"],
        "privacy_url": "https://remoteplus.hotel-co.jp/privacy",
        "publisher_name": "Hotel Operations",
        "support_email": "support@hotel-co.jp",
    }


def test_render_deployment_produces_fail_closed_bundle(tmp_path):
    output = tmp_path / "bundle"
    summary = render_deployment(deployment_profile(), output)

    caddy = (output / "Caddyfile").read_text(encoding="utf-8")
    site = (output / "site/index.html").read_text(encoding="utf-8")
    assert "remote_ip 203.0.113.12/32 10.8.0.0/24" in caddy
    assert 'Strict-Transport-Security "max-age=31536000; includeSubDomains"' in caddy
    assert "_HERE" not in caddy + site
    assert summary["manifest_url"].startswith("https://download.hotel-co.jp/")
    assert (output / "activate_release.sh").is_file()
    assert (output / "rollback_channel.sh").is_file()


@pytest.mark.parametrize("cidr", ["0.0.0.0/0", "::/0", "not-a-network"])
def test_render_deployment_rejects_public_or_invalid_network(tmp_path, cidr):
    profile = deployment_profile()
    profile["allowed_cidrs"] = [cidr]
    with pytest.raises(ValueError, match="CIDR|entire internet"):
        render_deployment(profile, tmp_path / "bundle")


def test_manifest_response_requires_security_headers():
    valid = {
        "Content-Type": "application/json; charset=utf-8",
        "Cache-Control": "no-store",
        "Strict-Transport-Security": "max-age=31536000; includeSubDomains",
        "X-Content-Type-Options": "nosniff",
    }
    validate_manifest_headers(valid)
    for missing in valid:
        headers = valid.copy()
        headers.pop(missing)
        with pytest.raises(ValueError):
            validate_manifest_headers(headers)


def _git_shell() -> Path | None:
    found = shutil.which("sh")
    candidates = [
        Path(found) if found else None,
        Path(r"C:\Program Files\Git\bin\sh.exe"),
    ]
    return next((path for path in candidates if path is not None and path.is_file()), None)


def _posix(path: Path) -> str:
    resolved = path.resolve().as_posix()
    if len(resolved) > 2 and resolved[1] == ":":
        return f"/{resolved[0].lower()}{resolved[2:]}"
    return resolved


def test_server_scripts_parse_and_activate_then_rollback(tmp_path):
    shell = _git_shell()
    if shell is None:
        pytest.skip("POSIX shell is unavailable")
    scripts = ["activate_release.sh", "rollback_channel.sh", "check_capacity.sh"]
    for script in scripts:
        result = subprocess.run(
            [str(shell), "-n", _posix(ROOT / "deploy/vps" / script)],
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, result.stderr

    stage = tmp_path / "stage"
    target = tmp_path / "target"
    site = stage / "site"
    release = stage / "releases/0.8.0"
    channel = stage / "channels/stable"
    ops = stage / "ops"
    site.mkdir(parents=True)
    release.mkdir(parents=True)
    channel.mkdir(parents=True)
    ops.mkdir(parents=True)
    (site / "index.html").write_text("ready", encoding="utf-8")
    artifact = release / "RemotePlusTranslator-Setup-0.8.0.exe"
    artifact.write_bytes(b"signed-development-fixture")
    manifest = {
        "schema": 1,
        "product": "RemotePlus Translator",
        "channel": "stable",
        "version": "0.8.0",
        "minimum_supported_version": "0.7.0",
        "artifact": {
            "filename": artifact.name,
            "url": f"https://download.hotel-co.jp/releases/0.8.0/{artifact.name}",
            "size": artifact.stat().st_size,
            "sha256": hashlib.sha256(artifact.read_bytes()).hexdigest(),
            "authenticode_required": True,
        },
    }
    (ops / "deployment.json").write_text(
        json.dumps(
            {
                "schema": 1,
                "version": "0.8.0",
                "download_domain": "download.hotel-co.jp",
            }
        ),
        encoding="utf-8",
    )
    for name in ("activate_release.sh", "rollback_channel.sh", "check_capacity.sh"):
        shutil.copy2(ROOT / "deploy/vps" / name, ops / name)
    (channel / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    env = os.environ.copy()
    env["REMOTEPLUS_ALLOW_TEST_ROOT"] = "1"
    env["PYTHON_BIN"] = _posix(Path(sys.executable))
    activate = subprocess.run(
        [
            str(shell),
            _posix(ROOT / "deploy/vps/activate_release.sh"),
            _posix(stage),
            "stable",
            _posix(target),
        ],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert activate.returncode == 0, activate.stderr
    assert (target / "site/index.html").read_text(encoding="utf-8") == "ready"
    assert (target / "channels/stable/manifest.json").is_file()

    next_stage = tmp_path / "next-stage"
    shutil.copytree(stage, next_stage)
    next_artifact_dir = next_stage / "releases/0.8.1"
    next_artifact_dir.mkdir()
    next_artifact = next_artifact_dir / "RemotePlusTranslator-Setup-0.8.1.exe"
    next_artifact.write_bytes(b"next-signed-development-fixture")
    manifest["version"] = "0.8.1"
    manifest["artifact"] = {
        "filename": next_artifact.name,
        "url": f"https://download.hotel-co.jp/releases/0.8.1/{next_artifact.name}",
        "size": next_artifact.stat().st_size,
        "sha256": hashlib.sha256(next_artifact.read_bytes()).hexdigest(),
        "authenticode_required": True,
    }
    deployment = json.loads((next_stage / "ops/deployment.json").read_text())
    deployment["version"] = "0.8.1"
    (next_stage / "ops/deployment.json").write_text(
        json.dumps(deployment), encoding="utf-8"
    )
    (next_stage / "channels/stable/manifest.json").write_text(
        json.dumps(manifest), encoding="utf-8"
    )
    activate_next = subprocess.run(
        [
            str(shell),
            _posix(ROOT / "deploy/vps/activate_release.sh"),
            _posix(next_stage),
            "stable",
            _posix(target),
        ],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert activate_next.returncode == 0, activate_next.stderr
    rollback = subprocess.run(
        [
            str(shell),
            _posix(ROOT / "deploy/vps/rollback_channel.sh"),
            "stable",
            _posix(target),
        ],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert rollback.returncode == 0, rollback.stderr
    active = json.loads((target / "channels/stable/manifest.json").read_text())
    assert active["version"] == "0.8.0"
