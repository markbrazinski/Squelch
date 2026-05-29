"""SPL revision via LLM: prompt builder + structural validator + syntax retry.

Given a detection's original SPL and the cluster output from cluster.py,
prompt Gemini to propose a revised SPL with one appended NOT clause
filtering the top FP cluster. Validate the LLM's output structurally
(must extend the original, must contain NOT). Validate as Splunk syntax
(| head 0 runs the parser without returning rows). One retry on syntax
error with the parse error appended to the prompt.

Consumed by Session 7's `_tune` method in squelch_command.py.

Vendored to /Applications/Splunk/etc/apps/squelch/bin/lib/squelch_eval/revise.py.
"""

from __future__ import annotations

import re

try:
    from .llm import call_gemini
except ImportError:
    try:
        from llm import call_gemini
    except ImportError:
        call_gemini = None  # LLM layer not available in standalone install


PROMPT_TEMPLATE = """You are tuning a Splunk correlation search to reduce false positives without dropping true positives.

ORIGINAL SPL:
{original_spl}

TOP FP CLUSTER (filtering these values drops 0% of true positives):
field = {field}
values = {values_quoted}
combined fp explanatory power = {fp_pct_pretty}
{lookup_line}

Output ONLY the revised SPL. No markdown. No code fences. No explanation.

Format requirements:
1. Start with the original SPL VERBATIM.
2. Append exactly one clause: NOT {field} IN ({values_quoted})
3. Do not modify any other logic in the original SPL.
"""


# Bundle 3 Sessions 23-24: minimum fp_pct floor on the FIELD's top entry.
# Without this, any random value with fp_count=1, tp_count=0 qualifies as
# "safe to filter" — pipeline would propose 10 random IPs explaining 15%
# of FPs (useless but technically safe). The floor pushes those cases
# into the no_safe_cluster path so diagnose_fp_pattern can run.
#
# Empirically tuned to 0.20: DNS's top scanner clears 0.2727, Identity's
# svc_backup clears 0.65, Endpoint's top entry maxes out at 0.027 (well
# below 0.20). The 0.30 spec value bit DNS — top scanner is just under it.
MIN_TOP_ENTRY_FP_PCT = 0.20


def _pick_top_cluster(clusters: dict) -> dict | None:
    """Pick the (field, top-N-values) hypothesis the LLM should propose.

    Strategy: pick the field whose top entry has the highest fp_pct AND
    tp_pct == 0 (safe to filter) AND fp_pct >= MIN_TOP_ENTRY_FP_PCT (real
    pattern, not random noise). Then take all leading entries in that
    field where tp_pct == 0, up to 80% cumulative fp_pct, capped at 10.

    Returns {field, values, total_fp_pct, lookup_match, lookup_context}
    or None if no field has a safe top entry above the floor.
    """
    by_field = clusters.get("by_field", {})
    best_field = None
    best_fp_pct = -1.0
    for fld, rows in by_field.items():
        if not rows:
            continue
        top = rows[0]
        if top["tp_pct"] != 0.0:
            continue
        if top["fp_pct"] < MIN_TOP_ENTRY_FP_PCT:
            continue
        if top["fp_pct"] > best_fp_pct:
            best_fp_pct = top["fp_pct"]
            best_field = fld
    if best_field is None:
        return None

    chosen: list[dict] = []
    cumulative = 0.0
    for row in by_field[best_field]:
        if row["tp_pct"] != 0.0:
            break
        if len(chosen) >= 10:
            break
        chosen.append(row)
        cumulative += row["fp_pct"]
        if cumulative >= 0.80:
            break

    return {
        "field": best_field,
        "values": [r["value"] for r in chosen],
        "total_fp_pct": cumulative,
        # Annotate with the lookup of the top row (all chosen rows share
        # the same lookup_match in the scanner-IPs case).
        "lookup_match": chosen[0].get("lookup_match"),
        "lookup_context": chosen[0].get("lookup_context"),
    }


