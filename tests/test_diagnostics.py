from translator_app.diagnostics import configure_runtime_logging
from translator_app.conversation import _create_debug_logger


def test_runtime_and_error_logs_are_written_without_customer_text(tmp_path):
    logger = configure_runtime_logging(tmp_path)
    logger.info("desktop start pid=123")
    try:
        raise RuntimeError("test failure")
    except RuntimeError:
        logger.exception("translation request failed")
    for handler in logger.handlers:
        handler.flush()

    assert {handler.maxBytes for handler in logger.handlers} == {1024 * 1024}
    assert {handler.backupCount for handler in logger.handlers} == {2}

    log_dir = tmp_path / "logs"
    runtime = (log_dir / "runtime.log").read_text(encoding="utf-8")
    errors = (log_dir / "errors.log").read_text(encoding="utf-8")
    assert "desktop start pid=123" in runtime
    assert "translation request failed" in runtime
    assert "RuntimeError: test failure" in errors


def test_new_session_clears_normal_logs_but_keeps_prior_error_log(tmp_path):
    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    (log_dir / "runtime.log").write_text("old normal log", encoding="utf-8")
    (log_dir / "timing-old.log").write_text("old timing log", encoding="utf-8")
    (log_dir / "errors.log").write_text("prior error evidence\n", encoding="utf-8")

    logger = configure_runtime_logging(tmp_path)
    for handler in logger.handlers:
        handler.flush()

    assert "old normal log" not in (log_dir / "runtime.log").read_text(encoding="utf-8")
    assert not list(log_dir.glob("timing-*.log*"))
    assert "prior error evidence" in (log_dir / "errors.log").read_text(encoding="utf-8")


def test_timing_log_is_created_without_debug_environment_flag(tmp_path, monkeypatch):
    monkeypatch.delenv("REMOTEPLUS_DEBUG", raising=False)
    logger = _create_debug_logger(tmp_path)
    assert logger is not None
    handler = logger.handlers[0]
    assert handler.maxBytes == 256 * 1024
    assert handler.backupCount == 1
    logger.info("translation_done text_characters=12")
    for handler in tuple(logger.handlers):
        handler.flush()
        handler.close()
        logger.removeHandler(handler)
    files = list((tmp_path / "logs").glob("timing-*.log"))
    assert len(files) == 1
    content = files[0].read_text(encoding="utf-8")
    assert "timing_log_started" in content
    assert "translation_done text_characters=12" in content
