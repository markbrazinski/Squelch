# Bundle 4: Decision Intelligence — Full Build Spec

## Purpose

Bundle 4 makes the agent show its reasoning. Bundles 1–3 built a pipeline that works and produces honest results across three detection patterns. Bundle 4 adds the transparency layer: judges and practitioners see *why* the agent chose what it chose, how sensitive the result is to label noise, and get a standalone eval tool they can install independently of the agent.

This is the 8→9 push on the roadmap's milestone map.

**Predecessor:** Bundle 3 complete. Three detections (DNS IP filter, Identity service-account filter, Endpoint decline-to-tune) run end-to-end with GitHub PR/Issue creation. Multi-detection orchestration works. Demo-fit gap log identifies D3/D6/D7 as the high-priority gaps Bundle 4 closes.

**Exit gate:** PRs contain decision trails with hypothesis rankings. Agent output shows multi-hypothesis display for all three demo detections. Label perturbation runs and sensitivity score is reported. Standalone `| squelch mode="eval"` command works. The full 9/10 demo (minus temporal holdout) is recordable.

---

## Scope Assessment — What to Build vs. Cut

The roadmap allocates 9 sessions (29–37). We're ahead of schedule with 1 session banked. Four features are scoped:

| Feature | Demo-fit gap closed | Engineering complexity | Sessions (roadmap) | Recommendation |
|---|---|---|---|---|
| Multi-hypothesis display | D3 (High) | Low — data already exists in `cluster_fps` output | 3 → compress to 2 | Build |
| Decision trail in PRs | D7 (High) | Medium — extends `build_pr_body`, per-detection branches | 3 → compress to 2 | Build |
| Label perturbation | D6 (High) | Medium — new eval step, sensitivity scoring | 2 | Build |
| Standalone eval command | Demo Beat 8 close | Low — subset of existing `_tune` flow | 1 | Build |

**Total: 7 sessions (29–35) + 2 sessions buffer/integration (36–37).** Compression is possible because:

- Multi-hypothesis display is *surfacing* data `cluster_fps` already produces (`by_field` dict with per-field ranked entries). No new computation — just formatting into the output row.
- Decision trail extends `build_pr_body` / `build_issue_body` with the hypothesis data. This pairs naturally with multi-hypothesis display.
- Per-detection branch upgrade (eliminating 422) can ride along with the PR enhancement sessions.

---

## Session Plan

### Sessions 29–30: Multi-Hypothesis Display

**Goal:** Agent output includes top 2–3 hypotheses per field with explanatory power scores. The "rejected" hypotheses are visible, not just the winner.

**What the demo script needs (D3):**
```
[HYPOTHESIS] src_ip cluster: 78% explanatory power ✓
[HYPOTHESIS] user+time cluster: 11% ✗
[HYPOTHESIS] sourcetype coverage: no gap ✗
```

**What already exists:** `cluster_fps()` returns a `by_field` dict where each field has a ranked list of `{value, fp_pct, tp_pct, lookup_match, lookup_context}` entries. `_pick_top_cluster()` selects the winner. The rejected fields and their top entries are computed but never surfaced.

**Deliverables:**

1. New helper in `eval/cluster.py`: `summarize_hypotheses(clusters: dict, picked: dict | None) -> list[dict]`
   - For each field in `clusters["by_field"]`, compute cumulative FP explanatory power of the safe (tp_pct=0) entries
   - Return a ranked list: `[{field, cumulative_fp_pct, top_value, top_value_fp_pct, picked: bool, reason_rejected: str | None}, ...]`
   - `reason_rejected` = "tp_pct > 0 on top entry" or "cumulative < 0.20 floor" or "no safe values" — human-readable
   - Endpoint's diagnosis case: all fields show low explanatory power + field extraction gap note

2. Wire into `squelch_command.py::_tune_one()`:
   - After `cluster_fps()` and `_pick_top_cluster()`, call `summarize_hypotheses()`
   - Add `hypotheses` field to the output row (JSON list)
   - Format for display: `hypothesis_summary` field with the `[HYPOTHESIS] field: X% ✓/✗` string

3. Wire into the declined path:
   - When `diagnose_fp_pattern()` fires, the hypothesis summary shows all fields below threshold — reinforcing the "no filterable pattern" narrative

4. Vendor changes

**Exit gate:** All three demo detections show hypothesis rankings in the output row. DNS shows src_ip winning with user/dest rejected. Identity shows user winning with src_ip/dest rejected. Endpoint shows all rejected + diagnosis.

### Sessions 31–32: Decision Trail in PRs + Per-Detection Branches

**Goal:** PR body includes the full hypothesis analysis. Per-detection branches eliminate the 422 problem from Bundle 3.

**What the demo script needs (D7):**
> "3 hypotheses evaluated, 2 revision candidates considered, conservative selected (attack injection caught aggressive candidate)"

**Deliverables:**

1. Extend `build_pr_body()` in `eval/github_integration.py`:
   - Add a "Hypothesis Analysis" section (collapsible `<details>` block) showing all hypotheses with scores
   - Add a "Decision Rationale" section: why the winning field was picked, what the runner-up was, why it was rejected
   - Attack injection section already exists — enhance with the "conservative selected because injection caught X" narrative when narrowing occurred

