from pathlib import Path


WEB = Path(__file__).resolve().parents[1] / "translator_app" / "web"


def test_first_run_ui_defaults_to_japanese():
    script = (WEB / "app.js").read_text(encoding="utf-8")
    html = (WEB / "index.html").read_text(encoding="utf-8")
    assert "remoteplus-ui-language') || 'ja'" in script
    assert '<html lang="ja">' in html


def test_ui_is_chat_based_and_has_no_tts_or_space_controls():
    script = (WEB / "app.js").read_text(encoding="utf-8")
    html = (WEB / "index.html").read_text(encoding="utf-8")
    assert 'id="reply-form"' in html
    assert 'id="reply-text"' in html
    assert "/api/reply" in script
    assert 'id="tts"' not in html
    assert 'id="speech-mode"' not in html
    assert "keydown" in script and "shiftKey" in script


def test_ui_renders_both_reading_guides_from_server_events():
    script = (WEB / "app.js").read_text(encoding="utf-8")
    styles = (WEB / "app.css").read_text(encoding="utf-8")
    assert "romanized_reading" in script
    assert "reading-kana" in script
    assert "event.type==='reading'" in script
    assert ".reading-guide .reading-kana,\n.reading-guide .reading-roman" in styles
    assert ".reading-guide .reading-roman {\n  color: var(--staff) !important" in styles
