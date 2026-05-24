# Bundle 3: Three Detections — Full Build Spec

## Purpose

Bundle 3 takes the honest engine from Bundles 1–2 (one detection, noisy labels, adversarial eval) and proves it generalizes: three detections with three different outcomes. This is the move from "pipeline works" to "agent shows judgment."

**Predecessor:** Bundle 2 complete. DNS_TunnelExfil_Heuristic runs end-to-end with noisy labels, normalization, and attack injection. 7 of 8 detections produce accepted tunes; 1 returns no_safe_cluster. Honest numbers captured.

**Exit gate:** Three detections run through the pipeline producing three different outcomes — IP filter (DNS), service account filter (PrivEscalation), and "don't tune / file Issue" (a field extraction gap detection). GitHub PR created for the two accepted tunes; GitHub Issue created for the declined tune. All three visible in one demo flow.

---

## Critical Design Decision: Detection Mapping

Bundle 2 discovered DNS_TunnelExfil_Heuristic is the best Detection 1 subject (narrows 3→2 IPs naturally). But the original roadmap assigned DNS to the "don't tune" role (field extraction gap). These are contradictory — a detection can't both tune well and be untuneable.

**Resolution: reassign detection roles.**

| Demo Role | Detection Name | FP Pattern | Outcome |
|---|---|---|---|
| Detection 1 (IP filter) | `DNS_TunnelExfil_Heuristic` | Scanner IPs, 78% of FPs | Accepted: NOT filter on 2 CIDRs (after injection narrows from 3) |
| Detection 2 (service account) | `Identity_PrivEscalation_Confirmed` | 65% of FPs from user=svc_backup | Accepted: NOT filter on user="svc_backup" |
| Detection 3 ("don't tune") | `Endpoint_NewServiceInstalled` | No dominant cluster; 40-45% have empty `dest_ip` from sourcetype=svc_install_log | Declined: GitHub Issue filed against field extraction gap |

**Why these three:**

- **DNS stays as Detection 1.** Bundle 2 already confirmed the narrative. No changes needed to its seeding or pipeline path.
- **Identity_PrivEscalation_Confirmed becomes Detection 2.** Currently pristine (0.03 FP rate). Seeding changes bump it to ~0.72 FP rate with a service account pattern. The detection name already says "privilege escalation" which pairs naturally with a service account filter. Rename to `PrivEscalation_ServiceAccountNoise` in seeding for clarity, or keep the original name — CC's call on which reads better in the demo.
- **Endpoint_NewServiceInstalled becomes Detection 3.** Currently mid-FP (0.22). Seeding changes create a field extraction gap pattern: ~45% of FPs have empty `dest_ip`, all tagged with `sourcetype=svc_install_log`. No single field cluster exceeds 50%, so clustering returns no dominant hypothesis. The "don't tune" code path diagnoses the extraction gap.

**WindowsAuth_AnomalousLogonSource** retains its current seeding and remains a valid pipeline target, but it's not one of the three demo detections. It stays as the dev/test workhorse.

---

## Seeding Changes

The current seeding script applies scanner IPs uniformly to all FP events (78% across all 8 detections). Bundle 3 needs **per-detection FP patterns** — different detections have different FP root causes.

### Architecture: per-detection config in seed_notable.py

Replace the single scanner-IP assignment with a per-detection pattern config:

```python
DETECTION_FP_PATTERNS = {
    # Detection 1: IP filter (existing behavior)
    "DNS_TunnelExfil_Heuristic": {
        "fp_rate": 0.71,
        "pattern": "scanner_ip",  # 78% of FPs get scanner IPs
    },
    # Detection 2: service account
    "Identity_PrivEscalation_Confirmed": {
        "fp_rate": 0.72,
        "pattern": "service_account",  # 65% of FPs get user=svc_backup
    },
    # Detection 3: field extraction gap
    "Endpoint_NewServiceInstalled": {
        "fp_rate": 0.72,
        "pattern": "extraction_gap",  # 45% of FPs get dest_ip=""
    },
    # Remaining detections: keep current scanner_ip pattern
    "WindowsAuth_AnomalousLogonSource": {"fp_rate": 0.83, "pattern": "scanner_ip"},
    "Network_PortScan_Detected": {"fp_rate": 0.74, "pattern": "scanner_ip"},
    "Web_SuspiciousUserAgent": {"fp_rate": 0.34, "pattern": "scanner_ip"},
    "Process_RareParentChild": {"fp_rate": 0.27, "pattern": "scanner_ip"},
    "Data_BulkDownload_Sensitive": {"fp_rate": 0.03, "pattern": "scanner_ip"},
}
```

