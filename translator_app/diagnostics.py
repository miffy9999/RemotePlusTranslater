from __future__ import annotations

import logging
import sys
import threading
from logging.handlers import RotatingFileHandler
from pathlib import Path


_LOGGER_NAME = "remoteplus.runtime"
_configured_dir: Path | None = None
_hooks_installed = False


def configure_runtime_logging(data_root: Path) -> logging.Logger:
    """Write operational diagnostics without storing customer conversation text.

    The portable EXE uses LOCALAPPDATA as ``data_root``.  Keep logs there so an
    update or replacement of the distribution folder does not discard the
    evidence needed to investigate an on-site incident.
    """
    global _configured_dir
    log_dir = data_root / "logs"
    logger = logging.getLogger(_LOGGER_NAME)
    logger.setLevel(logging.INFO)
    logger.propagate = False

    if _configured_dir != log_dir:
        for handler in tuple(logger.handlers):
            logger.removeHandler(handler)
            try:
                handler.close()
            except OSError:
                pass
        try:
            log_dir.mkdir(parents=True, exist_ok=True)
            # A new on-site session starts with fresh operational evidence.
            # Keep error evidence, but remove normal/timing logs from older
            # sessions so the operator never accumulates routine diagnostics.
            for pattern in ("runtime.log*", "timing-*.log*"):
                for old_log in log_dir.glob(pattern):
                    try:
                        old_log.unlink()
                    except OSError:
                        pass
            formatter = logging.Formatter(
                "%(asctime)s.%(msecs)03d %(levelname)s %(threadName)s %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S",
            )
            runtime = RotatingFileHandler(
                log_dir / "runtime.log",
                maxBytes=1 * 1024 * 1024,
                backupCount=2,
                encoding="utf-8",
            )
            runtime.setLevel(logging.INFO)
            runtime.setFormatter(formatter)
            errors = RotatingFileHandler(
                log_dir / "errors.log",
                maxBytes=1 * 1024 * 1024,
                backupCount=2,
                encoding="utf-8",
            )
            errors.setLevel(logging.ERROR)
            errors.setFormatter(formatter)
            logger.addHandler(runtime)
            logger.addHandler(errors)
            _configured_dir = log_dir
        except OSError:
            # Diagnostics must never prevent the front desk from opening.
            _configured_dir = None

    _install_exception_hooks()
    return logger


def runtime_logger() -> logging.Logger:
    return logging.getLogger(_LOGGER_NAME)


def log_exception(context: str) -> None:
    """Log the active exception with its traceback, never its customer text."""
    runtime_logger().exception("%s", context)


def _install_exception_hooks() -> None:
    global _hooks_installed
    if _hooks_installed:
        return
    _hooks_installed = True
    original_sys_hook = sys.excepthook
    original_thread_hook = threading.excepthook

    def sys_hook(exc_type, exc_value, exc_traceback):
        if not issubclass(exc_type, (KeyboardInterrupt, SystemExit)):
            runtime_logger().critical(
                "uncaught main-thread exception",
                exc_info=(exc_type, exc_value, exc_traceback),
            )
        original_sys_hook(exc_type, exc_value, exc_traceback)

    def thread_hook(args: threading.ExceptHookArgs) -> None:
        if not issubclass(args.exc_type, (KeyboardInterrupt, SystemExit)):
            runtime_logger().critical(
                "uncaught thread exception thread=%s",
                args.thread.name if args.thread is not None else "unknown",
                exc_info=(args.exc_type, args.exc_value, args.exc_traceback),
            )
        original_thread_hook(args)

    sys.excepthook = sys_hook
    threading.excepthook = thread_hook
