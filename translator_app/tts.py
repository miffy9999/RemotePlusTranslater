from __future__ import annotations

import asyncio
import queue
import tempfile
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .audio import PlaybackGate
from .config import AudioConfig, TtsConfig

MetricsCallback = Callable[..., None]

# Supported customer languages plus Japanese employee speech.
EDGE_OUTPUT_PREFIX = "edge:"

# Device names below are SDL/Pygame names, not Windows SAPI identifiers.
EDGE_VOICES: dict[str, str] = {
    "ja": "ja-JP-NanamiNeural",
    "en": "en-US-JennyNeural",
    "ko": "ko-KR-SunHiNeural",
    "zh": "zh-CN-XiaoxiaoNeural",
    "es": "es-ES-ElviraNeural",
    "fr": "fr-FR-DeniseNeural",
    "de": "de-DE-KatjaNeural",
    "it": "it-IT-ElsaNeural",
    "pt": "pt-BR-FranciscaNeural",
    "ru": "ru-RU-SvetlanaNeural",
    "ar": "ar-SA-ZariyahNeural",
    "hi": "hi-IN-SwaraNeural",
    "vi": "vi-VN-HoaiMyNeural",
    "th": "th-TH-PremwadeeNeural",
    "id": "id-ID-GadisNeural",
    "ms": "ms-MY-YasminNeural",
    "tr": "tr-TR-EmelNeural",
    "nl": "nl-NL-ColetteNeural",
    "pl": "pl-PL-ZofiaNeural",
    "uk": "uk-UA-PolinaNeural",
    "cs": "cs-CZ-VlastaNeural",
    "he": "he-IL-HilaNeural",
}


@dataclass(slots=True)
class SpeechRequest:
    request_id: int
    text: str
    language: str
    queued_at: float
    utterance_id: int | None = None
    speech_ended_at: float = 0.0
    translation_ready_at: float = 0.0


