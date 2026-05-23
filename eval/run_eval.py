#!/usr/bin/env python3
"""Eval-harness CLI: run a detection's SPL against the golden dataset.

Usage:
    python eval/run_eval.py --all
        Eval all saved searches in the squelch app; write a row per
        detection to --out (default eval/results/eval_results.csv).

    python eval/run_eval.py --search-name WindowsAuth_AnomalousLogonSource
        Eval one named saved search.

    python eval/run_eval.py --spl 'search index=notable ... NOT src_ip IN (...)' \
        --label WindowsAuth_tuned_v1
        Eval an ad-hoc SPL string (the agent's proposed tuning).

Reads Splunk creds from .env at repo root.
"""

from __future__ import annotations

import argparse
import csv
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "eval"))

from eval_lib import EvalResult, evaluate_detection, load_golden_query  # noqa: E402


CSV_FIELDS = [
    "timestamp", "detection_name", "tp", "fp", "fn",
    "total_dataset_size", "precision", "recall", "fp_rate", "runtime_ms",
    "label_confidence",
]


def _load_env(env_path: Path) -> None:
    if not env_path.exists():
        return
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        v = v.strip().strip("'").strip('"')
        os.environ.setdefault(k, v)


def _connect():
    import splunklib.client as splunk_client
    return splunk_client.connect(
        host=os.environ.get("SPLUNK_HOST", "localhost"),
        port=int(os.environ.get("SPLUNK_PORT", "8089")),
        username=os.environ["SPLUNK_ADMIN_USER"],
        password=os.environ["SPLUNK_ADMIN_PASSWORD"],
        scheme="https", verify=False, autologin=True,
        app="squelch", owner=os.environ["SPLUNK_ADMIN_USER"],
    )


def _saved_search_spl(service, name: str) -> str:
    return service.saved_searches[name]["search"]


def _list_saved_searches(service) -> list[str]:
    return sorted(s.name for s in service.saved_searches)


def _append_csv(out_path: Path, result: EvalResult) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    new_file = not out_path.exists()
    with out_path.open("a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        if new_file:
            w.writeheader()
        w.writerow(result.as_csv_row())


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    g = parser.add_mutually_exclusive_group()
    g.add_argument("--search-name", help="Saved search name in the squelch app")
    g.add_argument("--spl", help="Ad-hoc SPL to evaluate")
    g.add_argument("--all", action="store_true",
                   help="Eval all saved searches in the squelch app")
    parser.add_argument("--label",
                        help="Detection label for --spl runs (required with --spl)")
    parser.add_argument(
        "--out", default=str(REPO_ROOT / "eval" / "results" / "eval_results.csv"),
        help="CSV output path",
    )
    parser.add_argument(
        "--golden-conf",
        default=str(REPO_ROOT / "eval" / "golden_dataset.conf"),
        help="Path to golden_dataset.conf",
    )
    parser.add_argument("--golden-stanza", default="default")
    parser.add_argument(
        "--normalization-csv",
        default=str(REPO_ROOT / "lookups" / "disposition_normalization.csv"),
        help="Path to disposition_normalization.csv (Bundle 2). "
             "Pass empty string to disable normalization (legacy behavior).",
    )
    args = parser.parse_args()

    if not (args.search_name or args.spl or args.all):
        parser.error("specify one of --search-name, --spl, or --all")
    if args.spl and not args.label:
        parser.error("--spl requires --label")

    _load_env(REPO_ROOT / ".env")
    if not os.environ.get("SPLUNK_ADMIN_PASSWORD"):
        print("error: SPLUNK_ADMIN_PASSWORD missing from .env", file=sys.stderr)
        return 1

    service = _connect()
    golden_query, earliest, latest = load_golden_query(
        Path(args.golden_conf), args.golden_stanza,
    )

    out_path = Path(args.out)

    targets: list[tuple[str, str]] = []
    if args.all:
        for name in _list_saved_searches(service):
            targets.append((name, _saved_search_spl(service, name)))
    elif args.search_name:
        targets.append((args.search_name, _saved_search_spl(service, args.search_name)))
    else:
        targets.append((args.label, args.spl))

    norm_csv = Path(args.normalization_csv) if args.normalization_csv else None
    print(f"golden: {golden_query} ({earliest} → {latest})")
    print(f"normalization: {norm_csv if norm_csv else '<disabled>'}")
    print(f"writing to: {out_path}")
    print(f"{'detection':40}  {'tp':>4}  {'fp':>4}  {'fn':>4}  {'prec':>6}  {'rec':>6}  {'fp_r':>5}  {'conf':>5}  {'ms':>5}")
    print("-" * 110)
    for name, spl in targets:
        result = evaluate_detection(
            service=service,
            detection_name=name,
            detection_spl=spl,
            golden_query=golden_query,
            earliest=earliest,
            latest=latest,
            normalization_csv=norm_csv,
        )
        _append_csv(out_path, result)
        print(f"{name:40}  {result.tp:>4}  {result.fp:>4}  {result.fn:>4}  "
              f"{result.precision:>6.3f}  {result.recall:>6.3f}  "
              f"{result.fp_rate:>5.2f}  {result.label_confidence:>5.2f}  {result.runtime_ms:>5}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
