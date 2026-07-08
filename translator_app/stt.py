from __future__ import annotations

import re
import threading
from dataclasses import dataclass
from typing import Callable

import numpy as np

from .config import SttConfig


# faster-whisper/Hugging Face model initialization may touch shared progress
# state and cache locks. Keep model construction single-file so the final and
# live models never initialize concurrently in the same Python process.
_MODEL_LOAD_LOCK = threading.Lock()


@dataclass(slots=True)
class Recognition:
    text: str
    language: str
    probability: float = 1.0


def contains_japanese_kana(text: str) -> bool:
    return len(re.findall(r"[ぁ-ゖァ-ヺー]", text)) >= 2


def _compile_correction_pattern(corrections: dict[str, str]) -> re.Pattern[str] | None:
    if not corrections:
        return None
    phrases = sorted(corrections, key=len, reverse=True)
    return re.compile("|".join(re.escape(phrase) for phrase in phrases))


def apply_corrections(text: str, corrections: dict[str, str]) -> str:
    pattern = _compile_correction_pattern(corrections)
    if pattern is None:
        return text
    return pattern.sub(lambda match: corrections[match.group(0)], text)


class WhisperRecognizer:
    """One fixed-language Whisper model instance.

    The final and live-caption paths each own an instance. They never share a
    model object, so a live decode cannot wait for or mutate a final decode.
    """

    def __init__(
        self,
        cfg: SttConfig,
        status: Callable[[str, str], None],
        *,
        model_name: str | None = None,
        cpu_threads: int | None = None,
        beam_size: int | None = None,
        hotwords_max_items: int | None = None,
        apply_corrections: bool = True,
        label: str = "final",
    ):
        self.cfg = cfg
        self.status = status
        self.model = None
        self.label = label
        self.model_name = model_name or cfg.model
        self.cpu_threads = max(1, int(cpu_threads or cfg.cpu_threads))
        self.beam_size = max(1, int(beam_size or cfg.beam_size))
        self.hotwords_max_items = hotwords_max_items
        self.apply_corrections = apply_corrections
        self.context_language: str | None = None
        self.selected_language: str = cfg.language
        self.enabled_languages: list[str] = []
        self._correction_pattern = _compile_correction_pattern(cfg.corrections)
        self._hotwords_cache_key: tuple[str | None, str, int] | None = None
        self._hotwords_cache: str | None = None

    def set_context_language(self, language: str | None) -> None:
        self.context_language = language
        self._hotwords_cache_key = None

    def set_selected_language(self, language: str) -> None:
        language = str(language).strip().lower()
        self.selected_language = language
        self.set_context_language(None if language == "auto" else language)

    def set_enabled_languages(self, languages: list[str]) -> None:
        self.enabled_languages = list(dict.fromkeys(str(code).strip().lower() for code in languages if code))

    def _effective_language(self, language: str | None = None) -> str:
        chosen = str(language or self.selected_language).strip().lower()
        if chosen != "auto":
            return chosen
        if self.enabled_languages:
            return self.enabled_languages[0]
        raise RuntimeError("Select a customer language before starting speech recognition")

    def _hotwords(self, language: str | None = None) -> str | None:
        language = self.context_language or self._effective_language(language)
        limit = self.hotwords_max_items
        if limit is None:
            limit = len(self.cfg.hotwords) + len(self.cfg.language_hotwords.get(language, []))
        limit = max(0, int(limit))
        key = (self.context_language, language, limit)
        if key == self._hotwords_cache_key:
            return self._hotwords_cache
        if limit == 0:
            self._hotwords_cache_key = key
            self._hotwords_cache = None
            return None
        words = list(self.cfg.hotwords)
        words.extend(self.cfg.language_hotwords.get(language, []))
        if self.context_language and self.context_language != language:
            words.extend(self.cfg.language_hotwords.get(self.context_language, []))
        self._hotwords_cache_key = key
        self._hotwords_cache = ", ".join(list(dict.fromkeys(word for word in words if word.strip()))[:limit]) or None
        return self._hotwords_cache

    def load(self) -> None:
        if self.model is not None:
            return

        # Do not initialize the live and final models in parallel. Besides competing for
        # CPU/RAM, concurrent first-run downloads can race inside tqdm/cache
        # handling on Windows. This lock is held only during startup/model load,
        # never during transcription.
        with _MODEL_LOAD_LOCK:
            if self.model is not None:
                return
            self.status("loading", f"Loading {self.label} speech model")
            from faster_whisper import WhisperModel
            root = str(self.cfg.root / "models" / "whisper")
            try:
                self.model = WhisperModel(
                    self.model_name,
                    device=self.cfg.device,
                    compute_type=self.cfg.compute_type,
                    download_root=root,
                    cpu_threads=self.cpu_threads,
                    num_workers=max(1, int(self.cfg.num_workers)),
                )
            except Exception:
                if self.cfg.device == "cpu" and self.cfg.compute_type == "int8":
                    raise
                self.status("warning", "Configured STT device failed; retrying on CPU INT8")
                self.model = WhisperModel(
                    self.model_name,
                    device="cpu",
                    compute_type="int8",
                    download_root=root,
                    cpu_threads=self.cpu_threads,
                    num_workers=max(1, int(self.cfg.num_workers)),
                )

    def transcribe(self, audio: np.ndarray, *, language: str | None = None) -> Recognition:
        self.load()
        if self.model is None:
            raise RuntimeError("Speech model is not loaded")
        auto_mode = language is None and self.selected_language == "auto"
        forced = None if auto_mode else self._effective_language(language)
        hotword_language = forced or self.context_language or (self.enabled_languages[0] if self.enabled_languages else "en")
        segments, _info = self.model.transcribe(
            audio,
            language=forced,
            beam_size=self.beam_size,
            best_of=1,
            temperature=0.0,
            condition_on_previous_text=False,
            hotwords=self._hotwords(hotword_language),
            vad_filter=False,
            without_timestamps=True,
        )
        text = " ".join(segment.text.strip() for segment in segments).strip()
        if text and self.apply_corrections and self._correction_pattern is not None:
            text = apply_corrections(text, self.cfg.corrections)
        detected = forced or getattr(_info, "language", "") or hotword_language
        probability = float(getattr(_info, "language_probability", 1.0))
        return Recognition(text=text, language=detected, probability=probability)
