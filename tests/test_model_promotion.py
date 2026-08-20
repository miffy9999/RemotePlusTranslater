from scripts.benchmark_hymt2 import candidate_regressions, percentile


def test_percentile_is_stable_for_small_benchmark_sets():
    assert percentile([1.0, 2.0, 3.0, 4.0], 0.95) == 4.0
    assert percentile([], 0.95) == 0.0


def test_candidate_gate_rejects_any_quality_or_speed_regression():
    baseline = {
        "forward_score": 1.0,
        "reverse_score": 1.0,
        "failed": [],
        "model_latency_median_seconds": 0.8,
        "model_latency_p95_seconds": 1.2,
    }
    candidate = {
        **baseline,
        "forward_score": 0.99,
        "failed": ["one"],
        "model_latency_median_seconds": 0.81,
        "model_latency_p95_seconds": 1.21,
    }
    failures = candidate_regressions(candidate, baseline)
    assert "candidate has failed quality rows" in failures
    assert "forward_score regressed" in failures
    assert "model_latency_median_seconds regressed" in failures
    assert "model_latency_p95_seconds regressed" in failures


def test_candidate_gate_accepts_equal_or_better_model():
    baseline = {
        "forward_score": 0.99,
        "reverse_score": 1.0,
        "failed": [],
        "model_latency_median_seconds": 0.8,
        "model_latency_p95_seconds": 1.2,
    }
    candidate = {
        **baseline,
        "forward_score": 1.0,
        "model_latency_median_seconds": 0.79,
    }
    assert candidate_regressions(candidate, baseline) == []
