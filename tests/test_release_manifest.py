import hashlib

import pytest

from scripts.generate_release_manifest import generate_manifest


def test_release_manifest_has_immutable_https_artifact_metadata(tmp_path, monkeypatch):
    artifact = tmp_path / "RemotePlus Translator Setup.exe"
    artifact.write_bytes(b"signed installer")
    monkeypatch.setattr(
        "scripts.generate_release_manifest.authenticode_status", lambda _path: "Valid"
    )

    manifest = generate_manifest(
        artifact,
        "https://download.example.com/releases/0.7.0/",
        "stable",
    )

    assert manifest["schema"] == 1
    assert manifest["channel"] == "stable"
    assert manifest["artifact"]["url"].endswith("RemotePlus%20Translator%20Setup.exe")
    assert manifest["artifact"]["sha256"] == hashlib.sha256(b"signed installer").hexdigest()
    assert manifest["artifact"]["authenticode_build_status"] == "Valid"


def test_release_manifest_rejects_unsafe_urls_versions_and_unsigned_builds(
    tmp_path, monkeypatch
):
    artifact = tmp_path / "setup.exe"
    artifact.write_bytes(b"installer")
    monkeypatch.setattr(
        "scripts.generate_release_manifest.authenticode_status", lambda _path: "NotSigned"
    )

    with pytest.raises(ValueError, match="HTTPS"):
        generate_manifest(artifact, "http://download.example.com", "stable")
    with pytest.raises(ValueError, match="credentials"):
        generate_manifest(
            artifact, "https://user:secret@download.example.com", "stable"
        )
    with pytest.raises(ValueError, match="MAJOR.MINOR.PATCH"):
        generate_manifest(
            artifact, "https://download.example.com", "stable", version="next"
        )
    with pytest.raises(ValueError, match="cannot exceed"):
        generate_manifest(
            artifact,
            "https://download.example.com",
            "stable",
            version="0.8.0",
            minimum_supported_version="0.9.0",
        )
    with pytest.raises(ValueError, match="not valid"):
        generate_manifest(artifact, "https://download.example.com", "stable")
