from translator_app.config import load_config
import pytest


def test_default_configuration_is_valid():
    cfg = load_config()
    assert cfg.audio.sample_rate == 16000
    assert cfg.conversation.japanese_code == "ja"
    assert cfg.server.host == "127.0.0.1"
    assert cfg.translation.backend == "hymt2"


def test_invalid_local_overlay_does_not_prevent_startup(tmp_path, monkeypatch):
    import translator_app.config as config_module

    primary = config_module.ROOT / "config.toml"
    local = tmp_path / "config.local.toml"
    local.write_text("[audio\ninvalid", encoding="utf-8")
    monkeypatch.setattr(config_module, "DATA_ROOT", tmp_path)
    with pytest.warns(RuntimeWarning, match="Ignoring invalid local configuration"):
        cfg = load_config(primary)
    assert cfg.audio.sample_rate == 16000
    assert cfg.data_root == tmp_path
