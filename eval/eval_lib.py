"""Eval harness core: precision / recall / runtime for a detection SPL.

Used by both `eval/run_eval.py` (CLI) and the `| squelch mode="validate"`
custom search command (which imports a vendored copy from bin/lib/).

The golden dataset query is a **parameter**, not a hardcoded constant:
Bundle 2 (attack injection testing) needs to supply an alternate query
that UNIONs the seeded set with injected synthetic TP events. Keeping it
as an arg means that's a one-line change in the caller, not a refactor.
"""

from __future__ import annotations

import configparser
import time
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class EvalResult:
    detection_name: str
    tp: int
    fp: int
    fn: int
    total_dataset_size: int
    precision: float
    recall: float
    fp_rate: float
    runtime_ms: int
    timestamp: float
    # Fraction of golden events whose status_label normalized to TP or FP.
    # 1.0 when every event was usable; lower when blanks / unmapped labels
    # had to be excluded. Surfaced to the | squelch result row + KV trace.
    label_confidence: float = 1.0
    # Identity sets — needed by gate_revision to compute events_lost.
    # Not serialized to CSV (CSV consumers don't need them).
    fired_ids: frozenset[str] = field(default_factory=frozenset, repr=False)
    golden_tp_ids: frozenset[str] = field(default_factory=frozenset, repr=False)

    def as_csv_row(self) -> dict:
        return {
            "timestamp": f"{self.timestamp:.0f}",
            "detection_name": self.detection_name,
            "tp": self.tp,
            "fp": self.fp,
            "fn": self.fn,
            "total_dataset_size": self.total_dataset_size,
            "precision": f"{self.precision:.4f}",
            "recall": f"{self.recall:.4f}",
            "fp_rate": f"{self.fp_rate:.4f}",
            "runtime_ms": self.runtime_ms,
            "label_confidence": f"{self.label_confidence:.4f}",
        }

    def as_metric_dict(self) -> dict:
        """Pipeline-friendly metric bundle for KV writes (no identity sets)."""
        return {
            "detection_name": self.detection_name,
            "tp": self.tp, "fp": self.fp, "fn": self.fn,
            "total_dataset_size": self.total_dataset_size,
            "precision": round(self.precision, 4),
            "recall": round(self.recall, 4),
            "fp_rate": round(self.fp_rate, 4),
            "runtime_ms": self.runtime_ms,
            "timestamp": int(self.timestamp),
            "label_confidence": round(self.label_confidence, 4),
        }


def _read_json_results(stream) -> list[dict]:
    """splunklib oneshot stream → list of result dicts."""
    import splunklib.results as results
    out = []
    for item in results.JSONResultsReader(stream):
        if isinstance(item, dict):
            out.append(item)
    return out


def load_golden_query(conf_path: Path, stanza: str = "default") -> tuple[str, str, str]:
    """Load (query, earliest, latest) from a golden_dataset.conf stanza."""
    cfg = configparser.ConfigParser()
    cfg.read(conf_path)
    if stanza not in cfg:
        raise KeyError(f"stanza '{stanza}' not found in {conf_path}")
    s = cfg[stanza]
    return s["query"], s.get("earliest", "-90d"), s.get("latest", "now")


def _event_id(event: dict) -> str:
    """Use Splunk's internal _cd as a stable per-event identifier."""
    return event.get("_cd") or event.get("_serial") or repr(event)


_IDENTITY_NORM_MAP = {
    "true_positive": "true_positive",
    "false_positive": "false_positive",
}


def _load_normalization_map(normalization_csv: Path | None) -> dict[str, str]:
    """CSV path → {raw_label: normalized_label}. None / missing → identity map.

    Deferred import of load_lookup from .cluster to avoid a module-level
    circular import (cluster imports _read_json_results from us). The
    try/except mirrors the same dual-mode pattern cluster.py uses.
    """
    if normalization_csv is None:
        return dict(_IDENTITY_NORM_MAP)
    try:
        from .cluster import load_lookup
    except ImportError:
        from cluster import load_lookup
    m = load_lookup(normalization_csv)
    return m or dict(_IDENTITY_NORM_MAP)


