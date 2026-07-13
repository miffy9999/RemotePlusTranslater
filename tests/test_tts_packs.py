import hashlib
import io
import json
import tarfile

import pytest

from translator_app.tts_packs import (
    PACK_CATALOG,
    PackSpec,
    TtsPackManager,
    _download,
    _safe_extract,
)


def test_catalog_pins_every_download_and_license():
    for spec in PACK_CATALOG.values():
        assert spec.archive_url.startswith("https://")
        assert len(spec.archive_sha256) == 64
        assert spec.archive_bytes > 0
        assert spec.languages
        assert len(spec.license_sha256 or "") == 64
        if spec.license_url:
            assert spec.embedded_license_path is None
        else:
            assert spec.embedded_license_path


def test_download_rejects_https_to_http_downgrade(tmp_path, monkeypatch):
    class FakeResponse:
        headers = {}

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def geturl(self):
            return "http://mirror.invalid/model.tar.bz2"

        def read(self, _size):
            return b""

    monkeypatch.setattr("translator_app.tts_packs.urlopen", lambda *_args, **_kwargs: FakeResponse())
    with pytest.raises(ValueError, match="insecure transport"):
        _download("https://example.invalid/model", tmp_path / "model", max_bytes=10)


def test_safe_extract_rejects_parent_path(tmp_path):
    archive = tmp_path / "bad.tar.bz2"
    with tarfile.open(archive, "w:bz2") as bundle:
        info = tarfile.TarInfo("../outside.txt")
        payload = b"bad"
        info.size = len(payload)
        bundle.addfile(info, io.BytesIO(payload))
    with pytest.raises(ValueError, match="unsafe TTS pack member"):
        _safe_extract(archive, tmp_path / "out")


def test_installed_pack_requires_matching_receipt(tmp_path, monkeypatch):
    spec = PackSpec(
        "test", "supertonic", "1", ("en",), "https://example.invalid/test", "a" * 64,
        "model", "MIT",
    )
    monkeypatch.setitem(PACK_CATALOG, "test", spec)
    manager = TtsPackManager(tmp_path)
    root = manager.pack_path("test")
    (root / "model").mkdir(parents=True)
    asset = root / "model" / "asset.bin"
    asset.write_bytes(b"model")
    checksum = hashlib.sha256(b"model").hexdigest()
    (root / "pack-receipt.json").write_text(json.dumps({
        "schema": 1, "pack_id": "test", "version": "1", "archive_sha256": "a" * 64,
        "files": {"model/asset.bin": checksum},
    }), encoding="utf-8")
    assert manager.installed("test") is True
    assert manager.installed_languages() == {"en"}
    manager.validate_integrity("test")


def test_bundled_pack_has_priority_and_incomplete_copy_falls_back_to_user_cache(
    tmp_path, monkeypatch
):
    spec = PackSpec(
        "test", "supertonic", "1", ("en",), "https://example.invalid/test",
        "a" * 64, "model", "MIT",
    )
    monkeypatch.setitem(PACK_CATALOG, "test", spec)
    user_root = tmp_path / "user"
    bundled_root = tmp_path / "bundle"

    def create_pack(base, payload):
        root = base / "models" / "tts" / "test"
        (root / "model").mkdir(parents=True)
        asset = root / "model" / "asset.bin"
        asset.write_bytes(payload)
        (root / "pack-receipt.json").write_text(
            json.dumps(
                {
                    "schema": 1,
                    "pack_id": "test",
                    "version": "1",
                    "archive_sha256": "a" * 64,
                    "files": {"model/asset.bin": hashlib.sha256(payload).hexdigest()},
                }
            ),
            encoding="utf-8",
        )
        return root

    bundled_pack = create_pack(bundled_root, b"bundled")
    user_pack = create_pack(user_root, b"user")
    manager = TtsPackManager(user_root, bundled_root)

    assert manager.resolved_pack_path("test") == bundled_pack
    assert manager.pack_path("test") == user_pack
    bundled_pack.joinpath("model", "asset.bin").unlink()
    assert manager.resolved_pack_path("test") == user_pack
    manager.validate_integrity("test")


def test_bundled_receipt_cannot_escape_pack_directory(tmp_path, monkeypatch):
    spec = PackSpec(
        "test", "supertonic", "1", ("en",), "https://example.invalid/test",
        "a" * 64, "model", "MIT",
    )
    monkeypatch.setitem(PACK_CATALOG, "test", spec)
    bundled_root = tmp_path / "bundle"
    root = bundled_root / "models" / "tts" / "test"
    (root / "model").mkdir(parents=True)
    (root.parent / "outside.bin").write_bytes(b"outside")
    (root / "pack-receipt.json").write_text(
        json.dumps(
            {
                "schema": 1,
                "pack_id": "test",
                "version": "1",
                "archive_sha256": "a" * 64,
                "files": {"../outside.bin": hashlib.sha256(b"outside").hexdigest()},
            }
        ),
        encoding="utf-8",
    )

    assert TtsPackManager(tmp_path / "user", bundled_root).installed("test") is False
