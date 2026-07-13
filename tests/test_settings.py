from translator_app.settings import UserSettings


def test_runtime_settings_are_atomic_and_drop_removed_tts_fields(tmp_path):
    store = UserSettings(tmp_path)
    store.save({
        "active_language": "ko",
        "reply_language": "auto",
        "input_device": "default",
        "tts_enabled": True,
        "output_device": "old speaker",
    })
    assert store.load() == {
        "active_language": "ko",
        "reply_language": "auto",
        "input_device": "default",
    }
    assert not list(tmp_path.glob("*.tmp-*"))


def test_schema_one_is_safely_migrated_by_filtering_legacy_fields(tmp_path):
    store = UserSettings(tmp_path)
    store.path.write_text(
        '{"schema_version":1,"active_language":"es","tts_enabled":true,'
        '"output_device":"speaker"}',
        encoding="utf-8",
    )
    assert store.load() == {"active_language": "es"}


def test_incompatible_schema_and_malformed_types_are_ignored(tmp_path):
    store = UserSettings(tmp_path)
    store.path.write_text('{"schema_version":999,"active_language":"es"}', encoding="utf-8")
    assert store.load() == {}
    store.path.write_text(
        '{"active_language":123,"reply_language":[],"input_device":{}}',
        encoding="utf-8",
    )
    assert store.load() == {}
