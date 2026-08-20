"""Run a real-model endurance test without needing a microphone or guest data.

The test reuses public speech samples, local Whisper and Hy-MT2. It
intentionally overlaps one STT and one translation task
per cycle, matching the CPU contention possible during a continuous call.
"""

from __future__ import annotations

import argparse
import json
import statistics
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from typing import Any

from faster_whisper.audio import decode_audio

from translator_app.config import load_config
from translator_app.hymt2 import create_translator
from translator_app.reading import reading_guide, romanized_guide
from translator_app.stt import WhisperRecognizer


ROOT = Path(__file__).resolve().parent.parent
WAV_ROOT = ROOT / "benchmarks" / "public_audio" / "spoken-language-identification-test-wavs"
SAMPLES = (
    ("en", "en-english.wav", "Please bring two towels to room 305."),
    ("ko", "ko-korean.wav", "객실에 수건 두 장을 가져다 주세요."),
    ("zh", "zh-chinese.wav", "请给305房间送两条毛巾。"),
    ("es", "es-spanish.wav", "Por favor, traiga dos toallas a la habitación 305."),
)


def percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    return round(ordered[round((len(ordered) - 1) * fraction)], 3)


def memory_snapshot(process) -> dict[str, int] | None:
    try:
        children = process.children(recursive=True)
        own = process.memory_info().rss
        child = sum(item.memory_info().rss for item in children if item.is_running())
        return {"python_rss_bytes": own, "child_rss_bytes": child, "total_rss_bytes": own + child}
    except Exception:
        return None


def timed(call, *args, **kwargs):
    started = time.monotonic()
    return call(*args, **kwargs), time.monotonic() - started


def main() -> int:
    parser = argparse.ArgumentParser(description="RemotePlus real-model endurance test")
    parser.add_argument("--minutes", type=float, default=30.0)
    parser.add_argument("--interval-seconds", type=float, default=10.0)
    parser.add_argument("--stt-threads", type=int, help="temporary Whisper CPU thread override")
    parser.add_argument("--hymt2-threads", type=int, help="temporary Hy-MT2 CPU thread override")
    args = parser.parse_args()
    if args.minutes <= 0 or args.interval_seconds <= 0:
        raise SystemExit("All durations must be positive")

    try:
        import psutil
    except ImportError:
        psutil = None

    cfg = load_config()
    if args.stt_threads is not None:
        cfg.stt.cpu_threads = max(1, args.stt_threads)
    if args.hymt2_threads is not None:
        cfg.translation.hymt2_threads = max(1, args.hymt2_threads)
    recognizer = WhisperRecognizer(cfg.stt, lambda phase, message: print(f"STT {phase}: {message}"))
    translator = create_translator(cfg.translation, lambda phase, message: print(f"MT {phase}: {message}"))
    audio = {
        language: decode_audio(str(WAV_ROOT / filename), sampling_rate=cfg.audio.sample_rate)
        for language, filename, _ in SAMPLES
    }
    recognizer.load()
    translator.load()
    if hasattr(translator, "warmup"):
        translator.warmup()

    started_at = datetime.now().isoformat(timespec="seconds")
    deadline = time.monotonic() + args.minutes * 60
    index = 0
    rows: list[dict[str, Any]] = []
    memories: list[dict[str, int]] = []
    process = psutil.Process() if psutil is not None else None
    executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="runtime-stress")
    print(f"Running for {args.minutes:g} minute(s); Ctrl+C writes a partial report.", flush=True)

    try:
        while time.monotonic() < deadline:
            cycle_started = time.monotonic()
            language, _filename, hotel_text = SAMPLES[index % len(SAMPLES)]
            target = "ja"
            stt_future = executor.submit(timed, recognizer.transcribe, audio[language], language=language)
            mt_future = executor.submit(timed, translator.translate, hotel_text, language, target)
            (stt_result, stt_seconds) = stt_future.result()
            (translation, translation_seconds) = mt_future.result()
            row: dict[str, Any] = {
                "cycle": index + 1,
                "language": language,
                "stt_seconds": round(stt_seconds, 3),
                "translation_seconds": round(translation_seconds, 3),
                "stt_text_characters": len(stt_result.text),
                "translation_characters": len(translation),
                "ok": bool(stt_result.text and translation),
            }

            # Exercise both reading formats without adding another model call.
            reading_started = time.monotonic()
            reading_guide(hotel_text, language)
            romanized_guide(hotel_text, language)
            row["reading_seconds"] = round(time.monotonic() - reading_started, 6)

            if process is not None:
                snapshot = memory_snapshot(process)
                if snapshot is not None:
                    memories.append(snapshot)
                    row["total_rss_mib"] = round(snapshot["total_rss_bytes"] / 1024 / 1024, 1)
            rows.append(row)
            print(json.dumps(row, ensure_ascii=False), flush=True)
            index += 1
            remaining = args.interval_seconds - (time.monotonic() - cycle_started)
            if remaining > 0:
                time.sleep(remaining)
    except KeyboardInterrupt:
        print("Interrupted; writing partial report.", flush=True)
    finally:
        executor.shutdown(wait=True, cancel_futures=True)
        if hasattr(translator, "close"):
            translator.close()

    stt = [row["stt_seconds"] for row in rows]
    reading = [row["reading_seconds"] for row in rows]
    report = {
        "started_at": started_at,
        "requested_minutes": args.minutes,
        "interval_seconds": args.interval_seconds,
        "stt_threads": cfg.stt.cpu_threads,
        "hymt2_threads": cfg.translation.hymt2_threads,
        "cycles": len(rows),
        "failed_cycles": sum(not row["ok"] for row in rows),
        "stt_seconds": {"median": round(statistics.median(stt), 3) if stt else None, "p95": percentile(stt, 0.95), "max": max(stt, default=None)},
        "reading_seconds": {"median": round(statistics.median(reading), 6) if reading else None, "p95": percentile(reading, 0.95), "max": max(reading, default=None)},
        "memory": {
            "samples": len(memories),
            "start_total_rss_mib": round(memories[0]["total_rss_bytes"] / 1024 / 1024, 1) if memories else None,
            "end_total_rss_mib": round(memories[-1]["total_rss_bytes"] / 1024 / 1024, 1) if memories else None,
            "peak_total_rss_mib": round(max((item["total_rss_bytes"] for item in memories), default=0) / 1024 / 1024, 1) if memories else None,
        },
        "rows": rows,
    }
    output = ROOT / "benchmarks" / f"runtime_stress_{datetime.now():%Y%m%d_%H%M%S}.json"
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"REPORT {output}", flush=True)
    return 0 if report["failed_cycles"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
