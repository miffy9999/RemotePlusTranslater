from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Callable

import numpy as np

from .config import SttConfig


@dataclass(slots=True)
class Recognition:
    text: str
    language: str
    probability: float


def apply_corrections(text: str, corrections: dict[str, str]) -> str:
    """Apply explicit domain corrections, longest phrase first."""
    if not corrections:
        return text

    phrases = sorted(corrections, key=len, reverse=True)
    pattern = re.compile("|".join(re.escape(phrase) for phrase in phrases))
    return pattern.sub(lambda match: corrections[match.group(0)], text)


def contains_japanese_kana(text: str) -> bool:
    """Kept for compatibility with other modules."""
    return len(re.findall(r"[ぁ-ゖァ-ヺー]", text)) >= 2


def _compile_correction_pattern(
    corrections: dict[str, str],
) -> re.Pattern[str] | None:
    if not corrections:
        return None

    phrases = sorted(corrections, key=len, reverse=True)
    return re.compile("|".join(re.escape(phrase) for phrase in phrases))


class WhisperRecognizer:
    """
    Fixed-language recognizer for low-latency turn taking.

    The controller selects either the customer language or Japanese before each
    utterance. This class deliberately never calls detect_language() and never
    runs a second transcription pass.
    """

    def __init__(self, cfg: SttConfig, status: Callable[[str, str], None]):
        self.cfg = cfg
        self.status = status
        self.model = None

        self.context_language: str | None = None
        self.selected_language: str = cfg.language
        self.enabled_languages: list[str] = []

        self._correction_pattern = _compile_correction_pattern(cfg.corrections)
        self._hotwords_cache_key: tuple[str | None, str] | None = None
        self._hotwords_cache: str | None = None

    def set_context_language(self, language: str | None) -> None:
        self.context_language = language
        self._hotwords_cache_key = None

    def set_selected_language(self, language: str) -> None:
        """Set the language used for the next single Whisper decode."""
        normalized = language.strip().lower()
        self.selected_language = normalized
        self.set_context_language(None if normalized == "auto" else normalized)

    def set_enabled_languages(self, languages: list[str]) -> None:
        self.enabled_languages = list(
            dict.fromkeys(code.strip().lower() for code in languages if code)
        )

    def _apply_corrections(self, text: str) -> str:
        if self._correction_pattern is None:
            return text

        return self._correction_pattern.sub(
            lambda match: self.cfg.corrections[match.group(0)],
            text,
        )

    def _effective_language(self) -> str:
        """
        Automatic language recognition is intentionally disabled.

        The UI/controller should always set a customer language or Japanese.
        A first enabled customer language is used only as a safe startup
        fallback while settings are being restored.
        """
        language = self.selected_language
        if language != "auto":
            return language

        if self.enabled_languages:
            return self.enabled_languages[0]

        raise RuntimeError(
            "Select a customer language before starting speech recognition"
        )

    def _hotwords(self, language: str) -> str | None:
        cache_key = (self.context_language, language)
        if cache_key == self._hotwords_cache_key:
            return self._hotwords_cache

        words = list(self.cfg.hotwords)
        words.extend(self.cfg.language_hotwords.get(language, []))

        # Context is normally the same as the forced language, but preserving
        # it lets callers add domain terms without changing recognition mode.
        if self.context_language and self.context_language != language:
            words.extend(
                self.cfg.language_hotwords.get(self.context_language, [])
            )

        result = ", ".join(dict.fromkeys(words)) or None
        self._hotwords_cache_key = cache_key
        self._hotwords_cache = result
        return result

    def _model_kwargs(self) -> dict[str, int]:
        cpu_count = os.cpu_count() or 4
        default_cpu_threads = min(6, cpu_count)

        cpu_threads = int(
            getattr(self.cfg, "cpu_threads", default_cpu_threads)
            or default_cpu_threads
        )
        num_workers = int(
            getattr(self.cfg, "num_workers", 1) or 1
        )

        return {
            "cpu_threads": max(1, cpu_threads),
            "num_workers": max(1, num_workers),
        }

    def load(self) -> None:
        if self.model is not None:
            return

        self.status("loading", f"Loading speech model: {self.cfg.model}")
        from faster_whisper import WhisperModel

        model_kwargs = self._model_kwargs()
        model_path = str(self.cfg.root / "models" / "whisper")

        try:
            self.model = WhisperModel(
                self.cfg.model,
                device=self.cfg.device,
                compute_type=self.cfg.compute_type,
                download_root=model_path,
                **model_kwargs,
            )
        except Exception:
            if self.cfg.device == "cpu" and self.cfg.compute_type == "int8":
                raise

            self.status(
                "warning",
                "Configured STT device failed; retrying on CPU INT8",
            )
            self.model = WhisperModel(
                self.cfg.model,
                device="cpu",
                compute_type="int8",
                download_root=model_path,
                **model_kwargs,
            )

    def transcribe(self, audio: np.ndarray) -> Recognition:
        """
        Decode exactly once with the current forced language.

        No language detection, no fallback decode, and no Japanese-character
        reinterpretation are performed here.
        """
        self.load()

        if self.model is None:
            raise RuntimeError("Speech model is not loaded")

        language = self._effective_language()
        segments, _info = self.model.transcribe(
            audio,
            language=language,
            beam_size=self.cfg.beam_size,
            best_of=1,
            temperature=0.0,
            condition_on_previous_text=False,
            hotwords=self._hotwords(language),
            vad_filter=False,
            without_timestamps=True,
        )

        text = " ".join(
            segment.text.strip()
            for segment in segments
        ).strip()

        return Recognition(
            text=self._apply_corrections(text),
            language=language,
            probability=1.0,
        )
