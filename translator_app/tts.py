from __future__ import annotations

import os
import json
import hashlib
import queue
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import numpy as np

os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")

from .audio import PlaybackGate
from .config import AudioConfig, TtsConfig
from .tts_packs import PackSpec, TtsPackManager

MetricsCallback = Callable[..., None]
LOCAL_OUTPUT_PREFIX = "local:"
# Compatibility constants for old integrations. No Edge service is used.
EDGE_OUTPUT_PREFIX = LOCAL_OUTPUT_PREFIX
LEGACY_EDGE_OUTPUT_PREFIX = "edge:"


@dataclass(slots=True)
class SpeechRequest:
    request_id: int
    text: str
    language: str
    queued_at: float
    utterance_id: int | None = None
    speech_ended_at: float = 0.0
    translation_ready_at: float = 0.0


class LocalTtsEngine:
    """Lazy sherpa-onnx runtime shared by all reviewed local model packs."""

    def __init__(self, cfg: TtsConfig, interrupted: threading.Event):
        self.cfg = cfg
        self.interrupted = interrupted
        self.packs = TtsPackManager(cfg.data_root)
        self._models: dict[str, object] = {}
        self._model_lock = threading.RLock()

    def supports(self, language: str) -> bool:
        return self.packs.pack_for_language(language) is not None

    def installed_languages(self) -> set[str]:
        return self.packs.installed_languages()

    def _load(self, spec: PackSpec, root: Path):
        with self._model_lock:
            cached = self._models.get(spec.pack_id)
            if cached is not None:
                return cached
            return self._load_locked(spec, root)

    def _load_locked(self, spec: PackSpec, root: Path):
        self.packs.validate_integrity(spec.pack_id)
        import sherpa_onnx

        if spec.engine == "supertonic":
            model = sherpa_onnx.OfflineTtsSupertonicModelConfig(
                duration_predictor=str(root / "duration_predictor.int8.onnx"),
                text_encoder=str(root / "text_encoder.int8.onnx"),
                vector_estimator=str(root / "vector_estimator.int8.onnx"),
                vocoder=str(root / "vocoder.int8.onnx"),
                tts_json=str(root / "tts.json"),
                unicode_indexer=str(root / "unicode_indexer.bin"),
                voice_style=str(root / "voice.bin"),
            )
            config = sherpa_onnx.OfflineTtsConfig(
                model=sherpa_onnx.OfflineTtsModelConfig(
                    supertonic=model,
                    num_threads=self.cfg.local_threads,
                    provider="cpu",
                    debug=False,
                )
            )
        elif spec.engine == "kokoro":
            # ONNX Runtime and the voice table handle Unicode Windows paths,
            # but Kokoro's eSpeak/lexicon frontend does not. Stage only the
            # small frontend assets and keep the large, verified model in its
            # original location.
            frontend = self._ascii_frontend_copy(spec, root)
            model = sherpa_onnx.OfflineTtsKokoroModelConfig(
                model=str(root / "model.onnx"),
                voices=str(root / "voices.bin"),
                tokens=str(frontend / "tokens.txt"),
                data_dir=str(frontend / "espeak-ng-data"),
                lexicon=",".join(
                    str(frontend / name) for name in ("lexicon-us-en.txt", "lexicon-zh.txt")
                ),
            )
            config = sherpa_onnx.OfflineTtsConfig(
                model=sherpa_onnx.OfflineTtsModelConfig(
                    kokoro=model,
                    num_threads=max(1, min(self.cfg.local_kokoro_threads, os.cpu_count() or 2)),
                    provider="cpu",
                    debug=False,
                ),
            )
        else:
            raise ValueError(f"unsupported local TTS engine: {spec.engine}")
        if not config.validate():
            raise RuntimeError(f"invalid local TTS model pack: {spec.pack_id}")
        loaded = sherpa_onnx.OfflineTts(config)
        self._models[spec.pack_id] = loaded
        return loaded

    def preload(self, language: str) -> str | None:
        selected = self.packs.pack_for_language(language)
        if selected is None:
            return None
        spec, root = selected
        self._load(spec, root)
        return spec.pack_id

    @staticmethod
    def _hash_file(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    def _ascii_frontend_copy(self, spec: PackSpec, source: Path) -> Path:
        """Stage and verify only Unicode-hostile text frontend assets."""
        try:
            str(source).encode("ascii")
            return source
        except UnicodeEncodeError:
            pass
        program_data = Path(os.environ.get("ProgramData", r"C:\ProgramData"))
        target = (
            program_data / "RemotePlusTranslator" / "model-cache"
            / f"{spec.pack_id}-{spec.version}-frontend"
        )
        required_roots = ("tokens.txt", "lexicon-us-en.txt", "lexicon-zh.txt", "espeak-ng-data")
        try:
            receipt = json.loads((source.parent / "pack-receipt.json").read_text(encoding="utf-8"))
            inventory = receipt["files"]
            prefix = f"{spec.archive_root}/"
            required = {
                relative[len(prefix):]: checksum
                for relative, checksum in inventory.items()
                if relative.startswith(prefix)
                and any(
                    relative == prefix + name or relative.startswith(prefix + name + "/")
                    for name in required_roots
                )
            }
            if not required:
                raise ValueError("Kokoro frontend has no integrity inventory")

            def valid_cache() -> bool:
                return target.is_dir() and all(
                    (target / Path(relative)).is_file()
                    and self._hash_file(target / Path(relative)) == checksum
                    for relative, checksum in required.items()
                )

            if valid_cache():
                return target
            target.parent.mkdir(parents=True, exist_ok=True)
            temporary = target.with_name(f".{target.name}-{os.getpid()}")
            shutil.rmtree(temporary, ignore_errors=True)
            try:
                temporary.mkdir(parents=True)
                for name in required_roots:
                    item = source / name
                    destination = temporary / name
                    if item.is_dir():
                        shutil.copytree(item, destination)
                    else:
                        shutil.copy2(item, destination)
                if not all(
                    (temporary / Path(relative)).is_file()
                    and self._hash_file(temporary / Path(relative)) == checksum
                    for relative, checksum in required.items()
                ):
                    raise ValueError("Kokoro frontend cache failed integrity verification")
                shutil.rmtree(target, ignore_errors=True)
                os.replace(temporary, target)
            finally:
                shutil.rmtree(temporary, ignore_errors=True)
            return target
        except OSError as exc:
            raise RuntimeError(
                "Chinese local TTS requires a writable ASCII ProgramData model cache"
            ) from exc

    def synthesize(self, request: SpeechRequest, target: Path) -> str:
        selected = self.packs.pack_for_language(request.language)
        if selected is None:
            raise ValueError(f"No verified local voice pack is installed for '{request.language}'")
        spec, root = selected
        tts = self._load(spec, root)
        import sherpa_onnx

        generation = sherpa_onnx.GenerationConfig()
        generation.sid = (
            spec.default_speaker_id if spec.engine == "kokoro" else self.cfg.local_speaker_id
        )
        generation.speed = self.cfg.local_speed
        generation.num_steps = self.cfg.local_steps
        if spec.engine == "supertonic":
            generation.extra["lang"] = request.language

        # sherpa callback timing/return semantics have differed across model
        # frontends and releases. Hard cancellation is handled by terminating
        # this worker process, so full WAV generation does not rely on it.
        audio = tts.generate(request.text, generation)
        if self.interrupted.is_set():
            raise InterruptedError("Local TTS synthesis was interrupted")
        samples = np.asarray(audio.samples, dtype=np.float32).reshape(-1)
        if not samples.size:
            raise RuntimeError("Local TTS returned empty audio")
        pcm = (np.clip(samples, -1.0, 1.0) * 32767.0).astype("<i2").tobytes()
        with wave.open(str(target), "wb") as output:
            output.setnchannels(1)
            output.setsampwidth(2)
            output.setframerate(int(audio.sample_rate))
            output.writeframes(pcm)
        return spec.pack_id


class ProcessLocalTtsEngine:
    """Persistent local worker that can be terminated during native inference.

    sherpa's model generation is native code. Its callback is not guaranteed to
    run promptly for every architecture, so a Python thread cannot provide a
    hard cancellation boundary. Keeping models in a child process preserves
    warm-model latency while allowing a newer utterance to terminate stale CPU
    work immediately.
    """

    def __init__(self, cfg: TtsConfig, interrupted: threading.Event):
        self.cfg = cfg
        self.interrupted = interrupted
        self.packs = TtsPackManager(cfg.data_root)
        self._process: subprocess.Popen | None = None
        self._process_lock = threading.Lock()
        self._io_lock = threading.Lock()
        self._busy = threading.Event()
        self._log_handle = None

    def supports(self, language: str) -> bool:
        return self.packs.pack_for_language(language) is not None

    def installed_languages(self) -> set[str]:
        return self.packs.installed_languages()

    def _command(self) -> list[str]:
        if getattr(sys, "frozen", False):
            worker = Path(sys.executable).with_name("RemotePlusTtsWorker.exe")
            if not worker.is_file():
                raise RuntimeError("Bundled local TTS worker is missing")
            return [str(worker), "tts-worker"]
        return [sys.executable, "-m", "translator_app.cli", "tts-worker"]

    def _ensure_process(self) -> subprocess.Popen:
        with self._process_lock:
            process = self._process
            if process is not None and process.poll() is None:
                return process
            self._close_log()
            flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
            env = os.environ.copy()
            env["PYTHONUTF8"] = "1"
            process = subprocess.Popen(
                self._command(),
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=self._open_log(),
                text=True,
                encoding="utf-8",
                bufsize=1,
                env=env,
                creationflags=flags,
            )
            self._process = process
            return process

    def _open_log(self):
        log_dir = self.cfg.data_root / "logs"
        try:
            log_dir.mkdir(parents=True, exist_ok=True)
            path = log_dir / "local-tts-worker.log"
            if path.exists() and path.stat().st_size > 1024 * 1024:
                previous = path.with_suffix(".previous.log")
                previous.unlink(missing_ok=True)
                path.replace(previous)
            self._log_handle = path.open("ab", buffering=0)
            return self._log_handle
        except OSError:
            self._log_handle = None
            return subprocess.DEVNULL

    def _close_log(self) -> None:
        handle, self._log_handle = self._log_handle, None
        if handle is not None:
            try:
                handle.close()
            except OSError:
                pass

    def _request(self, payload: dict) -> dict:
        with self._io_lock:
            try:
                self._busy.set()
                process = self._ensure_process()
                if process.stdin is None or process.stdout is None:
                    raise RuntimeError("Local TTS worker pipes are unavailable")
                process.stdin.write(json.dumps(payload, ensure_ascii=False) + "\n")
                process.stdin.flush()
                line = process.stdout.readline()
            except (BrokenPipeError, OSError) as exc:
                raise InterruptedError("Local TTS worker was interrupted") from exc
            finally:
                self._busy.clear()
            if not line:
                if self.interrupted.is_set():
                    raise InterruptedError("Local TTS worker was interrupted")
                raise RuntimeError(f"Local TTS worker exited with code {process.poll()}")
            try:
                response = json.loads(line)
            except json.JSONDecodeError as exc:
                self.interrupt()
                raise RuntimeError("Local TTS worker returned an invalid protocol response") from exc
            if not response.get("ok"):
                raise RuntimeError(str(response.get("error") or "Local TTS worker failed"))
            return response

    def is_busy(self) -> bool:
        return self._busy.is_set()

    def preload(self, language: str) -> str | None:
        if not self.supports(language):
            return None
        return str(self._request({"action": "preload", "language": language}).get("pack_id") or "")

    def synthesize(self, request: SpeechRequest, target: Path) -> str:
        response = self._request({
            "action": "synthesize",
            "request_id": request.request_id,
            "text": request.text,
            "language": request.language,
            "target": str(target),
        })
        if self.interrupted.is_set():
            target.unlink(missing_ok=True)
            raise InterruptedError("Local TTS synthesis was interrupted")
        return str(response["pack_id"])

    def interrupt(self) -> None:
        with self._process_lock:
            process, self._process = self._process, None
        if process is None or process.poll() is not None:
            self._close_log()
            return
        try:
            process.terminate()
            process.wait(timeout=1.0)
        except subprocess.TimeoutExpired:
            process.kill()
            try:
                process.wait(timeout=1.0)
            except subprocess.TimeoutExpired:
                pass
        except OSError:
            pass
        finally:
            self._close_log()

    def close(self) -> None:
        self.interrupt()


def tts_worker_main() -> int:
    """Internal line-delimited JSON worker; never exposed through the web API."""
    from .config import load_config

    cfg = load_config().tts
    interrupted = threading.Event()
    engine = LocalTtsEngine(cfg, interrupted)
    input_stream, output_stream = sys.stdin, sys.stdout
    if input_stream is None or output_stream is None:
        return 2
    # PyInstaller's console bootloader can retain the Windows OEM code page
    # even when the parent sets PYTHONUTF8. The protocol carries arbitrary
    # customer languages, so make its byte contract explicit at both ends.
    for stream in (input_stream, output_stream):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8", errors="strict")
    for line in input_stream:
        try:
            request = json.loads(line)
            action = request.get("action")
            language = str(request.get("language", "")).strip().lower()
            if action == "preload":
                pack_id = engine.preload(language)
            elif action == "synthesize":
                target = Path(str(request["target"]))
                pack_id = engine.synthesize(
                    SpeechRequest(
                        int(request.get("request_id", 0)),
                        str(request["text"]), language, 0.0,
                    ),
                    target,
                )
            else:
                raise ValueError("unsupported local TTS worker action")
            response = {"ok": True, "pack_id": pack_id}
        except Exception as exc:
            response = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
        output_stream.write(json.dumps(response, ensure_ascii=False) + "\n")
        output_stream.flush()
    return 0


class LocalSpeaker(threading.Thread):
    """Offline TTS worker with latest-reply priority and interruptible synthesis."""

    def __init__(
        self,
        cfg: TtsConfig,
        audio_cfg: AudioConfig,
        gate: PlaybackGate,
        status: Callable[[str, str], None],
        metrics: MetricsCallback | None = None,
    ):
        super().__init__(name="local-tts", daemon=True)
        self.cfg = cfg
        self.audio_cfg = audio_cfg
        self.gate = gate
        self.status = status
        self.metrics = metrics
        self._requests: queue.Queue[SpeechRequest] = queue.Queue(maxsize=1)
        self._stop_event = threading.Event()
        self._interrupt_event = threading.Event()
        self._playing = threading.Event()
        self._request_lock = threading.RLock()
        self._next_request_id = 0
        self._latest_request_id = 0
        self._mixer_device_name: str | None = None
        self.engine = ProcessLocalTtsEngine(cfg, self._interrupt_event)
        self._preload_lock = threading.Lock()
        self._preload_requested: set[str] = set()
        self._cleanup_orphan_files()

    @staticmethod
    def _cleanup_orphan_files() -> None:
        cutoff = time.time() - 3600
        try:
            for path in Path(tempfile.gettempdir()).glob("remoteplus-local-*.wav"):
                try:
                    if path.stat().st_mtime < cutoff:
                        path.unlink(missing_ok=True)
                except OSError:
                    continue
        except OSError:
            pass

    def _metric(self, event: str, **fields: object) -> None:
        if self.metrics is not None:
            try:
                self.metrics(event, **fields)
            except Exception:
                pass

    def supports(self, language: str) -> bool:
        return self.engine.supports(language)

    def installed_languages(self) -> set[str]:
        return self.engine.installed_languages()

    def preload(self, language: str) -> None:
        code = language.strip().lower()
        with self._preload_lock:
            if code in self._preload_requested or not self.supports(code):
                return
            self._preload_requested.add(code)

        def load() -> None:
            started = time.monotonic()
            try:
                pack_id = self.engine.preload(code)
                self._metric("tts_preloaded", language=code, pack_id=pack_id or "", seconds=f"{time.monotonic()-started:.3f}")
            except Exception as exc:
                with self._preload_lock:
                    self._preload_requested.discard(code)
                self._metric("tts_preload_failed", language=code, error=repr(exc))

        threading.Thread(target=load, name=f"local-tts-preload-{code}", daemon=True).start()

    def _clear_requests(self, *, reason: str) -> None:
        while True:
            try:
                dropped = self._requests.get_nowait()
            except queue.Empty:
                return
            self._metric("tts_dropped", request_id=dropped.request_id, reason=reason)

    def interrupt(self, *, clear_queue: bool = True, reason: str = "manual") -> None:
        if clear_queue:
            with self._request_lock:
                self._latest_request_id = 0
                self._clear_requests(reason=reason)
        self._interrupt_event.set()
        if self.engine.is_busy():
            self.engine.interrupt()
        self._metric("tts_interrupt_requested", reason=reason)
        try:
            import pygame
            if self._playing.is_set() and pygame.mixer.get_init():
                pygame.mixer.music.stop()
        except Exception:
            pass

    def speak(
        self,
        text: str,
        language: str,
        *,
        utterance_id: int | None = None,
        speech_ended_at: float = 0.0,
        translation_ready_at: float = 0.0,
    ) -> int | None:
        clean = text.strip()
        code = language.strip().lower()
        if not self.cfg.enabled or not clean:
            return None
        with self._request_lock:
            # Keep capability validation in the same transaction as latest-ID
            # assignment. Concurrent replay and translation calls must not let
            # an older call delayed by disk I/O overwrite a newer request.
            if not self.supports(code):
                self._metric("tts_not_queued", utterance_id=utterance_id or 0, reason="voice_pack_missing", language=code)
                return None
            if self.cfg.latest_only:
                self._latest_request_id = 0
                self._clear_requests(reason="newer_tts_request")
                self._interrupt_event.set()
                if self.engine.is_busy():
                    self.engine.interrupt()
            self._next_request_id += 1
            request = SpeechRequest(
                self._next_request_id, clean, code, time.monotonic(), utterance_id,
                speech_ended_at, translation_ready_at,
            )
            self._latest_request_id = request.request_id
            try:
                self._requests.put_nowait(request)
            except queue.Full:
                self._clear_requests(reason="tts_queue_replaced")
                self._requests.put_nowait(request)
        self._metric("tts_queued", request_id=request.request_id, backend="local", language=code)
        return request.request_id

    def _is_latest_request(self, request: SpeechRequest) -> bool:
        with self._request_lock:
            return request.request_id == self._latest_request_id

    @staticmethod
    def output_devices() -> list[dict[str, str]]:
        initialized_here = False
        try:
            import pygame
            from pygame._sdl2 import audio as sdl_audio
            if not pygame.mixer.get_init():
                pygame.mixer.init(buffer=256)
                initialized_here = True
            return [
                {"id": f"{LOCAL_OUTPUT_PREFIX}{name}", "name": str(name)}
                for name in tuple(sdl_audio.get_audio_device_names(False) or ())
                if str(name).strip()
            ]
        except Exception:
            return []
        finally:
            if initialized_here:
                try:
                    import pygame
                    pygame.mixer.quit()
                except Exception:
                    pass

    def _requested_output_name(self) -> str | None:
        selected = str(self.audio_cfg.output_device or "default")
        if selected == "default":
            return None
        for prefix in (LOCAL_OUTPUT_PREFIX, LEGACY_EDGE_OUTPUT_PREFIX):
            if selected.startswith(prefix):
                return selected[len(prefix):] or None
        return None

    def _ensure_mixer_output(self, pygame) -> None:
        requested = self._requested_output_name()
        if pygame.mixer.get_init() and self._mixer_device_name == requested:
            return
        if pygame.mixer.get_init():
            pygame.mixer.quit()
        try:
            pygame.mixer.init(buffer=256, **({"devicename": requested} if requested else {}))
            self._mixer_device_name = requested
        except Exception:
            self.audio_cfg.output_device = "default"
            self._mixer_device_name = None
            pygame.mixer.init(buffer=256)
            self.status("warning", "Selected audio output is unavailable; using system default")

    def _synthesize(self, request: SpeechRequest) -> tuple[Path, str]:
        handle = tempfile.NamedTemporaryFile(prefix="remoteplus-local-", suffix=".wav", delete=False)
        path = Path(handle.name)
        handle.close()
        try:
            pack_id = self.engine.synthesize(request, path)
            return path, pack_id
        except Exception:
            path.unlink(missing_ok=True)
            raise

    def _play(self, request: SpeechRequest, begin_playback: Callable[[], None]) -> None:
        if not self._is_latest_request(request):
            return
        import pygame
        self._ensure_mixer_output(pygame)
        started = time.monotonic()
        path, pack_id = self._synthesize(request)
        self._metric("tts_local_generated", request_id=request.request_id, pack_id=pack_id, synthesis_seconds=f"{time.monotonic()-started:.3f}")
        try:
            if self._interrupt_event.is_set() or not self._is_latest_request(request):
                return
            pygame.mixer.music.load(str(path))
            pygame.mixer.music.set_volume(float(self.cfg.volume))
            begin_playback()
            pygame.mixer.music.play()
            while pygame.mixer.music.get_busy() and not self._stop_event.is_set():
                if self._interrupt_event.is_set():
                    pygame.mixer.music.stop()
                    raise InterruptedError("Local TTS playback was interrupted")
                time.sleep(0.02)
        finally:
            try:
                pygame.mixer.music.unload()
            except Exception:
                pass
            path.unlink(missing_ok=True)

    def run(self) -> None:
        try:
            while not self._stop_event.is_set():
                try:
                    request = self._requests.get(timeout=0.2)
                except queue.Empty:
                    continue
                self._interrupt_event.clear()
                self._playing.set()
                gate_started = False

                def begin_playback() -> None:
                    nonlocal gate_started
                    if not gate_started:
                        gate_started = True
                        self.gate.begin()
                        self.status("speaking", "Speaking translated reply")

                try:
                    self._play(request, begin_playback)
                    self.status("listening", "Listening")
                except InterruptedError:
                    self.status("listening", "Listening")
                except Exception as exc:
                    self._metric("tts_failed", request_id=request.request_id, error=repr(exc))
                    self.status("warning", f"Local TTS failed: {exc}")
                finally:
                    self._playing.clear()
                    if gate_started:
                        self.gate.end()
        finally:
            try:
                import pygame
                if pygame.mixer.get_init():
                    pygame.mixer.music.stop()
                    pygame.mixer.quit()
            except Exception:
                pass

    def stop(self) -> None:
        self._stop_event.set()
        self.interrupt(clear_queue=True, reason="shutdown")
        self.engine.close()


# Kept as a source-compatible alias for older integrations. It is fully local.
EdgeSpeaker = LocalSpeaker