class EdgeSpeaker(threading.Thread):
    """Online Edge Neural TTS with latest-answer priority.

    This implementation has no Windows SAPI or language-pack dependency. It
    downloads a compact MP3 for each reply and plays it through the Windows
    default audio output. A newer reply interrupts both queued and playing
    audio so an outdated hotel response is not spoken after the conversation
    has moved on.
    """

    def __init__(
        self,
        cfg: TtsConfig,
        audio_cfg: AudioConfig,
        gate: PlaybackGate,
        status: Callable[[str, str], None],
        metrics: MetricsCallback | None = None,
    ):
        super().__init__(name="edge-tts", daemon=True)
        self.cfg = cfg
        self.audio_cfg = audio_cfg
        self.gate = gate
        self.status = status
        self.metrics = metrics
        self._requests: queue.Queue[SpeechRequest] = queue.Queue(maxsize=1)
        self._stop_event = threading.Event()
        self._interrupt_event = threading.Event()
        self._playing = threading.Event()
        self._request_lock = threading.Lock()
        self._next_request_id = 0
        self._mixer_device_name: str | None = None

    def _metric(self, event: str, **fields: object) -> None:
        if self.metrics is None:
            return
        try:
            self.metrics(event, **fields)
        except Exception:
            pass

    def _clear_requests(self, *, reason: str) -> None:
        while True:
            try:
                dropped = self._requests.get_nowait()
            except queue.Empty:
                return
            self._metric(
                "tts_dropped",
                request_id=dropped.request_id,
                utterance_id=dropped.utterance_id or 0,
                reason=reason,
            )

    def interrupt(self, *, clear_queue: bool = True, reason: str = "manual") -> None:
        if self._playing.is_set():
            self._interrupt_event.set()
            self._metric("tts_interrupt_requested", reason=reason)
        if clear_queue:
            self._clear_requests(reason=reason)

    def speak(
        self,
        text: str,
        language: str,
        *,
        utterance_id: int | None = None,
        speech_ended_at: float = 0.0,
        translation_ready_at: float = 0.0,
    ) -> int | None:
        if not self.cfg.enabled:
            self._metric("tts_not_queued", utterance_id=utterance_id or 0, reason="tts_disabled")
            return None
        clean = text.strip()
        if not clean:
            return None
        with self._request_lock:
            self._next_request_id += 1
            request_id = self._next_request_id
        if self.cfg.latest_only:
            self.interrupt(clear_queue=True, reason="newer_tts_request")
        request = SpeechRequest(
            request_id=request_id,
            text=clean,
            language=language.strip().lower(),
            queued_at=time.monotonic(),
            utterance_id=utterance_id,
            speech_ended_at=speech_ended_at,
            translation_ready_at=translation_ready_at,
        )
        try:
            self._requests.put_nowait(request)
        except queue.Full:
            self._clear_requests(reason="tts_queue_replaced")
            try:
                self._requests.put_nowait(request)
            except queue.Full:
                self._metric("tts_dropped", request_id=request_id, utterance_id=utterance_id or 0, reason="tts_queue_full")
                return None
        self._metric(
            "tts_queued",
            request_id=request_id,
            utterance_id=utterance_id or 0,
            characters=len(clean),
            backend="edge",
            queue_depth_after=self._requests.qsize(),
            translation_to_tts_queue_seconds=(
                f"{max(0.0, request.queued_at - translation_ready_at):.3f}"
                if translation_ready_at else "0.000"
            ),
        )
        return request_id

    @staticmethod
    def output_devices() -> list[dict[str, str]]:
        """Return output choices understood by the SDL mixer used for Edge TTS."""
        initialized_here = False
        try:
            import pygame
            from pygame._sdl2 import audio as sdl_audio

            if not pygame.mixer.get_init():
                pygame.mixer.init(buffer=256)
                initialized_here = True
            names = tuple(sdl_audio.get_audio_device_names(False) or ())
            return [
                {"id": f"{EDGE_OUTPUT_PREFIX}{name}", "name": str(name)}
                for name in names
                if str(name).strip()
            ]
        except Exception:
            # The default output remains usable even when SDL cannot enumerate.
            return []
        finally:
            if initialized_here:
                try:
                    import pygame
                    pygame.mixer.quit()
                except Exception:
                    pass

    def _voice(self, language: str) -> str:
        return self.cfg.edge_voice_overrides.get(language) or EDGE_VOICES.get(language) or EDGE_VOICES["en"]

    def _requested_output_name(self) -> str | None:
        selected = str(self.audio_cfg.output_device or "default")
        if selected == "default":
            return None
        if selected.startswith(EDGE_OUTPUT_PREFIX):
            return selected[len(EDGE_OUTPUT_PREFIX):] or None
        # Old SAPI/soundcard values cannot be used by SDL. Keep audio working.
        return None

    def _ensure_mixer_output(self, pygame) -> None:
        requested = self._requested_output_name()
        current_ready = bool(pygame.mixer.get_init())
        if current_ready and self._mixer_device_name == requested:
            return

        if current_ready:
            try:
                pygame.mixer.music.stop()
            except Exception:
                pass
            pygame.mixer.quit()

        try:
            if requested is None:
                pygame.mixer.init(buffer=256)
            else:
                pygame.mixer.init(buffer=256, devicename=requested)
            self._mixer_device_name = requested
            self._metric(
                "tts_output_selected",
                output_device=(requested or "default"),
            )
        except Exception as exc:
            if requested is None:
                raise
            self.audio_cfg.output_device = "default"
            self._mixer_device_name = None
            pygame.mixer.init(buffer=256)
            self._metric(
                "tts_output_fallback",
                requested_output=requested,
                error=repr(exc),
            )
            self.status("warning", "Selected audio output is unavailable; using system default")

    async def _save_edge(self, text: str, voice: str, target: str) -> None:
        import edge_tts
        await edge_tts.Communicate(text, voice, rate=self.cfg.edge_rate).save(target)

    def _synthesize(self, request: SpeechRequest) -> Path:
        handle = tempfile.NamedTemporaryFile(prefix="remoteplus-edge-", suffix=".mp3", delete=False)
        output = Path(handle.name)
        handle.close()
        try:
            asyncio.run(asyncio.wait_for(
                self._save_edge(request.text, self._voice(request.language), str(output)),
                timeout=self.cfg.edge_timeout_seconds,
            ))
            if not output.exists() or output.stat().st_size < 1024:
                raise RuntimeError("Edge TTS returned an empty audio file")
            return output
        except Exception:
            output.unlink(missing_ok=True)
            raise

    def _play(self, request: SpeechRequest, begin_playback: Callable[[], None]) -> None:
        import pygame

        self._ensure_mixer_output(pygame)
        synthesized_at = time.monotonic()
        path = self._synthesize(request)
        self._metric(
            "tts_edge_generated",
            request_id=request.request_id,
            utterance_id=request.utterance_id or 0,
            synthesis_seconds=f"{time.monotonic() - synthesized_at:.3f}",
        )
        try:
            if self._stop_event.is_set() or self._interrupt_event.is_set():
                self._metric("tts_interrupted", request_id=request.request_id, utterance_id=request.utterance_id or 0, stage="before_playback")
                return
            pygame.mixer.music.load(str(path))
            pygame.mixer.music.set_volume(float(self.cfg.volume))
            begin_playback()
            pygame.mixer.music.play()
            while pygame.mixer.music.get_busy() and not self._stop_event.is_set():
                if self._interrupt_event.is_set():
                    pygame.mixer.music.stop()
                    self._metric("tts_interrupted", request_id=request.request_id, utterance_id=request.utterance_id or 0, stage="playback")
                    return
                time.sleep(0.02)
        finally:
            try:
                pygame.mixer.music.unload()
            except Exception:
                pass
            path.unlink(missing_ok=True)

    def run(self) -> None:
        while not self._stop_event.is_set():
            try:
                request = self._requests.get(timeout=0.2)
            except queue.Empty:
                continue

            self._interrupt_event.clear()
            self._playing.set()
            dequeued_at = time.monotonic()
            self._metric(
                "tts_dequeued",
                request_id=request.request_id,
                utterance_id=request.utterance_id or 0,
                queue_wait_seconds=f"{max(0.0, dequeued_at - request.queued_at):.3f}",
                queue_depth_after=self._requests.qsize(),
            )
            gate_started = False
            started_at = 0.0

            def begin_playback() -> None:
                nonlocal gate_started, started_at
                if gate_started:
                    return
                gate_started = True
                started_at = time.monotonic()
                self.gate.begin()
                self.status("speaking", "Speaking translated reply")
                self._metric(
                    "tts_playback_started",
                    request_id=request.request_id,
                    utterance_id=request.utterance_id or 0,
                    backend="edge",
                    speech_end_to_tts_start_seconds=(
                        f"{max(0.0, started_at - request.speech_ended_at):.3f}"
                        if request.speech_ended_at else "0.000"
                    ),
                    translation_to_tts_start_seconds=(
                        f"{max(0.0, started_at - request.translation_ready_at):.3f}"
                        if request.translation_ready_at else "0.000"
                    ),
                )

            try:
                self._play(request, begin_playback)
                finished_at = time.monotonic()
                self._metric(
                    "tts_playback_finished",
                    request_id=request.request_id,
                    utterance_id=request.utterance_id or 0,
                    backend="edge",
                    playback_seconds=(f"{max(0.0, finished_at - started_at):.3f}" if started_at else "0.000"),
                    speech_end_to_tts_finish_seconds=(
                        f"{max(0.0, finished_at - request.speech_ended_at):.3f}"
                        if request.speech_ended_at else "0.000"
                    ),
                )
                self.status("listening", "Listening")
            except Exception as exc:
                self._metric("tts_failed", request_id=request.request_id, utterance_id=request.utterance_id or 0, error=repr(exc))
                self.status("warning", f"Online TTS failed: {exc}")
            finally:
                self._playing.clear()
                if gate_started:
                    self.gate.end()

    def stop(self) -> None:
        self._stop_event.set()
        self.interrupt(clear_queue=True, reason="shutdown")
