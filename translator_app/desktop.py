from __future__ import annotations

import os
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import traceback
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path

import uvicorn

from .config import load_config
from .diagnostics import configure_runtime_logging, log_exception, runtime_logger
from .server import create_app
from .stt import WhisperRecognizer
from .process_cleanup import acquire_single_instance


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


def _desktop_client_idle_seconds(app) -> float | None:
    lock = getattr(app.state, "desktop_client_lock", None)
    if lock is None:
        return None
    with lock:
        if not getattr(app.state, "desktop_client_seen", False):
            return None
        if int(getattr(app.state, "desktop_client_count", 0)) > 0:
            return None
        disconnected_at = float(getattr(app.state, "desktop_last_disconnect", 0.0))
    if disconnected_at <= 0:
        return None
    return time.monotonic() - disconnected_at


def _desktop_client_seen(app) -> bool:
    lock = getattr(app.state, "desktop_client_lock", None)
    if lock is None:
        return False
    with lock:
        return bool(getattr(app.state, "desktop_client_seen", False))


def _desktop_client_active(app) -> bool:
    lock = getattr(app.state, "desktop_client_lock", None)
    if lock is None:
        return False
    with lock:
        return int(getattr(app.state, "desktop_client_count", 0)) > 0


def _candidate_app_browsers() -> list[Path]:
    """Return browsers that can open a chrome-style app window.

    Chrome is preferred when present because the user specifically wants a
    separate app-like window, not a normal browser tab and not a forced Edge tab.
    """
    env = os.environ
    candidates: list[Path] = []
    for base in (
        env.get("LOCALAPPDATA"),
        env.get("PROGRAMFILES"),
        env.get("PROGRAMFILES(X86)"),
    ):
        if not base:
            continue
        base_path = Path(base)
        candidates.extend([
            base_path / "Google" / "Chrome" / "Application" / "chrome.exe",
            base_path / "Microsoft" / "Edge" / "Application" / "msedge.exe",
        ])
    seen: set[str] = set()
    result: list[Path] = []
    for path in candidates:
        key = str(path).casefold()
        if key not in seen and path.exists():
            seen.add(key)
            result.append(path)
    return result


def _launch_app_window(url: str, data_root: Path) -> subprocess.Popen | None:
    """Open the UI as a separate app window and return its process handle.

    The server remains visible in the launcher console. A dedicated browser
    profile prevents Chrome/Edge from handing the URL to an existing browser
    window and exiting immediately.
    """
    browser = next(iter(_candidate_app_browsers()), None)
    if browser is None:
        # Last resort only: keeps the app usable on systems without Chrome/Edge.
        webbrowser.open(url)
        return None

    profile_root = Path(tempfile.gettempdir()) / f"remoteplus-app-profile-{os.getpid()}"
    profile_root.mkdir(parents=True, exist_ok=True)
    args = [
        str(browser),
        f"--app={url}",
        "--new-window",
        f"--user-data-dir={profile_root}",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-session-crashed-bubble",
        "--disable-features=Translate,TranslateUI",
    ]
    try:
        return subprocess.Popen(
            args,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            close_fds=True,
        )
    except Exception:
        shutil.rmtree(profile_root, ignore_errors=True)
        webbrowser.open(url)
        return None


def run_desktop() -> int:
    """Start the local server in the current console and open the UI."""
    os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")
    if not acquire_single_instance():
        _startup_log("another desktop instance is already running")
        if os.name == "nt":
            import ctypes
            ctypes.windll.user32.MessageBoxW(0, "RemotePlus Translator is already running.", "RemotePlus Translator", 0x40)
        return 3
    cfg = load_config()
    cfg.data_root.mkdir(parents=True, exist_ok=True)
    logger = configure_runtime_logging(cfg.data_root)
    logger.info("desktop start pid=%s data_root=%s", os.getpid(), cfg.data_root)
    cfg.server.open_browser = False

    cfg.server.port = _available_port(cfg.server.host, cfg.server.port)
    _startup_log(f"using port {cfg.server.port}")

    display_host = "127.0.0.1" if cfg.server.host in {"0.0.0.0", "::"} else cfg.server.host
    url = f"http://{display_host}:{cfg.server.port}"

    _startup_log("loading STT model on launcher thread")
    recognizer = WhisperRecognizer(cfg.stt, lambda phase, message: _startup_log(f"stt {phase}: {message}"), label="final")
    recognizer.load()
    _startup_log("STT model loaded")

    app = create_app(cfg, recognizer=recognizer)
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
    app_process = _launch_app_window(url, cfg.data_root)
    profile_root = Path(tempfile.gettempdir()) / f"remoteplus-app-profile-{os.getpid()}"
    app_launched_at = time.monotonic()
    no_client_shutdown_seconds = max(60, cfg.server.auto_shutdown_no_clients_seconds * 3)
    shutdown_requested = False

    try:
        while server_thread.is_alive():
            if app_process is not None and app_process.poll() is not None and not _desktop_client_active(app):
                _startup_log("app window process exited; stopping server")
                shutdown_requested = True
                break
            if cfg.server.shutdown_when_idle:
                if not _desktop_client_seen(app) and time.monotonic() - app_launched_at >= no_client_shutdown_seconds:
                    _startup_log("desktop client never connected; stopping server")
                    shutdown_requested = True
                    break
                idle_seconds = _desktop_client_idle_seconds(app)
                if idle_seconds is not None and idle_seconds >= cfg.server.auto_shutdown_no_clients_seconds:
                    _startup_log(f"desktop client disconnected for {idle_seconds:.1f}s; stopping server")
                    shutdown_requested = True
                    break
            time.sleep(0.5)
        _startup_log("server thread stopped")
        if not shutdown_requested:
            detail = server_error[-1] if server_error else "uvicorn returned without a shutdown request"
            raise RuntimeError(f"Local server stopped unexpectedly:\n{detail}")
    except KeyboardInterrupt:
        shutdown_requested = True
    finally:
        server.should_exit = True
        server_thread.join(timeout=12.0)
        if app_process is not None and app_process.poll() is None:
            app_process.terminate()
            try:
                app_process.wait(timeout=3.0)
            except subprocess.TimeoutExpired:
                app_process.kill()
        shutil.rmtree(profile_root, ignore_errors=True)
        runtime_logger().info("desktop shutdown requested")
    return 0
