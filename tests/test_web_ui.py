from pathlib import Path


WEB = Path(__file__).resolve().parents[1] / "translator_app" / "web"


def test_first_run_ui_defaults_to_japanese():
    script = (WEB / "app.js").read_text(encoding="utf-8")
    html = (WEB / "index.html").read_text(encoding="utf-8")
    assert "const ui = 'ja'" in script
    assert "remoteplus-ui-language" not in script
    assert 'id="ui-language"' not in html
    assert '<html lang="ja">' in html


def test_quick_phrase_collapsed_state_uses_persistent_server_storage():
    script = (WEB / "app.js").read_text(encoding="utf-8")
    assert "/api/quick-phrases/ui-state" in script
    assert "phraseData.collapsed_categories" in script
    assert "remoteplus-collapsed-phrase-categories" not in script


def test_ui_is_chat_based_and_has_no_tts_or_space_controls():
    script = (WEB / "app.js").read_text(encoding="utf-8")
    html = (WEB / "index.html").read_text(encoding="utf-8")
    assert 'id="reply-form"' in html
    assert 'id="reply-text"' in html
    assert "/api/reply" in script
    assert 'id="tts"' not in html
    assert 'id="speech-mode"' not in html
    assert "keydown" in script and "shiftKey" in script
    assert 'id="mode-customer"' not in html
    assert 'id="mode-staff"' not in html
    assert "マイクの翻訳方向" not in html
    assert "speech_mode:'staff'" not in script
    assert "data.speech_mode==='staff'?'reply':'incoming'" in script


def test_ui_renders_both_reading_guides_from_server_events():
    script = (WEB / "app.js").read_text(encoding="utf-8")
    styles = (WEB / "app.css").read_text(encoding="utf-8")
    assert "romanized_reading" in script
    assert "reading-kana" in script
    assert "event.type==='reading'" in script
    assert ".reading-guide .reading-kana,\n.reading-guide .reading-roman" in styles
    assert ".reading-guide .reading-roman {\n  color: var(--staff) !important" in styles


def test_quick_phrase_panel_uses_remaining_space_and_wav_is_collapsible():
    script = (WEB / "app.js").read_text(encoding="utf-8")
    styles = (WEB / "app.css").read_text(encoding="utf-8")
    html = (WEB / "index.html").read_text(encoding="utf-8")

    assert "grid-template-rows: repeat(4, auto) minmax(0, 1fr)" in styles
    assert ".quick-phrase-list {\n  flex: 1 1 auto;" in styles
    assert (
        ".quick-phrase-tools {\n  display: grid;\n"
        "  grid-template-columns: minmax(0, 1fr) minmax(128px, .58fr)"
    ) in styles
    assert ".wav-status:empty {\n  display: none" in styles
    assert '<details class="wav-import">' in html
    assert 'id="wav-drop-zone"' in html
    assert "wavDropZone.ondrop" in script
    assert "chooseWavFile(files[0])" in script
    assert "file.name.toLocaleLowerCase().endsWith('.wav')" in script
    assert html.index('<section class="quick-phrases"') < html.index('<section class="panel output">')
    assert html.index('<details class="wav-import">') > html.index('<section class="panel output">')
    assert "app.css?v=translation-memory-20260724" in html
    assert "app.js?v=translation-memory-20260724" in html
    assert "grid-template-rows: repeat(6, auto) 1fr" not in styles


def test_translation_cards_can_save_approved_target_text():
    script = (WEB / "app.js").read_text(encoding="utf-8")
    styles = (WEB / "app.css").read_text(encoding="utf-8")
    html = (WEB / "index.html").read_text(encoding="utf-8")

    assert 'id="translation-correction-dialog"' in html
    assert 'id="translation-correction-text"' in html
    assert "configureTranslationCorrection(card,data)" in script
    assert "configureTranslationCorrection(card,entry)" in script
    assert "target_language:correction.target_language" in script
    assert "corrected_translation:corrected" in script
    assert "await api('/api/feedback'" in script
    assert ".translation-correction-dialog" in styles
