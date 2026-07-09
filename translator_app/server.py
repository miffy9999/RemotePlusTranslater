from __future__ import annotations

import asyncio
import json
import os
import queue
import secrets
import subprocess
import sys
import threading
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .config import AppConfig, load_config
from .conversation import ConversationController
from .events import EventBus
from .feedback import FeedbackStore
from .languages import CUSTOMER_LANGUAGE_CODES, public_languages


def _fallback_devices(message: str) -> dict[str, list]:
    return {
        "inputs": [{"id": "default", "name": "System default input"}],
        "outputs": [],
        "warnings": [message],
    }


def _run_device_probe(root: Path, kind: str, code: str, timeout_seconds: float) -> dict[str, list]:
    env = os.environ.copy()
    env["PYTHONUTF8"] = "1"
    env["PYGAME_HIDE_SUPPORT_PROMPT"] = "1"
    env["PYTHONPATH"] = str(root) + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
    flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    command = [sys.executable, "device-probe", kind] if getattr(sys, "frozen", False) else [sys.executable, "-c", code]
    try:
        completed = subprocess.run(
            command,
            cwd=root,
            env=env,
            capture_output=True,
            timeout=timeout_seconds,
            creationflags=flags,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return _fallback_devices("Audio device enumeration timed out; system default remains available.")
    except Exception as exc:
        return _fallback_devices(f"Audio device enumeration failed; system default remains available: {exc}")
    stdout = (completed.stdout or b"").decode("utf-8", errors="replace")
    stderr = (completed.stderr or b"").decode("utf-8", errors="replace")
    if completed.returncode != 0:
        detail = (stderr or stdout).strip()
        return _fallback_devices(f"Audio device enumeration failed; system default remains available: {detail or completed.returncode}")
    try:
        lines = [line.strip() for line in stdout.splitlines() if line.strip()]
        return json.loads(lines[-1] if lines else "")
    except (TypeError, ValueError):
        return _fallback_devices("Audio device enumeration returned invalid data; system default remains available.")


def _enumerate_devices(root: Path, timeout_seconds: float = 8.0) -> dict[str, list]:
    input_code = (
        "import json;"
        "from translator_app.audio import list_audio_devices;"
        "result=list_audio_devices();"
        "print(json.dumps({'inputs':result.get('inputs',[]),'warnings':result.get('warnings',[])}, ensure_ascii=False), flush=True)"
    )
    output_code = (
        "import json;"
        "from translator_app.tts import EdgeSpeaker;"
        "print(json.dumps({'outputs':EdgeSpeaker.output_devices(),'warnings':[]}, ensure_ascii=False), flush=True)"
    )
    input_result = _run_device_probe(root, "input", input_code, timeout_seconds)
    output_result = _run_device_probe(root, "output", output_code, timeout_seconds)
    return {
        "inputs": input_result.get("inputs") or [{"id": "default", "name": "System default input"}],
        "outputs": output_result.get("outputs") or [],
        "warnings": [*input_result.get("warnings", []), *output_result.get("warnings", [])],
    }

WEB = Path(__file__).resolve().parent / "web"


class ControlRequest(BaseModel):
    paused: bool | None = None
    tts_enabled: bool | None = None
    active_language: str | None = None
    reply_language: str | None = None
    speech_mode: str | None = None
    input_device: str | int | None = None
    output_device: str | int | None = None
    enabled_languages: list[str] | None = None


class FeedbackRequest(BaseModel):
    direction: str
    source_language: str
    source: str
    translation: str
    corrected_source: str = ""
    corrected_translation: str = ""


def create_app(cfg: AppConfig | None = None, start_backend: bool = True, recognizer=None) -> FastAPI:
    config = cfg or load_config()
    bus = EventBus()
    controller = ConversationController(config, bus, recognizer=recognizer)
    feedback = FeedbackStore(config.data_root)
    devices_cache: dict[str, object] = {"expires_at": 0.0, "payload": None}

    # Every supported customer language is selectable immediately. There is no
    # Windows voice pack setup because Edge Neural TTS is online.
    controller.control(enabled_languages=list(CUSTOMER_LANGUAGE_CODES))

    auth_token = secrets.token_urlsafe(32)
    cookie_name = "remoteplus_session"
    allowed_hosts = {
        f"127.0.0.1:{config.server.port}",
        f"localhost:{config.server.port}",
        f"[::1]:{config.server.port}",
    }
    allowed_origins = {f"http://{host}" for host in allowed_hosts}

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if start_backend:
            controller.start()
        yield
        controller.stop()

    app = FastAPI(title="RemotePlus Translator", lifespan=lifespan)
    app.state.controller = controller
    app.state.auth_token = auth_token
    app.state.desktop_client_count = 0
    app.state.desktop_client_seen = False
    app.state.desktop_last_disconnect = 0.0
    app.state.desktop_client_lock = threading.Lock()

    @app.middleware("http")
    async def protect_local_api(request: Request, call_next):
        host = request.headers.get("host", "").casefold()
        if host not in allowed_hosts:
            return PlainTextResponse("Forbidden", status_code=403)
        if request.url.path.startswith("/api/"):
            supplied = request.cookies.get(cookie_name) or request.headers.get("x-auth-token", "")
            if not secrets.compare_digest(supplied, auth_token):
                return JSONResponse({"detail": "Unauthorized"}, status_code=401)
        return await call_next(request)

    app.mount("/assets", StaticFiles(directory=WEB), name="assets")

    @app.get("/")
    def index():
        response = FileResponse(WEB / "index.html")
        response.set_cookie(cookie_name, auth_token, httponly=True, samesite="strict", secure=False)
        return response

    @app.get("/remoteplus-health")
    def health():
        return {"app": "remoteplus-translator", "ok": True}

    @app.get("/api/state")
    def state():
        return {
            "state": controller.snapshot(),
            "history": bus.history(),
            "languages": public_languages(CUSTOMER_LANGUAGE_CODES),
            "tts": {"backend": "edge", "provider": "Edge online neural"},
        }

    @app.get("/api/devices")
    def devices():
        now = time.monotonic()
        cached = devices_cache.get("payload")
        if cached is not None and now < float(devices_cache["expires_at"]):
            return cached
        try:
            warnings: list[str] = []
            result = _enumerate_devices(config.root)
            warnings.extend(result.get("warnings", []))
            if not result.get("outputs"):
                warnings.append("Could not enumerate Edge TTS output devices; system default remains available.")
                result["outputs"] = []
            result["warnings"] = warnings
            devices_cache["payload"] = result
            devices_cache["expires_at"] = time.monotonic() + 30
            return result
        except Exception as exc:
            raise HTTPException(500, str(exc)) from exc

    @app.post("/api/control")
    def control(request: ControlRequest):
        try:
            payload = request.model_dump()
            # The UI no longer chooses a subset, but old clients cannot shrink
            # the supported language set accidentally.
            if payload.get("enabled_languages") is not None:
                payload["enabled_languages"] = list(CUSTOMER_LANGUAGE_CODES)
            return controller.control(**payload)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.get("/api/tts")
    def tts_info():
        return {
            "backend": "edge",
            "provider": "Edge online neural",
            "language_pack_required": False,
            "languages": public_languages(CUSTOMER_LANGUAGE_CODES),
        }

    @app.post("/api/feedback")
    def save_feedback(request: FeedbackRequest):
        try:
            path = feedback.append(request.model_dump())
            return {"saved": True, "file": str(path)}
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.delete("/api/history")
    def clear_history():
        bus.clear_history()
        bus.publish("history_cleared")
        return {"cleared": True}

    @app.delete("/api/feedback")
    def clear_feedback():
        return {"cleared": feedback.clear()}

    @app.websocket("/ws")
    async def events(websocket: WebSocket):
        host = websocket.headers.get("host", "").casefold()
        origin = websocket.headers.get("origin", "").casefold()
        supplied = websocket.cookies.get(cookie_name) or websocket.headers.get("x-auth-token", "")
        if host not in allowed_hosts or origin not in allowed_origins or not secrets.compare_digest(supplied, auth_token):
            await websocket.close(code=1008)
            return
        await websocket.accept()
        with app.state.desktop_client_lock:
            app.state.desktop_client_count += 1
            app.state.desktop_client_seen = True
        subscriber = bus.subscribe()
        try:
            await websocket.send_json({
                "type": "snapshot",
                "data": await asyncio.to_thread(state),
            })
            while True:
                try:
                    event = await asyncio.to_thread(subscriber.get, True, 1.0)
                except queue.Empty:
                    await websocket.send_json({"type": "ping"})
                    continue
                await websocket.send_json(event.as_dict())
        except (WebSocketDisconnect, RuntimeError):
            pass
        finally:
            with app.state.desktop_client_lock:
                app.state.desktop_client_count = max(0, app.state.desktop_client_count - 1)
                app.state.desktop_last_disconnect = time.monotonic()
            bus.unsubscribe(subscriber)

    return app
