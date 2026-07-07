from __future__ import annotations

import copy
import os
import sys
import tomllib
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Any, TypeVar

from .languages import get_language

FROZEN = bool(getattr(sys, "frozen", False))
ROOT = (
    Path(sys.executable).resolve().parent
    if FROZEN
    else Path(__file__).resolve().parent.parent
)
_configured_data_root = os.environ.get("REMOTEPLUS_DATA_DIR") or os.environ.get(
    "LOCAL_BRIDGE_DATA_DIR"
)
if _configured_data_root:
    DATA_ROOT = Path(_configured_data_root)
elif FROZEN:
    DATA_ROOT = Path(os.environ.get("LOCALAPPDATA", str(ROOT))) / "RemotePlusTranslator"
else:
    DATA_ROOT = ROOT
T = TypeVar("T")


@dataclass(slots=True)
class AudioConfig:
    sample_rate: int = 16000
    block_ms: int = 20
    input_device: str | int = "default"
    output_device: str | int = "default"
    start_rms: float = 0.012
    continue_rms: float = 0.007
    pre_roll_ms: int = 300
    end_silence_ms: int = 420
    min_speech_ms: int = 350
    max_utterance_ms: int = 12000
    post_tts_mute_ms: int = 500
    preview_enabled: bool = False
    preview_interval_ms: int = 1400
    preview_min_speech_ms: int = 900
    preview_max_audio_ms: int = 3600


@dataclass(slots=True)
class SttConfig:
    model: str = "small"
    device: str = "cpu"
    compute_type: str = "int8"
    beam_size: int = 1
    preview_beam_size: int = 1
    language: str = "auto"
    cpu_threads: int = 6
    num_workers: int = 1
    # Kept only so existing config.local.toml files from the pair-language
    # experiment still load. Fixed customer/staff mode does not use them.
    japanese_probe_ms: int = 1200
    japanese_probe_margin: float = 0.03
    # Kept for compatibility with existing config.toml/config.local.toml.
    # The two-language (Japanese vs selected customer language) pipeline
    # no longer uses these legacy auto-detection thresholds.
    japanese_reply_threshold: float = 0.5
    enabled_language_min_probability: float = 0.35
    hotwords: list[str] = field(default_factory=list)
    language_hotwords: dict[str, list[str]] = field(default_factory=dict)
    corrections: dict[str, str] = field(default_factory=dict)
    root: Path = field(default=ROOT, init=False, repr=False)


@dataclass(slots=True)
class TranslationConfig:
    backend: str = "hymt2"
    model: str = "facebook/m2m100_418M"
    device: str = "cpu"
    max_new_tokens: int = 256
    hymt2_model: str = "models/hymt2/Hy-MT2-1.8B-Q4_K_M.gguf"
    hymt2_runtime: str = "models/hymt2/llama"
    hymt2_threads: int = 8
    hymt2_context: int = 1024
    hymt2_timeout_seconds: int = 45
    hymt2_request_timeout_seconds: int = 15
    hymt2_startup_poll_ms: int = 80
    hymt2_preview_max_tokens: int = 72
    hymt2_warmup: bool = True
    glossary: dict[str, list[str]] = field(default_factory=dict)
    protected_terms: list[dict[str, list[str]]] = field(default_factory=list)
    root: Path = field(default=ROOT, init=False, repr=False)


@dataclass(slots=True)
class TtsConfig:
    enabled: bool = True
    volume: float = 0.9


@dataclass(slots=True)
class ConversationConfig:
    japanese_code: str = "ja"
    language_lock: str = "auto"
    reply_language: str = "auto"
    language_memory_seconds: int = 90
    minimum_language_probability: float = 0.55
    enabled_languages: list[str] = field(default_factory=lambda: ["en", "ko", "zh", "es"])


@dataclass(slots=True)
class ServerConfig:
    host: str = "127.0.0.1"
    port: int = 8765
    open_browser: bool = True


@dataclass(slots=True)
class AppConfig:
    audio: AudioConfig
    stt: SttConfig
    translation: TranslationConfig
    tts: TtsConfig
    conversation: ConversationConfig
    server: ServerConfig
    root: Path = ROOT
    data_root: Path = DATA_ROOT


