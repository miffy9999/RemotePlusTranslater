import faulthandler
import os
import tempfile
from pathlib import Path

from translator_app.process_cleanup import enable_windows_process_cleanup

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
        import traceback
        root = Path(os.environ.get("LOCALAPPDATA", tempfile.gettempdir())) / "RemotePlusTranslator" / "logs"
        root.mkdir(parents=True, exist_ok=True)
        path = root / "startup-error.log"
        path.write_text(traceback.format_exc(), encoding="utf-8")
        if os.name == "nt":
            import ctypes
            ctypes.windll.user32.MessageBoxW(0, f"RemotePlus failed to start.\n\n{exc}\n\nLog: {path}", "RemotePlus Translator", 0x10)
        raise SystemExit(1)
