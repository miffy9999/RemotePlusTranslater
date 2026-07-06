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
