from __future__ import annotations

import asyncio
import json
import os
import queue
import secrets
import subprocess
import sys
import tempfile
import threading
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse
from pydantic import BaseModel, ConfigDict

from . import __version__
from .config import AppConfig, load_config
from .conversation import ConversationController
from .events import EventBus
from .feedback import FeedbackStore
from .languages import CUSTOMER_LANGUAGE_CODES, public_languages
from .settings import UserSettings
from .tts_packs import PACK_CATALOG, TtsPackManager


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
    output_file = Path(tempfile.gettempdir()) / f"remoteplus-device-{os.getpid()}-{kind}-{secrets.token_hex(4)}.json"
    env["REMOTEPLUS_PROBE_OUTPUT"] = str(output_file)
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
        output_file.unlink(missing_ok=True)
        return _fallback_devices("Audio device enumeration timed out; system default remains available.")
    except Exception as exc:
        output_file.unlink(missing_ok=True)
        return _fallback_devices(f"Audio device enumeration failed; system default remains available: {exc}")
    try:
        stdout = (completed.stdout or b"").decode("utf-8", errors="replace")
        stderr = (completed.stderr or b"").decode("utf-8", errors="replace")
        if completed.returncode != 0:
            detail = (stderr or stdout).strip()
            return _fallback_devices(f"Audio device enumeration failed; system default remains available: {detail or completed.returncode}")
        if output_file.exists():
            return json.loads(output_file.read_text(encoding="utf-8"))
        lines = [line.strip() for line in stdout.splitlines() if line.strip()]
        return json.loads(lines[-1] if lines else "")
    except (TypeError, ValueError):
        return _fallback_devices("Audio device enumeration returned invalid data; system default remains available.")
    finally:
        output_file.unlink(missing_ok=True)


def _enumerate_devices(root: Path, timeout_seconds: float = 8.0) -> dict[str, list]:
    input_code = (
        "import json;"
        "from translator_app.audio import list_audio_devices;"
        "result=list_audio_devices();"
        "print(json.dumps({'inputs':result.get('inputs',[]),'warnings':result.get('warnings',[])}, ensure_ascii=False), flush=True)"
    )
    output_code = (
        "import json;"
        "from translator_app.tts import LocalSpeaker;"
        "print(json.dumps({'outputs':LocalSpeaker.output_devices(),'warnings':[]}, ensure_ascii=False), flush=True)"
    )
    input_result = _run_device_probe(root, "input", input_code, timeout_seconds)
    output_result = _run_device_probe(root, "output", output_code, timeout_seconds)
    return {
        "inputs": input_result.get("inputs") or [{"id": "default", "name": "System default input"}],
        "outputs": output_result.get("outputs") or [],
        "warnings": [*input_result.get("warnings", []), *output_result.get("warnings", [])],
    }

WEB = Path(__file__).resolve().parent / "web"
WEB_ASSETS = {
    "app.css": WEB / "app.css",
    "device.css": WEB / "device.css",
    "app.js": WEB / "app.js",
}
DEVICE_CACHE_SECONDS = 60.0


class StrictRequest(BaseModel):
    # Silently ignored fields hide version mismatches between an old UI and a
    # new backend. Reject them so the caller gets an actionable 422 response.
    model_config = ConfigDict(extra="forbid")


class ControlRequest(StrictRequest):
    paused: bool | None = None
    tts_enabled: bool | None = None
    active_language: str | None = None
    reply_language: str | None = None
    speech_mode: str | None = None
    input_device: str | int | None = None
    output_device: str | int | None = None
    enabled_languages: list[str] | None = None


class FeedbackRequest(StrictRequest):
    direction: str
    source_language: str
    source: str
    translation: str
    corrected_source: str = ""
    corrected_translation: str = ""


class ReplayRequest(StrictRequest):
    text: str
    language: str


class InstallVoicesRequest(StrictRequest):
    languages: list[str]


