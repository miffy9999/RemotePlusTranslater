import json
import threading

from translator_app.settings import UserSettings


def test_runtime_settings_are_atomic_and_drop_removed_tts_fields(tmp_path):
    store = UserSettings(tmp_path)
    store.save({
        "active_language": "ko",
        "reply_language": "auto",
        "speech_mode": "staff",
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


def test_many_concurrent_setting_updates_never_leave_partial_json(tmp_path):
    store = UserSettings(tmp_path)
    failures = []

    def save(index):
        try:
            store.save({
                "active_language": "ko" if index % 2 else "en",
                "reply_language": "auto",
                "input_device": index,
            })
        except Exception as exc:
            failures.append(exc)

    threads = [threading.Thread(target=save, args=(index,)) for index in range(100)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert failures == []
    payload = json.loads(store.path.read_text(encoding="utf-8"))
    assert payload["schema_version"] == UserSettings.SCHEMA_VERSION
    assert payload["active_language"] in {"en", "ko"}
    assert not list(tmp_path.glob("*.tmp-*"))
