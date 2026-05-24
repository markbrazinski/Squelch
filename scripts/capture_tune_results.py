#!/usr/bin/env python3
"""Capture the latest detection_lineage KV row per detection into a CSV.

Bundle 3 Sessions 27-28. Re-runnable; overwrites the target file. Reads
the most recent (max decision_timestamp) row for every detection that
has ever been tuned and flattens the eval_before/eval_after JSON into
per-metric columns.

Usage:
    ./scripts/capture_tune_results.py [--out eval/results/tune_results_bundle_3.csv]
"""

import argparse
import csv
import json
import os
import sys
from pathlib import Path

import splunklib.client as splunk_client


# Mirror the operational subset of Bundle 2's tune_results columns + the
# Bundle 3 GitHub-result additions (pr_url, pr_number, issue_url,
# issue_number, github_error, diagnosis). Bundle 2's full schema also
# carried initial_filter_values / final_filter_values / attack_injection_*
# / llm_* / total_runtime_ms; those live in eval_after JSON, retrievable
# but not surfaced here to keep the bundle-over-bundle comparison clean.
COLUMNS = [
    "detection_name",
    "decision",
    "decision_reason",
    "fp_rate_before",
    "precision_before",
    "recall_before",
    "fp_rate_after",
    "precision_after",
    "recall_after",
    "label_confidence",
    "pr_url",
    "pr_number",
    "issue_url",
    "issue_number",
    "github_error",
    "diagnosis",
    "decision_timestamp",
]


def _load_env(env_path: Path) -> None:
    if not env_path.exists():
        return
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k, v.strip().strip("'").strip('"'))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", default="eval/results/tune_results_bundle_3.csv")
    args = ap.parse_args()

    repo_root = Path(__file__).resolve().parent.parent
    _load_env(repo_root / ".env")
    user = os.environ.get("SPLUNK_ADMIN_USER")
    pw = os.environ.get("SPLUNK_ADMIN_PASSWORD")
    if not (user and pw):
        print("error: SPLUNK_ADMIN_USER / SPLUNK_ADMIN_PASSWORD missing from .env",
              file=sys.stderr)
        return 1

    svc = splunk_client.connect(
        host=os.environ.get("SPLUNK_HOST", "localhost"),
        port=int(os.environ.get("SPLUNK_PORT", "8089")),
        username=user, password=pw,
        scheme="https", verify=False, autologin=True,
        app="squelch",
    )

    kv = svc.kvstore["detection_lineage"]
    all_rows = kv.data.query()

    # Pick latest per detection (max decision_timestamp wins)
    latest: dict[str, dict] = {}
    for row in all_rows:
        name = row.get("search_name")
        if not name:
            continue
        ts = int(row.get("decision_timestamp", 0) or 0)
        if name not in latest or ts > int(latest[name].get("decision_timestamp", 0) or 0):
            latest[name] = row

    out_rows = []
    for name in sorted(latest.keys()):
        row = latest[name]
        eb = json.loads(row.get("eval_before", "") or "{}")
        ea_raw = row.get("eval_after", "") or ""
        ea_metrics = {}
        if ea_raw:
            try:
                ea = json.loads(ea_raw)
                ea_metrics = ea.get("metrics", {}) if isinstance(ea, dict) else {}
            except json.JSONDecodeError:
                ea_metrics = {}
        out_rows.append({
            "detection_name": name,
            "decision": row.get("decision", ""),
            "decision_reason": row.get("decision_reason", ""),
            "fp_rate_before": eb.get("fp_rate", ""),
            "precision_before": eb.get("precision", ""),
            "recall_before": eb.get("recall", ""),
            "fp_rate_after": ea_metrics.get("fp_rate", ""),
            "precision_after": ea_metrics.get("precision", ""),
            "recall_after": ea_metrics.get("recall", ""),
            "label_confidence": eb.get("label_confidence", ""),
            "pr_url": row.get("pr_url", ""),
            "pr_number": row.get("pr_number", ""),
            "issue_url": row.get("issue_url", ""),
            "issue_number": row.get("issue_number", ""),
            "github_error": row.get("github_error", ""),
            "diagnosis": row.get("diagnosis", ""),
            "decision_timestamp": row.get("decision_timestamp", ""),
        })

    out_path = repo_root / args.out
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS)
        w.writeheader()
        w.writerows(out_rows)
    print(f"OK: wrote {len(out_rows)} rows to {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
