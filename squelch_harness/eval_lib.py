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
import copy
import hashlib
import random
import time
from dataclasses import dataclass, field
from pathlib import Path


# Bundle 4 Sessions 33-34: max abs recall delta under 10% label-flip
# perturbation that still counts as PASS. 0.05 is informational only —
# the recall gate (gate_revision) remains the safety mechanism.
PERTURB_RECALL_PASS_THRESHOLD = 0.05

# Bundle 5 Sessions 38-39: holdout precision must not degrade vs training.
# 0.0 means the revision is allowed to hold flat but not drop. Informational
# only — the recall gate remains the safety mechanism.
HOLDOUT_PRECISION_FLOOR_DELTA = 0.0
HOLDOUT_SPLIT_PCT = 0.70  # 70% training, 30% holdout

try:
    # Vendored: squelch_eval/{utils,eval_lib}.py
    from .utils import load_lookup
except ImportError:
    # Repo-side sibling import.
    from utils import load_lookup


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
    # interpolation=None: the `query` values are raw SPL and may contain `%`
    # (strftime formats, like("...%foo%") patterns). ConfigParser's default
    # BasicInterpolation treats `%` as a sigil and would raise on those.
    cfg = configparser.ConfigParser(interpolation=None)
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
    """CSV path → {raw_label: normalized_label}. None / missing → identity map."""
    if normalization_csv is None:
        return dict(_IDENTITY_NORM_MAP)
    m = load_lookup(normalization_csv)
    return m or dict(_IDENTITY_NORM_MAP)


def _injected_would_fire(detection_spl: str, event: dict) -> bool:
    """Does `detection_spl` admit `event`? Bundle 2 Sessions 15-16.

    Assumes detection_spl is the original SPL plus at most one trailing
    `NOT field IN (...)` clause (the LLM contract enforced by revise.py).
    Returns False iff event[field] is in that NOT list — the rest of the
    SPL is treated as a pass, since we cannot run Splunk against a
    single in-memory event.

    Lazy import of parse_not_filter to avoid a module-level dependency
    loop with attack_inject (which imports evaluate_detection from us).
    """
    try:
        from .attack_inject import parse_not_filter
    except ImportError:
        from attack_inject import parse_not_filter
    field, values = parse_not_filter(detection_spl)
    if field is None:
        return True
    return event.get(field) not in values


