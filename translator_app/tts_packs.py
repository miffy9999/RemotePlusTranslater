from __future__ import annotations

import hashlib
import json
import os
import shutil
import tarfile
import tempfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Callable
from urllib.parse import urlparse
from urllib.request import Request, urlopen


ProgressCallback = Callable[[str, str], None]


@dataclass(frozen=True, slots=True)
class PackSpec:
    """Immutable, reviewed metadata for a downloadable TTS model pack.

    URLs supplied by a user or a settings file are intentionally unsupported.
    A release must pin both the artifact and its digest here before the app will
    install it. This prevents a compromised manifest server from replacing a
    voice model with an arbitrary archive.
    """

    pack_id: str
    engine: str
    version: str
    languages: tuple[str, ...]
    archive_url: str
    archive_sha256: str
    archive_root: str
    license_id: str
    license_url: str | None = None
    license_sha256: str | None = None
    archive_bytes: int = 0
    embedded_license_path: str | None = None
    default_speaker_id: int = 0


SUPERTONIC_LANGUAGES = (
    "ar", "bg", "cs", "da", "de", "el", "en", "es", "et", "fi", "fr",
    "hi", "hr", "hu", "id", "it", "ja", "ko", "lt", "lv", "nl", "pl",
    "pt", "ro", "ru", "sk", "sl", "sv", "tr", "uk", "vi",
)


