from __future__ import annotations

import queue
import re
import threading
from dataclasses import dataclass
from typing import Callable

from .audio import OUTPUT_PREFIX, PlaybackGate
from .config import AudioConfig, TtsConfig
from .languages import get_language


def _lcids(value: str) -> set[str]:
    return {part.strip().lower().lstrip("0") for part in value.split(";") if part.strip()}


def _device_guid(value: str) -> str | None:
    matches = re.findall(
        r"\{[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\}",
        value,
        re.IGNORECASE,
    )
    return matches[-1].casefold() if matches else None


@dataclass(slots=True)
class SpeechRequest:
    text: str
    language: str


class SapiSpeaker(threading.Thread):
    """Windows-installed voices: offline, commercially safe OS baseline."""

    def __init__(
        self,
        cfg: TtsConfig,
        audio_cfg: AudioConfig,
        gate: PlaybackGate,
        status: Callable[[str, str], None],
    ):
        super().__init__(name="tts", daemon=True)
        self.cfg = cfg
        self.audio_cfg = audio_cfg
        self.gate = gate
        self.status = status
        self._requests: queue.Queue[SpeechRequest] = queue.Queue(maxsize=3)
        self._stop_event = threading.Event()
        self._voice_cache: dict[str, object] = {}

    def speak(self, text: str, language: str) -> None:
        if not self.cfg.enabled:
            return
        try:
            self._requests.put_nowait(SpeechRequest(text, language))
        except queue.Full:
            self.status("warning", "TTS queue is full; speech output was skipped")

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
                    "language": str(voice.GetAttribute("Language")).lower(),
                    "id": str(voice.Id),
                }
                for voice in tokens
            ]
            del tokens, speaker
            return result
        finally:
            pythoncom.CoUninitialize()

    @classmethod
    def voice_status(cls, language_codes: list[str]) -> list[dict[str, str | bool]]:
        voices = cls.installed_voices()
        installed_lcids = set().union(*(_lcids(str(voice["language"])) for voice in voices))
        result = []
        for code in language_codes:
            item = get_language(code)
            if item is None:
                continue
            wanted = {value.lower().lstrip("0") for value in item.sapi_lcids or ()}
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
            raise ValueError(f"No Windows voice mapping for language '{language}'")
        wanted = {value.lower().lstrip("0") for value in item.sapi_lcids}
        for voice in speaker.GetVoices():
            actual = _lcids(str(voice.GetAttribute("Language")))
            if actual & wanted:
                self._voice_cache[language] = voice
                return voice
        raise RuntimeError(
            f"{item.native_name} Windows voice is not installed. Install its Speech language pack."
        )

    def _select_output(self, speaker, default_output) -> None:
        selected = self.audio_cfg.output_device
        if selected == "default":
            speaker.AudioOutput = default_output
            return
        device_id = str(selected)
        if device_id.startswith(OUTPUT_PREFIX):
            device_id = device_id[len(OUTPUT_PREFIX) :]
        wanted_guid = _device_guid(device_id)
        for output in speaker.GetAudioOutputs():
            actual_guid = _device_guid(str(output.Id))
            if wanted_guid is not None and actual_guid == wanted_guid:
                speaker.AudioOutput = output
                return
        self.audio_cfg.output_device = "default"
        speaker.AudioOutput = default_output
        self.status("warning", "Selected output disappeared; using the system default")

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
                try:
                    speaker.Volume = round(self.cfg.volume * 100)
                    self._select_output(speaker, default_output)
                    speaker.Voice = self._select_voice(speaker, request.language)
                    self.gate.begin()
                    self.status("speaking", "Speaking translated reply")
                    speaker.Speak(request.text)
                    self.status("listening", "Listening")
                except Exception as exc:
                    self.status("error", f"TTS failed: {exc}")
                finally:
                    self.gate.end()
        finally:
            pythoncom.CoUninitialize()

    def stop(self) -> None:
        self._stop_event.set()
