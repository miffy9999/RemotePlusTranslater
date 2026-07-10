import faulthandler
import os
import sys
import tempfile
from pathlib import Path

from translator_app.process_cleanup import enable_windows_process_cleanup

enable_windows_process_cleanup()

if getattr(sys, "frozen", False):
    os.environ.setdefault("REMOTEPLUS_DEBUG", "1")
    os.environ.setdefault("REMOTEPLUS_DEBUG_STARTUP", "1")

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
    raise SystemExit(main())
