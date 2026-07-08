from __future__ import annotations

import copy
import os
import sys
import tomllib
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Any, TypeVar

from .languages import CUSTOMER_LANGUAGE_CODES, get_language

FROZEN = bool(getattr(sys, "frozen", False))
ROOT = Path(sys.executable).resolve().parent if FROZEN else Path(__file__).resolve().parent.parent
_configured_data_root = os.environ.get("REMOTEPLUS_DATA_DIR") or os.environ.get("LOCAL_BRIDGE_DATA_DIR")
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
    # Retained for old config compatibility. Edge TTS uses Windows' default output.
    output_device: str | int = "default"
    start_rms: float = 0.012
    continue_rms: float = 0.007
    pre_roll_ms: int = 100
    end_silence_ms: int = 360
    tail_keep_ms: int = 180
    min_speech_ms: int = 350
    max_utterance_ms: int = 12000
    # Staff often speaks longer replies while holding Space. Keep the same
    # silence cutoff as customer mode, but allow longer captured utterances and
    # preserve a slightly longer ending tail.
    staff_end_silence_ms: int = 360
    staff_tail_keep_ms: int = 360
    staff_max_utterance_ms: int = 20000
    post_tts_mute_ms: int = 180
    # A base live model receives a longer snapshot after speech is
    # established. The small final model remains independent and authoritative.
    live_preview_enabled: bool = False
    # Preview is deliberately conservative: one caption only for speech that
    # continues long enough to justify the extra base-model CPU work.
    live_preview_interval_ms: int = 1800
    live_preview_min_speech_ms: int = 1800
    live_preview_max_audio_ms: int = 2200
    live_preview_max_revisions: int = 1
    # When a live decode is almost finished, let it publish for this short
    # window before final small STT begins. This avoids two Whisper decodes
    # competing for CPU in the common long-sentence case.
    live_preview_final_grace_ms: int = 0
    # Old files used these names. They are retained to avoid config failure.
    preview_enabled: bool = False
    preview_interval_ms: int = 1400
    preview_min_speech_ms: int = 900
    preview_max_audio_ms: int = 3600


@dataclass(slots=True)
class SttConfig:
    # Authoritative final transcription model.
    model: str = "small"
    device: str = "cpu"
    compute_type: str = "int8"
    # Final priority: beam 1 cuts CPU decode time substantially.
    beam_size: int = 1
    cpu_threads: int = 6
    num_workers: int = 1
    # Dedicated accuracy-balanced live model. It never blocks the final model.
    live_model: str = "base"
    live_cpu_threads: int = 2
    live_beam_size: int = 1
    live_hotwords_max_items: int = 0
    language: str = "auto"
    # Old probe settings are retained for config compatibility. No probe runs.
    preview_beam_size: int = 1
    japanese_probe_ms: int = 1200
    japanese_probe_margin: float = 0.03
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
    max_new_tokens: int = 128
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
    backend: str = "edge"
    edge_rate: str = "+0%"
    edge_timeout_seconds: int = 15
    latest_only: bool = True
    edge_voice_overrides: dict[str, str] = field(default_factory=dict)
    fallback_to_sapi: bool = False


@dataclass(slots=True)
class ConversationConfig:
    japanese_code: str = "ja"
    language_lock: str = "auto"
    reply_language: str = "auto"
    language_memory_seconds: int = 90
    minimum_language_probability: float = 0.55
    enabled_languages: list[str] = field(default_factory=lambda: list(CUSTOMER_LANGUAGE_CODES))


