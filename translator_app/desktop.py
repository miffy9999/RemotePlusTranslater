from __future__ import annotations

import os
import shutil
import socket
import subprocess
import tempfile
import threading
import time
import traceback
import webbrowser
from pathlib import Path

import uvicorn

from .config import load_config
from .server import create_app
from .stt import WhisperRecognizer


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

    The server is already running hidden inside pythonw. This function must not
    open a normal browser tab. A dedicated profile prevents Chrome/Edge from
    handing the URL to an existing browser window and exiting immediately.
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
    creationflags = 0
    startupinfo = None
    if os.name == "nt":
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startupinfo.wShowWindow = 0
    try:
        return subprocess.Popen(
            args,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=creationflags,
            startupinfo=startupinfo,
            close_fds=True,
        )
    except Exception:
        shutil.rmtree(profile_root, ignore_errors=True)
        webbrowser.open(url)
        return None


def run_desktop() -> int:
    """Start the local server hidden and open the UI in an app-like window."""
    os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")
    cfg = load_config()
    cfg.data_root.mkdir(parents=True, exist_ok=True)
    cfg.server.open_browser = False
    cfg.server.port = _available_port(cfg.server.host, cfg.server.port)
    _startup_log(f"using port {cfg.server.port}")

    display_host = "127.0.0.1" if cfg.server.host in {"0.0.0.0", "::"} else cfg.server.host
    url = f"http://{display_host}:{cfg.server.port}"

    # The app window sends /api/desktop/close on unload. We also wait for the
    # app-window process below, so closing the window stops the hidden server.
    os.environ["REMOTEPLUS_DESKTOP_AUTO_SHUTDOWN"] = "1"

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
    )
    server = uvicorn.Server(server_config)
    server_error: list[str] = []

    def run_server() -> None:
        try:
            server.run()
            _startup_log("server.run returned")
        except BaseException:
            server_error.append(traceback.format_exc())
            _startup_log("server failed:\n" + server_error[-1])

    server_thread = threading.Thread(target=run_server, name="remoteplus-hidden-server", daemon=True)
    server_thread.start()

    for _ in range(600):
        if server.started:
            break
        if not server_thread.is_alive():
            if server_error:
                _startup_log("server thread exited before startup")
            return 1
        time.sleep(0.05)
    if not server.started:
        _startup_log("server did not report startup before timeout")
        server.should_exit = True
        server_thread.join(timeout=3.0)
        return 1

    _startup_log(f"server started at {url}")
    _launch_app_window(url, cfg.data_root)

    try:
        while server_thread.is_alive():
            time.sleep(0.5)
        _startup_log("server thread stopped")
    except KeyboardInterrupt:
        pass
    finally:
        server.should_exit = True
        server_thread.join(timeout=3.0)
    return 0