def _build_prompt(original_spl: str, top: dict) -> str:
    values_quoted = ",".join(f'"{v}"' for v in top["values"])
    fp_pct_pretty = f"{top['total_fp_pct'] * 100:.1f}%"
    if top.get("lookup_match"):
        lookup_line = f"lookup annotation = {top['lookup_match']}: {top['lookup_context']}"
    else:
        lookup_line = ""
    return PROMPT_TEMPLATE.format(
        original_spl=original_spl,
        field=top["field"],
        values_quoted=values_quoted,
        fp_pct_pretty=fp_pct_pretty,
        lookup_line=lookup_line,
    )


_FENCE_RE = re.compile(r"^\s*```(?:spl|splunk|sql)?\s*\n?(.*?)\n?\s*```\s*$", re.DOTALL)
_LABEL_RE = re.compile(r"^\s*(?:revised\s*spl|spl|search)\s*:\s*", re.IGNORECASE)


def _clean_llm_output(text: str) -> str:
    """Strip code fences and leading labels the LLM may add despite instructions."""
    text = text.strip()
    m = _FENCE_RE.match(text)
    if m:
        text = m.group(1).strip()
    text = _LABEL_RE.sub("", text)
    return text.strip()


def _structurally_valid(revised: str, original: str) -> tuple[bool, str]:
    orig_stripped = original.strip()
    if not revised.lower().startswith(orig_stripped.lower()):
        return False, "rewrite_detected"
    appended = revised[len(orig_stripped):]
    if " NOT " not in appended.upper():
        return False, "missing_not_clause"
    return True, ""


def _syntax_check(service, spl: str) -> tuple[bool, str]:
    """Run `<spl> | head 0` to exercise the Splunk parser without rows.

    Returns (ok, error_message). On parse failure, error_message is the
    Splunk-reported error suitable for feeding back into the LLM.
    """
    try:
        service.jobs.oneshot(
            f"{spl} | head 0",
            earliest_time="-1s", latest_time="now",
            output_mode="json", count=0,
        )
        return True, ""
    except Exception as exc:
        # splunklib.binding.HTTPError carries body bytes; str(exc) is
        # usually the cleanest one-line summary.
        return False, str(exc)


def propose_revision(original_spl: str, clusters: dict, service,
                     api_key: str) -> dict:
    """End-to-end: pick cluster → prompt → parse → syntax-validate → retry.

    Returns:
        {status: "ok", revised_spl, llm_latency_ms, attempts} on success
        {status: "no_safe_cluster", error: ...} if no field has tp_pct==0 top
        {status: "rewrite_detected" | "missing_not_clause" | "syntax_error",
         error: ..., revised_spl: <last attempt>, llm_latency_ms, attempts}
        on failure
    """
    top = _pick_top_cluster(clusters)
    if top is None:
        return {
            "status": "no_safe_cluster",
            "error": "No field has a top cluster with tp_pct == 0; "
                     "every safe filter would drop recall.",
            "attempts": 0,
            "llm_latency_ms": 0,
        }

    prompt = _build_prompt(original_spl, top)
    total_latency = 0
    last_error = ""
    last_revised = ""

    for attempt in (1, 2):
        text, latency_ms = call_gemini(prompt, api_key)
        total_latency += latency_ms
        revised = _clean_llm_output(text)
        last_revised = revised

        ok, reason = _structurally_valid(revised, original_spl)
        if not ok:
            # Structural failure isn't recoverable by appending Splunk
            # error; this is the LLM ignoring the prompt. Return now.
            return {
                "status": reason,
                "error": f"LLM output failed structural check ({reason}).",
                "revised_spl": revised,
                "attempts": attempt,
                "llm_latency_ms": total_latency,
            }

        ok, err = _syntax_check(service, revised)
        if ok:
            return {
                "status": "ok",
                "revised_spl": revised,
                "attempts": attempt,
                "llm_latency_ms": total_latency,
            }

        last_error = err
        # Build retry prompt for the second attempt.
        prompt = (
            _build_prompt(original_spl, top)
            + f"\nThe previous attempt failed Splunk syntax validation:\n{err}\nTry again."
        )

    return {
        "status": "syntax_error",
        "error": last_error,
        "revised_spl": last_revised,
        "attempts": 2,
        "llm_latency_ms": total_latency,
    }
