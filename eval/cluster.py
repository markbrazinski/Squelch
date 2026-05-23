"""FP clustering for Squelch's tuning loop.

Given a detection's labeled notable events, produce per-field cluster
hypotheses ranked by FP explanatory power, annotated with recall risk
(tp_pct) and lookup matches (e.g. known-scanner IPs).

Consumed by:
  - Sessions 5-6: the LLM prompt builder picks by_field[<top_field>][0]
    as the top hypothesis to filter.
  - Bundle 4: the multi-hypothesis UI iterates by_field to render
    per-field hypotheses with ✓/✗ from the tp_pct safety annotation.

Vendored to /Applications/Splunk/etc/apps/squelch/bin/lib/squelch_eval/
after edits.
"""

from __future__ import annotations

import csv
from collections import Counter, defaultdict
from pathlib import Path

try:
    # Vendored as a package inside the Splunk app: squelch_eval/{eval_lib,cluster}.py
    from .eval_lib import _read_json_results
except ImportError:
    # Repo-side: eval/ is on sys.path, eval_lib is a sibling module.
    from eval_lib import _read_json_results


FIELDS_DEFAULT = ("src_ip", "dest", "user")


def pull_labeled_events(service, search_name: str,
                        earliest: str = "-90d", latest: str = "now") -> list[dict]:
    """Return labeled notable events for one detection.

    SPL is host-filtered to `squelch-seed` to match the golden dataset
    (D3 / eval/golden_dataset.conf). Rows without a status_label are
    dropped — clustering only operates on labeled events.
    """
    spl = (
        f'search index=notable sourcetype=squelch_notable host=squelch-seed '
        f'search_name="{search_name}" '
        f'| fields _cd, src_ip, dest, user, status_label'
    )
    stream = service.jobs.oneshot(
        spl, earliest_time=earliest, latest_time=latest,
        output_mode="json", count=0,
    )
    rows = _read_json_results(stream)
    return [r for r in rows if r.get("status_label")]


def load_lookup(csv_path: Path | None) -> dict[str, str]:
    """Two-column CSV → {value: context}. Returns {} if path missing.

    Column 0 is the lookup key; column 1 is the human-readable context.
    Header row is skipped (DictReader-style — first row defines names
    but we just read positionally for simplicity).
    """
    if csv_path is None or not Path(csv_path).exists():
        return {}
    out: dict[str, str] = {}
    with open(csv_path, newline="") as f:
        reader = csv.reader(f)
        next(reader, None)  # skip header
        for row in reader:
            if len(row) >= 2 and row[0]:
                out[row[0]] = row[1]
    return out


_IDENTITY_NORM_MAP = {
    "true_positive": "true_positive",
    "false_positive": "false_positive",
}


def cluster_fps(events: list[dict],
                fields: tuple[str, ...] = FIELDS_DEFAULT,
                lookup_csv_path: Path | None = None,
                lookup_name: str = "scanner_ips",
                normalization_csv: Path | None = None) -> dict:
    """Per-field FP clusters with recall-risk and lookup annotations.

    Args:
        events: output of pull_labeled_events (must carry status_label).
        fields: which event fields to cluster on.
        lookup_csv_path: optional CSV path; if set, values present in
            the lookup get lookup_match=lookup_name + lookup_context.
        lookup_name: tag written to lookup_match. Lets Bundle 2 wire
            additional lookups (e.g. service_accounts) without changing
            the function signature.
        normalization_csv: optional CSV path mapping noisy `status_label`
            values to canonical "true_positive"/"false_positive". Bundle 2
            Sessions 13-14. When None, only literal canonical labels count
            (Bundle 1 behavior).

    Returns:
        {
          "total_fps": int,
          "total_tps": int,
          "by_field": {
            <field>: [{"value", "fp_count", "fp_pct", "tp_count",
                       "tp_pct", "lookup_match", "lookup_context"}, ...],
            ...
          },
        }
    """
    lookup = load_lookup(lookup_csv_path)
    norm_map = load_lookup(normalization_csv) if normalization_csv else dict(_IDENTITY_NORM_MAP)
    if not norm_map:
        norm_map = dict(_IDENTITY_NORM_MAP)

    def _norm(e: dict) -> str | None:
        return norm_map.get(e.get("status_label"))

    total_fps = sum(1 for e in events if _norm(e) == "false_positive")
    total_tps = sum(1 for e in events if _norm(e) == "true_positive")

    by_field: dict[str, list[dict]] = {}
    for fld in fields:
        fp_counter: Counter = Counter()
        tp_counter: Counter = Counter()
        for e in events:
            val = e.get(fld)
            if val is None or val == "":
                continue
            normalized = _norm(e)
            if normalized == "false_positive":
                fp_counter[val] += 1
            elif normalized == "true_positive":
                tp_counter[val] += 1

        cluster_rows = []
        # Only emit values that appear in at least one FP (the things
        # the LLM might propose filtering). A value with tp_count>0
        # but fp_count==0 is just a TP, not a cluster hypothesis.
        for value, fp_count in fp_counter.items():
            tp_count = tp_counter.get(value, 0)
            fp_pct = fp_count / total_fps if total_fps else 0.0
            tp_pct = tp_count / total_tps if total_tps else 0.0
            ctx = lookup.get(value)
            cluster_rows.append({
                "value": value,
                "fp_count": fp_count,
                "fp_pct": round(fp_pct, 4),
                "tp_count": tp_count,
                "tp_pct": round(tp_pct, 4),
                "lookup_match": lookup_name if ctx is not None else None,
                "lookup_context": ctx,
            })
        cluster_rows.sort(key=lambda r: r["fp_pct"], reverse=True)
        by_field[fld] = cluster_rows

    return {
        "total_fps": total_fps,
        "total_tps": total_tps,
        "by_field": by_field,
    }
