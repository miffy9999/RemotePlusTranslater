from __future__ import annotations

import os
import json
import shutil
import socket
import sys
import tempfile
import threading
import time
import traceback
import urllib.error
import urllib.request
from pathlib import Path

import uvicorn

from .config import load_config
from .diagnostics import configure_runtime_logging, log_exception, runtime_logger
from .server import create_app
from .process_cleanup import acquire_single_instance, activate_existing_window


def _startup_log(message: str) -> None:
    if os.environ.get("REMOTEPLUS_DEBUG_STARTUP") != "1":
        return
    path = Path(tempfile.gettempdir()) / "remoteplus-startup.log"
    with path.open("a", encoding="utf-8") as handle:
        handle.write(f"desktop: {message}\n")


def _available_port(host: str, preferred: int) -> int:
    bind_host = "::1" if host == "::1" else "127.0.0.1"
    with socket.socket(socket.AF_INET6 if bind_host == "::1" else socket.AF_INET, socket.SOCK_STREAM) as probe:
        try:
            probe.bind((bind_host, preferred))
            return preferred
        except OSError:
            pass
    with socket.socket(socket.AF_INET6 if bind_host == "::1" else socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind((bind_host, 0))
        return int(probe.getsockname()[1])


def _wait_for_http(url: str, timeout_seconds: float = 10.0) -> bool:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=0.75) as response:
                if response.status == 200:
                    return True
        except (OSError, urllib.error.URLError, TimeoutError):
            time.sleep(0.1)
    return False


def _write_webview_state(path: Path, profile: str, clean_exit: bool) -> None:
    payload = {
        "schema": 1,
        "profile": profile,
        "clean_exit": clean_exit,
        "updated_at": time.time(),
    }
    temporary = path.with_suffix(f".tmp-{os.getpid()}")
    temporary.write_text(json.dumps(payload), encoding="utf-8")
    temporary.replace(path)


def _clear_webview_caches(profile: Path) -> None:
    cache_names = {"Cache", "Code Cache", "DawnCache", "GPUCache"}
    try:
        root = profile.resolve()
        candidates = [path for path in profile.rglob("*") if path.name in cache_names]
    except OSError:
        return
    for candidate in candidates:
        try:
            resolved = candidate.resolve()
            if root not in resolved.parents or candidate.is_symlink():
                continue
            if candidate.is_dir():
                shutil.rmtree(candidate, ignore_errors=True)
        except OSError:
            continue


def _prepare_webview_profile(data_root: Path) -> tuple[Path, Path, str]:
    profiles_root = data_root / "webview2-v2"
    state_path = profiles_root / "state.json"
    profiles_root.mkdir(parents=True, exist_ok=True)
    previous: dict = {}
    try:
        previous = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        pass
    profile_name = str(previous.get("profile", "a"))
    if profile_name not in {"a", "b"}:
        profile_name = "a"
    recovering = previous.get("clean_exit") is False
    if recovering:
        profile_name = "b" if profile_name == "a" else "a"
    profile = profiles_root / f"profile-{profile_name}"
    if recovering and profile.exists() and not profile.is_symlink():
        shutil.rmtree(profile, ignore_errors=True)
    profile.mkdir(parents=True, exist_ok=True)
    _clear_webview_caches(profile)
    _write_webview_state(state_path, profile_name, False)
    return profile, state_path, profile_name


