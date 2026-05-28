# Bundle 5: Temporal Holdout — Full Build Spec

## Purpose

Bundle 5 adds the overfitting check. Bundles 1–4 evaluate proposed revisions against the full golden dataset — the same data the clustering step analyzed to find the FP pattern. If the pattern is transient (e.g., a scanner IP that was active for 2 weeks then stopped), the revision looks good on training data but degrades on unseen data. Temporal holdout splits the golden dataset into a training window and a holdout window, evaluates the revision against both, and flags divergence.

This is the 9→10 push on the roadmap's milestone map. The demo is already a strong 9 without it. Bundle 5 adds the "we checked for overfitting" signal that separates a polished prototype from a rigorous one.

**Predecessor:** Bundle 4 complete. Decision intelligence layer (hypothesis display, decision trail, perturbation, standalone eval) ships. All three demo detections show hypothesis rankings, perturbation PASS, and decision trails in PRs.

**Exit gate:** Temporal holdout runs on all three demo detections. PR bodies include a "Temporal Stability" section showing training vs. holdout metrics. `| squelch mode="eval"` includes temporal holdout. The 10/10 demo is recordable.

---

## Scope Assessment — What to Build vs. Cut

The roadmap allocates 5 sessions (38–42). One feature with three integration points:

| Feature | Demo value | Engineering complexity | Sessions | Recommendation |
|---|---|---|---|---|
| `temporal_holdout_eval()` function | High — proves revision generalizes | Medium — 4 `evaluate_detection()` calls, time-window scoping | 2 | Build |
| Wire into `_tune_one()` + PR/Issue body | High — visible in GitHub artifacts | Low — follows perturbation wiring pattern exactly | 2 | Build |
| Integration dry run + bundle close | Required | Low | 1 | Build |

**Total: 4 sessions build (38–41) + 1 session close (42).**

The implementation reuses `evaluate_detection()` with its existing `earliest`/`latest` parameters. No new Splunk queries, no new eval logic — just scoping existing eval calls to different time windows and comparing.

---

## Key Design Decisions

| Decision | Choice | Rationale |
|---|---|---|
| Temporal split mechanism | Use `earliest`/`latest` params on `evaluate_detection()` | Both the golden query and the detection-fires query need to be scoped to the same time window. The existing params do this naturally. No in-memory splitting needed. |
| Split ratio | 70% training / 30% holdout | Standard ML holdout. With ~125 events per detection, holdout gets ~38 events — enough for meaningful precision/recall. |
| Split point discovery | Query golden data for min/max `_time`, compute boundary | One-time query per invocation. ~50ms. |
| Number of eval calls | 4 per detection (baseline×training, baseline×holdout, revised×training, revised×holdout) | Proper overfitting detection requires comparing *lift* across windows, not just absolute metrics. ~600ms total — within budget. |
| Informational vs. gating | Informational with PASS/WARN badge (same as perturbation) | The recall gate remains the safety mechanism. Holdout is a signal for the reviewer, not a veto. |
| PASS criteria | PASS if holdout precision lift ≥ 0 AND holdout recall holds | If the revision improves precision on training but *degrades* it on holdout, that's overfitting. Named constant: `HOLDOUT_PRECISION_FLOOR_DELTA = 0.0`. |
| Declined/rejected path | Report baseline temporal metrics only (no revised SPL to test) | Still informational — shows whether the *baseline* detection's metrics are temporally stable. |
| Where in `_tune_one` | After perturbation, before KV write | Same atomic-write principle as perturbation. |
| `mode="eval"` | Include temporal holdout | It's eval, not revision. Belongs in the standalone tool. |

---

## Session Plan

### Sessions 38–39: Temporal Holdout Function

**Goal:** `temporal_holdout_eval()` function exists in `eval/eval_lib.py`, tested against synthetic fixtures.

**Deliverables:**

1. New constant in `eval/eval_lib.py`:

```python
# Bundle 5: minimum holdout precision delta (revised vs baseline) that
# counts as PASS. 0.0 means the revision must not degrade precision on
# unseen data. Informational only — recall gate is the safety mechanism.
HOLDOUT_PRECISION_FLOOR_DELTA = 0.0
HOLDOUT_SPLIT_PCT = 0.70  # 70% training, 30% holdout
```

