"""Unit tests for temporal_holdout_eval() — Bundle 5 Sessions 38-39.

Patches evaluate_detection and _get_time_boundaries to avoid live Splunk.
"""

import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent))

from eval_lib import (
    EvalResult,
    HOLDOUT_PRECISION_FLOOR_DELTA,
    temporal_holdout_eval,
)

_T_MIN = 1_700_000_000.0
_T_MAX = 1_700_100_000.0
_T_SPLIT = _T_MIN + 0.70 * (_T_MAX - _T_MIN)  # 1_700_070_000.0


def _make_result(precision, recall, n=100):
    tp = int(precision * n)
    fp = n - tp
    return EvalResult(
        detection_name="test",
        tp=tp, fp=fp, fn=0,
        total_dataset_size=n,
        precision=precision, recall=recall, fp_rate=1 - precision,
        runtime_ms=10, timestamp=1.0,
    )


def test_happy_path_pass():
    """Training + holdout both improve → pass=True."""
    results = iter([
        _make_result(0.29, 1.0, 87),   # baseline_train
        _make_result(0.31, 1.0, 38),   # baseline_holdout
        _make_result(0.51, 1.0, 87),   # revised_train
        _make_result(0.44, 1.0, 38),   # revised_holdout
    ])

    with patch("eval_lib._get_time_boundaries", return_value=(_T_MIN, _T_MAX)), \
         patch("eval_lib.evaluate_detection", side_effect=lambda *a, **kw: next(results)):
        out = temporal_holdout_eval(None, "det", "orig_spl", "revised_spl", "golden_query")

    assert out["pass"] is True
    assert abs(out["training_precision_lift"] - round(0.51 - 0.29, 4)) < 1e-6
    assert abs(out["holdout_precision_lift"] - round(0.44 - 0.31, 4)) < 1e-6
    assert out["holdout_recall_delta"] == 0.0
    assert out["training_events"] == 87
    assert out["holdout_events"] == 38
    assert abs(out["t_split_epoch"] - _T_SPLIT) < 1.0


def test_overfitting_fails():
    """Training lift positive but holdout precision drops → pass=False."""
    results = iter([
        _make_result(0.30, 1.0, 87),   # baseline_train
        _make_result(0.32, 1.0, 38),   # baseline_holdout
        _make_result(0.55, 1.0, 87),   # revised_train  (big training gain)
        _make_result(0.25, 1.0, 38),   # revised_holdout (drops on holdout)
    ])

    with patch("eval_lib._get_time_boundaries", return_value=(_T_MIN, _T_MAX)), \
         patch("eval_lib.evaluate_detection", side_effect=lambda *a, **kw: next(results)):
        out = temporal_holdout_eval(None, "det", "orig_spl", "revised_spl", "golden_query")

    assert out["pass"] is False
    assert out["holdout_precision_lift"] < HOLDOUT_PRECISION_FLOOR_DELTA


def test_baseline_only_always_passes():
    """revised_spl=None → pass=True, all revised/delta fields are None."""
    results = iter([
        _make_result(0.22, 1.0, 87),   # baseline_train
        _make_result(0.24, 1.0, 38),   # baseline_holdout
    ])

    with patch("eval_lib._get_time_boundaries", return_value=(_T_MIN, _T_MAX)), \
         patch("eval_lib.evaluate_detection", side_effect=lambda *a, **kw: next(results)):
        out = temporal_holdout_eval(None, "det", "orig_spl", None, "golden_query")

    assert out["pass"] is True
    assert out["revised_train_precision"] is None
    assert out["revised_holdout_precision"] is None
    assert out["training_precision_lift"] is None
    assert out["holdout_precision_lift"] is None
    assert out["training_recall_delta"] is None
    assert out["holdout_recall_delta"] is None


def test_recall_drop_on_holdout_fails():
    """Precision holds but holdout recall drops → pass=False."""
    results = iter([
        _make_result(0.30, 1.0, 87),   # baseline_train
        _make_result(0.30, 1.0, 38),   # baseline_holdout
        _make_result(0.50, 1.0, 87),   # revised_train
        _make_result(0.50, 0.8, 38),   # revised_holdout — recall drops
    ])

    with patch("eval_lib._get_time_boundaries", return_value=(_T_MIN, _T_MAX)), \
         patch("eval_lib.evaluate_detection", side_effect=lambda *a, **kw: next(results)):
        out = temporal_holdout_eval(None, "det", "orig_spl", "revised_spl", "golden_query")

    assert out["pass"] is False
    assert out["holdout_recall_delta"] < 0


if __name__ == "__main__":
    test_happy_path_pass()
    print("PASS: test_happy_path_pass")
    test_overfitting_fails()
    print("PASS: test_overfitting_fails")
    test_baseline_only_always_passes()
    print("PASS: test_baseline_only_always_passes")
    test_recall_drop_on_holdout_fails()
    print("PASS: test_recall_drop_on_holdout_fails")
    print("\nAll tests passed.")
