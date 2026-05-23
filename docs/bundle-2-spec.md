# Bundle 2: Data Honesty + Attack Injection — Full Build Spec

## Purpose

This document is the single source of truth for Bundle 2. It takes the working engine from Bundle 1 (clean data, cooperative eval) and makes it honest: messy labels, label normalization, and adversarial eval via attack injection. After this bundle, Detection 1 runs on data that looks like a real SOC's notable index.

**Predecessor:** Bundle 1 complete. `| squelch mode="tune"` runs end-to-end on Detection 1, 2.7s wall time, recall-drop gate works, KV persistence works.

**Exit gate:** Detection 1 runs end-to-end with noisy labels (6 formats, ~30% unlabeled), label normalization, and attack injection. Numbers are honest (~87% precision, ~98% recall). A proposed filter that would catch an injected attack is automatically narrowed. Safety-net video #2 recorded.

---

## What Already Exists (Bundle 1 Output)

Do not rebuild any of this.

| Component | Location | What It Does |
|---|---|---|
| Full tune pipeline | `| squelch mode="tune" search_name="..."` | pull → cluster → propose → eval → gate → KV write, 2.7s |
| Eval harness | `eval/eval_lib.py` + vendored `squelch_eval/eval_lib.py` | `evaluate_detection()`, `gate_revision()`, `snapshot_baseline()` |
| FP clustering | `eval/cluster.py` + vendored | `pull_labeled_events()`, `cluster_fps()` with per-field grouped output |
| SPL revision | `eval/revise.py` + `eval/llm.py` + vendored | `propose_revision()`, `call_gemini()` |
| Scanner IP lookup | `lookups/scanner_ips.csv` + app mirror | 3 known scanner IPs with context annotations |
| KV persistence | `detection_lineage` collection | Append-only, JSON-stringified eval bundles |
| Rejection demo | `force_revision` option on `| squelch` | Bypass LLM, inject known-bad SPL |
| Seeding script | `scripts/seed_notable.py` | 1000 events, 8 detections × 125, `--clear-first` |
| Baseline evals | `eval/results/baseline_evals.csv` | Reference numbers for all 8 detections |

### Bundle 1 Key Numbers (Detection 1, clean data)

| Metric | Before Tune | After Tune |
|---|---|---|
| Precision | 0.168 | 0.512 |
| Recall | 0.0349 | 0.0349 (preserved) |
| FP rate | 0.832 | ~0.49 |
| Pipeline wall time | — | 2727ms |
| LLM latency | — | 1824ms |

---

## Architecture Constraints (unchanged from Bundle 1)

All direction-lock.md decisions carry forward. Key reminders for Bundle 2:

1. **Golden dataset = `host=squelch-seed` filter on `index=notable`.** No separate CSV. D3 locked this. The noisy labels go into the *same* index — the eval harness filters on `host=squelch-seed` to identify ground truth events.
2. **`_cd` is event identity.** Noisy labels change `status_label` values but `_cd` is still the join key for recall-drop detection.
3. **Recall-preservation gate is non-negotiable.** Even with label normalization, any revision that drops recall is rejected.
4. **Splunklib REST for writes, MCP for reads.** No changes to the read/write split.

---

## What Bundle 2 Adds

Three capabilities, layered in order:

1. **Noisy labels in the data** — the notable index looks like a real SOC (6 label formats, 30% unlabeled)
2. **Label normalization** — a lookup maps messy labels to canonical `true_positive`/`false_positive`, unlabeled events excluded
3. **Attack injection** — after the agent proposes a NOT filter, the eval harness injects synthetic TPs matching the filter pattern and re-evaluates

### Demo Script Alignment

The demo expects these specific outputs from Bundle 2:

| Demo Beat | What It Shows | Bundle 2 Responsibility |
|---|---|---|
| Beat 1 (0:00–0:15) | Messy `status_label` visible: "false_positive", "resolved", "FP - scanner", "fp", "closed", blanks | Sessions 11-12: noisy seeding |
| Beat 1 | "340 → 19, precision 14% → 87%" | Sessions 17-18: honest numbers with messy data |
| Beat 2 (0:15–0:30) | `\| lookup disposition_normalization` in trigger SPL | Sessions 13-14: normalization lookup |
| Beat 2 | "Unlabeled events excluded, not guessed" | Sessions 13-14: exclusion logic |
| Beat 3 (0:30–0:50) | "NOT filter on **two** CIDRs — not three. Attack injection caught 10.0.1.51" | Sessions 15-16: attack injection |

---

## Session-by-Session Build Spec

### Sessions 11–12: Noisy Label Seeding

**Goal:** The notable index contains events with 6 different label formats and ~30% unlabeled, visually matching what a real SOC produces.

#### The 6 Label Formats

| Label Value | Canonical Meaning | Distribution Target |
|---|---|---|
| `true_positive` | TP | ~35% of labeled events |
| `false_positive` | FP | ~20% of labeled events |
| `resolved` | FP (analyst shorthand) | ~8% |
| `closed` | FP (ticket workflow label) | ~7% |
| `fp` | FP (lazy analyst) | ~5% |
| `FP - scanner` | FP (specific annotation) | ~5% |
| `` (blank/empty) | Unknown — excluded from eval | ~30% of all events |

Total: ~55% usable after normalization, ~15% non-standard-but-mappable FP labels, ~30% unlabeled.

#### Deliverables

1. **Update `scripts/seed_notable.py`**
   - Replace the current clean `status_label` assignment with a weighted random draw from the 6 formats above
   - TPs get `true_positive` (no variant — analysts don't mislabel TPs in creative ways, they just sometimes don't label them at all)
   - FPs get randomly assigned: `false_positive` (40%), `resolved` (16%), `closed` (14%), `fp` (10%), `FP - scanner` (10%), blank (10%)
   - An additional ~20% of ALL events (TP and FP) get blank labels — these are the "analyst never looked at it" cases
   - The scanner IPs (`10.0.1.50/51/52`) should still be exclusively in FP events — don't put scanner IPs on TPs. The pattern must survive label noise.
   - Preserve `host=squelch-seed` on all events — this is the golden dataset filter

2. **Re-seed with `--clear-first`**
   - `python scripts/seed_notable.py --count 1000 --clear-first`
   - Wait for searchable
   - Verify: `index=notable sourcetype=squelch_notable | stats count by status_label` shows all 6 formats plus blanks
   - Verify: the 3 trigger-band detections still have high FP rates when counting only `status_label="false_positive"` events (they will — but the *effective* FP rate changes because many FPs are now labeled differently)

3. **Update `eval/results/baseline_evals.csv`**
   - Re-run `python eval/run_eval.py --all`
   - Numbers WILL change because the eval harness currently filters on `status_label` = exact match
   - Save new baselines — these are the "before normalization" numbers
   - The eval harness will initially break or produce weird numbers — that's expected, Sessions 13-14 fix it

4. **Visual verification**
   - Run `index=notable sourcetype=squelch_notable search_name="WindowsAuth_AnomalousLogonSource" | table status_label src_ip dest user` in Splunk
   - Screenshot: the `status_label` column should show the messy mix the demo Beat 1 expects
   - This is what the judge sees first

#### Session Exit Gate
`index=notable | stats count by status_label` shows 6+ distinct values plus blanks. Scanner IPs are exclusively in FP-labeled events (under any label format). Events are visually messy.

#### Status: COMPLETE (2026-05-23)

