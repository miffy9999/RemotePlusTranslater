from __future__ import annotations

import os
import re
import subprocess
import tomllib
from pathlib import Path

import pytest

from translator_app.process_cleanup import hidden_subprocess_options


ROOT = Path(__file__).resolve().parent.parent


def test_windows_build_embeds_release_version_metadata():
    spec = (ROOT / "build/local_bridge.spec").read_text(encoding="utf-8")
    version = (ROOT / "build/version_info.txt").read_text(encoding="utf-8")
    assert 'version=os.path.join(project_root, "build", "version_info.txt")' in spec
    assert "StringStruct('ProductVersion', '0.8.5')" in version


def test_backend_subprocesses_are_created_without_a_visible_console():
    options = hidden_subprocess_options()
    if os.name != "nt":
        assert options == {}
        return
    assert options["creationflags"] & subprocess.CREATE_NO_WINDOW
    startup_info = options["startupinfo"]
    assert startup_info.dwFlags & subprocess.STARTF_USESHOWWINDOW
    assert startup_info.wShowWindow == subprocess.SW_HIDE


def test_project_and_windows_release_versions_match_application():
    from translator_app import __version__

    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    installer = (ROOT / "build/installer.iss").read_text(encoding="utf-8")
    assert project["project"]["version"] == __version__
    assert f'#define MyAppVersion "{__version__}"' in installer


def test_build_packages_exactly_one_versioned_manual_pdf():
    script = (ROOT / "build.ps1").read_text(encoding="utf-8")

    assert "Get-ChildItem -LiteralPath '.\\docs\\manual_ja'" in script
    assert '-Filter "*_$version.pdf"' in script
    assert "Expected exactly one finished manual PDF" in script
    assert "Copy-Item -LiteralPath $manualPdf.FullName" in script
    assert "RemotePlus_Translator_かんたん操作ガイド_$version.pdf" not in script


@pytest.mark.skipif(os.name != "nt", reason="Windows CMD launcher regression")
def test_run_debug_cmd_parsing_and_timestamp_without_starting_app():
    cmd = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "cmd.exe"
    env = os.environ.copy()
    env["REMOTEPLUS_BATCH_SELFTEST"] = "1"
    completed = subprocess.run(
        [str(cmd), "/d", "/c", "run_debug.bat"],
        cwd=ROOT,
        env=env,
        capture_output=True,
        timeout=10,
        check=False,
    )
    output = (completed.stdout + completed.stderr).decode(errors="replace")
    assert completed.returncode == 0, output
    match = re.search(r"RUN_STARTED=(\d+)", output)
    assert match is not None, output
    assert int(match.group(1)) > 1_700_000_000
    assert "내부 또는 외부 명령" not in output
