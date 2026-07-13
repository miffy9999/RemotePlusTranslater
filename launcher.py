import faulthandler
import importlib.util
import os
import sys
import tempfile
from pathlib import Path

from update_guard import verify_update_tree


def _update_error(message: str) -> None:
    try:
        root = Path(os.environ.get("LOCALAPPDATA", tempfile.gettempdir())) / "RemotePlusTranslator" / "logs"
        root.mkdir(parents=True, exist_ok=True)
        (root / "update-error.log").write_text(message, encoding="utf-8")
    except OSError:
        # Logging must never turn a recoverable update problem into a startup
        # failure. The bundled package remains the authoritative fallback.
        pass


def _activate_verified_update() -> None:
    """Load a development side-by-side update only after explicit opt-in.

    Hashes detect corruption but do not authenticate a publisher. Commercial
    builds therefore keep this path disabled until the distributor adds a
    signed manifest/public-key policy or ships an Authenticode-signed full
    installer update.
    """
    if not getattr(sys, "frozen", False) or os.environ.get("REMOTEPLUS_DISABLE_APP_UPDATE") == "1":
        return
    if os.environ.get("REMOTEPLUS_ENABLE_UNAUTHENTICATED_APP_UPDATE") != "1":
        return
    update_root = Path(sys.executable).resolve().parent / "app_update"
    manifest_path = update_root / "manifest.json"
    package_root = update_root / "translator_app"
    if not manifest_path.is_file():
        return
    try:
        verify_update_tree(update_root)
        init_path = package_root / "__init__.py"
        spec = importlib.util.spec_from_file_location(
            "translator_app",
            init_path,
            submodule_search_locations=[str(package_root)],
        )
        if spec is None or spec.loader is None:
            raise RuntimeError("could not create update module loader")
        module = importlib.util.module_from_spec(spec)
        sys.modules["translator_app"] = module
        spec.loader.exec_module(module)
    except Exception as exc:
        sys.modules.pop("translator_app", None)
        _update_error(f"The app update was ignored; bundled fallback will be used.\n{exc}\n")


_activate_verified_update()

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
        import traceback
        root = Path(os.environ.get("LOCALAPPDATA", tempfile.gettempdir())) / "RemotePlusTranslator" / "logs"
        root.mkdir(parents=True, exist_ok=True)
        path = root / "startup-error.log"
        path.write_text(traceback.format_exc(), encoding="utf-8")
        if os.name == "nt":
            import ctypes
            ctypes.windll.user32.MessageBoxW(0, f"RemotePlus failed to start.\n\n{exc}\n\nLog: {path}", "RemotePlus Translator", 0x10)
        raise SystemExit(1)