2. New helper to discover the time range:

```python
def _get_time_boundaries(service, golden_query: str) -> tuple[float, float]:
    """Query golden data for min/max _time. Returns (earliest_epoch, latest_epoch)."""
    # Runs: {golden_query} | stats min(_time) as t_min, max(_time) as t_max
    # Returns the two epoch floats
```

3. New function in `eval/eval_lib.py`:

```python
def temporal_holdout_eval(
    service,
    detection_name: str,
    original_spl: str,
    revised_spl: str | None,
    golden_query: str,
    *,
    normalization_csv: Path | None = None,
    split_pct: float = HOLDOUT_SPLIT_PCT,
) -> dict:
    """Split golden data temporally, evaluate both SPLs on both windows.
    
    For accepted tunes: compares precision lift on training vs holdout.
    For declined/rejected tunes: revised_spl is None, reports baseline
    temporal metrics only.
    """
```

**Algorithm:**

1. Call `_get_time_boundaries(service, golden_query)` → `(t_min, t_max)`.
2. Compute split: `t_split = t_min + split_pct * (t_max - t_min)`.
3. Format as Splunk time strings (epoch format).
4. Run baseline (original_spl) on both windows:
   - `baseline_train = evaluate_detection(..., earliest=t_min_str, latest=t_split_str)`
   - `baseline_holdout = evaluate_detection(..., earliest=t_split_str, latest=t_max_str)`
5. If `revised_spl is not None`, run revised on both windows:
   - `revised_train = evaluate_detection(..., earliest=t_min_str, latest=t_split_str)`
   - `revised_holdout = evaluate_detection(..., earliest=t_split_str, latest=t_max_str)`
6. Compute deltas:
   - `training_precision_lift = revised_train.precision - baseline_train.precision`
   - `holdout_precision_lift = revised_holdout.precision - baseline_holdout.precision`
   - `training_recall_delta = revised_train.recall - baseline_train.recall`
   - `holdout_recall_delta = revised_holdout.recall - baseline_holdout.recall`

**Return shape:**

```python
{
    "split_pct": float,
    "t_split_epoch": float,
    "training_events": int,       # event count in training window
    "holdout_events": int,        # event count in holdout window
    "baseline_train_precision": float,
    "baseline_holdout_precision": float,
    "revised_train_precision": float | None,
    "revised_holdout_precision": float | None,
    "training_precision_lift": float | None,
    "holdout_precision_lift": float | None,
    "training_recall_delta": float | None,
    "holdout_recall_delta": float | None,
    "pass": bool,                 # holdout_precision_lift >= HOLDOUT_PRECISION_FLOOR_DELTA
                                  #   AND holdout_recall_delta >= 0
                                  # When revised_spl is None: True (baseline-only, no revision to judge)
}
```

4. Re-export from vendored `__init__.py`.

**Verification:**
- Unit: mock `service.jobs.oneshot` to return deterministic event streams for each time window. Assert correct split logic, delta computation, PASS/WARN threshold.
- Unit: when `revised_spl is None`, assert `pass=True` and all revised fields are None.
- Unit: when holdout precision degrades but training improves, assert `pass=False`.

**Exit gate:** `temporal_holdout_eval()` computes correct deltas on synthetic data. PASS/WARN logic works.

---

### Sessions 40–41: Integration

**Goal:** Temporal holdout wired into the full pipeline — `_tune_one()`, PR/Issue bodies, `mode="eval"`.

**Deliverables:**

1. **Wire into `_tune_one()`** — three insertion sites (same pattern as perturbation):

   **Accepted path** (after perturbation, before KV write):
   ```python
   holdout = temporal_holdout_eval(
       service, target_name, original_spl, final_spl, GOLDEN_QUERY,
       normalization_csv=NORMALIZATION_LOOKUP,
   )
   ```
   Add to `kv_payload` and yield row: `holdout_pass`, `holdout_training_precision_lift`, `holdout_holdout_precision_lift`.

   **Rejected-by-gate path:**
   ```python
   holdout = temporal_holdout_eval(
       service, target_name, original_spl, None, GOLDEN_QUERY,
       normalization_csv=NORMALIZATION_LOOKUP,
   )
   ```
   Baseline-only. Add three holdout fields to yield row.

   **Declined-diagnosis path:**
   Same as rejected — `revised_spl=None`. Add three holdout fields.

   **no_safe_revision path:**
   Same as rejected — `revised_spl=None`. Add three holdout fields.

