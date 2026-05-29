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

from collections import Counter, defaultdict
from pathlib import Path

try:
    # Vendored as a package inside the Splunk app: squelch_eval/{eval_lib,cluster,utils}.py
    from .eval_lib import _read_json_results
    from .utils import load_lookup  # re-exported below for back-compat
except ImportError:
    # Repo-side: eval/ is on sys.path, eval_lib is a sibling module.
    from eval_lib import _read_json_results
    from utils import load_lookup

# `load_lookup` remains importable from this module to avoid breaking
# callers like `from squelch_eval.cluster import load_lookup` (Bundle 2).
# Single source of truth lives in eval/utils.py.
__all__ = [
    "cluster_fps",
    "pull_labeled_events",
    "load_lookup",
    "FIELDS_DEFAULT",
    "diagnose_fp_pattern",
    "summarize_hypotheses",
    "format_hypothesis_summary",
]


FIELDS_DEFAULT = ("src_ip", "dest", "user")


def pull_labeled_events(service, search_name: str,
                        earliest: str = "-90d", latest: str = "now") -> list[dict]:
    """Return labeled notable events for one detection.

    SPL is host-filtered to `squelch-seed` to match the golden dataset
    (D3 / eval/golden_dataset.conf). Rows without a status_label are
    dropped — clustering only operates on labeled events.

    Bundle 3 Sessions 23-24: projection widened with `dest_ip` and
    `sourcetype_tag` so the same event list feeds both `cluster_fps`
    (which still operates on the 3-field default) and `diagnose_fp_pattern`
    (which needs `dest_ip` empties + `sourcetype_tag` correlation).
    """
    spl = (
        f'search index=notable sourcetype=squelch_notable host=squelch-seed '
        f'search_name="{search_name}" '
        f'| fields _cd, src_ip, dest, dest_ip, user, status_label, sourcetype_tag'
    )
    stream = service.jobs.oneshot(
        spl, earliest_time=earliest, latest_time=latest,
        output_mode="json", count=0,
    )
    rows = _read_json_results(stream)
    return [r for r in rows if r.get("status_label")]


_IDENTITY_NORM_MAP = {
    "true_positive": "true_positive",
    "false_positive": "false_positive",
}