def _show_native_window(
    url: str,
    data_root: Path,
    ui_ready: threading.Event | None = None,
    storage_path: Path | None = None,
) -> None:
    """Run the local UI in a native Windows WebView2 window.

    The HTTP server remains loopback-only. WebView2 is an embedded application
    runtime, so RemotePlus no longer opens or controls the user's browser.
    """
    try:
        import webview
    except ImportError as exc:
        raise RuntimeError("The native window component is missing. Reinstall RemotePlus.") from exc

    storage_path = storage_path or data_root / "webview2"
    storage_path.mkdir(parents=True, exist_ok=True)
    window = webview.create_window(
        "RemotePlus Translator",
        url,
        width=1280,
        height=820,
        min_size=(900, 620),
        resizable=True,
        maximized=True,
        background_color="#f4f4f1",
        text_select=True,
    )
    normal_close = threading.Event()
    stopped = threading.Event()
    startup_failure: list[str] = []
    if window is not None and hasattr(window, "events"):
        window.events.closing += normal_close.set

    def watch_ui_ready() -> None:
        if ui_ready is None or ui_ready.wait(8) or stopped.is_set():
            return
        runtime_logger().warning("WebView UI did not signal readiness; reloading once")
        try:
            window.load_url(f"{url}?recovery=1")
        except Exception:
            log_exception("WebView recovery reload failed")
        if ui_ready.wait(8) or stopped.is_set():
            return
        startup_failure.append("The application screen did not finish loading")
        runtime_logger().error("WebView UI readiness timed out after recovery reload")
        try:
            window.destroy()
        except Exception:
            pass

    try:
        webview.start(
            func=watch_ui_ready if ui_ready is not None else None,
            gui="edgechromium",
            private_mode=False,
            storage_path=str(storage_path),
            debug=os.environ.get("REMOTEPLUS_WEBVIEW_DEBUG") == "1",
        )
    except Exception as exc:
        raise RuntimeError(
            "Could not open the native window. Install or repair Microsoft Edge WebView2 Runtime."
        ) from exc
    finally:
        stopped.set()
    if startup_failure:
        raise RuntimeError(
            "The application screen could not load. RemotePlus will use a clean "
            "WebView profile on the next start."
        )
    if window is not None and hasattr(window, "events") and not normal_close.is_set():
        raise RuntimeError("The application window ended unexpectedly")


def _launch_available_update(cfg) -> bool:
    if not cfg.updates.enabled:
        return False
    from . import __version__
    from .app_updates import check_for_update, download_verified_installer

    update = None
    try:
        update = check_for_update(
            cfg.updates.manifest_url,
            __version__,
            cfg.updates.channel,
            cfg.updates.timeout_seconds,
        )
        if update is None:
            return False
        if os.name != "nt":
            return False
        import ctypes

        message = (
            f"RemotePlus Translator {update.version} 버전을 설치할 수 있습니다.\n\n"
            "서명된 설치 파일을 내려받아 업데이트하시겠습니까?"
        )
        if update.mandatory:
            message = (
                f"RemotePlus Translator {update.version} 필수 업데이트를 설치합니다.\n\n"
                "설치가 끝난 뒤 프로그램을 다시 실행하세요."
            )
        choice = ctypes.windll.user32.MessageBoxW(
            0,
            message,
            "RemotePlus 업데이트",
            0x40 if update.mandatory else 0x44,
        )
        if not update.mandatory and choice != 6:
            return False
        installer = download_verified_installer(
            update,
            cfg.data_root / "updates" / update.version,
            cfg.updates.trusted_publisher_thumbprints,
            cfg.updates.timeout_seconds,
        )
        shell_execute = ctypes.windll.shell32.ShellExecuteW
        shell_execute.argtypes = [
            ctypes.c_void_p,
            ctypes.c_wchar_p,
            ctypes.c_wchar_p,
            ctypes.c_wchar_p,
            ctypes.c_wchar_p,
            ctypes.c_int,
        ]
        shell_execute.restype = ctypes.c_void_p
        result = shell_execute(
            None,
            "open",
            str(installer),
            None,
            str(installer.parent),
            1,
        )
        result_value = int(result or 0)
        if result_value <= 32:
            raise RuntimeError(f"Could not start the update installer ({result_value})")
        return True
    except Exception as exc:
        runtime_logger().warning("update check failed: %s", exc)
        if update is not None and update.mandatory and os.name == "nt":
            import ctypes

            ctypes.windll.user32.MessageBoxW(
                0,
                "필수 업데이트를 안전하게 설치하지 못해 프로그램을 시작하지 않습니다.\n\n"
                "호텔 IT 담당자에게 문의하세요.",
                "RemotePlus 업데이트 오류",
                0x10,
            )
            return True
        return False


