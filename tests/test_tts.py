from translator_app.audio import PlaybackGate
from translator_app.config import AudioConfig, TtsConfig
from translator_app.tts import EDGE_OUTPUT_PREFIX, EdgeSpeaker


def _speaker(audio: AudioConfig | None = None) -> EdgeSpeaker:
    return EdgeSpeaker(
        TtsConfig(),
        audio or AudioConfig(),
        PlaybackGate(),
        lambda _phase, _message: None,
    )


def test_edge_voice_uses_language_mapping():
    assert _speaker()._voice("ja") == "ja-JP-NanamiNeural"


def test_edge_voice_falls_back_to_english():
    assert _speaker()._voice("unknown") == "en-US-JennyNeural"


def test_edge_output_device_prefix_is_unwrapped():
    speaker = _speaker(AudioConfig(output_device=f"{EDGE_OUTPUT_PREFIX}Speakers"))

    assert speaker._requested_output_name() == "Speakers"


def test_legacy_output_device_values_use_system_default():
    assert _speaker(AudioConfig(output_device=3))._requested_output_name() is None
