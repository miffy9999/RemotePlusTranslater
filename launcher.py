import faulthandler
import os
import sys
import tempfile
from pathlib import Path

# The portable build follows run_debug.bat so field failures remain visible.
if getattr(sys, "frozen", False):
    os.environ.setdefault("PYTHONUTF8", "1")
    os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")
    os.environ.setdefault("REMOTEPLUS_DEBUG", "1")
    os.environ.setdefault("REMOTEPLUS_DEBUG_STARTUP", "1")

from translator_app.process_cleanup import enable_windows_process_cleanup  # noqa: E402

enable_windows_process_cleanup()

debug_handle = None
if os.environ.get("REMOTEPLUS_DEBUG_STARTUP") == "1":
    debug_path = Path(tempfile.gettempdir()) / "remoteplus-startup.log"
    debug_handle = debug_path.open("w", encoding="utf-8")
    faulthandler.enable(file=debug_handle)
    faulthandler.dump_traceback_later(20, repeat=True, file=debug_handle)
    debug_handle.write("launcher: importing CLI\n")
    debug_handle.flush()

from translator_app.cli import main  # noqa: E402


if __name__ == "__main__":
    if debug_handle:
        debug_handle.write("launcher: entering main\n")
        debug_handle.flush()
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except BaseException as exc:
        from datetime import datetime
        import traceback

        configured_root = os.environ.get("REMOTEPLUS_DATA_DIR") or os.environ.get(
            "LOCAL_BRIDGE_DATA_DIR"
        )
        roots = [
            Path(configured_root) if configured_root else None,
            Path(os.environ.get("LOCALAPPDATA", tempfile.gettempdir()))
            / "RemotePlusTranslator",
            Path(tempfile.gettempdir()) / "RemotePlusTranslator",
        ]
        evidence = traceback.format_exc()
        path = None
        for root in roots:
            if root is None:
                continue
            try:
                log_root = root / "logs"
                log_root.mkdir(parents=True, exist_ok=True)
                candidate = log_root / f"startup-error-{datetime.now():%Y%m%d-%H%M%S}.log"
                candidate.write_text(evidence, encoding="utf-8")
                (log_root / "startup-error.log").write_text(evidence, encoding="utf-8")
                path = candidate
                break
            except OSError:
                continue
        if os.name == "nt":
            import ctypes

            log_detail = f"\n\nLog: {path}" if path is not None else ""
            ctypes.windll.user32.MessageBoxW(
                0,
                f"RemotePlus failed to start.\n\n{exc}{log_detail}",
                "RemotePlus Translator",
                0x10,
            )
        raise SystemExit(1)
