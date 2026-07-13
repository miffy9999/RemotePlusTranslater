from translator_app.settings import UserSettings


def test_first_run_uses_defaults_then_persists_selection(tmp_path):
    store = UserSettings(tmp_path)
    languages, required = store.load_languages(["en", "ko", "zh", "es"])
    assert languages == ["en", "ko", "zh", "es"]
    assert required is True

    store.save_languages(["en", "ko"])
    languages, required = store.load_languages(["en"])
    assert languages == ["en", "ko"]
    assert required is False


def test_runtime_settings_are_atomic_versioned_and_ignore_unknown_fields(tmp_path):
    store = UserSettings(tmp_path)
    store.save({
        "active_language": "ko",
        "reply_language": "auto",
        "tts_enabled": True,
        "input_device": "default",
        "output_device": "default",
        "phase": "listening",
    })
    assert store.load() == {
        "active_language": "ko",
        "reply_language": "auto",
        "tts_enabled": True,
        "input_device": "default",
        "output_device": "default",
    }
    assert not list(tmp_path.glob("*.tmp-*"))


def test_incompatible_settings_schema_is_ignored(tmp_path):
    store = UserSettings(tmp_path)
    store.path.write_text('{"schema_version": 999, "active_language": "es"}', encoding="utf-8")
    assert store.load() == {}


def test_malformed_runtime_setting_types_are_filtered(tmp_path):
    store = UserSettings(tmp_path)
    store.path.write_text(
        '{"active_language": 123, "reply_language": [], "tts_enabled": "false", '
        '"input_device": {}, "output_device": ["default"]}',
        encoding="utf-8",
    )

    assert store.load() == {}