def create_app(cfg: AppConfig | None = None, start_backend: bool = True, recognizer=None) -> FastAPI:
    config = cfg or load_config()
    # Tests, embedders and future multi-user launchers may relocate the data
    # root after loading the base config. Keep model managers on that exact root.
    config.tts.data_root = config.data_root
    bus = EventBus()
    controller = ConversationController(config, bus, recognizer=recognizer)
    feedback = FeedbackStore(config.data_root)
    user_settings = UserSettings(config.data_root)
    devices_cache: dict[str, object] = {"expires_at": 0.0, "payload": None}
    devices_lock = threading.Lock()
    tts_install_lock = threading.Lock()
    tts_installing: set[str] = set()
    tts_pending: set[str] = set()
    tts_installer_thread: threading.Thread | None = None
    local_voice_languages = {
        code for spec in PACK_CATALOG.values() for code in spec.languages
    }

    def public_state() -> dict:
        result = controller.snapshot()
        with tts_install_lock:
            queued = sorted(tts_installing | tts_pending)
        result["tts_installing_languages"] = queued
        result["tts_download_active"] = bool(queued)
        return result

    def selected_tts_language() -> str:
        state = controller.snapshot()
        target = state.get("reply_language")
        if target == "auto":
            target = state.get("active_language") or state.get("input_language")
        return str(target or "").strip().lower()

    def queue_voice_install(languages: list[str]) -> list[str]:
        """Queue reviewed packs without losing selections during another download."""
        nonlocal tts_installer_thread
        installed = controller.speaker.installed_languages()
        requested = {
            str(code).strip().lower() for code in languages
            if str(code).strip().lower() in local_voice_languages
        }
        missing = requested - installed
        if not missing:
            target = selected_tts_language()
            if target in requested and hasattr(controller.speaker, "preload"):
                controller.speaker.preload(target)
            return []
        with tts_install_lock:
            tts_pending.update(missing - tts_installing)
            queued = sorted(tts_pending | tts_installing)
            if tts_installer_thread is None or not tts_installer_thread.is_alive():
                tts_installer_thread = threading.Thread(
                    target=voice_install_worker,
                    name="tts-pack-installer",
                    daemon=True,
                )
                tts_installer_thread.start()
        bus.publish("state", **public_state())
        return queued

    def voice_install_worker() -> None:
        nonlocal tts_installer_thread
        manager = TtsPackManager(config.data_root, config.tts.bundled_data_root)
        while True:
            with tts_install_lock:
                if not tts_pending:
                    tts_installer_thread = None
                    return
                batch = sorted(tts_pending)
                tts_pending.clear()
                tts_installing.update(batch)
            try:
                manager.install_for_languages(
                    batch,
                    lambda phase, message: bus.publish(
                        "status", phase=phase, message=message
                    ),
                )
                target = selected_tts_language()
                # Installing every reviewed pack must not create one preload
                # thread per language. Supertonic is shared, so warm only the
                # language currently selected by the operator.
                if target in batch and hasattr(controller.speaker, "preload"):
                    controller.speaker.preload(target)
            except Exception as exc:
                bus.publish("warning", message=f"Local voice-pack installation failed: {exc}")
            finally:
                with tts_install_lock:
                    tts_installing.difference_update(batch)
                bus.publish("state", **public_state())

    # Every supported customer language is selectable immediately. There is no
    # Voice models are managed by the app and never depend on Windows packs.
    controller.control(enabled_languages=list(CUSTOMER_LANGUAGE_CODES))
    saved = user_settings.load()
    for key in ("active_language", "reply_language", "tts_enabled", "output_device", "input_device"):
        if key not in saved:
            continue
        try:
            controller.control(**{key: saved[key]})
        except (TypeError, ValueError):
            # Device names and language codes can disappear after moving the
            # portable build to another PC. Invalid persisted values never
            # prevent startup; the configured/default value remains active.
            continue

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
            if config.tts.auto_install_voice_packs:
                # Install both reviewed packs on the first run. This is queued
                # after the UI/backend starts so downloading never blocks the
                # window from opening or text translation from becoming ready.
                queue_voice_install(sorted(local_voice_languages))
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

    @app.get("/assets/{filename}")
    def asset(filename: str):
        # Do not pass a user-controlled path to Starlette StaticFiles on
        # Windows. Only the three packaged assets are addressable.
        path = WEB_ASSETS.get(filename)
        if path is None:
            raise HTTPException(404, "Asset not found")
        return FileResponse(path)

    @app.get("/")
    def index():
        response = FileResponse(WEB / "index.html")
        response.set_cookie(cookie_name, auth_token, httponly=True, samesite="strict", secure=False)
        return response

    @app.get("/remoteplus-health")
    def health():
        # `update_layer` makes support diagnostics unambiguous without exposing
        # arbitrary filesystem paths or enabling a general debug endpoint.
        return {
            "app": "remoteplus-translator",
            "version": __version__,
            "update_layer": "app_update" in Path(__file__).parts,
            "ok": True,
        }

    @app.get("/api/state")
    def state():
        return {
            "state": public_state(),
            "history": bus.history(),
            "languages": public_languages(CUSTOMER_LANGUAGE_CODES),
            "tts": {"backend": "local", "provider": "Verified local ONNX voice packs"},
        }

    @app.get("/api/devices")
    def devices():
        with devices_lock:
            now = time.monotonic()
            cached = devices_cache.get("payload")
            if cached is not None and now < float(devices_cache["expires_at"]):
                return cached
            try:
                warnings: list[str] = []
                result = _enumerate_devices(config.root)
                warnings.extend(result.get("warnings", []))
                if not result.get("outputs"):
                    warnings.append("Could not enumerate local TTS output devices; system default remains available.")
                    result["outputs"] = []
                result["warnings"] = warnings
                devices_cache["payload"] = result
                devices_cache["expires_at"] = time.monotonic() + DEVICE_CACHE_SECONDS
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
            state = controller.control(**payload)
            persistent_keys = {
                "active_language", "reply_language", "tts_enabled",
                "input_device", "output_device",
            }
            if any(payload.get(key) is not None for key in persistent_keys):
                try:
                    user_settings.save(state)
                    state["settings_persisted"] = True
                except OSError as exc:
                    state["settings_persisted"] = False
                    bus.publish("warning", message=f"Settings could not be saved: {exc}")
            if (
                config.tts.auto_install_voice_packs
                and state.get("tts_enabled")
                and any(payload.get(key) is not None for key in ("active_language", "reply_language", "tts_enabled"))
            ):
                target = state.get("reply_language")
                if target == "auto":
                    target = state.get("active_language") or state.get("input_language")
                if target:
                    queue_voice_install([str(target)])
            response_state = public_state()
            if "settings_persisted" in state:
                response_state["settings_persisted"] = state["settings_persisted"]
            return response_state
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.get("/api/tts")
    def tts_info():
        with tts_install_lock:
            installing = sorted(tts_installing | tts_pending)
        return {
            "backend": "local",
            "provider": "Verified local ONNX voice packs",
            "online": False,
            "language_pack_required": True,
            "installed_languages": sorted(controller.speaker.installed_languages()),
            "installing_languages": installing,
            "languages": public_languages(CUSTOMER_LANGUAGE_CODES),
        }

    @app.post("/api/install-voices", status_code=202)
    def install_voices(request: InstallVoicesRequest):
        languages = list(dict.fromkeys(str(code).strip().lower() for code in request.languages))
        allowed = set(CUSTOMER_LANGUAGE_CODES)
        if not languages or len(languages) > 10 or any(code not in allowed for code in languages):
            raise HTTPException(400, "Choose 1 to 10 supported customer languages")
        unavailable = sorted(set(languages) - local_voice_languages)
        if unavailable:
            raise HTTPException(400, f"No commercially reviewed local voice pack for: {', '.join(unavailable)}")
        queued = queue_voice_install(languages)
        return {"accepted": True, "languages": queued, "already_installing": bool(queued)}

    @app.post("/api/feedback")
    def save_feedback(request: FeedbackRequest):
        try:
            path = feedback.append(request.model_dump())
            return {"saved": True, "file": str(path)}
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.post("/api/replay")
    def replay(request: ReplayRequest):
        try:
            request_id = controller.replay_tts(request.text, request.language)
            return {"queued": bool(request_id), "request_id": request_id}
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.delete("/api/history")
    def clear_history():
        bus.clear_history_and_publish()
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
                    await websocket.send_json({"type": "state", "data": public_state()})
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
