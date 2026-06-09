#!/usr/bin/env python3
"""Standalone tune driver for the BOTSv3 external-dataset validation.

The live `| squelch mode="tune"` command hardcodes its golden query to the
synthetic seed (`GOLDEN_QUERY = "search index=notable sourcetype=squelch_notable
host=squelch-seed"` in squelch_command.py:45) and pulls cluster events via
`pull_labeled_events()`, which is likewise pinned to the notable index. Neither
can see `index=botsv3`.

This driver mirrors `squelch_command.py::_tune_one()` step-for-step — same
functions, same order, same recall gate — but sources its golden query from the
`[botsv3]` stanza of eval/golden_dataset.conf and pulls cluster events from the
golden query directly (which `cluster_fps()` accepts as a plain list). Nothing
in the eval harness is modified; only the data source changes.

Usage:
    python scripts/run_tune_botsv3.py [--no-pr]

Env (from .env at repo root): SPLUNK_*, GOOGLE_API_KEY.
GitHub token is read from `gh auth token` unless GITHUB_TOKEN is set.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "eval"))

DETECTION_NAME = "DNS_SuspiciousResolution_Botsv3"
GOLDEN_STANZA = "botsv3"
GITHUB_REPO = "markbrazinski/Squelch"
GOLDEN_CONF = REPO_ROOT / "eval" / "golden_dataset.conf"
# Normalization disabled: the [botsv3] golden query emits canonical
# true_positive/false_positive directly (no analyst-disposition mapping needed).
NORMALIZATION_CSV = None
# src_ip annotation lookup is optional (annotation-only). The benign BOTSv3
# resolvers are not in scanner_ips.csv, so clusters carry lookup_context=None;
# clustering and proposal still run. Left None deliberately.
FIELD_LOOKUPS = None

# Cluster on src_ip ONLY for this DNS detection. The default 3-field set
# ("src_ip","dest","user") is wrong for DNS: `dest` is the resolver IP that
# EVERY query funnels through (172.16.0.2), so its FP cluster also carries the
# coinhive TPs — a NOT dest filter is a recall trap and the gate (correctly)
# vetoes it. The querying host (src_ip) is the discriminative axis: the benign
# RDS/LDAP resolvers (172.16.0.178 etc.) that generate the noise are disjoint
# from the infected coinhive host (192.168.247.131). `user` is absent on
# stream:dns. This is per-detection clustering config, not a harness change.
CLUSTER_FIELDS = ("src_ip",)


def _load_env(env_path: Path) -> None:
    if not env_path.exists():
        return
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k, v.strip().strip("'").strip('"'))


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


def _github_token() -> str:
    tok = os.environ.get("GITHUB_TOKEN")
    if tok:
        return tok
    return subprocess.run(
        ["gh", "auth", "token"], capture_output=True, text=True, check=True
    ).stdout.strip()


def main() -> int:
    import urllib3
    urllib3.disable_warnings()

    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--no-pr", action="store_true",
                    help="Run the full pipeline but skip GitHub PR/Issue creation")
    args = ap.parse_args()

    _load_env(REPO_ROOT / ".env")
    api_key = os.environ.get("GOOGLE_API_KEY")
    if not api_key or api_key == "your_gemini_api_key":
        print("error: GOOGLE_API_KEY missing/placeholder in .env", file=sys.stderr)
        return 1

    from eval_lib import (
        evaluate_detection, gate_revision, perturb_and_eval,
        temporal_holdout_eval, load_golden_query, _read_json_results,
    )
    from cluster import (
        cluster_fps, diagnose_fp_pattern, summarize_hypotheses,
        format_hypothesis_summary,
    )
    from revise import propose_revision, _pick_top_cluster
    from attack_inject import run_adversarial_eval
    from github_integration import (
        create_pr_for_detection, create_issue, build_pr_body, build_issue_body,
    )

    service = _connect()
    golden_query, earliest, latest = load_golden_query(GOLDEN_CONF, GOLDEN_STANZA)
    original_spl = service.saved_searches[DETECTION_NAME]["search"]

    print(f"detection : {DETECTION_NAME}")
    print(f"golden    : {golden_query}")
    print(f"window    : {earliest} -> {latest}\n")

    start = time.time()

    # [1] baseline eval (golden_query is parameterized — works as-is)
    baseline = evaluate_detection(
        service=service, detection_name=DETECTION_NAME,
        detection_spl=original_spl, golden_query=golden_query,
        earliest=earliest, latest=latest, normalization_csv=NORMALIZATION_CSV,
    )
    print(f"[1] baseline: tp={baseline.tp} fp={baseline.fp} fn={baseline.fn} "
          f"prec={baseline.precision:.4f} rec={baseline.recall:.4f} "
          f"fp_rate={baseline.fp_rate:.4f}")

    # [2] cluster — pull labeled events from the botsv3 golden query directly,
    #     projecting the same fields pull_labeled_events would, then hand the
    #     list to cluster_fps (which never queries Splunk itself).
    cluster_spl = (
        f"{golden_query} | fields _cd, src_ip, dest, dest_ip, user, "
        f"status_label, sourcetype_tag"
    )
    stream = service.jobs.oneshot(
        cluster_spl, earliest_time=earliest, latest_time=latest,
        output_mode="json", count=0,
    )
    events = [r for r in _read_json_results(stream) if r.get("status_label")]
    clusters = cluster_fps(
        events, fields=CLUSTER_FIELDS,
        field_lookups=FIELD_LOOKUPS, normalization_csv=NORMALIZATION_CSV,
    )
    print(f"[2] cluster : {len(events)} labeled events "
          f"({clusters['total_fps']} FP / {clusters['total_tps']} TP)")
    for fld, rows in clusters["by_field"].items():
        if rows:
            t = rows[0]
            print(f"      {fld:7} top={t['value']!r:24} "
                  f"fp_pct={t['fp_pct']:.3f} tp_pct={t['tp_pct']:.3f} "
                  f"(fp_count={t['fp_count']})")

    picked = _pick_top_cluster(clusters)
    hypotheses = summarize_hypotheses(clusters, picked)
    print(f"      picked  : {picked['field']+'='+str(picked['values']) if picked else 'NONE (no field cleared safety floor)'}")

    # [3] propose (Gemini) — or decline-to-tune via diagnosis
    revision = propose_revision(original_spl, clusters, service, api_key=api_key)
    print(f"[3] propose : status={revision['status']} "
          f"attempts={revision.get('attempts')} "
          f"latency_ms={revision.get('llm_latency_ms')}")
    if revision["status"] == "ok":
        print(f"      revised : {revision['revised_spl']}")

    decision = None
    diagnosis = None

    if revision["status"] == "no_safe_cluster":
        diagnosis = diagnose_fp_pattern(events, normalization_csv=NORMALIZATION_CSV)
        if diagnosis:
            decision = "declined"
            print(f"[3b] DECLINE: {diagnosis['type']} on {diagnosis['field']} "
                  f"({diagnosis.get('empty_pct')} empty)")

    if decision is None and revision["status"] != "ok":
        print(f"ERROR: propose failed: {revision.get('error', revision['status'])}",
              file=sys.stderr)
        return 2

    final_spl = None
    revised_eval = None
    adversarial = None
    gate = None

    if decision is None:  # revision ok → adversarial → gate
        # [4] adversarial eval (earliest=0 so it queries botsv3)
        adversarial = run_adversarial_eval(
            service, detection_name=DETECTION_NAME,
            revised_spl=revision["revised_spl"], golden_query=golden_query,
            normalization_csv=NORMALIZATION_CSV, events=events,
            earliest=earliest, latest=latest,
        )
        print(f"[4] adversarial: status={adversarial['status']} "
              f"iterations={adversarial['iterations']} "
              f"initial={adversarial['initial_values']} "
              f"final={adversarial['final_values']}")

        if adversarial["status"] == "no_safe_revision":
            decision = "rejected"
        else:
            final_spl = adversarial["final_spl"]
            revised_eval = adversarial["final_eval"]
            # [5] recall gate
            gate = gate_revision(baseline, revised_eval)
            decision = gate["status"]
            if gate["status"] == "accepted":
                print(f"[5] gate    : ACCEPTED  recall {baseline.recall:.4f}->"
                      f"{revised_eval.recall:.4f} (delta {gate['recall_delta']:+}) "
                      f"precision delta {gate['precision_delta']:+} "
                      f"fp_rate delta {gate['fp_rate_delta']:+}  events_lost=0")
            else:
                print(f"[5] gate    : REJECTED ({gate['reason']}) "
                      f"baseline_recall={gate['baseline_recall']} "
                      f"revised_recall={gate['revised_recall']} "
                      f"events_lost={len(gate['events_lost'])}")
            if revised_eval is not None:
                print(f"      after   : tp={revised_eval.tp} fp={revised_eval.fp} "
                      f"prec={revised_eval.precision:.4f} rec={revised_eval.recall:.4f} "
                      f"fp_rate={revised_eval.fp_rate:.4f}")

    # [6/7] perturbation + holdout (informational), mirroring _tune_one branches
    if decision == "accepted":
        perturbation = perturb_and_eval(
            service, DETECTION_NAME, final_spl, golden_query,
            normalization_csv=NORMALIZATION_CSV, baseline=revised_eval,
            earliest=earliest, latest=latest,
        )
        holdout = temporal_holdout_eval(
            service, DETECTION_NAME, original_spl, final_spl, golden_query,
            normalization_csv=NORMALIZATION_CSV,
        )
    else:
        perturbation = perturb_and_eval(
            service, DETECTION_NAME, original_spl, golden_query,
            normalization_csv=NORMALIZATION_CSV, baseline=baseline,
            earliest=earliest, latest=latest,
        )
        holdout = temporal_holdout_eval(
            service, DETECTION_NAME, original_spl, None, golden_query,
            normalization_csv=NORMALIZATION_CSV,
        )
    print(f"[6] perturb : pass={perturbation['pass']} "
          f"prec_delta={perturbation['mean_precision_delta']} "
          f"recall_delta={perturbation['mean_recall_delta']}")
    print(f"[7] holdout : pass={holdout['pass']} "
          f"train_lift={holdout['training_precision_lift']} "
          f"holdout_lift={holdout['holdout_precision_lift']}")

    # [8] GitHub PR (accepted) or Issue (declined)
    gh_url = ""
    if args.no_pr:
        print("[8] github  : skipped (--no-pr)")
    elif decision == "accepted":
        pr_body = build_pr_body(
            DETECTION_NAME, baseline, revised_eval, picked,
            adversarial["injection_results"],
            adversarial["initial_values"], adversarial["final_values"],
            final_spl, original_spl,
            hypotheses=hypotheses, perturbation=perturbation, holdout=holdout,
        )
        field_tag = picked["field"] if picked else "filter"
        pr_title = (f"[squelch] {DETECTION_NAME}: NOT {field_tag} filter "
                    f"(precision {baseline.precision:.2f}->{revised_eval.precision:.2f})")
        pr = create_pr_for_detection(
            GITHUB_REPO, DETECTION_NAME, pr_title, pr_body,
            token=_github_token(), original_spl=original_spl, revised_spl=final_spl,
        )
        gh_url = pr["pr_url"]
        print(f"[8] PR      : {gh_url} (branch {pr.get('branch')})")
    elif decision == "declined" and diagnosis:
        issue_body = build_issue_body(
            DETECTION_NAME, diagnosis, baseline, original_spl,
            hypotheses=hypotheses, perturbation=perturbation, holdout=holdout,
        )
        issue = create_issue(
            GITHUB_REPO,
            f"[squelch] {DETECTION_NAME}: {diagnosis['type']} ({diagnosis['field']})",
            issue_body, token=_github_token(), labels=["squelch"],
        )
        gh_url = issue["issue_url"]
        print(f"[8] Issue   : {gh_url}")
    else:
        print(f"[8] github  : no PR/Issue (decision={decision})")

    total_ms = int((time.time() - start) * 1000)
    print(f"\nDECISION: {decision}   ({total_ms} ms)")
    if gh_url:
        print(f"GITHUB  : {gh_url}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