2. **PR body — Temporal Stability section** (in `build_pr_body()`):

   Extend signature with `holdout: dict | None = None`. Insert after Label Sensitivity, before Cluster Analysis:

   ```markdown
   ## Temporal Stability (70/30 split)

   **PASS** — revision generalizes to unseen time window.

   | Window | Events | Baseline Precision | Revised Precision | Lift |
   |---|---|---|---|---|
   | Training (70%) | 87 | 0.29 | 0.51 | +0.22 |
   | Holdout (30%) | 38 | 0.31 | 0.44 | +0.13 |
   ```

   Badge: **PASS** if `holdout["pass"]`, else **WARN — revision may overfit to training window**.

3. **Issue body — Temporal Stability section** (in `build_issue_body()`):

   Extend signature with `holdout: dict | None = None`. Insert after Label Sensitivity:

   ```markdown
   ## Temporal Stability (baseline, 70/30 split)

   Baseline detection metrics are temporally stable.

   | Window | Events | Precision | Recall |
   |---|---|---|---|
   | Training (70%) | 87 | 0.22 | 1.00 |
   | Holdout (30%) | 38 | 0.24 | 1.00 |
   ```

4. **Wire into `mode="eval"`** — add after `perturb_and_eval()` call:

   ```python
   holdout = temporal_holdout_eval(
       service, target_name, spl, None, golden_query,
       normalization_csv=normalization_csv,
   )
   ```

   Add `holdout_pass`, `holdout_training_precision`, `holdout_holdout_precision` to the yield row.

   If `spl` override is provided, run as revised vs saved-search baseline:
   ```python
   holdout = temporal_holdout_eval(
       service, target_name, saved_spl, override_spl, golden_query,
       normalization_csv=normalization_csv,
   )
   ```

5. **Imports + vendoring:**
   - Add `temporal_holdout_eval` to `from squelch_eval import (...)` in `squelch_command.py`
   - Update `__init__.py` exports
   - Mirror `eval_lib.py`, `github_integration.py` to vendored paths
   - diff all mirrors — must be empty

**Verification:**
- Smoke (live Splunk): run DNS through full pipeline. Confirm PR has "Temporal Stability" section with PASS.
- Multi-detection: run all 3 demo detections. Confirm holdout columns populated in all rows.
- `mode="eval"`: `| squelch mode="eval" search_name="DNS_AnomalousResolver"` returns holdout fields.
- Latency: total `_tune_one` runtime still ≤ 6s with holdout (4 extra eval calls at ~150ms each = ~600ms).

**Exit gate:** All three demo detections show temporal holdout in output and PR/Issue bodies. `mode="eval"` includes holdout.

---

### Session 42: Validation + Bundle Close

**Goal:** Final numbers, full integration validation, bundle retro.

**Deliverables:**

1. Full pipeline run across all three demo detections with every feature active (hypothesis display, decision trail, perturbation, temporal holdout).
2. Capture to `eval/results/tune_results_bundle_5.csv`. Schema = Bundle 4 columns + `holdout_pass`, `holdout_training_precision_lift`, `holdout_holdout_precision_lift`.
3. Demo-fit gap log update — all D-gaps should now be resolved or deferred to Phase 9.
4. Bundle retro appended to docs.

**End-to-End Verification (whole bundle):**

- **Temporal stability:** All three demo detections show holdout results. DNS and Identity should show PASS (the scanner IP and svc_backup patterns are persistent, not transient). Document Endpoint's result.
- **PR temporal section:** Open the DNS PR on GitHub. Confirm "Temporal Stability" section renders with training/holdout table and PASS badge.
- **No regressions:** hypothesis display, decision trail, perturbation, per-detection branches, standalone eval — all still work. DNS is the canary.
- **Latency budget:** total pipeline time per detection ≤ 6s.
- **Vendor mirror parity:** diff between `eval/` and `bin/lib/squelch_eval/` is empty for all changed files.

**Exit gate:** Bundle 5 complete. The 10/10 demo is recordable.