- `_pick_status_label(is_fp)` added in [scripts/seed_notable.py](../scripts/seed_notable.py); `_gen_event` calls it on each event. `--clear-first` now fails loudly if the runner lacks `can_delete` (a prior silent-fail had stacked Bundle 1 + Bundle 2 cohorts on one re-seed).
- Re-seeded 1000 events: 48.3% `true_positive`, 14.0% `false_positive`, 5.1% `resolved`, 4.9% `closed`, 3.4% `fp`, 2.6% `FP - scanner`, **21.7% blank** (target was 20–30%).
- Scanner IPs `10.0.1.50/51/52` cover 301 events; **0** are labeled `true_positive`. They span `false_positive`, `resolved`, `closed`, `fp`, `FP - scanner`, and blanks — the pattern is intact but the label is diluted, exactly the entry condition Sessions 13–14 need.
- Bundle 1 baseline snapshot preserved at `eval/results/baseline_evals_pre_bundle2.csv`. New transitional baselines at `eval/results/baseline_evals.csv` show the expected harness regression: WindowsAuth fp_rate 0.83 → 0.70 (literal-label counting only), recall ≈ unchanged. To be replaced by post-normalization baselines in Sessions 13–14.

---

### Sessions 13–14: Label Normalization

**Goal:** A lookup maps 6 label formats to 2 canonical values. The eval harness, clustering, and trigger SPL all normalize before computing metrics. Unlabeled events are excluded, not guessed.

#### Deliverables

1. **Create `lookups/disposition_normalization.csv`**
   ```
   status_label,normalized_label
   true_positive,true_positive
   false_positive,false_positive
   resolved,false_positive
   closed,false_positive
   fp,false_positive
   FP - scanner,false_positive
   ```
   - Mirror to `/Applications/Splunk/etc/apps/squelch/lookups/disposition_normalization.csv`
   - Add `[disposition_normalization]` stanza to transforms.conf: `filename = disposition_normalization.csv`