2. Extend `build_issue_body()`:
   - Add the hypothesis analysis showing all fields below threshold
   - Connect to the diagnosis: "No field clears 20% explanatory power → diagnosis path activated"

3. Per-detection branch upgrade:
   - Instead of all PRs sharing `squelch/proposals`, each PR gets its own branch: `squelch/tune/<detection_name>-<timestamp>`
   - `create_pr()` creates the branch via Git Data API (create ref from main HEAD), opens PR from that branch
   - Eliminates the 422 duplicate-head problem entirely
   - Old `squelch/proposals` branch can be deleted or left as documentation

4. Vendor changes

**Exit gate:** DNS PR shows collapsible hypothesis section. Identity PR shows service account winning over IP cluster. Per-detection branches work — two sequential accepted detections both create PRs without 422.

### Sessions 33–34: Label Perturbation

**Goal:** After standard eval, randomly flip 10% of labels, re-eval, report sensitivity score. If precision/recall shift significantly under perturbation, the revision is fragile.

**What the demo script needs (D6):** "label perturbation PASS"

**Deliverables:**

1. New function in `eval/eval_lib.py`: `perturb_and_eval(service, detection_name, detection_spl, golden_query, normalization_csv, *, flip_pct=0.10, n_trials=3, rng=None) -> dict`
   - For each trial: copy the golden event set, randomly flip `flip_pct` of labels (TP↔FP), re-run `evaluate_detection()` against the perturbed set
   - Return: `{mean_precision_delta, mean_recall_delta, max_precision_delta, max_recall_delta, pass: bool}`
   - `pass` = True if `max_recall_delta < 0.05` (recall doesn't drop more than 5 points under any perturbation)
   - RNG seeded for reproducibility (same pattern as attack injection)

2. Wire into `_tune_one()`:
   - Run after the gate decision (accepted or rejected — perturbation is informational, not a gate)
   - Add `perturbation_pass`, `perturbation_precision_delta`, `perturbation_recall_delta` to output row
   - Add to KV payload

3. Wire into `build_pr_body()`:
   - New section: "Label Sensitivity" showing the perturbation results
   - "PASS" or "WARN" badge

4. Wire into `build_issue_body()`:
   - Perturbation on the baseline (no revised SPL) — shows how sensitive the current detection's metrics are to label noise

5. Vendor changes

**Implementation note:** Perturbation operates on the in-memory event set, not the index. Same approach as attack injection. Each trial is one `evaluate_detection()` call with modified labels — ~150ms per trial × 3 trials = ~450ms additional latency. Well within the 5s budget.

**Exit gate:** All three detections report perturbation results. DNS and Identity show "PASS" (robust under 10% noise). Perturbation data visible in PR body.

### Sessions 35–36: Standalone Eval Command + Integration

**Goal:** `| squelch mode="eval"` runs the eval harness without clustering, revision, or the agent. This is the "install the eval harness Monday" product from the demo close.

**Deliverables:**

1. New mode in `squelch_command.py`:
   ```
   | squelch mode="eval" search_name="WindowsAuth_AnomalousLogonSource" [spl="optional override SPL"]
   ```
   - Runs `evaluate_detection()` with normalization
   - Runs `perturb_and_eval()` for sensitivity
   - Returns: precision, recall, fp_rate, label_confidence, perturbation results, runtime
   - No clustering, no LLM, no revision, no GitHub — pure eval
   - If `spl` is provided, evaluates that SPL instead of the saved search's SPL

2. Integration dry run:
   - Full pipeline with all Bundle 4 features active across all 3 demo detections
   - Capture to `eval/results/tune_results_bundle_4.csv`
   - Demo-fit gap update: D3, D6, D7 should now show as resolved

3. Vendor changes

**Exit gate:** `| squelch mode="eval"` returns eval results for any detection. Integration run shows hypothesis display + decision trail + perturbation across all three demo detections.

### Session 37: Bundle Close + Demo-Fit Reconciliation

**Goal:** Final numbers, updated demo-fit gap log, bundle retro.

**Deliverables:**

1. Final `tune_results_bundle_4.csv` with all 8 detections
2. Demo-fit gap log update: which of the 8 drifts from Bundle 3 are now resolved
3. Demo script reconciliation notes for Phase 9
4. Bundle retro in `docs/bundle-4-spec.md`

**Exit gate:** Bundle 4 complete. The 9/10 demo is recordable.

---

## Key Architecture Decisions for Bundle 4

| Decision | Rationale |
|---|---|
| Hypotheses are computed from existing `cluster_fps` output, not a new LLM call | The data already exists. Adding an LLM call to "rank hypotheses" adds latency and hallucination risk for zero information gain. |
| Perturbation is informational, not a gate | A "WARN" on perturbation shouldn't block an accepted tune — it's a signal for the reviewer, not a veto. The recall gate is still the safety mechanism. |
| Per-detection branches via Git Data API | Each accepted tune gets `squelch/tune/<name>-<timestamp>`. Eliminates 422 entirely. The API cost is one create-ref + one create-PR — two calls, ~400ms. |
| Standalone eval reuses `evaluate_detection()` directly | No new eval logic. `mode="eval"` is a thin wrapper that skips everything after eval (clustering, revision, injection, GitHub). |
| Perturbation flips labels in-memory, not in the index | Same architecture principle as attack injection. No index mutation. |
| `n_trials=3` for perturbation | 3 trials balances signal quality against latency. Each trial is ~150ms. |

---

## Files Changed (predicted)

| File | Sessions | Change |
|---|---|---|
| `eval/cluster.py` | 29–30 | `summarize_hypotheses()` function |
| `eval/eval_lib.py` | 33–34 | `perturb_and_eval()` function |
| `eval/github_integration.py` | 31–32 | Hypothesis section in PR/Issue body, per-detection branches |
| `squelch_command.py` | 29–30, 31–32, 33–34, 35–36 | Hypothesis display, decision trail wiring, perturbation wiring, `mode="eval"` |
| App vendored copies | All | Mirror every eval/ change |
| `eval/results/tune_results_bundle_4.csv` | 35–37 | New — final capture |

---

## Risks

| Risk | Mitigation |
|---|---|
| Per-detection branch creation via Git Data API is complex | Fallback: keep `squelch/proposals` + manual close between runs. Inconvenient but functional. |
| Perturbation adds ~450ms to every tune invocation | Run after the gate decision, not before. If total exceeds 5s, reduce to `n_trials=1`. |
| Multi-hypothesis display clutters the output row | JSON field (`hypotheses`) keeps the row flat. `hypothesis_summary` is a formatted string for display. |
| Standalone eval mode bypasses injection/perturbation debate | `mode="eval"` includes perturbation (it's part of eval) but not injection (injection is revision-specific). Clear boundary. |
| Demo script still references Bundle 4 features that might not match exactly | Sessions 37 reconciliation catches this. Phase 9 is the final script update. |

---

## Out of Scope

- Temporal holdout (Bundle 5, CUT IF BEHIND)
- Scheduled trigger firing (deferred since Bundle 1)
- Real file commits in PRs beyond the per-detection branch (the PR body is still the primary artifact)
- MCP tool expansion beyond existing 2 tools
- Demo recording (Phase 9)

---

## What Comes After Bundle 4

| Phase | Sessions | What |
|---|---|---|
| Bundle 5: Temporal Holdout | 38–42 | CUT IF BEHIND (cut trigger: Bundle 4 closes later than Session 40) |
| Phase 9: Polish + Ship | 43–50 | Architecture diagram, recording, Devpost, README, submit |

With Bundle 4 at Session 37 and 1 banked session, we'd be at effective Session 36 — well under the Session 40 cut trigger for Bundle 5.

---

## Demo-Fit Gap Log — Bundle 4 Resolution

| Gap | Description | Status |
|---|---|---|
| D3 | Agent doesn't show rejected hypotheses | ✅ Resolved — `hypothesis_summary` field in output row + Hypothesis Analysis table in PR body |
| D6 | No label-perturbation signal | ✅ Resolved — `perturbation_pass`, `perturbation_precision_delta`, `perturbation_recall_delta` in output; Label Sensitivity section in PR/Issue body |
| D7 | PRs lack decision trail | ✅ Resolved — Hypothesis Analysis table + Decision Rationale section in every accepted PR |

Integration dry run results (`eval/results/tune_results_bundle_4.csv`):

| Detection | Decision | Precision before→after | Recall held | Perturbation pass |
|---|---|---|---|---|
| DNS_TunnelExfil_Heuristic | accepted | 0.40 → 0.76 | ✅ 0.10 | ✅ |
| Identity_PrivEscalation_Confirmed | accepted | 0.27 → 0.45 | ✅ 0.06 | ✅ |
| Endpoint_NewServiceInstalled | declined (field_extraction_gap) | — | — | ✅ |

---

## Bundle 4 Retro

**Closed:** 2026-05-24. Sessions 29–37 (effective 36 with 1 banked).

**What went well:**
- All three D3/D6/D7 gaps closed. PR #25 on GitHub shows the full decision trail rendering correctly.
- `perturb_and_eval` reused the in-memory event pattern from attack injection cleanly — no new Splunk queries per trial.
- `summarize_hypotheses` required zero new computation — the data was already in `cluster_fps`'s `by_field` output.
- `| squelch mode="eval"` works as a standalone tool with no side effects.

**What was harder than expected:**
- Per-detection branch PRs 422 because branches have no commits ahead of base (no real file diffs yet — that's Bundle 5). Mitigated with auto-close of the `squelch/proposals` PR before each new open.
- Saved searches needed to be manually created in Splunk and golden data re-seeded before the integration dry run could run.

**Carried to Bundle 5:**
- Real SPL file commits on per-detection branches (eliminates the `squelch/proposals` shared-branch workaround).
- Temporal holdout eval (CUT IF BEHIND — bundle 4 closed at effective session 36, well under the session 40 trigger).