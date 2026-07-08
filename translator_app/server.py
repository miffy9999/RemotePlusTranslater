from __future__ import annotations

import asyncio
import os
import queue
import secrets
import threading
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .audio import list_audio_devices
from .config import AppConfig, load_config
from .conversation import ConversationController
from .events import EventBus
from .feedback import FeedbackStore
from .languages import CUSTOMER_LANGUAGE_CODES, public_languages
from .tts import EdgeSpeaker

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


def create_app(cfg: AppConfig | None = None, start_backend: bool = True) -> FastAPI:
    config = cfg or load_config()
    bus = EventBus()
    controller = ConversationController(config, bus)
    feedback = FeedbackStore(config.data_root)

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

    @app.post("/api/desktop/close")
    async def desktop_close():
        # Only the hidden desktop launcher enables this. Normal debug/server mode ignores it.
        if os.environ.get("REMOTEPLUS_DESKTOP_AUTO_SHUTDOWN") != "1":
            return {"ok": False, "ignored": True}

        def _shutdown_soon() -> None:
            time.sleep(0.25)
            try:
                controller.stop()
            finally:
                os._exit(0)

        threading.Thread(target=_shutdown_soon, name="remoteplus-ui-close-shutdown", daemon=True).start()
        return {"ok": True}

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
        try:
            result = list_audio_devices()
            # Edge TTS audio is played by SDL/Pygame, so expose exactly the
            # device names SDL can open rather than legacy SAPI identifiers.
            edge_outputs = EdgeSpeaker.output_devices()
            if edge_outputs:
                result["outputs"] = edge_outputs
            else:
                result.setdefault("warnings", []).append(
                    "Could not enumerate Edge TTS output devices; system default remains available."
                )
                result["outputs"] = []
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
            bus.unsubscribe(subscriber)

    return app