2. **Update eval harness (`eval/eval_lib.py`)**
   - In `evaluate_detection()`: after pulling events, normalize `status_label` via the lookup CSV
   - Load the normalization map once (same pattern as `cluster.py`'s `load_lookup()`)
   - Events where `status_label` is blank or not in the normalization map → **exclude** from TP/FP counts entirely
   - This means precision/recall are computed only against labeled, normalized events
   - Add a new metric to `EvalResult`: `label_confidence` = `labeled_events / total_events` — the fraction of events that had usable labels
   - Re-vendor after changes

3. **Update clustering (`eval/cluster.py`)**
   - In `pull_labeled_events()`: normalize labels before returning
   - Or: `cluster_fps()` accepts a `normalization_map` parameter and normalizes internally
   - Either way: clustering only counts events with normalized labels, excludes blanks
   - The scanner IP cluster should still emerge at ~78% of FPs — the pattern is in the data, not the labels

4. **Update trigger SPL concept**
   - The trigger saved search should normalize before computing FP rate:
     ```
     index=notable sourcetype=squelch_notable
     | lookup disposition_normalization status_label OUTPUT normalized_label
     | where isnotnull(normalized_label)
     | stats count(eval(normalized_label="false_positive")) as fp, count as total by search_name
     | eval fp_rate=fp/total
     | where fp_rate >= 0.70
     ```
   - Bundle 1 deferred the scheduled trigger — but the SPL pattern needs to exist for the demo. Create a saved search stanza in `savedsearches.conf` with `disabled=1` (reviewable but not firing). Or just document the SPL — the demo shows it in the search bar.

5. **Re-run baselines**
   - `python eval/run_eval.py --all` with normalization active
   - Numbers should be close to the original clean-data numbers (because normalization recovers the FP labels)
   - But not identical — some events are now excluded (unlabeled), so counts shift
   - `label_confidence` should be ~0.70 (70% of events have usable labels)
   - Save updated `baseline_evals.csv`

6. **Verify pipeline still works**
   - `| squelch mode="tune" search_name="WindowsAuth_AnomalousLogonSource"`
   - Should still produce `decision=accepted` with precision improvement and recall preserved
   - Numbers will differ from Bundle 1 — that's correct and expected

#### Session Exit Gate
Eval harness produces correct precision/recall on noisy-labeled data after normalization. `label_confidence` metric is present. Clustering finds the same scanner IP pattern. Pipeline runs end-to-end with noisy data.

#### Status: COMPLETE (2026-05-23)

- `lookups/disposition_normalization.csv` created and mirrored to the app; `[disposition_normalization]` stanza added to `transforms.conf`; `| inputlookup disposition_normalization` returns all 6 rows.
- `evaluate_detection` and `cluster_fps` both gained an optional `normalization_csv` parameter. `EvalResult` carries a new `label_confidence: float` field (default 1.0). Backcompat preserved: `mode="validate"` and other callers that pass no normalization see Bundle 1 behavior with `label_confidence` computed against the exact-match definition.
- `load_lookup()` reuse: deferred import from `eval_lib → cluster` via try/except mirrors the dual-mode pattern already in `cluster.py`. Flagged in [load_lookup_placement memory](file:///Users/markbrazinski/.claude/projects/-Users-markbrazinski-Desktop-coding-fun-Squelch/memory/load_lookup_placement.md) — promote to `eval/utils.py` only if Bundle 3 adds a second cross-module helper.
- `run_eval.py` learned a `--normalization-csv` flag (defaults to `lookups/disposition_normalization.csv`); `CSV_FIELDS` includes `label_confidence`.
- Disabled `[squelch_trigger_high_fp_rate]` saved search added with the lookup-based trigger SPL — visible in the saved-searches UI for demo Beat 2.
- Vendored copies refreshed in `/Applications/Splunk/etc/apps/squelch/bin/lib/squelch_eval/`.
- **Normalized baselines** at `eval/results/baseline_evals.csv`:
  | detection | precision | recall | fp_rate | label_confidence |
  |---|---|---|---|---|
  | WindowsAuth_AnomalousLogonSource | 0.181 | 0.035 | 0.819 | 0.783 |
  | Network_PortScan_Detected | 0.255 | 0.052 | 0.745 | 0.783 |
  | DNS_TunnelExfil_Heuristic | 0.274 | 0.054 | 0.726 | 0.783 |
  | Web_SuspiciousUserAgent | 0.663 | 0.135 | 0.337 | 0.783 |
  | Process_RareParentChild | 0.745 | 0.157 | 0.255 | 0.783 |
  | Endpoint_NewServiceInstalled | 0.813 | 0.153 | 0.187 | 0.783 |
  | Identity_PrivEscalation_Confirmed | 1.000 | 0.213 | 0.000 | 0.783 |
  | Data_BulkDownload_Sensitive | 0.951 | 0.201 | 0.049 | 0.783 |

  Sessions 11–12 transitional snapshot preserved at `eval/results/baseline_evals_sessions_11_12.csv`. Bundle 1 clean-label snapshot at `baseline_evals_pre_bundle2.csv`.
- **End-to-end smoke (`| squelch mode="tune" search_name="WindowsAuth_AnomalousLogonSource"`)**:
  - decision=accepted, recall preserved (0.0352 → 0.0352, 0 events lost)
  - precision 0.181 → 0.531
  - fp_rate 0.819 → 0.469
  - label_confidence = 0.783 (78% of events had usable labels; 22% blanks excluded — matches the 21.7% blank rate seeded in Sessions 11-12)
  - LLM 1 attempt, 2225ms; total pipeline 3022ms (under 5s budget)

---

### Sessions 15–16: Attack Injection

**Goal:** After the agent proposes a NOT filter, the eval harness generates synthetic TP events that match the filter pattern (simulating attacks from the filtered IPs), injects them into the eval run, and re-evaluates. If the injected TPs get caught by the filter, the revision is narrowed.

This is the **adversarial eval** — the harness actively tries to break the proposed revision.

#### The Attack Injection Narrative

The demo script (Beat 3) tells this story:
- Agent proposes NOT filter on 3 scanner IPs
- Eval harness injects a synthetic TP event from `10.0.1.51` (simulating a compromised scanner)
- The filter would have dropped that TP → recall drops
- The recall gate catches it
- **The agent narrows the filter to 2 IPs**, excluding `10.0.1.51`
- Final filter: `NOT src_ip IN ("10.0.1.50","10.0.1.52")` — two CIDRs, not three

This means attack injection isn't just a check — it feeds back into revision generation.

#### Deliverables

1. **Attack injection function in `eval/eval_lib.py` (or new `eval/attack_inject.py`)**
   - Input: proposed revision SPL (specifically the NOT filter values), golden dataset events
   - For each value in the NOT filter: generate N synthetic TP events (N=1 is enough for the demo) with that field value
   - Example: if filter is `NOT src_ip IN ("10.0.1.50","10.0.1.51","10.0.1.52")`, generate 3 synthetic TPs — one from each IP
   - Synthetic events get `status_label=true_positive`, realistic field values for other fields, and are added to the eval dataset (in-memory, not persisted to index)
   - Re-run eval with the injected events included
   - If recall drops (injected TPs are filtered) → identify WHICH filter values caught TPs

2. **Filter narrowing logic**
   - If attack injection catches a value: remove that value from the NOT filter
   - Re-propose: `NOT src_ip IN ("10.0.1.50","10.0.1.52")` (dropped `10.0.1.51`)
   - Re-run eval against the narrowed filter (WITH the injected events still present)
   - If the narrowed filter passes → that's the final revision
   - If it still fails → narrow further, or reject entirely if no safe filter remains

3. **Integration point**
   - Attack injection runs AFTER `propose_revision()` returns and BEFORE the final `gate_revision()` call
   - Pipeline flow becomes: propose → inject attacks → eval with injections → narrow if needed → re-eval → gate → KV write
   - The KV row should record: `attack_injection_results` in the eval_after JSON (which IPs were tested, which were excluded)

4. **Seeding support**
   - For the demo to show `10.0.1.51` specifically getting caught: seed one real TP event from `10.0.1.51` into the notable index
   - OR: attack injection creates synthetic events that don't exist in the index but are added to the eval dataset in-memory
   - The second approach is cleaner — no index mutation, injection is purely an eval-time concept
   - **Decision for CC:** whether to inject into the index (persistent, visible in Splunk) or into the eval dataset (in-memory, invisible). The demo shows the *result* of injection in the agent output, not the injected events themselves. In-memory is likely cleaner.

5. **Self-test**
   - Run pipeline on Detection 1 with attack injection enabled
   - Expect: agent initially proposes 3 IPs → injection catches `10.0.1.51` (or whichever IP the injection generates a TP for) → filter narrows to 2 IPs
   - Final precision should be slightly lower than Bundle 1 (fewer IPs filtered = more FPs remain)
   - Recall should be preserved or improved (injected TPs are not filtered)

#### Session Exit Gate
Attack injection generates synthetic TPs matching the proposed filter. At least one filter value is caught and excluded. The final revision contains fewer IPs than initially proposed. The narrowing is automatic, not manual.

#### Status: COMPLETE (2026-05-23)

- New `eval/attack_inject.py` module with `parse_not_filter`, `inject_attack`, `narrow_filter`, `_pick_template_event`, `run_adversarial_eval`. Vendored to `squelch_eval/`; exports added to `__init__.py`.
- `evaluate_detection` gained an `injected_events: list[dict] | None = None` param plus a `_injected_would_fire` helper (deferred-import of `parse_not_filter` to avoid module-level loop). When injected events are supplied, they union into `golden_tp_ids`; their `fired_ids` membership is decided in Python via the structural NOT-filter check — no extra Splunk query for the synthetic set.
- Adversarial loop: one synthetic TP per iteration, picking a random filter value, deterministic per `(detection_name, revised_spl)` via SHA-256 seeding (NOT Python's `hash()`, which is process-randomized and would shift across Splunk restarts).
- `run_adversarial_eval` returns `status="ok"` even when hitting `max_iterations`, as long as at least one filter value survives — a final clean eval runs on the narrowed SPL so the metrics are honest. Only the truly empty-filter case returns `no_safe_revision`.
- `squelch_command.py::_tune` wired in: after `propose_revision` succeeds, the adversarial loop runs before `gate_revision`. KV `eval_after` is now a structured JSON object with `metrics`, `attack_injection_results`, `iterations`, `initial_values`, `final_values`. Output row gains `initial_filter_values`, `final_filter_values`, `attack_injection_excluded`, `injection_iterations`, and `revised_spl` reflects the post-narrowing SPL.
- **End-to-end smoke (`| squelch mode="tune" search_name="WindowsAuth_AnomalousLogonSource"`)**:
  - decision=accepted, recall preserved (0.0352 → 0.0352, 0 events lost)
  - initial_filter_values: `10.0.1.52,10.0.1.50,10.0.1.51,192.168.75.117` (4 values, LLM's first proposal)
  - final_filter_values: `10.0.1.50` (1 survivor — three IPs each caught a synthetic attack)
  - attack_injection_excluded: 3
  - injection_iterations: 3
  - precision 0.181 → 0.230 (modest lift because only one IP survived adversarial review)
  - fp_rate 0.819 → 0.770
  - total runtime 4014ms (under 5s budget)
- **Determinism**: two back-to-back runs of `| squelch mode="tune"` produced identical `initial_filter_values`, `final_filter_values`, `attack_injection_excluded`, `injection_iterations` (verified via comparison harness).
- **Unit sanity** on `parse_not_filter`, `narrow_filter`, `_seeded_rng`, `inject_attack` all passed.

Note: the precision lift is smaller than Bundle 1's (0.181 → 0.531 without injection) because attack injection rejects the riskier scanner IPs. This is the *honest* outcome the bundle is supposed to surface. Sessions 17-18 will document this in the demo-fit gap log and decide whether to adjust seeding or the demo script narrative.

---

### Sessions 17–18: Integration + Honest Numbers

**Goal:** Run the full pipeline with noisy labels + normalization + attack injection active on Detection 1. Capture the honest numbers the demo will show. Verify everything works together.

#### Deliverables

1. **Full integration run**
   - `| squelch mode="tune" search_name="WindowsAuth_AnomalousLogonSource"`
   - With: noisy labels active, normalization active, attack injection active
   - Capture every metric the demo needs

2. **Expected demo numbers (targets, not exact)**
   - Precision before: ~14% (0.14) — lower than clean data because normalized label counts differ
   - Precision after: ~87% (0.87) — the demo script says this; if actual is different, update the demo script
   - Recall: held (the exact number depends on normalization — report it honestly)
   - Label confidence: ~70% (30% unlabeled)
   - Attack injection: 1 IP excluded from filter
   - Final filter: 2 CIDRs, not 3

3. **If numbers don't match demo script**
   - Adjust seeding distribution (more/fewer FPs from scanners, different label noise ratios)
   - The seeding script is the tuning knob — iterate on the distribution until the pipeline produces numbers close to the demo narrative
   - The demo script numbers can flex — "~87%" is a target, not a contract. Actual honest numbers are better than manufactured exact matches.

4. **Label confidence reporting**
   - Add `label_confidence` to the `| squelch mode="tune"` result row
   - This is the "honest numbers" commitment: report how much of the data had usable labels

5. **Pipeline timing**
   - Should still be under 15s (Bundle 1 was 2.7s; normalization adds ~50ms, attack injection adds one extra eval pass ~500ms)
   - If over 5s, profile and identify the bottleneck

6. **Demo-fit check**
   - Does the pipeline output match what each demo beat expects?
   - Is the `status_label` mess visible in the Splunk table? (Beat 1)
   - Does the trigger SPL show `| lookup disposition_normalization`? (Beat 2)
   - Does the agent output show the attack injection exclusion? (Beat 3)
   - Document any gaps for Bundle 3+

7. **Update baseline_evals.csv**
   - Final post-normalization, post-injection baselines for all 8 detections
   - These are the reference numbers going forward

#### Session Exit Gate
Detection 1 runs end-to-end with noisy labels, normalization, and attack injection. Numbers are captured and documented. Pipeline is under 5s. Demo-fit gaps are logged. `baseline_evals.csv` is updated.

---

## Key File Changes Summary

| File | Sessions | Change |
|---|---|---|
| `scripts/seed_notable.py` | 11-12 | Noisy label distribution |
| `lookups/disposition_normalization.csv` | 13-14 | New — label mapping lookup |
| `eval/eval_lib.py` | 13-14, 15-16 | Normalization in eval, label_confidence metric, attack injection |
| `eval/cluster.py` | 13-14 | Normalization in clustering |
| `eval/attack_inject.py` (or in eval_lib) | 15-16 | New — attack injection logic |
| `eval/revise.py` | 15-16 | Filter narrowing after injection |
| App vendored copies | All | Mirror every change |
| `squelch_command.py` | 15-16, 17-18 | Wire injection into `_tune`, add `label_confidence` to output |
| `transforms.conf` | 13-14 | Add `[disposition_normalization]` stanza |
| `savedsearches.conf` | 13-14 | Add disabled trigger with normalization SPL (optional) |
| `eval/results/baseline_evals.csv` | 11-12, 17-18 | Updated baselines |

---

## Risk Mitigations

| Risk | Trigger | Response |
|---|---|---|
| Noisy labels break the eval harness badly | Numbers are nonsensical after re-seed | Normalization is Sessions 13-14. Accept that Sessions 11-12 leave the harness temporarily broken — it's fixed in the next session pair. |
| Label normalization doesn't recover the FP pattern | Scanner IPs are diluted by label noise | The pattern is in `src_ip` values, not labels. Normalization recovers labels; clustering finds the same IPs. If it doesn't, the seeding distribution is wrong — adjust scanner IP concentration upward. |
| Attack injection is architecturally complex | In-memory injection interacts badly with eval harness | Keep injection simple: add synthetic events to the event list BEFORE passing to `evaluate_detection()`. It's list manipulation, not index mutation. |
| Filter narrowing creates an infinite loop | Narrowing removes all IPs, no filter remains | Cap narrowing iterations at 3. If no safe filter exists after 3 rounds, return `status: "no_safe_revision"` — the agent can't tune this detection safely. |
| Numbers don't match demo script | Precision is 72% instead of 87% | Adjust seeding distribution. The seeding script is the knob. Don't fake numbers — adjust the data so the pipeline produces honest numbers that tell the right story. |
| Sessions overrun | Any pair takes >2 sessions | Sessions 17-18 are integration + buffer. If 11-16 overrun by 1 session, compress integration to 1 session. |

---

## What This Bundle Does NOT Do (Intentional)

- **No Detection 2 or 3.** Bundle 3 scope.
- **No Git PR creation.** Bundle 3 scope.
- **No multi-hypothesis display in output.** Bundle 4 scope. Clustering already outputs per-field hypotheses — display is deferred.
- **No label perturbation.** Bundle 4 scope.
- **No temporal holdout.** Bundle 5 scope (CUT IF BEHIND).
- **No scheduled trigger.** Deferred per Bundle 1 decision. The SPL pattern exists for the demo but doesn't fire automatically.
- **No multi-detection orchestration.** Bundle 3 scope. Pipeline still runs one detection at a time via `search_name` parameter.

---

## What Comes After (Context Only — Do Not Build)

- **Bundle 3 (Sessions 19–28):** Detection 2 (service account, `svc_backup`), Detection 3 ("don't tune" — field extraction gap), three-detection orchestration, Git PR/Issue creation
- **Bundle 4 (Sessions 29–37):** Multi-hypothesis display, decision trails in PR body, label perturbation, standalone `| squelch mode="eval"` command
- **Bundle 5 (Sessions 38–42):** Temporal holdout (CUT IF BEHIND)
- **Phase 9 (Sessions 43–50):** Architecture diagram, recording, Devpost, README, submit