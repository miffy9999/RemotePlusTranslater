from __future__ import annotations

import asyncio
import ctypes
import os
import queue
import secrets
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
from .languages import public_languages
from .settings import UserSettings
from .tts import SapiSpeaker

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


class LanguageSetupRequest(BaseModel):
    languages: list[str]


class VoiceInstallRequest(BaseModel):
    languages: list[str]


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
    settings = UserSettings(config.data_root)
    enabled_languages, setup_required = settings.load_languages(
        config.conversation.enabled_languages
    )
    controller.control(enabled_languages=enabled_languages)
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

    app = FastAPI(title="Local Conversation Translator", lifespan=lifespan)
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
        response.set_cookie(
            cookie_name,
            auth_token,
            httponly=True,
            samesite="strict",
            secure=False,
        )
        return response

    @app.get("/api/state")
    def state():
        snapshot = controller.snapshot()
        return {
            "state": snapshot,
            "history": bus.history(),
            "languages": public_languages(snapshot["enabled_languages"]),
            "setup_required": setup_required,
        }

    @app.get("/api/devices")
    def devices():
        try:
            return list_audio_devices()
        except Exception as exc:
            raise HTTPException(500, str(exc)) from exc

    @app.post("/api/control")
    def control(request: ControlRequest):
        try:
            return controller.control(**request.model_dump())
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.get("/api/language-setup")
    def language_setup():
        snapshot = controller.snapshot()
        primary = ["en", "ko", "zh", "es"]
        return {
            "enabled": snapshot["enabled_languages"],
            "available": public_languages(primary),
            "voices": SapiSpeaker.voice_status(primary),
            "setup_required": setup_required,
        }

    @app.post("/api/language-setup")
    def save_language_setup(request: LanguageSetupRequest):
        nonlocal setup_required
        available = {"en", "ko", "zh", "es"}
        selected = list(dict.fromkeys(code.lower() for code in request.languages))
        if not selected or any(code not in available for code in selected):
            raise HTTPException(400, "Select at least one supported language")
        settings.save_languages(selected)
        setup_required = False
        state = controller.control(enabled_languages=selected)
        return {"saved": True, "state": state, "languages": public_languages(selected)}

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

    @app.get("/api/voices")
    def voices():
        try:
            return {"voices": SapiSpeaker.voice_status(["en", "ko", "zh", "es"])}
        except Exception as exc:
            raise HTTPException(500, str(exc)) from exc

    @app.post("/api/voice-settings")
    def open_voice_settings():
        try:
            os.startfile("ms-settings:regionlanguage")
            return {"opened": True}
        except OSError as exc:
            raise HTTPException(500, str(exc)) from exc

    @app.post("/api/install-voices")
    def install_voices(request: VoiceInstallRequest):
        locales = {"en": "en-US", "ko": "ko-KR", "zh": "zh-CN", "es": "es-ES"}
        selected = [locales[code] for code in request.languages if code in locales]
        if not selected:
            raise HTTPException(400, "No installable voice language selected")
        script = config.root / "install_voice_packs.ps1"
        if not script.exists():
            raise HTTPException(500, "Voice pack installer is missing")
        locale_list = ",".join(selected)
        powershell = (
            os.path.join(os.environ.get("SystemRoot", r"C:\Windows"),
                         "System32", "WindowsPowerShell", "v1.0", "powershell.exe")
        )
        arguments = (
            f'-NoProfile -ExecutionPolicy Bypass -File "{script}" '
            f'-LocaleList "{locale_list}"'
        )
        result = ctypes.windll.shell32.ShellExecuteW(
            None, "runas", powershell, arguments, str(config.root), 1
        )
        if result <= 32:
            raise HTTPException(500, f"Unable to start installer: Windows error {result}")
        return {"started": True, "restart_required": True}

    @app.websocket("/ws")
    async def events(websocket: WebSocket):
        host = websocket.headers.get("host", "").casefold()
        origin = websocket.headers.get("origin", "").casefold()
        supplied = websocket.cookies.get(cookie_name) or websocket.headers.get(
            "x-auth-token", ""
        )
        if (
            host not in allowed_hosts
            or origin not in allowed_origins
            or not secrets.compare_digest(supplied, auth_token)
        ):
            await websocket.close(code=1008)
            return
        await websocket.accept()
        subscriber = bus.subscribe()
        try:
            await websocket.send_json({"type": "snapshot", "data": await asyncio.to_thread(state)})
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