---

## Files Changed (predicted)

| File | Sessions | Change |
|---|---|---|
| `eval/eval_lib.py` | 38–39 | `temporal_holdout_eval()`, `_get_time_boundaries()`, constants |
| `eval/github_integration.py` | 40–41 | Temporal Stability section in PR/Issue body |
| `bin/squelch_command.py` | 40–41 | Holdout wiring in `_tune_one()` + `_eval()` |
| App vendored copies | All | Mirror every eval/ change |
| `eval/results/tune_results_bundle_5.csv` | 42 | Final capture |

---

## Risks

| Risk | Mitigation |
|---|---|
| Not enough events in holdout window | 30% of ~125 events = ~38. Enough for precision/recall. If a detection has very few events in one window, report metrics but note low confidence. |
| Seeded data has uniform temporal distribution (no temporal patterns to catch) | Expected for synthetic data. Holdout will show PASS for all detections. That's fine — the *capability* is the demo, not the *result*. Phase 9 can note "on production data with temporal drift, holdout would catch overfitting." |
| 4 extra eval calls add ~600ms | Well within 6s budget. If it spikes, cache the time boundaries and reuse `golden_events` bypass from Bundle 4. |
| `evaluate_detection` earliest/latest params need to be epoch strings | Splunk accepts epoch format (`earliest=1716000000`). Verify in Session 38. |

---

## Out of Scope

- Configurable split ratios in the UI (hardcoded 70/30)
- Multiple holdout folds (k-fold cross-validation — overkill for hackathon)
- Temporal pattern detection (identifying *which* events are transient)
- Demo recording (Phase 9)
- Demo script updates (Phase 9)

---

## What Comes After Bundle 5

| Phase | Sessions | What |
|---|---|---|
| Phase 9: Polish + Ship | 43–50 | Architecture diagram, Devpost, README, final skeptical pass, demo recording, submit |

Target: submit June 13, 48 hours before deadline.

---

## Demo-Fit Gap Log — Bundle 5 Resolution

| Gap | Description | Status |
|---|---|---|
| D8 | No overfitting check — revision evaluated on same data used to find the FP pattern | ✅ Resolved — `holdout_pass`, `holdout_training_precision_lift`, `holdout_holdout_precision_lift` in output row; Temporal Stability section in PR/Issue body |

Integration dry run results (`eval/results/tune_results_bundle_5.csv`):

| Detection | Decision | Precision before→after | Holdout pass | Holdout lift (training → holdout) |
|---|---|---|---|---|
| DNS_TunnelExfil_Heuristic | accepted | 0.40 → 0.76 | ✅ | +0.36 → +0.32 |
| Identity_PrivEscalation_Confirmed | accepted | 0.27 → 0.45 | ✅ | +0.23 → +0.11 |
| Endpoint_NewServiceInstalled | declined (field_extraction_gap) | — | ✅ (baseline-only) | — |

All D-gaps are now resolved. Remaining work (Phase 9): demo recording, Devpost write-up, README, architecture diagram.

---

## Bundle 5 Retro

**Closed:** 2026-05-24. Sessions 38–42.

**What went well:**
- `temporal_holdout_eval()` slotted in cleanly alongside `perturb_and_eval` — same deferred-import pattern, same optional-kwarg pattern in PR/Issue body builders.
- Both accepted detections show PASS with holdout lift slightly lower than training lift (DNS: +0.36 train → +0.32 holdout; Identity: +0.23 → +0.11). Expected with seeded data — proves the capability without requiring real temporal drift.
- Endpoint declined path correctly returns `pass=True` with all revised/delta fields as None.
- The `_get_time_boundaries` fix (missing `output_mode="json"`) was caught immediately on first run.

**What was harder than expected:**
- `_get_time_boundaries` used raw `list(service.jobs.oneshot(...))` instead of `_read_json_results` — the bytes-vs-str TypeError only surfaces at runtime against live Splunk. A unit test can't catch it without a real splunklib mock.

**Carried to Phase 9:**
- Real SPL file commits on per-detection branches (still deferred — PRs use squelch/tune/\<slug\> branches with no file diff)
- Demo recording, Devpost write-up, README, architecture diagram
- Final skeptical pass on all three detections