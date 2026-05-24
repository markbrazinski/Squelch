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


def create_issue(repo: str, title: str, body: str, *, token: str,
                 labels: list[str] | None = None) -> dict:
    """Open an issue on `repo`. Returns {issue_url, issue_number}."""
    payload = {"title": title, "body": body}
    if labels:
        payload["labels"] = labels
    issue = _post(f"{_API}/repos/{repo}/issues", payload, token=token)
    return {"issue_url": issue["html_url"], "issue_number": issue["number"]}


def build_pr_body(detection_name: str, eval_before, eval_after,
                  picked_cluster: dict | None,
                  injection_results: list[dict],
                  initial_values: list[str], final_values: list[str],
                  revised_spl: str, original_spl: str) -> str:
    """Markdown body for an accepted-tune PR.

    eval_before / eval_after are EvalResult dataclasses (eval/eval_lib.py).
    picked_cluster is the dict returned by _pick_top_cluster (or None if
    unavailable — defensive against re-call edge cases).
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
                     eval_before, original_spl: str) -> str:
    """Markdown body for a decline-to-tune Issue.

    diagnosis is the dict returned by diagnose_fp_pattern (eval/cluster.py).
    eval_before is the EvalResult from the baseline run.
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
        "## Original SPL",
        "",
        "```spl",
        original_spl,
        "```",
        "",
        "---",
        "*Generated by `| squelch mode=\"tune\"`.*",
    ]
    return "\n".join(lines)