def _merge(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    result = copy.deepcopy(base)
    for key, value in overlay.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _merge(result[key], value)
        else:
            result[key] = value
    return result


def _make(cls: type[T], values: dict[str, Any]) -> T:
    allowed = {f.name for f in fields(cls) if f.init}
    unknown = set(values) - allowed
    if unknown:
        raise ValueError(f"Unknown {cls.__name__} settings: {', '.join(sorted(unknown))}")
    return cls(**values)


def load_config(path: Path | None = None) -> AppConfig:
    primary = path or ROOT / "config.toml"
    if not primary.exists():
        raise FileNotFoundError(f"Configuration not found: {primary}")
    with primary.open("rb") as handle:
        data = tomllib.load(handle)
    local = DATA_ROOT / "config.local.toml"
    if local.exists() and local != primary:
        with local.open("rb") as handle:
            data = _merge(data, tomllib.load(handle))
    cfg = AppConfig(
        audio=_make(AudioConfig, data.get("audio", {})),
        stt=_make(SttConfig, data.get("stt", {})),
        translation=_make(TranslationConfig, data.get("translation", {})),
        tts=_make(TtsConfig, data.get("tts", {})),
        conversation=_make(ConversationConfig, data.get("conversation", {})),
        server=_make(ServerConfig, data.get("server", {})),
        root=primary.resolve().parent,
        data_root=DATA_ROOT,
    )
    cfg.stt.root = cfg.root
    cfg.translation.root = cfg.root
    validate_config(cfg)
    return cfg


def validate_config(cfg: AppConfig) -> None:
    a = cfg.audio
    if a.sample_rate != 16000:
        raise ValueError("The current Whisper audio pipeline requires sample_rate=16000")
    if a.block_ms not in (10, 20, 30):
        raise ValueError("audio.block_ms must be 10, 20, or 30")
    if not 0 < a.continue_rms <= a.start_rms < 1:
        raise ValueError("RMS thresholds must satisfy 0 < continue_rms <= start_rms < 1")
    if a.min_speech_ms >= a.max_utterance_ms:
        raise ValueError("min_speech_ms must be less than max_utterance_ms")
    if a.preview_interval_ms < 400:
        raise ValueError("audio.preview_interval_ms must be at least 400")
    if a.preview_min_speech_ms < 300:
        raise ValueError("audio.preview_min_speech_ms must be at least 300")
    if a.preview_max_audio_ms < a.preview_min_speech_ms:
        raise ValueError("audio.preview_max_audio_ms must be >= preview_min_speech_ms")
    if not 0 <= cfg.tts.volume <= 1:
        raise ValueError("tts.volume must be between 0 and 1")
    if cfg.translation.backend not in {"m2m100", "hymt2"}:
        raise ValueError("translation.backend must be m2m100 or hymt2")
    if not 1 <= cfg.server.port <= 65535:
        raise ValueError("server.port must be between 1 and 65535")
    if cfg.server.host not in {"127.0.0.1", "localhost", "::1"}:
        raise ValueError("server.host must be a loopback address")
    if cfg.stt.cpu_threads < 1 or cfg.stt.num_workers < 1:
        raise ValueError("stt.cpu_threads and stt.num_workers must be at least 1")
    if cfg.stt.japanese_probe_ms < 300:
        raise ValueError("stt.japanese_probe_ms must be at least 300")
    if not 0 <= cfg.stt.japanese_probe_margin <= 1:
        raise ValueError("stt.japanese_probe_margin must be between 0 and 1")
    if not 0 <= cfg.stt.japanese_reply_threshold <= 1:
        raise ValueError("stt.japanese_reply_threshold must be between 0 and 1")
    if not 0 <= cfg.stt.enabled_language_min_probability <= 1:
        raise ValueError("stt.enabled_language_min_probability must be between 0 and 1")
    if cfg.translation.hymt2_threads < 1:
        raise ValueError("translation.hymt2_threads must be at least 1")
    if cfg.translation.hymt2_request_timeout_seconds < 1:
        raise ValueError("translation.hymt2_request_timeout_seconds must be at least 1")
    if cfg.translation.hymt2_startup_poll_ms < 20:
        raise ValueError("translation.hymt2_startup_poll_ms must be at least 20")
    enabled = cfg.conversation.enabled_languages
    if not enabled or any(code == "ja" or get_language(code) is None for code in enabled):
        raise ValueError("conversation.enabled_languages must contain supported foreign codes")
    if (
        cfg.conversation.reply_language != "auto"
        and cfg.conversation.reply_language not in enabled
    ):
        raise ValueError("conversation.reply_language must be auto or an enabled language")


def sounddevice_value(value: str | int) -> int | None:
    if value == "default":
        return None
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            "audio.input_device must be a device number, 'default', or 'loopback:...'"
        ) from exc