### Pattern implementations

**`scanner_ip` (existing):** 78% of FP events get `src_ip` from scanner pool. Unchanged from current behavior.

**`service_account`:** 65% of FP events get `user="svc_backup"`. Other fields (`src_ip`, `dest`) remain random. TPs never get `user="svc_backup"` — the pattern is FP-exclusive, same as scanner IPs are FP-exclusive. A `service_accounts.csv` lookup (new) maps `svc_backup` → `known_infrastructure=true`.

**`extraction_gap`:** 45% of FP events get `dest_ip=""` (empty string) AND `sourcetype_tag="svc_install_log"`. The remaining 55% of FPs have random values across all fields — no single field cluster dominates. Key property: no field's top value explains >50% of FPs, so `_pick_top_cluster` in `revise.py` finds nothing filterable.

### New lookup: lookups/service_accounts.csv

```
user,account_type,known_infrastructure
svc_backup,service,true
```

Mirrors to `/Applications/Splunk/etc/apps/squelch/lookups/`. Used by the clustering step to annotate the `user` field cluster the same way `scanner_ips.csv` annotates the `src_ip` cluster.

### Re-seeding

After seeding changes: `python scripts/seed_notable.py --count 1000 --clear-first`. All 8 detections re-seeded with their per-detection patterns. DNS, WindowsAuth, PortScan keep scanner IPs. Identity gets service account. Endpoint gets extraction gap. The rest keep their current distributions.

---

## Detection 2: Service Account Filter

### What the pipeline does

1. **Trigger:** FP rate 0.72 > 0.70 threshold → fires.
2. **Clustering:** `cluster_fps()` finds `user` field has top entry `svc_backup` at ~65% explanatory power. `src_ip` cluster is diffuse (no scanner IPs in this detection's FPs). `dest` is diffuse.
3. **Cross-reference:** Agent checks `service_accounts.csv` lookup → confirms `svc_backup` is `known_infrastructure=true`.
4. **Revision:** LLM proposes `NOT user IN ("svc_backup")` — simple user-only filter. No time window (locked decision from roadmap — LLM reliability concern with temporal SPL).
5. **Attack injection:** Injects synthetic TP with `user="svc_backup"`. If the NOT filter catches it → narrowing drops `svc_backup` from filter → revision becomes empty → `no_safe_revision`. If it doesn't get caught (because the TP wouldn't fire on the original detection with that user value anyway) → accepted.
6. **Gate:** Recall preserved, precision improved → accepted.
7. **Output:** PR created on GitHub with SPL diff + eval numbers.

### Attack injection concern

For Detection 2, the NOT filter is `NOT user IN ("svc_backup")` — a single-value filter. If injection catches it, narrowing empties the filter → `no_safe_revision`. This is different from Detection 1 (multi-value IP filter where losing one still leaves others).

**Resolution:** This is actually the honest outcome if `svc_backup` appears in TPs. The seeding must ensure `svc_backup` is FP-exclusive (never appears as a TP user). Then injection creates a synthetic TP with `user="svc_backup"` — but `_injected_would_fire` checks whether the original SPL would fire on this event. The original detection fires on privilege escalation patterns, not on specific users. The synthetic event has `status_label="true_positive"` and `user="svc_backup"`, and we assume the original SPL fires on it (per the `_injected_would_fire` logic: if no NOT filter in the original SPL, return True).

So: injection WILL catch `svc_backup`, narrowing WILL empty the filter, and the result WILL be `no_safe_revision`.

