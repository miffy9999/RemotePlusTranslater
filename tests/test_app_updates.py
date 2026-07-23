import hashlib
import json

import pytest

from translator_app.app_updates import (
    AvailableUpdate,
    check_for_update,
    download_verified_installer,
    parse_manifest,
)


def manifest_payload(**artifact_overrides):
    artifact = {
        "filename": "RemotePlusTranslator-Setup-0.8.0.exe",
        "url": "https://download.example.com/releases/0.8.0/setup.exe",
        "size": 4,
        "sha256": hashlib.sha256(b"data").hexdigest(),
        "authenticode_required": True,
    }
    artifact.update(artifact_overrides)
    return json.dumps(
        {
            "schema": 1,
            "product": "RemotePlus Translator",
            "channel": "stable",
            "version": "0.8.0",
            "mandatory": False,
            "minimum_supported_version": "0.7.0",
            "artifact": artifact,
        }
    ).encode()


def test_update_manifest_requires_https_hash_size_and_authenticode():
    update = parse_manifest(manifest_payload(), "stable")
    assert update.version == "0.8.0"
    assert update.size == 4
    assert update.minimum_supported_version == "0.7.0"

    with pytest.raises(ValueError, match="HTTPS"):
        parse_manifest(manifest_payload(url="http://example.com/setup.exe"), "stable")
    with pytest.raises(ValueError, match="credentials"):
        parse_manifest(
            manifest_payload(url="https://user:secret@example.com/setup.exe"), "stable"
        )
    with pytest.raises(ValueError, match="fragment"):
        parse_manifest(manifest_payload(url="https://example.com/setup.exe#old"), "stable")
    with pytest.raises(ValueError, match="SHA-256"):
        parse_manifest(manifest_payload(sha256="bad"), "stable")
    with pytest.raises(ValueError, match="Authenticode"):
        parse_manifest(manifest_payload(authenticode_required=False), "stable")


def test_download_verifies_size_hash_and_pinned_publisher(tmp_path, monkeypatch):
    update = AvailableUpdate(
        version="0.8.0",
        mandatory=False,
        minimum_supported_version="0.7.0",
        filename="setup.exe",
        url="https://download.example.com/setup.exe",
        size=4,
        sha256=hashlib.sha256(b"data").hexdigest(),
    )

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def read(self, _size):
            if hasattr(self, "used"):
                return b""
            self.used = True
            return b"data"

    monkeypatch.setattr("urllib.request.urlopen", lambda *_args, **_kwargs: FakeResponse())
    monkeypatch.setattr(
        "translator_app.app_updates._authenticode_identity",
        lambda _path: ("Valid", "AA" * 20),
    )

    result = download_verified_installer(update, tmp_path, ["AA" * 20], 5)
    assert result.read_bytes() == b"data"


def test_download_rejects_another_valid_publisher(tmp_path, monkeypatch):
    update = AvailableUpdate(
        "0.8.0",
        False,
        "0.7.0",
        "setup.exe",
        "https://download.example.com/setup.exe",
        4,
        hashlib.sha256(b"data").hexdigest(),
    )

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def read(self, _size):
            value, self.value = getattr(self, "value", b"data"), b""
            return value

    monkeypatch.setattr("urllib.request.urlopen", lambda *_args, **_kwargs: FakeResponse())
    monkeypatch.setattr(
        "translator_app.app_updates._authenticode_identity",
        lambda _path: ("Valid", "BB" * 20),
    )
    with pytest.raises(ValueError, match="publisher certificate"):
        download_verified_installer(update, tmp_path, ["AA" * 20], 5)
    assert not (tmp_path / "setup.exe.part").exists()


def test_manifest_download_rejects_https_redirect_to_plain_http(monkeypatch):
    class DowngradedResponse:
        status = 200
        headers = {}

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def geturl(self):
            return "http://download.example.com/manifest.json"

        def read(self, _size):
            return manifest_payload()

    monkeypatch.setattr(
        "urllib.request.urlopen", lambda *_args, **_kwargs: DowngradedResponse()
    )
    with pytest.raises(ValueError, match="HTTPS"):
        check_for_update(
            "https://download.example.com/manifest.json", "0.7.0", "stable", 5
        )


def test_download_rejects_content_length_that_disagrees_with_manifest(
    tmp_path, monkeypatch
):
    update = AvailableUpdate(
        "0.8.0",
        False,
        "0.7.0",
        "setup.exe",
        "https://download.example.com/setup.exe",
        4,
        hashlib.sha256(b"data").hexdigest(),
    )

    class WrongLengthResponse:
        status = 200
        headers = {"Content-Length": "5"}

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def geturl(self):
            return update.url

        def read(self, _size):
            return b"data"

    monkeypatch.setattr(
        "urllib.request.urlopen", lambda *_args, **_kwargs: WrongLengthResponse()
    )
    with pytest.raises(ValueError, match="Content-Length"):
        download_verified_installer(update, tmp_path, ["AA" * 20], 5)
    assert not (tmp_path / "setup.exe.part").exists()


def test_client_older_than_minimum_supported_version_gets_mandatory_update(monkeypatch):
    class Response:
        status = 200
        headers = {}

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def geturl(self):
            return "https://download.example.com/channels/stable/manifest.json"

        def read(self, _size):
            return manifest_payload()

    monkeypatch.setattr("urllib.request.urlopen", lambda *_args, **_kwargs: Response())
    update = check_for_update(
        "https://download.example.com/channels/stable/manifest.json",
        "0.6.9",
        "stable",
        5,
    )
    assert update is not None
    assert update.mandatory is True


def test_manifest_requires_valid_minimum_supported_version():
    payload = json.loads(manifest_payload())
    payload["minimum_supported_version"] = "latest"
    with pytest.raises(ValueError, match="Invalid release version"):
        parse_manifest(json.dumps(payload).encode(), "stable")

    payload["minimum_supported_version"] = "0.9.0"
    with pytest.raises(ValueError, match="exceeds"):
        parse_manifest(json.dumps(payload).encode(), "stable")