PACK_CATALOG: dict[str, PackSpec] = {
    "supertonic-3-int8": PackSpec(
        pack_id="supertonic-3-int8",
        engine="supertonic",
        version="2026-05-11",
        languages=SUPERTONIC_LANGUAGES,
        archive_url=(
            "https://github.com/k2-fsa/sherpa-onnx/releases/download/tts-models/"
            "sherpa-onnx-supertonic-3-tts-int8-2026-05-11.tar.bz2"
        ),
        archive_sha256="82fa96f91c4ef8abaae3a14a3f4153facf88bed821d1f7331cec2700f432c427",
        archive_root="sherpa-onnx-supertonic-3-tts-int8-2026-05-11",
        license_id="BigScience-OpenRAIL-M",
        license_url="https://huggingface.co/Supertone/supertonic-3/resolve/main/LICENSE",
        license_sha256="0d944a9110fed9a9602d60e0423a272903e7bd21ab060490774efc77c2275e9f",
        archive_bytes=128_774_318,
    ),
    "kokoro-v1.1-zh": PackSpec(
        pack_id="kokoro-v1.1-zh",
        engine="kokoro",
        version="1.1",
        languages=("zh",),
        archive_url=(
            "https://github.com/k2-fsa/sherpa-onnx/releases/download/tts-models/"
            "kokoro-multi-lang-v1_1.tar.bz2"
        ),
        archive_sha256="a3f4c73d043860e3fd2e5b06f36795eb81de0fc8e8de6df703245edddd87dbad",
        archive_root="kokoro-multi-lang-v1_1",
        license_id="Apache-2.0",
        license_sha256="cfc7749b96f63bd31c3c42b5c471bf756814053e847c10f3eb003417bc523d30",
        archive_bytes=364_816_464,
        embedded_license_path="LICENSE",
        # 0-2 are English voices; 3 is the first reviewed Mandarin voice.
        default_speaker_id=3,
    ),
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _download(url: str, target: Path, *, max_bytes: int, expected_bytes: int | None = None) -> None:
    request = Request(url, headers={"User-Agent": "RemotePlusTranslator/0.6"})
    with urlopen(request, timeout=60) as response, target.open("wb") as output:
        if urlparse(response.geturl()).scheme.casefold() != "https":
            raise ValueError("TTS download was redirected to an insecure transport")
        announced = response.headers.get("Content-Length")
        if announced and int(announced) > max_bytes:
            raise ValueError("TTS download is larger than the reviewed artifact limit")
        total = 0
        while True:
            chunk = response.read(1024 * 1024)
            if not chunk:
                break
            total += len(chunk)
            if total > max_bytes:
                raise ValueError("TTS download exceeded the reviewed artifact limit")
            output.write(chunk)
    if expected_bytes is not None and total != expected_bytes:
        raise ValueError(f"TTS download size mismatch; expected={expected_bytes} actual={total}")


def _safe_extract(archive: Path, destination: Path) -> None:
    """Extract a pinned tarball without links, devices or path traversal."""
    root = destination.resolve()
    with tarfile.open(archive, "r:bz2") as bundle:
        members = bundle.getmembers()
        for member in members:
            normalized = PurePosixPath(member.name)
            if normalized.is_absolute() or ".." in normalized.parts or member.issym() or member.islnk():
                raise ValueError(f"unsafe TTS pack member: {member.name}")
            if not (member.isdir() or member.isfile()):
                raise ValueError(f"unsupported TTS pack member: {member.name}")
            target = (root / Path(*normalized.parts)).resolve()
            if target != root and root not in target.parents:
                raise ValueError(f"TTS pack path escaped destination: {member.name}")
        bundle.extractall(root, members=members)


class TtsPackManager:
    def __init__(self, data_root: Path, bundled_data_root: Path | None = None):
        # Downloads and repairs always go to the per-user data root. A frozen
        # release may additionally ship read-only reviewed packs beside the
        # EXE; those take priority and avoid a first-run network dependency.
        self.root = data_root / "models" / "tts"
        bundled = bundled_data_root / "models" / "tts" if bundled_data_root else None
        self.bundled_root = bundled if bundled != self.root else None

    def _read_roots(self) -> tuple[Path, ...]:
        return (
            (self.bundled_root, self.root)
            if self.bundled_root is not None
            else (self.root,)
        )

    def pack_path(self, pack_id: str) -> Path:
        """Return the writable per-user destination for a pack."""
        if pack_id not in PACK_CATALOG:
            raise ValueError(f"unknown TTS pack: {pack_id}")
        return self.root / pack_id

    def _installed_at(self, pack_id: str, root: Path) -> bool:
        spec = PACK_CATALOG[pack_id]
        receipt = root / "pack-receipt.json"
        try:
            data = json.loads(receipt.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            return False
        files = data.get("files")
        if not isinstance(files, dict) or not files:
            return False
        # Checking existence is inexpensive and detects incomplete USB/folder
        # copies before the native runtime tries to open a model. Full hashes
        # are still checked once immediately before model load.
        resolved_root = root.resolve()
        for relative in files:
            if not isinstance(relative, str) or "\\" in relative:
                return False
            normalized = PurePosixPath(relative)
            if normalized.is_absolute() or ".." in normalized.parts:
                return False
            path = (root / Path(*normalized.parts)).resolve()
            if resolved_root not in path.parents or not path.is_file():
                return False
        return (
            data.get("schema") == 1
            and data.get("pack_id") == spec.pack_id
            and data.get("version") == spec.version
            and data.get("archive_sha256") == spec.archive_sha256
            and data.get("license_sha256") == spec.license_sha256
            and (root / spec.archive_root).is_dir()
        )

    def resolved_pack_path(self, pack_id: str) -> Path | None:
        if pack_id not in PACK_CATALOG:
            raise ValueError(f"unknown TTS pack: {pack_id}")
        for base in self._read_roots():
            candidate = base / pack_id
            if self._installed_at(pack_id, candidate):
                return candidate
        return None

    def installed(self, pack_id: str) -> bool:
        return self.resolved_pack_path(pack_id) is not None

    def validate_integrity(self, pack_id: str) -> None:
        """Hash model assets once before a runtime loads executable model data."""
        root = self.resolved_pack_path(pack_id)
        if root is None:
            raise ValueError(f"TTS pack is not installed: {pack_id}")
        try:
            receipt = json.loads((root / "pack-receipt.json").read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError) as exc:
            raise ValueError(f"TTS pack receipt is missing or invalid: {pack_id}") from exc
        files = receipt.get("files")
        if not isinstance(files, dict) or not files:
            raise ValueError(f"TTS pack has no integrity inventory: {pack_id}")
        for relative, expected in files.items():
            normalized = PurePosixPath(relative)
            if normalized.is_absolute() or ".." in normalized.parts or "\\" in relative:
                raise ValueError(f"invalid TTS pack inventory path: {relative}")
            path = (root / Path(*normalized.parts)).resolve()
            if root.resolve() not in path.parents or not path.is_file() or _sha256(path) != expected:
                raise ValueError(f"TTS pack file failed integrity check: {relative}")

    def installed_languages(self) -> set[str]:
        result: set[str] = set()
        for pack_id, spec in PACK_CATALOG.items():
            if self.installed(pack_id):
                result.update(spec.languages)
        return result

    def pack_for_language(self, language: str) -> tuple[PackSpec, Path] | None:
        code = language.strip().lower()
        # The dedicated Mandarin model is preferred over a generic multilingual
        # model if a future Supertonic release adds Chinese.
        order = ("kokoro-v1.1-zh", "supertonic-3-int8")
        for pack_id in order:
            spec = PACK_CATALOG[pack_id]
            root = self.resolved_pack_path(pack_id)
            if code in spec.languages and root is not None:
                return spec, root / spec.archive_root
        return None

    def install(self, pack_id: str, progress: ProgressCallback | None = None) -> Path:
        spec = PACK_CATALOG[pack_id]
        existing = self.resolved_pack_path(pack_id)
        if existing is not None:
            return existing
        notify = progress or (lambda _phase, _message: None)
        self.root.mkdir(parents=True, exist_ok=True)
        work = Path(tempfile.mkdtemp(prefix=f".{pack_id}-", dir=self.root))
        archive = work / "pack.tar.bz2"
        extracted = work / "content"
        final = self.pack_path(pack_id)
        try:
            notify("loading", f"Downloading local voice pack: {pack_id}")
            _download(
                spec.archive_url,
                archive,
                max_bytes=spec.archive_bytes,
                expected_bytes=spec.archive_bytes,
            )
            actual = _sha256(archive)
            if actual != spec.archive_sha256:
                raise ValueError(
                    f"TTS pack checksum mismatch: {pack_id}; expected={spec.archive_sha256} "
                    f"actual={actual} bytes={archive.stat().st_size}"
                )
            extracted.mkdir()
            notify("loading", f"Verifying and extracting voice pack: {pack_id}")
            _safe_extract(archive, extracted)
            model_root = extracted / spec.archive_root
            if not model_root.is_dir():
                raise ValueError(f"TTS pack has no expected model directory: {pack_id}")
            if spec.license_url and spec.license_sha256:
                license_path = model_root / "MODEL-LICENSE.txt"
                _download(spec.license_url, license_path, max_bytes=256 * 1024)
                if _sha256(license_path) != spec.license_sha256:
                    raise ValueError(f"TTS model license checksum mismatch: {pack_id}")
            elif spec.embedded_license_path and spec.license_sha256:
                license_path = model_root / spec.embedded_license_path
                if not license_path.is_file() or _sha256(license_path) != spec.license_sha256:
                    raise ValueError(f"Embedded TTS model license mismatch: {pack_id}")
            receipt = {
                "schema": 1,
                "pack_id": spec.pack_id,
                "engine": spec.engine,
                "version": spec.version,
                "languages": list(spec.languages),
                "license": spec.license_id,
                "license_sha256": spec.license_sha256,
                "archive_url": spec.archive_url,
                "archive_sha256": spec.archive_sha256,
                "files": {
                    path.relative_to(extracted).as_posix(): _sha256(path)
                    for path in sorted(model_root.rglob("*")) if path.is_file()
                },
            }
            (extracted / "pack-receipt.json").write_text(
                json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
            )
            if final.exists():
                shutil.rmtree(final)
            os.replace(extracted, final)
            notify("loading", f"Installed local voice pack: {pack_id}")
            return final
        finally:
            shutil.rmtree(work, ignore_errors=True)

    def install_for_languages(
        self, languages: list[str] | tuple[str, ...], progress: ProgressCallback | None = None
    ) -> list[Path]:
        requested = {str(code).strip().lower() for code in languages}
        pack_ids = [
            pack_id for pack_id, spec in PACK_CATALOG.items()
            if requested.intersection(spec.languages)
        ]
        return [self.install(pack_id, progress) for pack_id in pack_ids]
