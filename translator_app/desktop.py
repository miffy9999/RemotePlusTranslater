from __future__ import annotations

import socket
import threading
import time

import uvicorn

from .config import load_config
from .server import create_app


def _wait_until_ready(host: str, port: int, timeout: float = 30.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with socket.socket() as probe:
            probe.settimeout(0.25)
            if probe.connect_ex((host, port)) == 0:
                return
        time.sleep(0.1)
    raise RuntimeError("로컬 번역 화면을 시작하지 못했습니다.")


def run_desktop() -> int:
    import webview

    cfg = load_config()
    cfg.data_root.mkdir(parents=True, exist_ok=True)

    uvicorn_config = uvicorn.Config(
        create_app(cfg),
        host=cfg.server.host,
        port=cfg.server.port,
        log_level="warning",
        loop="asyncio",
        http="h11",
    )
    server = uvicorn.Server(uvicorn_config)
    server_thread = threading.Thread(target=server.run, name="local-server", daemon=True)
    server_thread.start()

    try:
        _wait_until_ready(cfg.server.host, cfg.server.port)
        window = webview.create_window(
            "RemotePlus 실시간 통역",
            f"http://{cfg.server.host}:{cfg.server.port}",
            width=1280,
            height=820,
            min_size=(960, 640),
            confirm_close=True,
        )
        window.events.closed += lambda: setattr(server, "should_exit", True)
        webview.start(gui="edgechromium", debug=False)
    finally:
        server.should_exit = True
        server_thread.join(timeout=8)
    return 0