def cluster_fps(events: list[dict],
                fields: tuple[str, ...] = FIELDS_DEFAULT,
                field_lookups: dict[str, Path] | None = None,
                normalization_csv: Path | None = None) -> dict:
    """Per-field FP clusters with recall-risk and lookup annotations.

    Args:
        events: output of pull_labeled_events (must carry status_label).
        fields: which event fields to cluster on.
        field_lookups: optional `{field: csv_path}` map. For each field
            present in the map, values found in the corresponding CSV
            get lookup_match=<file_stem> (e.g. "scanner_ips") and
            lookup_context=<column-1 value>. Bundle 3 Sessions 21-22
            replaced the single-lookup `lookup_csv_path`/`lookup_name`
            kwargs so Detection 2's `user` field can cross-reference
            service_accounts.csv while `src_ip` keeps scanner_ips.csv.
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
    loaded_lookups: dict[str, tuple[str, dict[str, str]]] = {}
    if field_lookups:
        for fld, path in field_lookups.items():
            loaded_lookups[fld] = (Path(path).stem, load_lookup(path))

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

        lookup_name_for_field, lookup_for_field = loaded_lookups.get(fld, (None, {}))

        cluster_rows = []
        # Only emit values that appear in at least one FP (the things
        # the LLM might propose filtering). A value with tp_count>0
        # but fp_count==0 is just a TP, not a cluster hypothesis.
        for value, fp_count in fp_counter.items():
            tp_count = tp_counter.get(value, 0)
            fp_pct = fp_count / total_fps if total_fps else 0.0
            tp_pct = tp_count / total_tps if total_tps else 0.0
            ctx = lookup_for_field.get(value)
            cluster_rows.append({
                "value": value,
                "fp_count": fp_count,
                "fp_pct": round(fp_pct, 4),
                "tp_count": tp_count,
                "tp_pct": round(tp_pct, 4),
                "lookup_match": lookup_name_for_field if ctx is not None else None,
                "lookup_context": ctx,
            })
        cluster_rows.sort(key=lambda r: r["fp_pct"], reverse=True)
        by_field[fld] = cluster_rows

    return {
        "total_fps": total_fps,
        "total_tps": total_tps,
        "by_field": by_field,
    }


# Bundle 3 Sessions 23-24 thresholds for the decline-to-tune diagnosis path.
# Locked from spec; tunable if data-quality patterns shift.
DIAGNOSE_EMPTY_THRESHOLD = 0.30       # field empty in >30% of FPs
DIAGNOSE_SOURCETYPE_THRESHOLD = 0.80  # >80% of empties share one sourcetype_tag


def diagnose_fp_pattern(events: list[dict],
                        normalization_csv: Path | None = None,
                        fields: tuple[str, ...] = ("src_ip", "dest", "dest_ip", "user"),
                        sourcetype_field: str = "sourcetype_tag") -> dict | None:
    """Field-coverage analysis for the decline-to-tune path.

    For each field, compute the empty/missing share among FPs. If any
    field is empty in >DIAGNOSE_EMPTY_THRESHOLD of FPs AND those empties
    correlate with one `sourcetype_field` value at
    >DIAGNOSE_SOURCETYPE_THRESHOLD, return a field_extraction_gap diagnosis.

    Returns:
        {
          "type": "field_extraction_gap",
          "field": str,
          "empty_pct": float,
          "sourcetype": str,
          "sourcetype_pct": float,
          "fp_count": int,
          "empty_count": int,
          "recommendation": str,
        }
        or None if no diagnosable pattern.
    """
    norm_map = load_lookup(normalization_csv) if normalization_csv else dict(_IDENTITY_NORM_MAP)
    if not norm_map:
        norm_map = dict(_IDENTITY_NORM_MAP)

    fp_events = [e for e in events
                 if norm_map.get(e.get("status_label")) == "false_positive"]
    fp_count = len(fp_events)
    if fp_count == 0:
        return None

    for fld in fields:
        empty_events = [e for e in fp_events if not e.get(fld)]
        empty_count = len(empty_events)
        empty_pct = empty_count / fp_count
        if empty_pct < DIAGNOSE_EMPTY_THRESHOLD:
            continue

        st_counter: Counter = Counter()
        for e in empty_events:
            st = e.get(sourcetype_field)
            if st:
                st_counter[st] += 1
        if not st_counter:
            continue
        top_st, top_st_count = st_counter.most_common(1)[0]
        st_pct = top_st_count / empty_count
        if st_pct < DIAGNOSE_SOURCETYPE_THRESHOLD:
            continue

        return {
            "type": "field_extraction_gap",
            "field": fld,
            "empty_pct": round(empty_pct, 4),
            "sourcetype": top_st,
            "sourcetype_pct": round(st_pct, 4),
            "fp_count": fp_count,
            "empty_count": empty_count,
            "recommendation": (
                f"Fix field extraction for '{fld}' in props.conf for "
                f"sourcetype_tag='{top_st}'. {empty_count}/{fp_count} FPs "
                f"({empty_pct:.0%}) have empty {fld}; {st_pct:.0%} of those "
                f"are tagged {top_st}."
            ),
        }

    return None


def _floor_pct() -> float:
    # Lazy import: revise.py imports llm.py at module load, which we don't
    # want to drag in just to read a constant. Match _pick_top_cluster's floor.
    try:
        from .revise import MIN_TOP_ENTRY_FP_PCT
    except ImportError:
        from revise import MIN_TOP_ENTRY_FP_PCT
    return MIN_TOP_ENTRY_FP_PCT


def summarize_hypotheses(clusters: dict, picked: dict | None) -> list[dict]:
    """Rank every field in `clusters["by_field"]` as a filter hypothesis.

    For each field, "explanatory power" is the cumulative fp_pct of the
    leading safe (tp_pct == 0) entries — the share of FPs a NOT-filter
    on those values would eliminate without dropping any TPs. If the top
    entry has tp_pct > 0, no filter is safe and explanatory power is 0.

    `picked` is the dict returned by revise._pick_top_cluster (or None
    when the declined path fires). The matching field gets picked=True.

    Returned list is sorted descending by cumulative_fp_pct so the demo
    output renders winner-first.
    """
    floor = _floor_pct()
    picked_field = picked["field"] if picked else None

    by_field = clusters.get("by_field", {})
    out: list[dict] = []
    for fld, rows in by_field.items():
        if not rows:
            out.append({
                "field": fld,
                "cumulative_fp_pct": 0.0,
                "top_value": None,
                "top_value_fp_pct": 0.0,
                "lookup_context": None,
                "picked": False,
                "reason_rejected": "no safe values",
            })
            continue

        top = rows[0]
        top_value = top["value"]
        top_value_fp_pct = top["fp_pct"]
        lookup_context = top.get("lookup_context")

        if top["tp_pct"] != 0.0:
            cumulative = 0.0
            reason = "tp_pct > 0 on top entry"
        else:
            cumulative = 0.0
            for row in rows:
                if row["tp_pct"] != 0.0:
                    break
                cumulative += row["fp_pct"]
                if cumulative >= 0.80:
                    break

            if fld == picked_field:
                reason = None
            elif cumulative < floor:
                reason = f"cumulative < {floor:.0%} floor"
            elif picked_field is None:
                reason = f"cumulative < {floor:.0%} floor"
            else:
                reason = f"runner-up to {picked_field}"

        out.append({
            "field": fld,
            "cumulative_fp_pct": round(cumulative, 4),
            "top_value": top_value,
            "top_value_fp_pct": top_value_fp_pct,
            "lookup_context": lookup_context,
            "picked": fld == picked_field,
            "reason_rejected": reason,
        })

    out.sort(key=lambda h: h["cumulative_fp_pct"], reverse=True)
    return out


def format_hypothesis_summary(hypotheses: list[dict],
                              diagnosis: dict | None = None) -> str:
    """Render hypotheses as the demo-script's `[HYPOTHESIS] ...` lines.

    Format mirrors docs/demo-script.md Beats 3-5:
      [HYPOTHESIS] src_ip cluster: 78% explanatory power ✓
      [HYPOTHESIS] user cluster: 11% ✗
      [HYPOTHESIS] sourcetype coverage: 45% — FIELD EXTRACTION GAP DETECTED ✓

    The trailing sourcetype line is appended only when `diagnosis` is a
    field_extraction_gap dict (declined path on Endpoint).
    """
    lines: list[str] = []
    any_picked = any(h["picked"] for h in hypotheses)
    for h in hypotheses:
        pct = f"{h['cumulative_fp_pct']:.0%}"
        if h["picked"]:
            lines.append(
                f"[HYPOTHESIS] {h['field']} cluster: {pct} explanatory power ✓"
            )
        else:
            lines.append(f"[HYPOTHESIS] {h['field']} cluster: {pct} ✗")

    if diagnosis and diagnosis.get("type") == "field_extraction_gap":
        st_pct = f"{diagnosis['sourcetype_pct']:.0%}"
        mark = "✓" if not any_picked else "✗"
        lines.append(
            f"[HYPOTHESIS] sourcetype coverage: {st_pct} — "
            f"FIELD EXTRACTION GAP DETECTED {mark}"
        )

    return "\n".join(lines)