def evaluate_detection(
    service,
    detection_name: str,
    detection_spl: str,
    golden_query: str,
    earliest: str = "-90d",
    latest: str = "now",
    normalization_csv: Path | None = None,
) -> EvalResult:
    """Run detection_spl + golden_query, compute confusion matrix and metrics.

    golden_query returns events with a `status_label` field. When
    normalization_csv is provided, raw labels are mapped through it
    (e.g. "resolved" → "false_positive"); blank / unmapped labels are
    excluded from both TP and FP counts. label_confidence reports the
    share of golden events whose label was usable.

    Without normalization_csv, only literal "true_positive" /
    "false_positive" count (Bundle 1 behavior preserved).

    detection_spl is whatever the saved search runs (the "detection
    fires on these events" definition).
    """
    norm_map = _load_normalization_map(normalization_csv)

    # 1. Golden ground truth
    # Both queries get wrapped with `| fields ...` so search-time extracted
    # fields (status_label, etc.) are surfaced to JSONResultsReader.
    golden_wrapped = f"{golden_query} | fields _cd, status_label"
    golden_stream = service.jobs.oneshot(
        golden_wrapped, earliest_time=earliest, latest_time=latest,
        output_mode="json", count=0,
    )
    golden_rows = _read_json_results(golden_stream)
    golden_tp_ids: set[str] = set()
    golden_fp_ids: set[str] = set()
    for e in golden_rows:
        normalized = norm_map.get(e.get("status_label"))
        if normalized == "true_positive":
            golden_tp_ids.add(_event_id(e))
        elif normalized == "false_positive":
            golden_fp_ids.add(_event_id(e))

    labeled = len(golden_tp_ids) + len(golden_fp_ids)
    label_confidence = labeled / len(golden_rows) if golden_rows else 0.0

    # 2. Detection fires — _cd alone is enough; we just need identity
    detection_wrapped = f"{detection_spl} | fields _cd"
    start = time.time()
    detection_stream = service.jobs.oneshot(
        detection_wrapped, earliest_time=earliest, latest_time=latest,
        output_mode="json", count=0,
    )
    detection_rows = _read_json_results(detection_stream)
    runtime_ms = int((time.time() - start) * 1000)
    fired_ids = {_event_id(e) for e in detection_rows}

    # 3. Confusion matrix
    tp = len(fired_ids & golden_tp_ids)
    fp = len(fired_ids & golden_fp_ids)
    fn = len(golden_tp_ids - fired_ids)
    fires = tp + fp
    precision = tp / fires if fires else 0.0
    recall = tp / len(golden_tp_ids) if golden_tp_ids else 0.0
    fp_rate = fp / fires if fires else 0.0

    return EvalResult(
        detection_name=detection_name,
        tp=tp, fp=fp, fn=fn,
        total_dataset_size=len(golden_rows),
        precision=precision, recall=recall, fp_rate=fp_rate,
        runtime_ms=runtime_ms,
        timestamp=time.time(),
        label_confidence=label_confidence,
        fired_ids=frozenset(fired_ids),
        golden_tp_ids=frozenset(golden_tp_ids),
    )


def gate_revision(baseline: EvalResult, proposed: EvalResult) -> dict:
    """Recall-preservation gate (D3).

    Accept if proposed.recall >= baseline.recall. Reject otherwise with
    the specific _cd IDs that the revision would drop — surfacing those
    is what makes the rejection actionable for an analyst.

    The two EvalResults must come from the same golden dataset run (same
    golden_tp_ids); the function does not assert this but assumes it.
    """
    if proposed.recall >= baseline.recall:
        return {
            "status": "accepted",
            "precision_delta": round(proposed.precision - baseline.precision, 4),
            "recall_delta": round(proposed.recall - baseline.recall, 4),
            "fp_rate_delta": round(proposed.fp_rate - baseline.fp_rate, 4),
        }
    # Events the baseline caught (TP) but the proposal missed.
    baseline_tp_caught = baseline.fired_ids & baseline.golden_tp_ids
    events_lost = sorted(baseline_tp_caught - proposed.fired_ids)
    return {
        "status": "rejected",
        "reason": "recall_drop",
        "baseline_recall": round(baseline.recall, 4),
        "revised_recall": round(proposed.recall, 4),
        "events_lost": events_lost,
    }


def evaluate_recall_preserved(baseline: EvalResult, proposed: EvalResult) -> bool:
    """Back-compat shim. Prefer gate_revision() for the structured output.

    Kept so external callers don't break; will be removed once Bundle 1
    Session 7 lands and we've confirmed no other consumers exist.
    """
    return proposed.recall >= baseline.recall


def snapshot_baseline(service, detection_name: str, golden_conf_path: Path,
                      golden_stanza: str = "default",
                      normalization_csv: Path | None = None) -> EvalResult:
    """Run a saved search's current SPL against the golden dataset.

    Returns the EvalResult the pipeline persists to detection_lineage KV
    as `eval_before`. Pure: the caller decides where the result goes.
    """
    detection_spl = service.saved_searches[detection_name]["search"]
    golden_query, earliest, latest = load_golden_query(golden_conf_path, golden_stanza)
    return evaluate_detection(
        service=service,
        detection_name=detection_name,
        detection_spl=detection_spl,
        golden_query=golden_query,
        earliest=earliest,
        latest=latest,
        normalization_csv=normalization_csv,
    )
