"""Adversarial eval: inject one synthetic TP matching the proposed NOT
filter, see if the filter drops it, narrow if so.

The contract with `propose_revision()` ([revise.py](revise.py)) is that
the LLM appends exactly one trailing `NOT <field> IN ("v1","v2",...)`
clause to the original detection SPL. Attack injection exploits that:

  1. Parse the NOT clause to recover (field, values).
  2. Pick one value at random (deterministic per detection + proposal).
  3. Synthesize a TP-labeled event with that field value, copying
     other fields from a real FP in the cluster so the event looks
     realistic.
  4. Re-run `evaluate_detection(..., injected_events=[ev])`. The eval
     harness unions the synthetic TP into golden_tp_ids and decides
     `fired` membership via the same parser — if the NOT clause matches
     the value, the event does NOT fire and recall drops.
  5. If caught: remove that value, retry. If not caught: accept.
  6. Up to 3 iterations; if all values caught, return no_safe_revision.

Why one TP per iteration (not one per value): NOT excludes every listed
value, so "inject one per value" would catch them all and narrow to the
empty filter every time. Picking one random value at a time models a
real attacker pivoting through one of the previously-quiet IPs.

Vendored to /Applications/Splunk/etc/apps/squelch/bin/lib/squelch_eval/.
"""

from __future__ import annotations

import hashlib
import random
import re
from pathlib import Path

try:
    from .eval_lib import evaluate_detection
except ImportError:
    from eval_lib import evaluate_detection


_NOT_FILTER_RE = re.compile(
    r'NOT\s+(\w+)\s+IN\s*\(\s*'
    r'("[^"]+"(?:\s*,\s*"[^"]+")*)'
    r'\s*\)\s*$',
    re.IGNORECASE,
)


def parse_not_filter(spl: str) -> tuple[str | None, list[str]]:
    """Extract (field, values) from a trailing `NOT field IN ("a","b")`
    clause. Returns (None, []) if no such clause is found."""
    m = _NOT_FILTER_RE.search(spl.rstrip())
    if not m:
        return None, []
    field = m.group(1)
    values_str = m.group(2)
    values = [v.strip().strip('"') for v in values_str.split(",")]
    return field, [v for v in values if v]


def narrow_filter(spl: str, drop_values: list[str]) -> str | None:
    """Remove `drop_values` from the NOT clause. Returns None if the
    narrowing would empty the clause (caller should treat as
    no_safe_revision)."""
    field, values = parse_not_filter(spl)
    if field is None:
        return spl
    survivors = [v for v in values if v not in drop_values]
    if not survivors:
        return None
    quoted = ",".join(f'"{v}"' for v in survivors)
    new_clause = f'NOT {field} IN ({quoted})'
    return _NOT_FILTER_RE.sub(new_clause, spl.rstrip())


def _pick_template_event(events: list[dict], field: str,
                         values: list[str]) -> dict:
    """Pick a realistic template: prefer an FP event whose field value
    is in the filter, so dest/user/etc. look right for an attack from
    that IP. Falls back to any FP, then to events[0]."""
    for ev in events:
        if ev.get(field) in values and ev.get("status_label") in (
            "false_positive", "resolved", "closed", "fp", "FP - scanner"
        ):
            return ev
    for ev in events:
        if ev.get("status_label") in (
            "false_positive", "resolved", "closed", "fp", "FP - scanner"
        ):
            return ev
    return events[0] if events else {}


def inject_attack(field: str, target_value: str, template_event: dict,
                  *, rng: random.Random) -> dict:
    """Build one synthetic TP dict that an attacker pivoting through
    `target_value` would produce. Other fields copied from template so
    the event looks plausible (right dest network, right user pattern)."""
    ev = dict(template_event)
    ev[field] = target_value
    ev["status_label"] = "true_positive"
    ev["_cd"] = f"injected_{field}_{target_value}_{rng.randint(0, 1 << 32)}"
    return ev