def evaluate_detection(
    service,
    detection_name: str,
    detection_spl: str,
    golden_query: str,
    earliest: str = "-90d",
    latest: str = "now",
    normalization_csv: Path | None = None,
    injected_events: list[dict] | None = None,
    golden_events: list[dict] | None = None,
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

    Bundle 4 Sessions 33-34: when `golden_events` is provided, the golden
    Splunk query is skipped and the supplied events are used directly.
    Callers are responsible for providing events with the *raw*
    `status_label` field — the function re-normalizes via
    normalization_csv. Used by perturb_and_eval to flip labels in-memory
    across trials without re-querying Splunk.
    """
    norm_map = _load_normalization_map(normalization_csv)

    # 1. Golden ground truth
    # Both queries get wrapped with `| fields ...` so search-time extracted
    # fields (status_label, etc.) are surfaced to JSONResultsReader.
    if golden_events is None:
        golden_wrapped = f"{golden_query} | fields _cd, status_label"
        golden_stream = service.jobs.oneshot(
            golden_wrapped, earliest_time=earliest, latest_time=latest,
            output_mode="json", count=0,
        )
        golden_rows = _read_json_results(golden_stream)
    else:
        golden_rows = golden_events
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

    # 2b. Union in synthetic TPs (Bundle 2 Sessions 15-16). Each injected
    # event is a TP by construction; whether it would fire is decided by
    # checking detection_spl's trailing NOT clause structurally in Python
    # (no second Splunk query for the in-memory set).
    if injected_events:
        for ev in injected_events:
            golden_tp_ids.add(_event_id(ev))
            if _injected_would_fire(detection_spl, ev):
                fired_ids.add(_event_id(ev))
        # Recompute label_confidence to include the synthetic events in
        # the denominator — they ARE labeled (TPs by construction).
        labeled = len(golden_tp_ids) + len(golden_fp_ids)
        label_confidence = (
            labeled / (len(golden_rows) + len(injected_events))
            if (golden_rows or injected_events) else 0.0
        )

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
        total_dataset_size=len(golden_rows) + (len(injected_events) if injected_events else 0),
        precision=precision, recall=recall, fp_rate=fp_rate,
        runtime_ms=runtime_ms,
        timestamp=time.time(),
        label_confidence=label_confidence,
        fired_ids=frozenset(fired_ids),
        golden_tp_ids=frozenset(golden_tp_ids),
    )


_LABEL_FLIP = {
    "true_positive": "false_positive",
    "false_positive": "true_positive",
}


def _perturb_seeded_rng(detection_name: str, trial_idx: int) -> random.Random:
    """SHA-256-seeded RNG, namespaced to perturbation. Matches the
    template at attack_inject._seeded_rng so the two RNGs never collide
    (different namespace token: `:perturb:` vs the SPL itself).
    """
    seed_bytes = hashlib.sha256(
        f"{detection_name}:perturb:{trial_idx}".encode("utf-8")
    ).digest()[:8]
    return random.Random(int.from_bytes(seed_bytes, "big"))


def perturb_and_eval(
    service,
    detection_name: str,
    detection_spl: str,
    golden_query: str,
    *,
    normalization_csv: Path | None = None,
    earliest: str = "-90d",
    latest: str = "now",
    flip_pct: float = 0.10,
    n_trials: int = 3,
    baseline: EvalResult | None = None,
) -> dict:
    """Flip a random fraction of golden labels, re-eval, repeat.

    Reports how much precision/recall move under label noise. PASS when
    abs(max_recall_delta) < PERTURB_RECALL_PASS_THRESHOLD — informational
    only; the recall gate in gate_revision remains the safety mechanism.

    Re-uses the in-memory event pattern from attack_inject: pulls the
    golden set once and flips labels per trial without re-querying Splunk.
    """
    if baseline is None:
        baseline = evaluate_detection(
            service, detection_name, detection_spl, golden_query,
            earliest=earliest, latest=latest,
            normalization_csv=normalization_csv,
        )

    golden_wrapped = f"{golden_query} | fields _cd, status_label"
    golden_stream = service.jobs.oneshot(
        golden_wrapped, earliest_time=earliest, latest_time=latest,
        output_mode="json", count=0,
    )
    golden_rows = _read_json_results(golden_stream)

    precision_deltas: list[float] = []
    recall_deltas: list[float] = []

    for i in range(n_trials):
        rng = _perturb_seeded_rng(detection_name, i)
        perturbed = copy.deepcopy(golden_rows)
        k = max(1, int(flip_pct * len(perturbed))) if perturbed else 0
        if k:
            for idx in rng.sample(range(len(perturbed)), k):
                ev = perturbed[idx]
                ev["status_label"] = _LABEL_FLIP.get(
                    ev.get("status_label"), ev.get("status_label"),
                )

        trial = evaluate_detection(
            service, detection_name, detection_spl, golden_query,
            earliest=earliest, latest=latest,
            normalization_csv=normalization_csv,
            golden_events=perturbed,
        )
        precision_deltas.append(trial.precision - baseline.precision)
        recall_deltas.append(trial.recall - baseline.recall)

    mean_precision_delta = (
        sum(precision_deltas) / len(precision_deltas) if precision_deltas else 0.0
    )
    mean_recall_delta = (
        sum(recall_deltas) / len(recall_deltas) if recall_deltas else 0.0
    )
    # Signed value with largest absolute magnitude — keeps directional info.
    max_precision_delta = (
        max(precision_deltas, key=abs) if precision_deltas else 0.0
    )
    max_recall_delta = (
        max(recall_deltas, key=abs) if recall_deltas else 0.0
    )

    return {
        "mean_precision_delta": round(mean_precision_delta, 4),
        "mean_recall_delta": round(mean_recall_delta, 4),
        "max_precision_delta": round(max_precision_delta, 4),
        "max_recall_delta": round(max_recall_delta, 4),
        "n_trials": n_trials,
        "flip_pct": flip_pct,
        "pass": abs(max_recall_delta) < PERTURB_RECALL_PASS_THRESHOLD,
    }


def _get_time_boundaries(service, golden_query: str) -> tuple[float, float]:
    """Query golden data for min/max _time. Returns (earliest_epoch, latest_epoch)."""
    # Don't blindly prepend `search ` — golden_query already begins with a
    # `search` command (or a `|` generating command). Prepending produced
    # `search search index=...`, which Splunk reads as a literal term match and
    # returns zero rows. Only add the verb when the query lacks a leading one.
    q = golden_query.lstrip()
    if not (q.startswith("search ") or q.startswith("|")):
        q = f"search {q}"
    stats_query = f"{q} | stats min(_time) as t_min max(_time) as t_max"
    # earliest_time="0": scan all time, not the dispatch default window. A
    # golden dataset whose events predate the default window (e.g. BOTSv3's
    # 2018 data) would otherwise return zero rows and IndexError below.
    stream = service.jobs.oneshot(
        stats_query, earliest_time="0", latest_time="now",
        output_mode="json", count=1,
    )
    rows = _read_json_results(stream)
    if not rows or rows[0].get("t_min") in (None, ""):
        raise ValueError(
            f"golden query returned no time boundaries (no events in window): {golden_query}"
        )
    row = rows[0]
    return float(row["t_min"]), float(row["t_max"])


def temporal_holdout_eval(
    service,
    detection_name: str,
    original_spl: str,
    revised_spl: str | None,
    golden_query: str,
    *,
    normalization_csv: Path | None = None,
    split_pct: float = HOLDOUT_SPLIT_PCT,
) -> dict:
    """Split golden data temporally, evaluate both SPLs on both windows.

    For accepted tunes: compares precision lift on training vs holdout to
    detect overfitting. For declined/rejected tunes: revised_spl is None,
    reports baseline temporal metrics only (always pass=True).
    """
    t_min, t_max = _get_time_boundaries(service, golden_query)
    t_split = t_min + split_pct * (t_max - t_min)

    t_min_str = str(int(t_min))
    t_split_str = str(int(t_split))
    t_max_str = str(int(t_max))

    baseline_train = evaluate_detection(
        service, detection_name, original_spl, golden_query,
        earliest=t_min_str, latest=t_split_str,
        normalization_csv=normalization_csv,
    )
    baseline_holdout = evaluate_detection(
        service, detection_name, original_spl, golden_query,
        earliest=t_split_str, latest=t_max_str,
        normalization_csv=normalization_csv,
    )

    if revised_spl is not None:
        revised_train = evaluate_detection(
            service, detection_name, revised_spl, golden_query,
            earliest=t_min_str, latest=t_split_str,
            normalization_csv=normalization_csv,
        )
        revised_holdout = evaluate_detection(
            service, detection_name, revised_spl, golden_query,
            earliest=t_split_str, latest=t_max_str,
            normalization_csv=normalization_csv,
        )
        training_precision_lift = round(
            revised_train.precision - baseline_train.precision, 4
        )
        holdout_precision_lift = round(
            revised_holdout.precision - baseline_holdout.precision, 4
        )
        training_recall_delta = round(
            revised_train.recall - baseline_train.recall, 4
        )
        holdout_recall_delta = round(
            revised_holdout.recall - baseline_holdout.recall, 4
        )
        pass_flag = (
            holdout_precision_lift >= HOLDOUT_PRECISION_FLOOR_DELTA
            and holdout_recall_delta >= 0
        )
        return {
            "split_pct": split_pct,
            "t_split_epoch": t_split,
            "training_events": baseline_train.total_dataset_size,
            "holdout_events": baseline_holdout.total_dataset_size,
            "baseline_train_precision": baseline_train.precision,
            "baseline_holdout_precision": baseline_holdout.precision,
            "revised_train_precision": revised_train.precision,
            "revised_holdout_precision": revised_holdout.precision,
            "training_precision_lift": training_precision_lift,
            "holdout_precision_lift": holdout_precision_lift,
            "training_recall_delta": training_recall_delta,
            "holdout_recall_delta": holdout_recall_delta,
            "pass": pass_flag,
        }

    return {
        "split_pct": split_pct,
        "t_split_epoch": t_split,
        "training_events": baseline_train.total_dataset_size,
        "holdout_events": baseline_holdout.total_dataset_size,
        "baseline_train_precision": baseline_train.precision,
        "baseline_holdout_precision": baseline_holdout.precision,
        "revised_train_precision": None,
        "revised_holdout_precision": None,
        "training_precision_lift": None,
        "holdout_precision_lift": None,
        "training_recall_delta": None,
        "holdout_recall_delta": None,
        "pass": True,
    }


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
