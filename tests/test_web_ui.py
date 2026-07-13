from pathlib import Path


WEB = Path(__file__).resolve().parent.parent / "translator_app" / "web"


def test_first_run_ui_defaults_to_japanese():
    script = (WEB / "app.js").read_text(encoding="utf-8")
    html = (WEB / "index.html").read_text(encoding="utf-8")
    assert "localStorage.getItem('remoteplus-ui-language')||'ja'" in script
    assert '<html lang="ja">' in html
    assert "システムを準備しています" in html


def test_staff_reply_keeps_customer_language_in_partner_display():
    script = (WEB / "app.js").read_text(encoding="utf-8")
    assert "d.direction==='reply'?d.target_language:d.source_language" in script
