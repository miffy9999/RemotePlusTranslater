from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from pathlib import Path

from translator_app.tts_packs import PACK_CATALOG, TtsPackManager


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def bundle(source_data_root: Path, destination_data_root: Path) -> dict:
    """Copy only reviewed, fully verified TTS packs into a portable release."""
    source = TtsPackManager(source_data_root)
    destination_tts = destination_data_root / "models" / "tts"
    shutil.rmtree(destination_tts, ignore_errors=True)
    destination_tts.mkdir(parents=True, exist_ok=True)

    results = []
    for pack_id, spec in PACK_CATALOG.items():
        source_path = source.resolved_pack_path(pack_id)
        if source_path is None:
            raise RuntimeError(
                f"Reviewed TTS pack is missing: {pack_id}. Run prepare_models.bat first."
            )
        source.validate_integrity(pack_id)
        target = destination_tts / pack_id
        shutil.copytree(source_path, target)

        # Verify the destination bytes too, so an interrupted release copy is
        # caught before the portable folder is handed to another computer.
        copied = TtsPackManager(destination_data_root)
        copied.validate_integrity(pack_id)
        files = [path for path in target.rglob("*") if path.is_file()]
        results.append(
            {
                "pack_id": pack_id,
                "version": spec.version,
                "license": spec.license_id,
                "file_count": len(files),
                "bytes": sum(path.stat().st_size for path in files),
                "receipt_sha256": _sha256(target / "pack-receipt.json"),
            }
        )

    manifest = {"schema": 1, "packs": results}
    (destination_data_root / "bundled-tts-packs.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify and bundle reviewed local TTS packs")
    parser.add_argument("source_data_root", type=Path)
    parser.add_argument("destination_data_root", type=Path)
    args = parser.parse_args()
    try:
        result = bundle(args.source_data_root.resolve(), args.destination_data_root.resolve())
    except Exception as exc:
        print(f"TTS bundling failed: {exc}")
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
