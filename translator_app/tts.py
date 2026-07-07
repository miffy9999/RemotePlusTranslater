from __future__ import annotations

import queue
import re
import threading
import time
from dataclasses import dataclass
from typing import Callable

from .audio import OUTPUT_PREFIX, PlaybackGate
from .config import AudioConfig, TtsConfig
from .languages import get_language


MetricsCallback = Callable[..., None]


def _lcids(value: str) -> set[str]:
    return {
        part.strip().lower().lstrip("0")
        for part in value.split(";")
        if part.strip()
    }


def _device_guid(value: str) -> str | None:
    matches = re.findall(
        r"\{[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-"
        r"[0-9a-f]{4}-[0-9a-f]{12}\}",
        value,
        re.IGNORECASE,
    )
    return matches[-1].casefold() if matches else None


@dataclass(slots=True)
class SpeechRequest:
    request_id: int
    text: str
    language: str
    queued_at: float
    utterance_id: int | None = None
    speech_ended_at: float = 0.0
    translation_ready_at: float = 0.0


class SapiSpeaker(threading.Thread):
    """Windows SAPI speaker with queue and playback timing diagnostics."""

    def __init__(
        self,
        cfg: TtsConfig,
        audio_cfg: AudioConfig,
        gate: PlaybackGate,
        status: Callable[[str, str], None],
        metrics: MetricsCallback | None = None,
    ):
        super().__init__(name="tts", daemon=True)
        self.cfg = cfg
        self.audio_cfg = audio_cfg
        self.gate = gate
        self.status = status
        self.metrics = metrics

        self._requests: queue.Queue[SpeechRequest] = queue.Queue(maxsize=3)
        self._stop_event = threading.Event()
        self._voice_cache: dict[str, object] = {}
        self._request_lock = threading.Lock()
        self._next_request_id = 0

    def _metric(self, event: str, **fields: object) -> None:
        if self.metrics is None:
            return

        try:
            self.metrics(event, **fields)
        except Exception:
            # Diagnostics must never interrupt playback.
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
        """Queue a request and return its trace ID, or None when dropped."""
        if not self.cfg.enabled:
            self._metric(
                "tts_not_queued",
                utterance_id=utterance_id or 0,
                reason="tts_disabled",
            )
            return None

        with self._request_lock:
            self._next_request_id += 1
            request_id = self._next_request_id

        queued_at = time.monotonic()
        request = SpeechRequest(
            request_id=request_id,
            text=text,
            language=language,
            queued_at=queued_at,
            utterance_id=utterance_id,
            speech_ended_at=speech_ended_at,
            translation_ready_at=translation_ready_at,
        )
        queue_before = self._requests.qsize()

        try:
            self._requests.put_nowait(request)

            self._metric(
                "tts_queued",
                request_id=request_id,
                utterance_id=utterance_id or 0,
                characters=len(text),
                queue_depth_before=queue_before,
                queue_depth_after=self._requests.qsize(),
                translation_to_tts_queue_seconds=(
                    f"{max(0.0, queued_at - translation_ready_at):.3f}"
                    if translation_ready_at
                    else "0.000"
                ),
            )
            return request_id

        except queue.Full:
            self._metric(
                "tts_dropped",
                request_id=request_id,
                utterance_id=utterance_id or 0,
                reason="tts_queue_full",
                queue_depth=queue_before,
            )
            self.status(
                "warning",
                "TTS queue is full; speech output was skipped",
            )
            return None

    @staticmethod
    def installed_voices() -> list[dict[str, str]]:
        import pythoncom
        import win32com.client

        pythoncom.CoInitialize()

        try:
            speaker = win32com.client.Dispatch("SAPI.SpVoice")
            tokens = speaker.GetVoices()

            result = [
                {
                    "name": voice.GetDescription(),
                    "language": str(
                        voice.GetAttribute("Language")
                    ).lower(),
                    "id": str(voice.Id),
                }
                for voice in tokens
            ]

            del tokens, speaker
            return result

        finally:
            pythoncom.CoUninitialize()

    @classmethod
    def voice_status(
        cls,
        language_codes: list[str],
    ) -> list[dict[str, str | bool]]:
        voices = cls.installed_voices()
        installed_lcids = set().union(
            *(
                _lcids(str(voice["language"]))
                for voice in voices
            )
        )

        result = []

        for code in language_codes:
            item = get_language(code)

            if item is None:
                continue

            wanted = {
                value.lower().lstrip("0")
                for value in item.sapi_lcids or ()
            }

            result.append(
                {
                    "code": code,
                    "name": item.name,
                    "native_name": item.native_name,
                    "installed": bool(wanted & installed_lcids),
                }
            )

        return result

    def _select_voice(self, speaker, language: str):
        if language in self._voice_cache:
            return self._voice_cache[language]

        item = get_language(language)

        if item is None or item.sapi_lcids is None:
            raise ValueError(
                f"No Windows voice mapping for language '{language}'"
            )

        wanted = {
            value.lower().lstrip("0")
            for value in item.sapi_lcids
        }

        for voice in speaker.GetVoices():
            actual = _lcids(str(voice.GetAttribute("Language")))

            if actual & wanted:
                self._voice_cache[language] = voice
                return voice

        raise RuntimeError(
            f"{item.native_name} Windows voice is not installed. "
            "Install its Speech language pack."
        )

    def _select_output(self, speaker, default_output) -> None:
        selected = self.audio_cfg.output_device

        if selected == "default":
            speaker.AudioOutput = default_output
            return

        device_id = str(selected)

        if device_id.startswith(OUTPUT_PREFIX):
            device_id = device_id[len(OUTPUT_PREFIX):]

        wanted_guid = _device_guid(device_id)

        for output in speaker.GetAudioOutputs():
            actual_guid = _device_guid(str(output.Id))

            if wanted_guid is not None and actual_guid == wanted_guid:
                speaker.AudioOutput = output
                return

        self.audio_cfg.output_device = "default"
        speaker.AudioOutput = default_output
        self.status(
            "warning",
            "Selected output disappeared; using the system default",
        )

    def run(self) -> None:
        import pythoncom
        import win32com.client

        pythoncom.CoInitialize()

        try:
            speaker = win32com.client.Dispatch("SAPI.SpVoice")
            default_output = speaker.AudioOutput
            speaker.Volume = round(self.cfg.volume * 100)

            while not self._stop_event.is_set():
                try:
                    request = self._requests.get(timeout=0.2)
                except queue.Empty:
                    continue

                dequeued_at = time.monotonic()

                self._metric(
                    "tts_dequeued",
                    request_id=request.request_id,
                    utterance_id=request.utterance_id or 0,
                    queue_wait_seconds=(
                        f"{max(0.0, dequeued_at - request.queued_at):.3f}"
                    ),
                    queue_depth_after=self._requests.qsize(),
                )

                try:
                    prepare_started = time.monotonic()

                    speaker.Volume = round(self.cfg.volume * 100)
                    self._select_output(speaker, default_output)
                    speaker.Voice = self._select_voice(
                        speaker,
                        request.language,
                    )

                    prepare_seconds = time.monotonic() - prepare_started
                    playback_started_at = time.monotonic()

                    self.gate.begin()
                    self.status("speaking", "Speaking translated reply")

                    self._metric(
                        "tts_playback_started",
                        request_id=request.request_id,
                        utterance_id=request.utterance_id or 0,
                        voice_prepare_seconds=f"{prepare_seconds:.3f}",
                        speech_end_to_tts_start_seconds=(
                            f"{max(0.0, playback_started_at - request.speech_ended_at):.3f}"
                            if request.speech_ended_at
                            else "0.000"
                        ),
                        translation_to_tts_start_seconds=(
                            f"{max(0.0, playback_started_at - request.translation_ready_at):.3f}"
                            if request.translation_ready_at
                            else "0.000"
                        ),
                    )

                    # SAPI Speak is synchronous: return means playback has finished.
                    speaker.Speak(request.text)

                    playback_finished_at = time.monotonic()

                    self._metric(
                        "tts_playback_finished",
                        request_id=request.request_id,
                        utterance_id=request.utterance_id or 0,
                        playback_seconds=(
                            f"{max(0.0, playback_finished_at - playback_started_at):.3f}"
                        ),
                        speech_end_to_tts_finish_seconds=(
                            f"{max(0.0, playback_finished_at - request.speech_ended_at):.3f}"
                            if request.speech_ended_at
                            else "0.000"
                        ),
                    )

                    self.status("listening", "Listening")

                except Exception as exc:
                    self._metric(
                        "tts_failed",
                        request_id=request.request_id,
                        utterance_id=request.utterance_id or 0,
                        error=repr(exc),
                    )
                    self.status("error", f"TTS failed: {exc}")

                finally:
                    self.gate.end()

        finally:
            pythoncom.CoUninitialize()

    def stop(self) -> None:
        self._stop_event.set()
