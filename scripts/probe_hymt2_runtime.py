from __future__ import annotations

import argparse
import json
import subprocess
import time
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runtime", choices=("cpu", "openvino"), default="cpu")
    args = parser.parse_args()
    root = Path(__file__).resolve().parent.parent
    report_path = root / f"benchmarks/hymt2_{args.runtime}_runtime_probe.json"
    runtime_dir = "llama" if args.runtime == "cpu" else "llama-openvino"
    command = [
        str(root / "models/hymt2" / runtime_dir / "llama-cli.exe"),
        "-m",
        str(root / "models/hymt2/Hy-MT2-1.8B-Q4_K_M.gguf"),
        "-p",
        "Translate the following text into Japanese. Only output the translation:\n\nHello.",
        "-n",
        "16",
        "-c",
        "256",
        "-t",
        "4",
        "--no-display-prompt",
        "--single-turn",
    ]
    process = subprocess.Popen(
        command,
        cwd=root,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    started = time.monotonic()
    timed_out = False
    while process.poll() is None:
        elapsed = time.monotonic() - started
        print(f"Hy-MT2 runtime probe: {elapsed:.0f}s", flush=True)
        if elapsed > 180:
            process.kill()
            timed_out = True
            break
        time.sleep(5)
    stdout, stderr = process.communicate()
    report = {
        "return_code": process.returncode,
        "timed_out": timed_out,
        "seconds": round(time.monotonic() - started, 2),
        "stdout": stdout[-4000:],
        "stderr": stderr[-8000:],
    }
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print("RETURN_CODE", process.returncode)
    print("STDOUT", stdout[-2000:])
    print("STDERR", stderr[-4000:])
    if timed_out or process.returncode:
        raise SystemExit(process.returncode)


if __name__ == "__main__":
    main()
