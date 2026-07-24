from __future__ import annotations

import argparse
import importlib.metadata as metadata
import json
import re
import shutil
from pathlib import Path

from packaging.requirements import Requirement

from translator_app import __version__


ROOT_PACKAGES = {
    "faster-whisper", "numpy", "sounddevice", "soundcard", "pywin32", "fastapi",
    "starlette", "pydantic", "uvicorn", "pypinyin", "anyascii", "pywebview",
    "pyinstaller",
}
LICENSE_NAMES = re.compile(r"^(licen[cs]e|copying|notice|authors?|lgpl|gpl)(\.|$)", re.IGNORECASE)


def normalized(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def dependency_closure() -> list[metadata.Distribution]:
    installed = {normalized(dist.metadata["Name"]): dist for dist in metadata.distributions() if dist.metadata.get("Name")}
    pending = list(ROOT_PACKAGES)
    selected: dict[str, metadata.Distribution] = {}
    while pending:
        key = normalized(pending.pop())
        if key in selected or key not in installed:
            continue
        dist = installed[key]
        selected[key] = dist
        for raw in dist.requires or ():
            try:
                req = Requirement(raw)
                # Include optional runtime dependencies conservatively. An
                # over-inclusive notice is safer than omitting a bundled DLL.
                if req.marker and not any(
                    req.marker.evaluate({"extra": extra})
                    for extra in ("", "standard", "all")
                ):
                    continue
                pending.append(req.name)
            except Exception:
                continue
    return [selected[key] for key in sorted(selected)]


def generate(destination: Path) -> dict:
    licenses = destination / "licenses" / "python"
    if licenses.exists():
        shutil.rmtree(licenses)
    licenses.mkdir(parents=True, exist_ok=True)
    components = []
    missing_license_files = []
    project_mit = Path(__file__).resolve().parent.parent / "LICENSE"
    apache_2 = Path(__file__).resolve().parent.parent / "legal" / "APACHE-2.0.txt"
    fallback_license = {
        "ctranslate2": project_mit,
        "flatbuffers": apache_2,
        "proxy-tools": Path(__file__).resolve().parent.parent
        / "legal"
        / "PROXY_TOOLS-BSD.txt",
        "tokenizers": apache_2,
    }
    for dist in dependency_closure():
        name = dist.metadata.get("Name", "unknown")
        version = dist.version
        component = {
            "type": "library",
            "name": name,
            "version": version,
            "purl": f"pkg:pypi/{name}@{version}",
            "licenses": [{"license": {"name": dist.metadata.get("License-Expression") or dist.metadata.get("License") or "UNKNOWN"}}],
        }
        components.append(component)
        copied = 0
        target = licenses / f"{name}-{version}"
        for item in dist.files or ():
            path = Path(str(item))
            if not LICENSE_NAMES.match(path.name):
                continue
            source = dist.locate_file(item)
            if not source.is_file():
                continue
            target.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target / path.name)
            copied += 1
        if not copied:
            fallback = fallback_license.get(normalized(name))
            if fallback is not None and Path(fallback).is_file():
                target.mkdir(parents=True, exist_ok=True)
                shutil.copy2(fallback, target / "LICENSE.txt")
                copied += 1
        if not copied:
            missing_license_files.append(f"{name}=={version}")
    sbom = {
        "bomFormat": "CycloneDX",
        "specVersion": "1.5",
        "version": 1,
        "metadata": {
            "component": {
                "type": "application",
                "name": "RemotePlus Translator",
                "version": __version__,
            }
        },
        "components": components,
        "properties": [
            {"name": "remoteplus:missing-license-files", "value": ",".join(missing_license_files)}
        ],
    }
    (destination / "sbom.cdx.json").write_text(
        json.dumps(sbom, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return {"components": len(components), "missing_license_files": missing_license_files}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    result = generate(args.destination)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 1 if result["missing_license_files"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