def _seeded_rng(detection_name: str, revised_spl: str) -> random.Random:
    """Deterministic per (detection, proposal). Uses SHA-256 instead of
    hash() because Python's hash is process-randomized (PYTHONHASHSEED)
    and would silently shift the chosen attack target across restarts."""
    seed_bytes = hashlib.sha256(
        f"{detection_name}:{revised_spl}".encode("utf-8")
    ).digest()[:8]
    return random.Random(int.from_bytes(seed_bytes, "big"))


def run_adversarial_eval(
    service,
    *,
    detection_name: str,
    revised_spl: str,
    golden_query: str,
    normalization_csv: Path | None,
    events: list[dict],
    rng: random.Random | None = None,
    max_iterations: int = 3,
    earliest: str = "-90d",
    latest: str = "now",
) -> dict:
    """Outer loop: attack random filter values until one survives or we
    run out of values.

    Returns a dict with:
      status: "ok" | "no_safe_revision"
      final_spl: the narrowed SPL (or None if no safe filter)
      final_eval: the EvalResult from the final (passing) iteration,
                  or None if no_safe_revision
      initial_values: values from the LLM's original proposal
      final_values: values remaining after narrowing
      injection_results: [{value, was_caught}, ...] in order tested
      iterations: count of injection attempts run
    """
    if rng is None:
        rng = _seeded_rng(detection_name, revised_spl)

    _, initial_values = parse_not_filter(revised_spl)

    spl = revised_spl
    caught_so_far: list[dict] = []
    last_result = None

    for iteration in range(max_iterations):
        field, values = parse_not_filter(spl)
        if not values:
            # No NOT filter to attack — nothing to narrow.
            return {
                "status": "ok",
                "final_spl": spl,
                "final_eval": last_result,
                "initial_values": initial_values,
                "final_values": [],
                "injection_results": caught_so_far,
                "iterations": iteration,
            }

        target = rng.choice(values)
        template = _pick_template_event(events, field, values)
        injected = [inject_attack(field, target, template, rng=rng)]

        result = evaluate_detection(
            service=service,
            detection_name=f"{detection_name}_adv_{iteration}",
            detection_spl=spl,
            golden_query=golden_query,
            earliest=earliest, latest=latest,
            normalization_csv=normalization_csv,
            injected_events=injected,
        )
        last_result = result

        injected_id = injected[0]["_cd"]
        was_caught = injected_id not in result.fired_ids
        caught_so_far.append({"value": target, "was_caught": was_caught})

        if not was_caught:
            return {
                "status": "ok",
                "final_spl": spl,
                "final_eval": result,
                "initial_values": initial_values,
                "final_values": values,
                "injection_results": caught_so_far,
                "iterations": iteration + 1,
            }

        narrowed = narrow_filter(spl, [target])
        if narrowed is None:
            return {
                "status": "no_safe_revision",
                "final_spl": None,
                "final_eval": None,
                "initial_values": initial_values,
                "final_values": [],
                "injection_results": caught_so_far,
                "iterations": iteration + 1,
            }
        spl = narrowed

    # Hit max_iterations. If survivors remain, accept the narrowed filter
    # with a final non-adversarial eval (the surviving IPs weren't tested
    # individually but the filter is still strictly narrower than what
    # the LLM proposed). Run one clean eval against the narrowed SPL so
    # the metrics in final_eval reflect the actual final filter, not the
    # last in-loop result that still had an injected event.
    _, final_values = parse_not_filter(spl)
    if final_values:
        clean_result = evaluate_detection(
            service=service,
            detection_name=f"{detection_name}_adv_final",
            detection_spl=spl,
            golden_query=golden_query,
            earliest=earliest, latest=latest,
            normalization_csv=normalization_csv,
        )
        return {
            "status": "ok",
            "final_spl": spl,
            "final_eval": clean_result,
            "initial_values": initial_values,
            "final_values": final_values,
            "injection_results": caught_so_far,
            "iterations": max_iterations,
        }

    # No values left — truly no safe revision.
    return {
        "status": "no_safe_revision",
        "final_spl": None,
        "final_eval": None,
        "initial_values": initial_values,
        "final_values": [],
        "injection_results": caught_so_far,
        "iterations": max_iterations,
    }