@dataclass(slots=True)
class ServerConfig:
    host: str = "127.0.0.1"
    port: int = 8765
    open_browser: bool = True
    # Run the local server as a hidden background process and exit it when the
    # browser/app window disconnects. This does not force Edge or Chrome.
    shutdown_when_idle: bool = True
    auto_shutdown_no_clients_seconds: int = 10


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
    allowed = {item.name for item in fields(cls) if item.init}
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
    audio = cfg.audio
    if audio.sample_rate != 16000:
        raise ValueError("The current Whisper audio pipeline requires sample_rate=16000")
    if audio.block_ms not in (10, 20, 30):
        raise ValueError("audio.block_ms must be 10, 20, or 30")
    if not 0 < audio.continue_rms <= audio.start_rms < 1:
        raise ValueError("RMS thresholds must satisfy 0 < continue_rms <= start_rms < 1")
    if audio.min_speech_ms >= audio.max_utterance_ms:
        raise ValueError("min_speech_ms must be less than max_utterance_ms")
    if audio.tail_keep_ms < 0 or audio.tail_keep_ms > audio.end_silence_ms:
        raise ValueError("audio.tail_keep_ms must be between 0 and end_silence_ms")
    if audio.staff_end_silence_ms < audio.end_silence_ms:
        raise ValueError("audio.staff_end_silence_ms must be greater than or equal to end_silence_ms")
    if audio.staff_tail_keep_ms < 0 or audio.staff_tail_keep_ms > audio.staff_end_silence_ms:
        raise ValueError("audio.staff_tail_keep_ms must be between 0 and staff_end_silence_ms")
    if audio.staff_max_utterance_ms < audio.max_utterance_ms:
        raise ValueError("audio.staff_max_utterance_ms must be greater than or equal to max_utterance_ms")
    if audio.live_preview_interval_ms < 250 or audio.live_preview_min_speech_ms < 300:
        raise ValueError("live preview intervals are too small")
    if audio.live_preview_max_audio_ms < 800:
        raise ValueError("live_preview_max_audio_ms must be at least 800")
    if audio.live_preview_max_revisions < 0:
        raise ValueError("live_preview_max_revisions must be zero or greater")
    if not 0 <= audio.live_preview_final_grace_ms <= 500:
        raise ValueError("live_preview_final_grace_ms must be between 0 and 500")
    if not 0 <= cfg.tts.volume <= 1:
        raise ValueError("tts.volume must be between 0 and 1")
    if cfg.tts.backend != "edge":
        raise ValueError("tts.backend must be 'edge'. Windows language-pack TTS has been removed.")
    if cfg.tts.edge_timeout_seconds < 3:
        raise ValueError("tts.edge_timeout_seconds must be at least 3")
    if cfg.translation.backend not in {"m2m100", "hymt2"}:
        raise ValueError("translation.backend must be m2m100 or hymt2")
    if not 1 <= cfg.server.port <= 65535:
        raise ValueError("server.port must be between 1 and 65535")
    if cfg.server.auto_shutdown_no_clients_seconds < 3:
        raise ValueError("server.auto_shutdown_no_clients_seconds must be at least 3")
    if cfg.server.host not in {"127.0.0.1", "localhost", "::1"}:
        raise ValueError("server.host must be a loopback address")
    if min(cfg.stt.cpu_threads, cfg.stt.num_workers, cfg.stt.live_cpu_threads) < 1:
        raise ValueError("stt thread counts must be at least 1")
    if cfg.translation.hymt2_threads < 1:
        raise ValueError("translation.hymt2_threads must be at least 1")
    if cfg.translation.hymt2_request_timeout_seconds < 1:
        raise ValueError("translation.hymt2_request_timeout_seconds must be at least 1")
    if cfg.translation.hymt2_startup_poll_ms < 20:
        raise ValueError("translation.hymt2_startup_poll_ms must be at least 20")
    enabled = [str(code).lower() for code in cfg.conversation.enabled_languages]
    if not enabled or any(code == "ja" or get_language(code) is None for code in enabled):
        raise ValueError("conversation.enabled_languages must contain supported customer language codes")
    if cfg.conversation.reply_language != "auto" and cfg.conversation.reply_language not in enabled:
        raise ValueError("conversation.reply_language must be auto or an enabled language")


def sounddevice_value(value: str | int) -> int | None:
    if value == "default":
        return None
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("audio.input_device must be a device number, 'default', or 'loopback:...'") from exc
