# Repository Guidelines

## Project Structure & Module Organization

`translator_app/` contains the application: `audio.py` (capture/VAD), `stt.py` (Whisper), `hymt2.py` (translation), `conversation.py` (pipeline), and `server.py` (FastAPI/WebSocket). The browser UI lives in `translator_app/web/`. Reading-guide rules belong in `reading.py` and hotel vocabulary in `phrasebook.py`.

Tests mirror these modules under `tests/` (for example, `tests/test_audio.py`). Build and installer inputs are in `build/`; operational and legal documentation is in `docs/` and `legal/`. Treat `models/`, `cache/`, `logs/`, `.venv/`, and `dist/` as generated or local runtime content unless a release task explicitly requires them.

## Build, Test, and Development Commands

Run these from the repository root on Windows:

```powershell
install.bat                         # create/update the virtual environment
prepare_models.bat                  # obtain required local models
run_debug.bat                       # start the desktop app and retain debug logs
doctor.bat                          # validate models, binaries, and configuration
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe -m ruff check .
.\qa.ps1                           # full QA; use .\qa.ps1 -Models for model checks
.\build.ps1                        # create portable dist\RemotePlusTranslator
```

Use `build.ps1 -CommercialRelease` only with the required distributor metadata and signing certificate.

## Coding Style & Naming Conventions

Use Python 3.11+, four-space indentation, and type annotations for public interfaces. Use `snake_case` for functions, variables, and modules; `PascalCase` for classes; and `UPPER_SNAKE_CASE` for constants. Keep Ruff-compliant lines at 100 characters or fewer. Snapshot settings at utterance start, bound queues, and discard stale results rather than blocking realtime work.

## Testing Guidelines

Write `pytest` tests named `test_<behavior>.py`; exercise the production worker/queue path for audio, STT, translation, events, or shutdown changes. Add a regression test for every defect. Run focused tests while iterating, then `pytest`, Ruff, and `qa.ps1` before review. Mock real microphones, network access, and bundled models in unit tests.

## Commit & Pull Request Guidelines

Follow the existing concise, imperative style: `fix: stabilize realtime flow`, `feat: add reading guide`, or `chore: refresh release files`. Keep commits narrowly scoped. Pull requests should state user-visible impact, configuration/model changes, tests run, and any deployment or license implications. Include screenshots for UI changes and never commit customer audio, logs, credentials, or distributor signing data.

## Configuration & Release Safety

Keep defaults in `config.toml`; user-specific settings belong under `%LOCALAPPDATA%\RemotePlusTranslator`. Validate device names and language codes before persisting them. A portable deployment requires the entire `dist\RemotePlusTranslator` folder, not the EXE alone.
