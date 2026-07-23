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


def test_semantically_invalid_local_overlay_falls_back_to_primary(tmp_path, monkeypatch):
    import translator_app.config as config_module

    primary = config_module.ROOT / "config.toml"
    (tmp_path / "config.local.toml").write_text(
        "[audio]\nstart_rms = -1\n", encoding="utf-8"
    )
    monkeypatch.setattr(config_module, "DATA_ROOT", tmp_path)
    with pytest.warns(RuntimeWarning, match="Ignoring incompatible local configuration"):
        cfg = load_config(primary)
    assert cfg.audio.start_rms > 0


def test_unknown_top_level_section_is_rejected(tmp_path):
    config = tmp_path / "config.toml"
    config.write_text("[traslation]\nbackend = 'hymt2'\n", encoding="utf-8")

    with pytest.raises(ValueError, match="Unknown configuration sections"):
        load_config(config)


def test_enabled_updates_reject_url_credentials_and_fragments(tmp_path):
    config = tmp_path / "config.toml"
    config.write_text(
        """
[updates]
enabled = true
manifest_url = "https://user:secret@example.com/manifest.json#old"
trusted_publisher_thumbprints = ["AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"]
""",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="credentials or a fragment"):
        load_config(config)