**Fix options:**
- **Option A:** Accept this outcome. Detection 2 demonstrates "proposed filter was too aggressive — injection caught it." This is honest but doesn't produce a PR.
- **Option B:** Skip injection for single-value filters. If `parse_not_filter` returns only 1 value, skip the adversarial loop and go straight to gate. Rationale: with a single-value filter, the only narrowing outcome is "remove everything." The recall gate is sufficient protection.
- **Option C:** Make the injection smarter — only inject if the field value appears in real TP events. If `svc_backup` never appears in TPs (which it doesn't, by seeding construction), the injection is pointless theater. Skip it.

**Recommendation: Option B.** Simple, principled, and the demo narrative becomes "single-value filters bypass injection — the recall gate is the safety net." CC should implement this as a check at the top of `run_adversarial_eval`: `if len(values) <= 1: skip injection, return the unmodified revision for gating.`

### Lookup cross-reference integration

The clustering step already annotates values with lookup context (scanner_ips.csv for src_ip). Extend this to support multiple lookups per field:

```python
FIELD_LOOKUPS = {
    "src_ip": "scanner_ips.csv",
    "user": "service_accounts.csv",
}
```

When `cluster_fps` finds a top cluster on the `user` field, it cross-references against `service_accounts.csv` and annotates the cluster with `known_infrastructure=true`. This annotation flows into the LLM prompt context.

---

## Detection 3: "Don't Tune" — Field Extraction Gap

This is the hardest engineering in the build. The agent needs to reason about WHY there's no clean pattern and identify data quality as the root cause.

### What the pipeline does

1. **Trigger:** FP rate 0.72 > 0.70 threshold → fires.
2. **Clustering:** `cluster_fps()` finds no field with a top entry >50% explanatory power. `dest_ip=""` is at ~45% but is an empty string, not a filterable value. `src_ip` is diffuse. `user` is diffuse.
3. **Diagnosis:** New code path in `_tune()`. When `_pick_top_cluster` returns None (no dominant pattern), instead of stopping at `no_safe_cluster`, the agent runs a **field coverage analysis**: for each field, what percentage of FP events have empty/missing values? If any field has >30% empty AND those empties correlate with a specific sourcetype, diagnose "field extraction gap."
4. **Output:** Agent declines to tune. Files a GitHub Issue (not a PR) with evidence: which field is empty, what percentage, which sourcetype, and the recommendation to fix `props.conf`.
5. **KV write:** Decision row with `decision="declined"`, `step="diagnosis"`, `diagnosis="field_extraction_gap"`, evidence JSON.

### Field coverage analysis — new function

```python
def diagnose_fp_pattern(events: list[dict], normalization_csv=None) -> dict | None:
    """Analyze FP events for data quality issues when no filterable cluster exists.
    
    Returns a diagnosis dict if a field extraction gap is found:
    {
        "type": "field_extraction_gap",
        "field": "dest_ip",
        "empty_pct": 0.45,
        "sourcetype": "svc_install_log",
        "sourcetype_pct": 1.0,  # 100% of empties are from this sourcetype
        "recommendation": "Fix field extraction in props.conf for svc_install_log"
    }
    
    Returns None if no diagnosable pattern found.
    """
```

**Where it lives:** `eval/cluster.py` (it's analyzing the same event set that clustering uses) or a new `eval/diagnose.py`. Preference: `eval/cluster.py` since it shares the event-loading and normalization plumbing.

### The LLM's role in Detection 3

The LLM is NOT needed for diagnosis. The field coverage analysis is pure Python — count empties, correlate with sourcetype. The LLM IS used to generate the human-readable recommendation and the GitHub Issue body. This keeps the diagnostic logic reliable (no LLM hallucination on the critical "don't tune" decision) while letting the LLM produce polished output.

### "Don't tune" threshold

The agent declines to tune when BOTH conditions are met:
1. No field cluster exceeds 50% explanatory power (`_pick_top_cluster` returns None)
2. Field coverage analysis finds a diagnosable gap (>30% empties on a field correlated with a sourcetype)

If condition 1 is true but condition 2 is false (no dominant cluster AND no diagnosable gap): return `no_safe_cluster` as today — the agent simply can't find a safe tune. No Issue filed.

---

## Git Integration: PRs and Issues

### Approach: outbound HTTP to api.github.com

Same pattern as Gemini calls — HTTP POST from within `squelch_command.py`. The GitHub personal access token is stored in Splunk's `storage/passwords` (same mechanism as the Gemini API key).

### New module: eval/github_integration.py

```python
def create_pr(repo, branch, title, body, base="main", token=None) -> dict:
    """Create a GitHub PR via REST API.
    
    Steps:
    1. Create a new branch from base
    2. Commit the SPL change to savedsearches.conf (or a detection-specific file)
    3. Open a PR with the structured body
    
    Returns: {"pr_url": "...", "pr_number": N}
    """

def create_issue(repo, title, body, labels=None, token=None) -> dict:
    """Create a GitHub Issue via REST API.
    
    Returns: {"issue_url": "...", "issue_number": N}
    """

def build_pr_body(detection_name, eval_before, eval_after, 
                   cluster_results, injection_results) -> str:
    """Structured PR body with eval numbers + decision trail.
    
    Sections:
    - Detection: name + current FP rate
    - Revision: SPL diff (the NOT filter added)
    - Eval: before/after precision/recall/fp_rate, label_confidence
    - Attack injection: which values tested, which survived
    - Cluster analysis: top hypotheses with explanatory power
    """

def build_issue_body(detection_name, diagnosis, cluster_results) -> str:
    """Structured Issue body for "don't tune" cases.
    
    Sections:
    - Detection: name + current FP rate
    - Diagnosis: field extraction gap details
    - Evidence: empty field %, affected sourcetype, event count
    - Recommendation: fix props.conf, not the detection
    - Cluster analysis: why no filterable pattern exists
    """
```

### GitHub token storage

Store in `storage/passwords` with realm `squelch_github`:

```python
def _fetch_github_token(service):
    """Same pattern as _fetch_gemini_secret()."""
    for cred in service.storage_passwords:
        if cred.realm == "squelch_github":
            return cred.clear_password
    raise RuntimeError("GitHub token not found in storage/passwords")
```

### What gets committed in a PR

For the demo, the PR doesn't need to contain a real file change — showing the SPL diff in the PR body is sufficient. But if we want a real commit:

**Option A (simple):** PR body contains the SPL diff as markdown. No actual file committed. PR is a "proposed change" artifact, not a mergeable code change. Simpler, but less impressive.

**Option B (real commit):** Create/update a file like `detections/DNS_TunnelExfil_Heuristic.spl` in the repo with the revised SPL. The PR diff shows the actual SPL change. More impressive, more engineering.

**Recommendation: Option A for Bundle 3, upgrade to Option B in Bundle 4 (decision trail sessions).** Bundle 3 has enough new surface area (3 detections, seeding overhaul, diagnosis logic, Git integration). Keep PRs as structured documentation artifacts. Bundle 4 adds the real commit + diff.

### Repo target

The Squelch repo at `github.com/markbrazinski/Squelch`. PRs and Issues land here. The GitHub token needs `repo` scope.

---

## Session Plan

### Sessions 19–20: Seeding Overhaul + Detection 2 Data

**Goal:** Per-detection FP patterns in `seed_notable.py`. Identity_PrivEscalation gets service account pattern. Endpoint_NewServiceInstalled gets extraction gap pattern. Re-seed. Verify all three demo detections have the right FP shapes.

**Deliverables:**
1. Refactor `_gen_event` to use `DETECTION_FP_PATTERNS` config dict
2. Implement three pattern generators: `scanner_ip` (existing), `service_account` (new), `extraction_gap` (new)
3. Create `lookups/service_accounts.csv` + mirror to app
4. Re-seed 1000 events with `--clear-first`
5. Verify in Splunk:
   - DNS: scanner IPs in FPs, FP rate ~0.71
   - Identity: `svc_backup` in FPs, FP rate ~0.72, no scanner IPs
   - Endpoint: empty `dest_ip` in ~45% of FPs, FP rate ~0.72, no dominant cluster
6. Run existing pipeline on DNS — should still produce the Bundle 2 result (regression check)
7. Regenerate `baseline_evals.csv`

**Session exit gate:** Three detections have distinct FP patterns visible in Splunk. DNS pipeline still works. Baselines updated.

### Sessions 21–22: Detection 2 Pipeline (Service Account)

**Goal:** `| squelch mode="tune" search_name="Identity_PrivEscalation_Confirmed"` produces an accepted user-field filter.

**Deliverables:**
1. Extend `cluster_fps` field-lookup cross-reference to support `service_accounts.csv` on the `user` field
2. Verify clustering finds `user=svc_backup` as the dominant cluster (~65%)
3. Verify `propose_revision()` generates `NOT user IN ("svc_backup")`
4. Implement single-value injection bypass in `run_adversarial_eval` (skip injection when filter has ≤1 value)
5. End-to-end: pipeline produces `decision=accepted`, precision lift, recall preserved
6. Vendor changes

**Session exit gate:** Detection 2 runs end-to-end with service account filter accepted.

### Sessions 23–24: Detection 3 — "Don't Tune" Logic

**Goal:** `| squelch mode="tune" search_name="Endpoint_NewServiceInstalled"` produces a decline-to-tune diagnosis with field extraction gap evidence.

**Deliverables:**
1. `diagnose_fp_pattern()` function in `eval/cluster.py` — field coverage analysis, sourcetype correlation
2. Wire into `_tune()`: when `_pick_top_cluster` returns None, call `diagnose_fp_pattern()` before giving up
3. If diagnosis found: yield a result row with `decision="declined"`, `diagnosis="field_extraction_gap"`, evidence fields
4. If no diagnosis: yield `decision="error"`, `step="no_safe_cluster"` (existing behavior)
5. KV write with diagnosis JSON
6. Vendor changes
7. End-to-end: Endpoint detection produces the decline-to-tune output with evidence

**Session exit gate:** Detection 3 correctly declines to tune and reports the field extraction gap with evidence.

### Sessions 25–26: Git Integration + Three-Detection Orchestration

**Goal:** GitHub PRs and Issues created from pipeline output. All three detections runnable in sequence.

**Deliverables:**
1. `eval/github_integration.py` — `create_pr()`, `create_issue()`, `build_pr_body()`, `build_issue_body()`
2. GitHub token in `storage/passwords` (realm `squelch_github`)
3. Wire into `_tune()`:
   - On `decision=accepted`: call `create_pr()` with structured body
   - On `decision=declined` with diagnosis: call `create_issue()` with evidence
4. PR/Issue URLs in the output row + KV payload
5. Vendor `github_integration.py` to `squelch_eval/`
6. Multi-detection mode: `| squelch mode="tune" search_name="DNS_TunnelExfil_Heuristic,Identity_PrivEscalation_Confirmed,Endpoint_NewServiceInstalled"` — comma-separated, processed sequentially, one output row per detection
7. Test: all three run in sequence, producing 2 PRs + 1 Issue on GitHub

**Session exit gate:** Three detections produce three GitHub artifacts (2 PRs + 1 Issue). Multi-detection invocation works.

### Sessions 27–28: Integration + Safety-Net Video

**Goal:** Full demo dry run. Capture numbers. Record safety-net video (8-9/10 submission quality).

**Deliverables:**
1. Full pipeline run: all three detections in one invocation
2. Capture all demo metrics per detection in `tune_results_bundle_3.csv`
3. Demo-fit checklist:
   - [ ] Detection 1: IP filter, 3→2 CIDRs, PR created
   - [ ] Detection 2: service account filter, cross-reference annotation, PR created
   - [ ] Detection 3: decline-to-tune, field extraction gap, Issue created
   - [ ] Three GitHub artifacts visible (2 PRs + 1 Issue)
   - [ ] Multi-detection invocation works in one command
4. Demo-fit gaps logged in `bundle-3-spec.md`
5. Safety-net video #3 recorded (2-minute screen recording of all three detections)
6. Bundle close retro

**Session exit gate:** All three detections run cleanly. Video recorded. This is a shippable submission.

---

## Key File Changes Summary

| File | Sessions | Change |
|---|---|---|
| `scripts/seed_notable.py` | 19–20 | Per-detection FP pattern config, 3 pattern generators |
| `lookups/service_accounts.csv` | 19–20 | New — svc_backup mapping |
| `eval/cluster.py` | 19–20, 21–22, 23–24 | Multi-lookup cross-reference, `diagnose_fp_pattern()` |
| `eval/attack_inject.py` | 21–22 | Single-value injection bypass |
| `eval/github_integration.py` | 25–26 | New — PR/Issue creation via GitHub API |
| `squelch_command.py` | 21–22, 23–24, 25–26 | Detection 2 path, decline-to-tune path, Git integration, multi-detection mode |
| App vendored copies | All | Mirror every eval/ change |
| `eval/results/baseline_evals.csv` | 19–20 | Regenerated with new seeding |
| `eval/results/tune_results_bundle_3.csv` | 27–28 | New — per-detection honest numbers |
| `docs/bundle-3-spec.md` | All | Session status blocks |

---

## Risk Mitigations

| Risk | Trigger | Response |
|---|---|---|
| Per-detection seeding breaks existing pipeline | DNS numbers drift after seeding overhaul | Regression check in Sessions 19-20: DNS must still produce the Bundle 2 result. If not, the seeding config for DNS is wrong. |
| LLM generates time-window SPL for Detection 2 | Gemini includes `date_hour` despite prompt saying user-only | The prompt template at `revise.py` already constrains to `NOT field IN (...)` format. If the LLM generates anything else, the structural validator rejects it. Keep the constraint. |
| Detection 3 diagnosis logic is fragile | Empty `dest_ip` isn't reliably detectable | Seeding controls this — if 45% of FPs have `dest_ip=""`, the diagnosis function WILL find it. The risk is in the threshold tuning (30% vs 40% vs 50%). Start at 30%, adjust if too noisy. |
| GitHub API calls add latency | Token auth + network round-trip | ~200-500ms per API call. Acceptable for a demo. Not on the critical path (runs after gate decision). |
| GitHub rate limiting | 60 req/hour unauthenticated, 5000 authenticated | With a PAT, 5000/hour is more than enough. |
| Multi-detection mode adds complexity to squelch_command.py | Sequential processing, error handling per detection | Keep it simple: split on comma, loop, yield one row per detection. If one detection errors, log the error row and continue to the next. Don't abort the batch. |
| Safety-net video takes more than 1 session | Recording + editing overhead | Use the audio-spine method: script narration first, then screen record with VO in headphones. Each beat is independent — reshoot one without reshooting all. |
| `load_lookup` circular import gets worse with service_accounts.csv | Third lookup added | If this session pair adds a third cross-module reference, promote `load_lookup` to `eval/utils.py` (flagged since Sessions 13-14). |

---

## Out of Scope (deferred)

- Multi-hypothesis display in agent output (Bundle 4)
- Decision trails in PR body (Bundle 4 — Bundle 3 PRs have eval numbers but not full hypothesis rankings)
- Label perturbation (Bundle 4)
- Standalone `| squelch mode="eval"` (Bundle 4)
- Temporal holdout (Bundle 5, CUT IF BEHIND)
- Real file commits in PRs (Bundle 4 — Bundle 3 PRs are documentation artifacts)
- Scheduled trigger actually firing (deferred since Bundle 1)

---

## What Comes After Bundle 3

| Bundle | Sessions | What It Adds |
|---|---|---|
| Bundle 4: Decision Intelligence | 29–37 | Multi-hypothesis display, decision trails in PRs, label perturbation, standalone eval |
| Bundle 5: Temporal Holdout | 38–42 | CUT IF BEHIND — temporal split in eval |
| Phase 9: Polish + Ship | 43–50 | Architecture diagram, recording, Devpost, README, submit |

With Bundle 3 complete at session 28, the submission is an 8-9/10. Bundle 4 pushes to 9/10. Bundle 5 is 10/10 polish. Phase 9 is shipping.

---

## Sessions Status Blocks

Per-session-pair status, populated as each pair closes. Scannable; one line each.

- **Sessions 19–20** ✅ Complete. Per-detection FP patterns in `seed_notable.py`. `service_accounts.csv` lookup. `mirror_lookups.sh` automation. DNS regression preserved. Baselines regenerated; Bundle 2 baseline preserved as `baseline_evals_bundle_2.csv`.
- **Sessions 21–22** ✅ Complete. `load_lookup` promoted to `eval/utils.py` (Bundle 2 [[load_lookup_placement]] follow-through). `cluster_fps` now takes `field_lookups: dict[str, Path]` (multi-lookup). Single-value bypass in `run_adversarial_eval`. Identity tunes accepted with svc_backup filter (was no_safe_revision pre-bypass).
- **Sessions 23–24** ✅ Complete. `MIN_TOP_ENTRY_FP_PCT = 0.20` floor in `_pick_top_cluster` (tuned 0.30 → 0.20 mid-execution because DNS scanners measured at 0.273). `diagnose_fp_pattern()` field-coverage analysis. Decline-to-tune branch in `_tune()` produces `field_extraction_gap` evidence for Endpoint.
- **Sessions 25–26** ✅ Complete. `eval/github_integration.py` (PR + Issue creation, body builders). `_fetch_github_token` mirrors Gemini pattern. `_tune()` → `_tune()` + `_tune_one()` refactor with per-target try/except (multi-detection mode). KV row patched with `pr_url`/`issue_url`/`github_error` after GitHub call. Known constraint: same-branch 422 on subsequent accepted detections in a multi-detection invocation (Bundle 4 fixes).
- **Sessions 27–28** ✅ Complete. 4 retroactive commits land on `main` (one per session pair). `scripts/capture_tune_results.py` reusable KV→CSV. `eval/results/tune_results_bundle_3.csv` captured (8 detections, all artifacts populated). Demo-fit Gap Log below. `docs/bundle-3-recording-recipe.md` written. Bundle 3 shippable; video recording is a separate human-driven session.

---

## Sessions 27–28 Dry Run — Actual Numbers

Captured 2026-05-23 via `./scripts/capture_tune_results.py` after a sequential 8-detection dry run with PR-close between accepts. All 8 detections produced fresh KV rows and GitHub artifacts; zero `github_error`.

| Detection | Decision | FP rate | Precision | Recall | Artifact |
|---|---|---|---|---|---|
| `Identity_PrivEscalation_Confirmed` | accepted | 0.802 → 0.583 | 0.198 → 0.417 | 0.0588 → 0.0588 | PR #15 |
| `DNS_TunnelExfil_Heuristic` | accepted | 0.710 → 0.526 | 0.290 → 0.474 | 0.0794 → 0.0794 | PR #11 |
| `Endpoint_NewServiceInstalled` | **declined** | 0.705 → — | 0.295 → — | 0.0912 → — | Issue #14 (field_extraction_gap) |
| `WindowsAuth_AnomalousLogonSource` | accepted | 0.874 → 0.769 | 0.126 → 0.231 | 0.0353 → 0.0353 | PR #9 |
| `Network_PortScan_Detected` | accepted | 0.777 → 0.410 | 0.223 → 0.590 | 0.0676 → 0.0676 | PR #10 |
| `Web_SuspiciousUserAgent` | accepted | 0.380 → 0.197 | 0.620 → 0.803 | 0.1676 → 0.1676 | PR #12 |
| `Process_RareParentChild` | accepted | 0.233 → 0.127 | 0.767 → 0.873 | 0.2029 → 0.2029 | PR #13 |
| `Data_BulkDownload_Sensitive` | accepted | 0.019 → 0.010 | 0.981 → 0.990 | 0.2971 → 0.2971 | PR #16 |

Every accepted tune preserves recall exactly. Largest precision lifts: PortScan **2.6×** (0.22 → 0.59), Identity **2.1×** (0.20 → 0.42), DNS **1.6×** (0.29 → 0.47). Endpoint's declined Issue carries full diagnosis evidence (46% empty `dest_ip`, 100% correlated with `sourcetype_tag=svc_install_log`).

---

## Demo-fit Gap Log (Sessions 27–28)

`docs/demo-script.md` was written before Bundle 3's detection reassignment (spec line 19–23) and before Bundle 4 scope was carved out. This log captures the drift between what the script promises and what the Bundle 3 pipeline actually delivers, so the recording session knows what to adjust.

### Critical (script must change OR demo can't be recorded as written)

| # | Beat | Script | Pipeline reality | Resolution |
|---|---|---|---|---|
| **D1** | 1 (Payoff) | `WindowsAuth` "precision 14 → 87, 340 → 19 notables" | `WindowsAuth` precision **0.126 → 0.231**, 95 fired → 26 fired. The 14→87 number was aspirational, never matched a real run. | Pivot to a real number. Options: **PortScan (0.22 → 0.59, 2.6× lift)** is the strongest; **Identity (0.20 → 0.42, 2.1×)** is dramatic and Beat 1's "your analysts stopped reading them" still lands at 80% FP rate; **DNS (0.29 → 0.47)** moderate but is also Beat 3's subject. **Recommended:** lead with PortScan or Identity — both pair the "FP rate above 70%" framing with a real precision lift in the demo arc. |
| **D2** | 3 (Det 1) | `WindowsAuth_AnomalousLogonSource` (3 scanner CIDRs, 2 after narrowing) | `DNS_TunnelExfil_Heuristic` is the Bundle 3 demo's Detection 1. Its 3-scanner-IP-narrowing-to-2 narrative matches the spec exactly. | Update script to name `DNS_TunnelExfil_Heuristic`. Numbers match the 3→2 narrowing; only the detection name needs swapping. |
| **D5** | 5 (Det 3, climax) | `DNS_TunnelExfil_Heuristic` + `sourcetype=dns_proxy_v2` + 45% empty `dest_ip` | `Endpoint_NewServiceInstalled` + `sourcetype_tag=svc_install_log` + **46% empty `dest_ip`** (matches percentage almost exactly) | Update script: detection name + sourcetype tag wrong, percentages right. The climax line "the data feeding it is broken" still lands; rephrase to "every empty `dest_ip` traces back to one sourcetype — `svc_install_log`." |

### High (Bundle 4 scope promised in script)

| # | Beat | Script promises | Bundle 3 actually has | Resolution |
|---|---|---|---|---|
| **D3** | 3, 4, 5 | Multi-hypothesis display per detection (`cluster: X% ✓`/`cluster: Y% ✗`) | Single winner from `_pick_top_cluster`; rejected hypotheses not surfaced in the prompt or PR | Cut the `cluster: X% ✗` mock displays. Bundle 3 narration can claim "the agent picks the strongest hypothesis above a 20% explanatory-power floor" without listing rejected ones. Multi-hypothesis is on the Bundle 4 roadmap (spec line 382). |
| **D6** | 3, 4 | "label perturbation PASS" | No label-perturbation step in pipeline | Drop the phrase entirely. Bundle 3 has label *normalization* (different feature) and attack injection (different feature) — both real and worth narrating; perturbation is Bundle 4 (spec line 384). |
| **D7** | 6 (PRs) | "Decision trail: 3 hypotheses evaluated, 2 revision candidates considered, conservative selected (attack injection caught aggressive candidate)" in PR body | Single top hypothesis, single revision, attack-injection record. PR body has: SPL diff, eval table, attack-injection list, single cluster annotation | Update narration to describe what the PR body actually shows: "SPL diff, before/after metrics, the attack-injection record, the cluster annotation." Full decision trail is Bundle 4 (spec line 383). |

### Medium (cosmetic or operational)

| # | Beat | Note | Resolution |
|---|---|---|---|
| **D4** | 4 (Det 2) | Script: `PrivilegeEscalation_UnusualServiceAccess`. Actual: `Identity_PrivEscalation_Confirmed`. Numbers (65% `svc_backup`) match exactly. | Update name in script. Behavioral narrative is identical. |
| **D8** | All | Multi-detection invocation hits 422 on subsequent accepted detections (shared `squelch/proposals` head). | Two recording paths: **(recommended)** swap detection order to Identity → DNS → Endpoint — Identity first, no prior PR conflict; close Identity PR in the jump cut between beats; Endpoint third (Issue, no conflict). This is also a stronger story arc (behavioral → IP → "don't tune"). **(alternative)** keep script order, close DNS PR via a separate browser tab between beats 3 and 4. Bundle 4's per-detection-branch upgrade eliminates the constraint. |

### Recording decision required

The biggest call is **D1 (the payoff)**. Three options, ranked by dramatic strength:

1. **Lead with PortScan** — precision 0.22 → 0.59 (**2.6× lift**), the largest in the dry run. fp_rate 0.78 → 0.41 also strong. Numbers feel substantial without overpromising.
2. **Lead with Identity** — precision 0.20 → 0.42 (**2.1× lift**), pairs naturally with the "your analysts stopped reading them" line at 80% FP rate. Has the bonus that the cross-reference-lookup beat (Beat 4) gets to call back to "you saw it in Beat 1."
3. **Cherry-pick across detections** — "Two PRs that lift precision by 60% on average, one Issue that catches a data-quality bug." Composite but harder to verify on a single search-results screenshot.

**Default suggestion: Option 1 (lead with PortScan).** Largest verifiable lift; the dry run's strongest single number. DNS becomes Beat 3 (the warm-up) and the arc preserves its escalation shape (IP scanner cluster → behavioral cluster → decline-to-tune).

---

## Sessions 27–28 Recording Recipe Pointer

The video production setup (window layout, browser tabs, beat recording order, post-record sanity) lives in `docs/bundle-3-recording-recipe.md`. The narration script (`docs/demo-script.md`) is the source for what the narrator says; the recipe handles the mechanics; this gap log handles what's stale.