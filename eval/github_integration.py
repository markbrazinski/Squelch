"""GitHub REST API client for Squelch's PR/Issue creation.

Bundle 3 Sessions 25-26:
- create_pr() opens a PR from squelch/proposals → main with a structured body.
- create_issue() opens an issue tagged with the squelch label.
- build_pr_body() / build_issue_body() compose the markdown.

The PR body-only approach (no real file commit) is the Bundle 3 shape;
Bundle 4 upgrades to per-detection branches with actual SPL file diffs.
All requests use stdlib urllib (no new dependencies; matches eval/llm.py).

Vendored to /Applications/Splunk/etc/apps/squelch/bin/lib/squelch_eval/.
"""

from __future__ import annotations

import json
import re
import time
import urllib.request
import urllib.error


PROPOSALS_BRANCH = "squelch/proposals"
DEFAULT_LABEL = "squelch"
_API = "https://api.github.com"


def _post(url: str, body: dict, token: str, timeout: int = 30) -> dict:
    req = urllib.request.Request(
        url,
        data=json.dumps(body).encode(),
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "Content-Type": "application/json",
            "User-Agent": "squelch-pipeline",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


def _get(url: str, token: str, timeout: int = 30) -> dict:
    req = urllib.request.Request(
        url,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "User-Agent": "squelch-pipeline",
        },
        method="GET",
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


def _slugify(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def _patch(url: str, body: dict, token: str, timeout: int = 30) -> dict:
    req = urllib.request.Request(
        url,
        data=json.dumps(body).encode(),
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "Content-Type": "application/json",
            "User-Agent": "squelch-pipeline",
        },
        method="PATCH",
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


def close_open_prs(repo: str, head: str, *, token: str) -> list[int]:
    """Close any open PRs whose head branch matches `head`.

    Returns the list of PR numbers closed. Called before opening a new PR
    on the same head branch so multi-detection runs don't 422.
    """
    prs = _get(
        f"{_API}/repos/{repo}/pulls?state=open&head={repo.split('/')[0]}:{head}&per_page=100",
        token=token,
    )
    closed = []
    for pr in prs:
        _patch(
            f"{_API}/repos/{repo}/pulls/{pr['number']}",
            {"state": "closed"},
            token=token,
        )
        closed.append(pr["number"])
    return closed


def create_pr(repo: str, title: str, body: str, *, token: str,
              head: str = PROPOSALS_BRANCH, base: str = "main",
              label: str | None = DEFAULT_LABEL) -> dict:
    """Open a PR head→base on `repo`. Returns {pr_url, pr_number}.

    Label is applied via a second POST to /issues/{n}/labels — GitHub
    treats PRs as issues for labeling. If `label` is None, skip the
    second call.
    """
    pr = _post(
        f"{_API}/repos/{repo}/pulls",
        {"title": title, "body": body, "head": head, "base": base},
        token=token,
    )
    pr_number = pr["number"]
    if label:
        _post(
            f"{_API}/repos/{repo}/issues/{pr_number}/labels",
            {"labels": [label]},
            token=token,
        )
    return {"pr_url": pr["html_url"], "pr_number": pr_number}


def create_ref(repo: str, branch: str, base_sha: str, *, token: str) -> dict:
    """Create a new branch ref pointing at base_sha. Lets HTTPError propagate
    so callers can catch 422 (ref already exists)."""
    return _post(
        f"{_API}/repos/{repo}/git/refs",
        {"ref": f"refs/heads/{branch}", "sha": base_sha},
        token=token,
    )


def create_pr_for_detection(
    repo: str, detection_name: str, title: str, body: str, *,
    token: str, base: str = "main", label: str | None = DEFAULT_LABEL,
) -> dict:
    """Open a PR on a per-detection branch.

    Sequence: GET base HEAD → create_ref(squelch/tune/<slug>-<epoch>) →
    create_pr from that branch. On 422 (collision in the same epoch
    second), retry once with epoch+1 before propagating.

    Returns the create_pr result extended with the chosen `branch`.
    """
    base_ref = _get(f"{_API}/repos/{repo}/git/ref/heads/{base}", token=token)
    base_sha = base_ref["object"]["sha"]

    slug = _slugify(detection_name)
    ts = int(time.time())
    branch = f"squelch/tune/{slug}-{ts}"
    try:
        create_ref(repo, branch, base_sha, token=token)
    except urllib.error.HTTPError as exc:
        if exc.code != 422:
            raise
        ts += 1
        branch = f"squelch/tune/{slug}-{ts}"
        create_ref(repo, branch, base_sha, token=token)

    try:
        pr = create_pr(repo, title, body, token=token,
                       head=branch, base=base, label=label)
    except urllib.error.HTTPError as exc:
        if exc.code != 422:
            raise
        # Branch has no commits ahead of base — fall back to proposals branch.
        # Close any open PR on proposals first so multi-detection runs don't 422.
        close_open_prs(repo, PROPOSALS_BRANCH, token=token)
        pr = create_pr(repo, title, body, token=token,
                       head=PROPOSALS_BRANCH, base=base, label=label)
        branch = PROPOSALS_BRANCH
    return {**pr, "branch": branch}


def create_issue(repo: str, title: str, body: str, *, token: str,
                 labels: list[str] | None = None) -> dict:
    """Open an issue on `repo`. Returns {issue_url, issue_number}."""
    payload = {"title": title, "body": body}
    if labels:
        payload["labels"] = labels
    issue = _post(f"{_API}/repos/{repo}/issues", payload, token=token)
    return {"issue_url": issue["html_url"], "issue_number": issue["number"]}


def _label_sensitivity_section(perturbation: dict,
                               *, baseline_only: bool = False) -> list[str]:
    """Render the Bundle 4 Label Sensitivity section. Caller decides
    placement; this just returns the line list."""
    badge = "**PASS**" if perturbation["pass"] else "**WARN**"
    max_r = perturbation["max_recall_delta"]
    stability = "stable" if perturbation["pass"] else "unstable"
    header_qual = "baseline, " if baseline_only else ""
    subject = "baseline detection's recall" if baseline_only else "recall"
    lines = [
        f"## Label Sensitivity ({header_qual}{int(perturbation['flip_pct'] * 100)}% flip, "
        f"{perturbation['n_trials']} trials)",
        "",
        f"{badge} — {subject} is {stability} under label noise "
        f"(max Δ recall = {max_r:+.3f}).",
        "",
        "| Metric | Mean Δ | Max Δ |",
        "|---|---|---|",
        f"| Precision | {perturbation['mean_precision_delta']:+.3f} "
        f"| {perturbation['max_precision_delta']:+.3f} |",
        f"| Recall | {perturbation['mean_recall_delta']:+.3f} "
        f"| {perturbation['max_recall_delta']:+.3f} |",
        "",
    ]
    return lines


def build_pr_body(detection_name: str, eval_before, eval_after,
                  picked_cluster: dict | None,
                  injection_results: list[dict],
                  initial_values: list[str], final_values: list[str],
                  revised_spl: str, original_spl: str,
                  *, hypotheses: list[dict] | None = None,
                  perturbation: dict | None = None) -> str:
    """Markdown body for an accepted-tune PR.

    eval_before / eval_after are EvalResult dataclasses (eval/eval_lib.py).
    picked_cluster is the dict returned by _pick_top_cluster (or None if
    unavailable — defensive against re-call edge cases).
    hypotheses is the summarize_hypotheses() output (Bundle 4); when
    provided, Hypothesis Analysis + Decision Rationale sections render.
    perturbation is the perturb_and_eval() output (Bundle 4); when
    provided, a Label Sensitivity section renders after Decision Rationale.
    """
    lines = [
        f"## Detection: `{detection_name}`",
        "",
        f"FP rate **{eval_before.fp_rate:.1%} → {eval_after.fp_rate:.1%}**, "
        f"precision **{eval_before.precision:.1%} → {eval_after.precision:.1%}**, "
        f"recall **{eval_before.recall:.1%} → {eval_after.recall:.1%}** "
        f"(label confidence {eval_before.label_confidence:.2f}).",
        "",
        "## Proposed revision",
        "",
        "```diff",
        f"- {original_spl}",
        f"+ {revised_spl}",
        "```",
        "",
        "## Eval before / after",
        "",
        "| | precision | recall | fp_rate | tp | fp | fn |",
        "|---|---|---|---|---|---|---|",
        f"| baseline | {eval_before.precision:.4f} | {eval_before.recall:.4f} "
        f"| {eval_before.fp_rate:.4f} | {eval_before.tp} | {eval_before.fp} | {eval_before.fn} |",
        f"| revised  | {eval_after.precision:.4f}  | {eval_after.recall:.4f}  "
        f"| {eval_after.fp_rate:.4f}  | {eval_after.tp}  | {eval_after.fp}  | {eval_after.fn}  |",
        "",
        "## Attack injection",
        "",
    ]
    if not injection_results:
        lines.append(
            "Single-value filter — adversarial injection bypassed "
            "(recall gate is the safety net)."
        )
    else:
        lines.append(f"Tested {len(injection_results)} value(s):")
        lines.append("")
        for r in injection_results:
            mark = "❌ caught (narrowed out)" if r["was_caught"] else "✅ survived"
            lines.append(f"- `{r['value']}` — {mark}")
    lines.append("")
    lines.append(
        f"Initial values proposed by LLM: "
        f"{', '.join(f'`{v}`' for v in initial_values) or '(none)'}"
    )
    lines.append(
        f"Final values after narrowing: "
        f"{', '.join(f'`{v}`' for v in final_values) or '(none)'}"
    )
    lines.append("")

    # Bundle 4 Sessions 31-32: hypothesis ranking + decision rationale.
    # Renders only when summarize_hypotheses() output was passed in.
    if hypotheses:
        rejected_count = sum(1 for h in hypotheses if not h["picked"])
        lines.append("## Hypothesis Analysis")
        lines.append("")
        lines.append(
            f"{len(hypotheses)} hypothesis(es) evaluated, "
            f"{rejected_count} rejected."
        )
        lines.append("")
        lines.append("| Field | Explanatory Power | Status | Reason |")
        lines.append("|---|---|---|---|")
        for h in hypotheses:
            status = "✓ picked" if h["picked"] else "✗"
            reason = h["reason_rejected"] or "—"
            lines.append(
                f"| {h['field']} | {h['cumulative_fp_pct']:.0%} "
                f"| {status} | {reason} |"
            )
        lines.append("")

        lines.append("## Decision Rationale")
        lines.append("")
        narrowed = len(initial_values) > len(final_values)
        reason_phrase = (
            "attack injection caught aggressive candidate"
            if narrowed
            else "single candidate held under attack injection"
        )
        lines.append(
            f"{len(hypotheses)} hypotheses evaluated, "
            f"{len(initial_values)} revision candidates considered, "
            f"conservative selected ({reason_phrase})."
        )
        picked_h = next((h for h in hypotheses if h["picked"]), None)
        runner_up = next(
            (h for h in hypotheses
             if not h["picked"] and h["cumulative_fp_pct"] > 0),
            None,
        )
        if picked_h and runner_up:
            lines.append("")
            lines.append(
                f"{picked_h['field']} cluster selected over "
                f"{runner_up['field']} cluster "
                f"({picked_h['cumulative_fp_pct']:.0%} vs "
                f"{runner_up['cumulative_fp_pct']:.0%} explanatory power)."
            )
        lines.append("")

    # Bundle 4 Sessions 33-34: label-sensitivity badge from perturb_and_eval.
    if perturbation is not None:
        lines.extend(_label_sensitivity_section(perturbation))

    lines.append("## Cluster analysis")
    lines.append("")
    if picked_cluster:
        ctx = ""
        if picked_cluster.get("lookup_match"):
            ctx = (f" — lookup `{picked_cluster['lookup_match']}`: "
                   f"{picked_cluster['lookup_context']}")
        lines.append(
            f"Top hypothesis: field=`{picked_cluster['field']}`, "
            f"cumulative fp explanatory power = "
            f"**{picked_cluster['total_fp_pct']:.1%}**{ctx}."
        )
    else:
        lines.append("(cluster data unavailable)")
    lines.append("")
    lines.append("---")
    lines.append("*Generated by `| squelch mode=\"tune\"`.*")
    return "\n".join(lines)


def build_issue_body(detection_name: str, diagnosis: dict,
                     eval_before, original_spl: str,
                     *, hypotheses: list[dict] | None = None,
                     perturbation: dict | None = None) -> str:
    """Markdown body for a decline-to-tune Issue.

    diagnosis is the dict returned by diagnose_fp_pattern (eval/cluster.py).
    eval_before is the EvalResult from the baseline run.
    hypotheses is the summarize_hypotheses() output (Bundle 4); when
    provided, the "Why no tune?" breakdown is rendered before Original SPL.
    perturbation is the perturb_and_eval() output (Bundle 4); when
    provided, a Label Sensitivity section renders before Original SPL.
    """
    lines = [
        f"## Detection: `{detection_name}`",
        "",
        f"Current FP rate **{eval_before.fp_rate:.1%}** "
        f"(precision {eval_before.precision:.1%}, recall {eval_before.recall:.1%}, "
        f"label confidence {eval_before.label_confidence:.2f}).",
        "",
        f"The tuning pipeline declined to propose a filter. "
        f"Root cause: **{diagnosis['type']}**.",
        "",
        "## Evidence",
        "",
        f"- Field: `{diagnosis['field']}`",
        f"- Empty in **{diagnosis['empty_pct']:.1%}** of FPs "
        f"({diagnosis['empty_count']}/{diagnosis['fp_count']})",
        f"- Empties correlate with `sourcetype_tag={diagnosis['sourcetype']}` at "
        f"**{diagnosis['sourcetype_pct']:.1%}**",
        "",
        "## Recommendation",
        "",
        f"> {diagnosis['recommendation']}",
        "",
        "Fix this in `props.conf` — not in the detection SPL. Once "
        f"`{diagnosis['field']}` extracts correctly for "
        f"`{diagnosis['sourcetype']}` events, re-run the pipeline.",
        "",
    ]

    # Bundle 4 Sessions 31-32: show every field's rejection reason so the
    # reader understands why no filter was proposed before the SPL.
    if hypotheses:
        # Lazy import to avoid a cycle with cluster.py (which imports revise
        # which imports llm — none of which we need just for the floor).
        try:
            from .cluster import _floor_pct
        except ImportError:
            from cluster import _floor_pct
        floor = _floor_pct()

        lines.append("## Why no tune?")
        lines.append("")
        lines.append(
            f"No field cleared the {floor:.0%} explanatory-power floor."
        )
        lines.append("")
        lines.append("| Field | Cumulative Power | Why rejected |")
        lines.append("|---|---|---|")
        for h in hypotheses:
            reason = h["reason_rejected"] or "—"
            lines.append(
                f"| {h['field']} | {h['cumulative_fp_pct']:.0%} | {reason} |"
            )
        lines.append("")
        lines.append("→ Diagnosis path activated: see Recommendation above.")
        lines.append("")

    # Bundle 4 Sessions 33-34: baseline label-sensitivity badge.
    if perturbation is not None:
        lines.extend(_label_sensitivity_section(perturbation, baseline_only=True))

    lines.extend([
        "## Original SPL",
        "",
        "```spl",
        original_spl,
        "```",
        "",
        "---",
        "*Generated by `| squelch mode=\"tune\"`.*",
    ])
    return "\n".join(lines)
