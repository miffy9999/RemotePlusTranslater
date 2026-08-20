from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from pathlib import Path

from translator_app.config import load_config
from translator_app.hymt2 import create_translator

ROOT = Path(__file__).resolve().parent.parent
CORPORA = (
    ROOT / "benchmarks/hotel_translation_extended.json",
    ROOT / "benchmarks/hotel_translation_holdout.json",
    ROOT / "benchmarks/hotel_translation_validation.json",
    ROOT / "benchmarks/hotel_context_validation.json",
)
REPORT = ROOT / "benchmarks/latest_product_validation_report.json"


def score(text: str, groups: list[list[str]]) -> tuple[float, list[list[str]]]:
    folded = text.casefold()
    missed = [group for group in groups if not any(term.casefold() in folded for term in group)]
    return (len(groups) - len(missed)) / len(groups), missed


def percentile(values: list[float], fraction: float) -> float:
    """Return a nearest-rank percentile without an optional statistics package."""
    ordered = sorted(values)
    if not ordered:
        return 0.0
    index = min(len(ordered) - 1, max(0, round((len(ordered) - 1) * fraction)))
    return ordered[index]


def candidate_regressions(
    candidate: dict,
    baseline: dict,
    *,
    speed_tolerance: float = 0.0,
) -> list[str]:
    """Apply a fail-closed quality and model-latency promotion gate."""
    failures = []
    if candidate.get("failed"):
        failures.append("candidate has failed quality rows")
    for key in ("forward_score", "reverse_score"):
        if candidate.get(key, 0) < baseline.get(key, 0):
            failures.append(f"{key} regressed")
    for key in ("model_latency_median_seconds", "model_latency_p95_seconds"):
        limit = baseline.get(key, 0) * (1 + speed_tolerance)
        if not limit:
            failures.append(f"baseline is missing {key}")
        elif candidate.get(key, float("inf")) > limit:
            failures.append(f"{key} regressed")
    return failures


def main() -> int:
    """Run every hotel corpus through the same translator used by the app."""
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
    parser = argparse.ArgumentParser(description=main.__doc__)
    parser.add_argument("--model", help="GGUF path to benchmark instead of the configured model")
    parser.add_argument("--report", type=Path, default=REPORT)
    parser.add_argument("--baseline-report", type=Path)
    parser.add_argument("--repeats", type=int, default=1)
    parser.add_argument("--speed-tolerance", type=float, default=0.0)
    args = parser.parse_args()
    if args.repeats < 1:
        parser.error("--repeats must be at least 1")
    if args.speed_tolerance < 0:
        parser.error("--speed-tolerance cannot be negative")
    cfg = load_config()
    if args.model:
        cfg.translation.hymt2_model = args.model
    translator = create_translator(
        cfg.translation,
        lambda phase, message: print(phase, message, flush=True),
    )
    rows = []
    try:
        translator.load()
        if not translator.is_available():
            summary = {
                "samples": 0,
                "forward_score": 0.0,
                "reverse_score": 0.0,
                "failed": ["model_unavailable"],
                "model_routed_samples": 0,
                "model_latency_median_seconds": 0.0,
                "model_latency_p95_seconds": 0.0,
            }
            if args.baseline_report:
                summary["promotion_regressions"] = ["candidate model failed to load"]
            args.report.parent.mkdir(parents=True, exist_ok=True)
            args.report.write_text(
                json.dumps({"summary": summary, "rows": []}, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            print("SUMMARY", json.dumps(summary, ensure_ascii=False), flush=True)
            return 1
        translator.warmup()
        for repeat in range(args.repeats):
            for corpus_path in CORPORA:
                corpus = json.loads(corpus_path.read_text(encoding="utf-8"))
                for item in corpus:
                    started = time.perf_counter()
                    if item.get("previous") or item.get("next"):
                        translated = translator.translate_contextual(
                            item["text"],
                            item["source"],
                            item["target"],
                            previous_text=item.get("previous", ""),
                            next_text=item.get("next", ""),
                        )
                    else:
                        translated = translator.translate(
                            item["text"], item["source"], item["target"]
                        )
                    seconds = time.perf_counter() - started
                    term_score, missed = score(translated, item["expected_any"])
                    row = {
                        **item,
                        "corpus": corpus_path.stem,
                        "repeat": repeat + 1,
                        "translated": translated,
                        "score": round(term_score, 3),
                        "missed": missed,
                        "seconds": round(seconds, 3),
                        # Exact phrasebook hits return nearly instantly. Excluding them prevents
                        # deterministic rules from hiding a slower neural candidate.
                        "model_routed": seconds >= 0.05,
                    }
                    rows.append(row)
                    print(
                        f"{item['id']} {term_score:.3f} {row['seconds']:.2f}s | {translated}",
                        flush=True,
                    )
    finally:
        translator.close()

    forward = [row for row in rows if row["source"] != "ja"]
    reverse = [row for row in rows if row["source"] == "ja"]
    model_latencies = [row["seconds"] for row in rows if row["model_routed"]]
    if not model_latencies:
        raise RuntimeError("No neural model-routed samples were measured")
    summary = {
        "samples": len(rows),
        "forward_score": round(sum(row["score"] for row in forward) / len(forward), 3),
        "reverse_score": round(sum(row["score"] for row in reverse) / len(reverse), 3),
        "failed": sorted({row["id"] for row in rows if row["score"] < 1}),
        "model_routed_samples": len(model_latencies),
        "model_latency_median_seconds": round(statistics.median(model_latencies), 3),
        "model_latency_p95_seconds": round(percentile(model_latencies, 0.95), 3),
    }
    regressions = []
    if args.baseline_report:
        baseline = json.loads(args.baseline_report.read_text(encoding="utf-8"))["summary"]
        regressions = candidate_regressions(
            summary,
            baseline,
            speed_tolerance=args.speed_tolerance,
        )
        summary["promotion_regressions"] = regressions
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(
        json.dumps({"summary": summary, "rows": rows}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print("SUMMARY", json.dumps(summary, ensure_ascii=False), flush=True)
    return 1 if summary["failed"] or regressions else 0


if __name__ == "__main__":
    raise SystemExit(main())
