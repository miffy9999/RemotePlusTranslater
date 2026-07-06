from translator_app.config import load_config


def test_default_configuration_is_valid():
    cfg = load_config()
    assert cfg.audio.sample_rate == 16000
    assert cfg.conversation.japanese_code == "ja"
    assert cfg.server.host == "127.0.0.1"
    assert cfg.translation.backend == "hymt2"
