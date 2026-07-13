from __future__ import annotations

import argparse
import importlib
import json
import os
import platform
import sys
import tempfile
import threading
import webbrowser
from pathlib import Path

from .config import load_config
from .process_cleanup import enable_windows_process_cleanup


enable_windows_process_cleanup()


def _emit(*values, **kwargs) -> None:
    if sys.stdout is not None:
        print(*values, **kwargs)


def _debug_startup(message: str) -> None:
    if os.environ.get("REMOTEPLUS_DEBUG_STARTUP") != "1":
        return
    path = Path(tempfile.gettempdir()) / "remoteplus-startup.log"
    with path.open("a", encoding="utf-8") as handle:
        handle.write(f"cli: {message}\n")


def doctor() -> int:
    checks: list[tuple[str, bool, str]] = []
    version_ok = (3, 11) <= sys.version_info[:2] < (3, 14)
    checks.append(("Python", version_ok, platform.python_version()))
    for package in (
        "numpy", "sounddevice", "faster_whisper", "fastapi", "pypinyin", "anyascii"
    ):
        try:
            module = importlib.import_module(package)
            checks.append((package, True, getattr(module, "__version__", "installed")))
        except Exception as exc:
            checks.append((package, False, str(exc)))
    try:
        cfg = load_config()
        checks.append(("configuration", True, str(cfg.root / "config.toml")))
        if cfg.translation.backend == "hymt2":
            model = cfg.root / cfg.translation.hymt2_model
            runtime = cfg.root / cfg.translation.hymt2_runtime / "llama-server.exe"
            checks.append(("Hy-MT2 model", model.exists(), str(model)))
            checks.append(("llama.cpp runtime", runtime.exists(), str(runtime)))
        checks.append(("live captions", True, "disabled for final-STT priority"))
        checks.append(("staff replies", True, "typed Japanese with katakana/romanized guides"))
    except Exception as exc:
        checks.append(("configuration", False, str(exc)))
    if os.environ.get("REMOTEPLUS_ENUMERATE_AUDIO_DEVICES") == "1":
        try:
            from .audio import list_audio_devices
            devices = list_audio_devices()
            checks.append(("audio input", bool(devices["inputs"]), f"{len(devices['inputs'])} devices"))
        except Exception as exc:
            checks.append(("audio", False, str(exc)))
    else:
        checks.append(("audio input", True, "native enumeration skipped; set REMOTEPLUS_ENUMERATE_AUDIO_DEVICES=1 to inspect"))
    width = max(len(name) for name, _, _ in checks)
    report = "\n".join(f"[{'OK' if ok else 'FAIL'}] {name:<{width}}  {detail}" for name, ok, detail in checks)
    _emit(report)
    if getattr(sys, "frozen", False):
        cfg_root = Path(os.environ.get("LOCALAPPDATA", tempfile.gettempdir())) / "RemotePlusTranslator"
        cfg_root.mkdir(parents=True, exist_ok=True)
        (cfg_root / "doctor-report.txt").write_text(report + "\n", encoding="utf-8")
    return 0 if all(ok for _, ok, _ in checks) else 1


def prepare() -> int:
    cfg = load_config()
    cfg.data_root.mkdir(parents=True, exist_ok=True)
    from .stt import WhisperRecognizer
    from .hymt2 import create_translator, prepare_hymt2_files

    def report(phase: str, message: str) -> None:
        _emit(f"[{phase.upper()}] {message}")

    _emit("Final speech model is downloaded once and then used locally.")
    _emit("Live preview is disabled for queue stability and CPU priority.")
    _emit("Staff replies use typed Japanese and local reading-guide rules.")
    WhisperRecognizer(cfg.stt, report, label="final").load()
    if cfg.translation.backend == "hymt2":
        prepare_hymt2_files(cfg.translation, report)
    translator = create_translator(cfg.translation, report)
    translator.load()
    if hasattr(translator, "close"):
        translator.close()
    _emit("Preparation complete.")
    return 0


def device_probe(kind: str) -> int:
    if kind == "input":
        from .audio import list_audio_devices

        result = list_audio_devices()
        payload = {"inputs": result.get("inputs", []), "warnings": result.get("warnings", [])}
    else:
        return 2
    encoded = json.dumps(payload, ensure_ascii=False)
    output = os.environ.get("REMOTEPLUS_PROBE_OUTPUT")
    if output:
        Path(output).write_text(encoded, encoding="utf-8")
    else:
        _emit(encoded, flush=True)
    return 0


def serve() -> int:
    _debug_startup("serve loading config")
    cfg = load_config()
    cfg.data_root.mkdir(parents=True, exist_ok=True)
    _debug_startup("serve importing server")
    from .server import create_app
    _debug_startup("serve importing uvicorn")
    import uvicorn

    display_host = "127.0.0.1" if cfg.server.host in {"0.0.0.0", "::"} else cfg.server.host
    url = f"http://{display_host}:{cfg.server.port}"
    if cfg.server.open_browser:
        threading.Timer(1.2, lambda: webbrowser.open(url)).start()
    _emit(f"Local Bridge: {url}")
    _debug_startup("serve creating app")
    app = create_app(cfg)
    _debug_startup("serve entering uvicorn")
    uvicorn.run(app, host=cfg.server.host, port=cfg.server.port, log_level="warning", loop="asyncio", http="h11", log_config=None)
    return 0


def desktop() -> int:
    from .desktop import run_desktop
    return run_desktop()


def main() -> int:
    parser = argparse.ArgumentParser(description="RemotePlus hotel voice translator")
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("serve", help="start the translator")
    sub.add_parser("desktop", help="open the translator as a desktop application")
    sub.add_parser("doctor", help="check installation and audio input")
    sub.add_parser("prepare", help="download local speech and translation models")
    probe = sub.add_parser("device-probe", help=argparse.SUPPRESS)
    probe.add_argument("kind", choices=("input",))
    args = parser.parse_args()
    if args.command is None or args.command == "desktop":
        return desktop()
    if args.command == "serve":
        return serve()
    if args.command == "doctor":
        return doctor()
    if args.command == "prepare":
        return prepare()
    if args.command == "device-probe":
        return device_probe(args.kind)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
