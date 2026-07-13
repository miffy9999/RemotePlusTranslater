from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parent.parent


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