def run_desktop() -> int:
    """Start the hidden local engine and own it with one native app window."""
    os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")
    if not acquire_single_instance():
        _startup_log("another desktop instance is already running")
        if activate_existing_window():
            return 0
        if os.name == "nt":
            import ctypes
            ctypes.windll.user32.MessageBoxW(0, "RemotePlus Translator is already running.", "RemotePlus Translator", 0x40)
        return 3
    cfg = load_config()
    cfg.data_root.mkdir(parents=True, exist_ok=True)
    logger = configure_runtime_logging(cfg.data_root)
    logger.info("desktop start pid=%s data_root=%s", os.getpid(), cfg.data_root)
    if _launch_available_update(cfg):
        logger.info("update flow ended application startup")
        return 0
    cfg.server.open_browser = False

    cfg.server.port = _available_port(cfg.server.host, cfg.server.port)
    _startup_log(f"using port {cfg.server.port}")

    display_host = "127.0.0.1" if cfg.server.host in {"0.0.0.0", "::"} else cfg.server.host
    url = f"http://{display_host}:{cfg.server.port}"

    # The controller loads STT and translation models in workers. Starting the
    # UI first gives the operator visible preparation status instead of a blank
    # desktop during the potentially slow first model load.
    app = create_app(cfg)
    server_config = uvicorn.Config(
        app,
        host=cfg.server.host,
        port=cfg.server.port,
        log_level="warning",
        loop="asyncio",
        http="h11",
        access_log=False,
        log_config=None,
    )
    server = uvicorn.Server(server_config)
    server_error: list[str] = []

    def run_server() -> None:
        try:
            server.run()
            _startup_log("server.run returned")
        except BaseException:
            server_error.append(traceback.format_exc())
            log_exception("local server thread failed")
            _startup_log("server failed:\n" + server_error[-1])

    server_thread = threading.Thread(target=run_server, name="remoteplus-server", daemon=True)
    server_thread.start()

    for _ in range(600):
        if server.started:
            break
        if not server_thread.is_alive():
            if server_error:
                _startup_log("server thread exited before startup")
                raise RuntimeError("Local server failed to start:\n" + server_error[-1])
            raise RuntimeError("Local server exited before startup")
        time.sleep(0.05)
    if not server.started:
        _startup_log("server did not report startup before timeout")
        server.should_exit = True
        server_thread.join(timeout=3.0)
        raise RuntimeError("Local server did not start before timeout")

    if not _wait_for_http(url, timeout_seconds=10.0):
        _startup_log(f"server did not answer HTTP at {url}")
        server.should_exit = True
        server_thread.join(timeout=3.0)
        raise RuntimeError(f"Local server did not answer at {url}")

    _startup_log(f"server started at {url}")
    if sys.stdout is not None:
        print(f"RemotePlus server: {url}", flush=True)
        print("Close the app window to stop RemotePlus.", flush=True)
    profile, webview_state, profile_name = _prepare_webview_profile(cfg.data_root)
    clean_exit = False
    try:
        _show_native_window(url, cfg.data_root, app.state.ui_ready_event, profile)
        _startup_log("native app window closed; stopping server")
        if not server_thread.is_alive():
            detail = server_error[-1] if server_error else "uvicorn returned without a shutdown request"
            raise RuntimeError(f"Local server stopped unexpectedly:\n{detail}")
        clean_exit = True
    except KeyboardInterrupt:
        pass
    finally:
        if clean_exit:
            try:
                _write_webview_state(webview_state, profile_name, True)
            except OSError:
                runtime_logger().warning("Could not record a clean WebView shutdown")
        server.should_exit = True
        server_thread.join(timeout=12.0)
        runtime_logger().info("desktop shutdown requested")
    return 0
