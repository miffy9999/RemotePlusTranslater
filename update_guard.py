from __future__ import annotations

import hashlib
import json
from pathlib import Path, PurePosixPath


def verify_update_tree(update_root: Path) -> dict:
    """Validate a complete fast-update tree and return its manifest.

    This detects interrupted copies and accidental file changes. It is not a
    digital signature: the manifest and files travel together.
    """
    root = update_root.resolve()
    manifest_path = root / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    files = manifest.get("files")
    if manifest.get("schema") != 1 or not isinstance(files, dict) or not files:
        raise ValueError("unsupported or empty update manifest")

    expected_files: set[str] = set()
    for relative, expected in files.items():
        if not isinstance(relative, str) or not isinstance(expected, str):
            raise ValueError("update manifest entries must be strings")
        normalized = PurePosixPath(relative)
        if normalized.is_absolute() or ".." in normalized.parts or "\\" in relative:
            raise ValueError(f"invalid update path: {relative}")
        if len(expected) != 64 or any(char not in "0123456789abcdefABCDEF" for char in expected):
            raise ValueError(f"invalid update checksum: {relative}")
        expected_files.add(relative)

    # Bytecode caches may be created by Python after the first successful run;
    # they are derived artifacts and are never trusted as update inputs.
    actual_files = {
        path.relative_to(root).as_posix()
        for path in root.rglob("*")
        if path.is_file()
        and path.name != "manifest.json"
        and "__pycache__" not in path.parts
        and path.suffix not in {".pyc", ".pyo"}
    }
    if actual_files != expected_files:
        missing = sorted(expected_files - actual_files)
        extra = sorted(actual_files - expected_files)
        raise ValueError(f"update file set mismatch; missing={missing}, extra={extra}")

    for relative, expected in files.items():
        path = (root / relative).resolve()
        if root not in path.parents or not path.is_file():
            raise ValueError(f"invalid update path: {relative}")
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
        if actual.casefold() != expected.casefold():
            raise ValueError(f"update checksum mismatch: {relative}")
    return manifest
