"""Summarize one RemotePlus debug timing log without third-party packages.

Run by ``run_debug.bat`` after the application exits. The JSON file is meant
for performance review: it records the exact run file, timing percentiles,
queue/drop/failure counts, and the CPU-related config used for that run.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import statistics
import tomllib
from collections import Counter
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parent.parent
LOG_DIR = PROJECT_ROOT / "logs"
LINE = re.compile(r"^\S+\s+\S+\s+(?P<event>\S+)(?:\s+(?P<fields>.*))?$")
FIELD = re.compile(r"(?P<key>[A-Za-z][A-Za-z0-9_]*)=(?P<value>[^\s]+)")


def _number(value: str) -> float | None:
    try:
        return float(value)
    except ValueError:
        return None


def _summary(values: list[float]) -> dict[str, float | int] | None:
    if not values:
        return None
    ordered = sorted(values)
    p95_index = round((len(ordered) - 1) * 0.95)
    return {
        "count": len(ordered),
        "min": round(ordered[0], 3),
        "median": round(statistics.median(ordered), 3),
        "p95": round(ordered[p95_index], 3),
        "max": round(ordered[-1], 3),
    }


def _config_snapshot() -> dict[str, Any]:
    path = PROJECT_ROOT / "config.toml"
    with path.open("rb") as handle:
        config = tomllib.load(handle)
    audio = config.get("audio", {})
    stt = config.get("stt", {})
    translation = config.get("translation", {})
    return {
        "config_path": str(path),
        "config_modified_unix": round(path.stat().st_mtime, 3),
        "logical_cpu_count": os.cpu_count(),
        "audio": {
            key: audio.get(key)
            for key in ("end_silence_ms", "tail_keep_ms", "max_utterance_ms", "live_preview_enabled")
        },
        "stt": {key: stt.get(key) for key in ("model", "beam_size", "cpu_threads", "num_workers")},
        "translation": {
            key: translation.get(key)
            for key in ("hymt2_threads", "hymt2_context", "max_new_tokens", "hymt2_warmup")
        },
    }


def analyze(path: Path) -> dict[str, Any]:
    measures: dict[str, list[float]] = {
        "stt_seconds": [],
        "translation_seconds": [],
        "speech_end_to_translation_seconds": [],
        "stt_queue_wait_seconds": [],
    }
    events: Counter[str] = Counter()
    failure_events: Counter[str] = Counter()
    utterances: set[str] = set()

    for raw_line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        match = LINE.match(raw_line)
        if match is None:
            continue
        event = match.group("event")
        fields = {item.group("key"): item.group("value") for item in FIELD.finditer(match.group("fields") or "")}
        events[event] += 1
        if "utterance_id" in fields:
            utterances.add(fields["utterance_id"])
        if event in {"stt_done", "translation_done", "stt_started"}:
            keys = {
                "stt_done": ("stt_seconds",),
                "translation_done": ("translation_seconds", "speech_end_to_translation_seconds"),
                "stt_started": ("queue_wait_seconds",),
            }[event]
            for key in keys:
                value = _number(fields.get(key, ""))
                if value is None:
                    continue
                target = {
                    "queue_wait_seconds": "stt_queue_wait_seconds",
                }.get(key, key)
                measures[target].append(value)
        if "failed" in event or "dropped" in event or "interrupted" in event or "skipped" in event:
            failure_events[event] += 1

    return {
        "source_log": str(path.resolve()),
        "source_modified_unix": round(path.stat().st_mtime, 3),
        "config": _config_snapshot(),
        "unique_utterance_ids": len(utterances),
        "timings_seconds": {key: _summary(values) for key, values in measures.items()},
        "event_counts": dict(events),
        "attention_counts": dict(failure_events),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Summarize a RemotePlus timing log")
    parser.add_argument("--file", type=Path, help="timing log to analyze")
    parser.add_argument("--latest", action="store_true", help="analyze the newest timing log")
    parser.add_argument(
        "--after-unix",
        type=float,
        help="only accept a log modified after this Unix timestamp",
    )
    parser.add_argument("--write", action="store_true", help="write JSON beside the timing log")
    args = parser.parse_args()

    path = args.file
    if path is None:
        candidates = sorted(
            (
                item
                for item in LOG_DIR.glob("timing-*.log")
                if args.after_unix is None or item.stat().st_mtime >= args.after_unix
            ),
            key=lambda item: item.stat().st_mtime,
        )
        if not candidates:
            print("No timing log was created for this debug run.")
            return 1
        path = candidates[-1]
    if not path.exists():
        print(f"Timing log not found: {path}")
        return 1

    report = analyze(path)
    encoded = json.dumps(report, ensure_ascii=False, indent=2)
    print(encoded)
    if args.write:
        output = path.with_name(path.stem.replace("timing-", "summary-") + ".json")
        output.write_text(encoded + "\n", encoding="utf-8")
        print(f"\nSaved summary: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
