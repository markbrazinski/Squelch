# Bundle 1: The Engine — Full Build Spec

## Purpose

This document is the single source of truth for Bundle 1. It contains everything a build agent (Claude Code) needs to plan and execute all 10 sessions without returning for context. Read this first; read referenced project files for implementation detail.

---

## What This Bundle Delivers

A working tuning pipeline that runs end-to-end on one detection. Input: a noisy correlation search. Output: a proposed SPL revision with eval scores, or a rejection with explanation. This is the foundation — Bundles 2–5 layer on top of it.

**Exit gate:** `| squelch mode="tune"` runs against Detection 1, produces precision/recall/runtime, rejects a bad revision with explanation, and writes results to KV store. Safety-net video recorded.

---

## What Already Exists

These are proven and working. Do not rebuild them.

| Component | Location / Invocation | What It Does |
|---|---|---|
| `| squelch` custom command | `bin/squelch.py` (or similar in squelch app) | Modes: `test`, `tune` (stub), `llm_probe` (671ms Gemini), `validate` (eval metrics) |
| `| ai` command | Splunk AITK built-in | 5.5s Gemini 2.5 Flash via AITK |
| MCP BYOT tools | `Splunk_MCP_Server` KV `mcp_tools` | `squelch:tune_detection`, `squelch:fp_rates_by_search` |
| KV store: `detection_lineage` | `squelch` app, `collections.conf` | Empty. Schema loose (Phase 8 pins it). Lookup: `detection_lineage_lookup` |
| Scheduled trigger | Saved search | Fires when FP rate > 0.70 over 7d window |
| Synthetic events | `index=notable sourcetype=squelch_notable` | 1000 events, 8 detections × 125 each |
| Seeding script | `scripts/seed_notable.py` | `--count 1000 --clear-first`. ~2s ingest, 5–15s searchable |
| `run_eval.py` (Phase 4 S3) | `scripts/run_eval.py` | CLI that computes tp/fp/fn/precision/recall/fp_rate/runtime_ms |
| `mode="validate"` | `| squelch mode="validate" search_name="..."` | Returns same metrics as run_eval.py in one SPL row |
| LLM secrets | `storage/passwords` realm `aitk_llm_secrets` | Key: `gemini-default` |

**Critical: Phase 4 S3 already built a working eval harness.** Sessions 1–2 are about hardening it (golden dataset formalization, recall-drop rejection gate, baseline snapshots), not building from scratch.

---

## Architecture Constraints (from direction-lock.md)

These are non-negotiable. Do not deviate.

1. **Brain:** `| ai` (Gemini 2.5 Flash via AITK) primary. `| squelch mode="llm_probe"` (outbound HTTP, 671ms) fallback. Provider-agnostic architecture — code must not hardcode Gemini-specific logic.
2. **Read/Write split:** MCP for reads (BYOT tools). `splunklib` REST for writes. `| squelch` never routes through MCP (allowlist blocks it).
3. **Eval semantics:** Golden dataset required. `_cd` field is event identity. Recall-preservation gate is non-negotiable — any revision that drops recall is auto-rejected. Golden query is a parameter (not hardcoded).
4. **Notable schema:** `| squelch` owns `index=notable`. No ES dependency. Schema locked at 10 fields.
5. **Memory:** KV collection `detection_lineage`. Per-detection SPL revisions, FP rate trajectory, agent decision log.
6. **Secrets:** `storage/passwords` realm `aitk_llm_secrets`. Never hardcode API keys.

---

## Detection 1: WindowsAuth_AnomalousLogonSource

This is the only detection in Bundle 1 scope. Everything runs against this.

| Property | Value |
|---|---|
| `search_name` | `WindowsAuth_AnomalousLogonSource` |
| Events in index | 125 (of 1000 total across 8 detections) |
| Baseline FP rate | 0.83 |
| FP count / TP count | 104 FP / 21 TP |
| Baseline precision | 0.168 |
| Baseline recall | 0.0349 (relative to full event set) |
| Known FP pattern | 3 scanner IPs: `10.0.1.50`, `10.0.1.51`, `10.0.1.52` |
| Scanner IPs explain | 78% of FPs |
| Expected tuned SPL | `+ NOT src_ip IN ("10.0.1.50","10.0.1.51","10.0.1.52")` |
| Post-tune FPs | 104 → ~20 |
| Post-tune precision | 0.168 → ~0.512 |
| Post-tune recall | Preserved exactly (no TPs from scanner IPs) |

**Demo script expects (Beat 1):** "340 notables → 19 after tune. Precision 14% → 87%." These are Bundle 2+ numbers with messy labels. Bundle 1 uses clean data — expect different numbers. That's fine; Bundle 2 re-seeds with noisy labels and recalibrates.

---

## Session-by-Session Build Spec

### Sessions 1–2: Eval Harness Hardening

**Goal:** The eval harness is formalized, has a golden dataset schema, stores baselines, and auto-rejects recall-dropping revisions.

**What exists:** `run_eval.py` CLI and `| squelch mode="validate"` both compute metrics. Need to confirm: does golden dataset exist as a formal artifact, or is it just running against raw `index=notable`?

**First action:** Read `scripts/run_eval.py` and the `mode="validate"` code path in the custom command. Map what exists vs. what's needed below.

#### Deliverables

1. **Golden dataset schema**
   - Format: CSV or KV collection. Each row = one event.
   - Required fields: `_cd` (event identity), `search_name`, `status_label` (ground truth: `true_positive` or `false_positive`), plus the fields the detection uses (`src_ip`, `dest`, `user`, etc.)
   - Source: extract from current `index=notable` for Detection 1, with labels as seeded
   - Storage: `lookups/golden_dataset.csv` in squelch app, or a dedicated KV collection

2. **Baseline snapshot**
   - Run original Detection 1 SPL against golden dataset
   - Store result: `{search_name, spl_hash, precision, recall, fp_rate, runtime_ms, timestamp}`
   - Storage location: `detection_lineage` KV collection (first real write to it)
   - This baseline is the comparison target for all future revisions

3. **Recall-drop rejection gate**
   - Input: baseline recall + proposed revision recall
   - Logic: if `revised_recall < baseline_recall`, reject. Hard gate, not configurable threshold.
   - Output on rejection: `{status: "rejected", reason: "recall_drop", baseline_recall: X, revised_recall: Y, events_lost: [list of _cd values]}`
   - Output on acceptance: `{status: "accepted", precision_delta, recall_delta, fp_rate_delta}`

4. **Test: baseline numbers match expectations**
   - Run eval against Detection 1 with original SPL
   - Confirm: ~104 FP, ~21 TP, precision ~0.168, recall preserved
   - Run eval against Detection 1 with known-good tuned SPL (`+ NOT src_ip IN (...)`)
   - Confirm: FPs drop, precision rises, recall unchanged

#### Session Exit Gate
`run_eval.py --search_name WindowsAuth_AnomalousLogonSource --spl "<original>"` returns baseline metrics. Same command with tuned SPL returns improved metrics. A deliberately bad SPL (e.g., filtering a TP source IP) is rejected with explanation.

---

### Sessions 3–4: FP Clustering

**Goal:** Given a detection's notable events, identify which field-value patterns explain the most false positives.

#### Deliverables

1. **Notable event pull**
   - SPL: `index=notable sourcetype=squelch_notable search_name="WindowsAuth_AnomalousLogonSource" | fields _cd, src_ip, dest, user, status_label, search_name`
   - Filter to labeled events only (where `status_label` is not empty)
   - This is the input to clustering

2. **Clustering function**
   - Input: list of notable events with fields + labels
   - Configurable fields to cluster on (start with `src_ip` only; extend to `dest`, `user` after it works)
   - For each field, for each unique value:
     - Count FPs where field=value
     - Compute explanatory power: `fp_count_for_value / total_fp_count`
   - Rank by explanatory power descending
   - Output: ranked list of `{field, value, fp_count, fp_pct, tp_count, tp_pct}` — the tp_pct is critical for identifying values that would hurt recall if filtered

3. **Cross-reference against lookups**
   - If a top cluster value matches an asset/identity lookup (e.g., IP in a scanner list, user in a service account list), flag it
   - For Bundle 1: may need to seed a simple `scanner_ips.csv` lookup with the 3 known IPs to demonstrate this capability
   - Output annotation: `{..., lookup_match: "scanner_ips", lookup_context: "known vulnerability scanner"}`

4. **Forward-compatibility: output ALL hypotheses**
   - Bundle 4 needs multi-hypothesis display: `[HYPOTHESIS] src_ip cluster: 78% ✓ | [HYPOTHESIS] user+time: 11% ✗`
   - Design the clustering output to include all field clusters (not just top-1) with their explanatory power scores now
   - Data structure ships in Bundle 1; display ships in Bundle 4

#### Session Exit Gate
`cluster_fps(search_name="WindowsAuth_AnomalousLogonSource", fields=["src_ip"])` returns a ranked list where `10.0.1.50/51/52` are the top 3 entries explaining ~78% of FPs, with tp_pct showing 0% (safe to filter). Cross-reference flags them as known scanners. All field hypotheses are in the output.

---

### Sessions 5–6: SPL Revision Generation

**Goal:** Given original SPL + cluster results, use the LLM to propose a revised SPL with a targeted NOT filter.

#### Deliverables

1. **LLM prompt template**
   - Input context: original SPL, cluster results (top patterns with explanatory power), lookup cross-reference results
   - Instruction: propose a revised SPL that adds a NOT filter for the top cluster, preserving all other logic
   - Constraint in prompt: "Output ONLY the revised SPL. Do not explain. Do not add comments."
   - Constraint in prompt: "The filter must be a NOT clause appended to the existing search. Do not rewrite the original logic."

2. **Structured output parsing**
   - Extract SPL from LLM response (strip markdown fences, whitespace, explanatory text if the LLM ignores the constraint)
   - Validate: the revised SPL starts with the original SPL (the LLM didn't rewrite it)
   - Validate: the revision adds a NOT clause

3. **SPL syntax validation**
   - Run the proposed SPL as a Splunk search (with `| stats count` appended) to verify it parses
   - If syntax error: retry LLM once with the error message appended to prompt
   - If second attempt fails: abort with structured error

4. **Invocation path**
   - This will be called via `| squelch mode="tune"` → internally calls LLM → returns proposed SPL
   - Or: standalone Python function callable from the pipeline
   - Decision: wherever the existing `mode="tune"` stub lives, extend it

#### Session Exit Gate
Given Detection 1 cluster results (3 scanner IPs, 78% explanatory power), the LLM proposes `<original SPL> + NOT src_ip IN ("10.0.1.50","10.0.1.51","10.0.1.52")`. The output parses as valid SPL in Splunk. A retry-on-syntax-error path is tested.

---

### Sessions 7–8: End-to-End Wiring

**Goal:** The full pipeline runs as one invocation: trigger → pull notables → cluster → propose revision → eval → accept/reject → write to KV.

#### Pipeline Flow

```
1. TRIGGER: Saved search fires (FP rate > 0.70)
   └── Passes search_name to pipeline

2. PULL: Query index=notable for that search_name
   └── Returns labeled events with fields

3. CLUSTER: Run FP clustering on pulled events
   └── Returns ranked patterns with explanatory power

4. PROPOSE: Send original SPL + clusters to LLM
   └── Returns proposed revised SPL

5. EVAL: Run eval harness — original SPL vs. revised SPL against golden dataset
   └── Returns precision/recall/runtime for both, plus delta

6. GATE: Recall-drop check
   ├── PASS → step 7
   └── FAIL → write rejection to KV, stop

7. WRITE: Store result in detection_lineage KV
   └── {search_name, original_spl, revised_spl, eval_before, eval_after, decision, timestamp}

8. OUTPUT: Return structured result to SPL pipeline
   └── One row with all metrics + decision
```

#### Deliverables

1. **Wire all components** built in Sessions 1–6 into a single `| squelch mode="tune" search_name="<name>"` invocation
2. **Run on Detection 1** — capture real numbers from the full pipeline
3. **Verify KV write** — after successful run, `| inputlookup detection_lineage_lookup | search search_name="WindowsAuth_AnomalousLogonSource"` returns the result
4. **Capture timing** — total wall time from invocation to result. Target: under 15 seconds (671ms LLM + search time + eval time)
5. **Error handling** — if any step fails, pipeline stops with a structured error indicating which step failed and why

#### Session Exit Gate
`| squelch mode="tune" search_name="WindowsAuth_AnomalousLogonSource"` runs end-to-end. Returns one row with: `decision=accepted, precision_before=0.168, precision_after=~0.51, recall_before=X, recall_after=X, revised_spl="...", runtime_ms=<under 15000>`. KV store has the record.

---

### Session 9: Rejection Case

**Goal:** Prove the safety net works. A bad revision is caught and rejected with a clear explanation.

#### Setup

1. **Force a bad revision** — options:
   - Temporarily modify the LLM prompt to propose an overly broad filter that catches TPs
   - Or: bypass the LLM entirely and inject a known-bad SPL revision into the pipeline
   - The second option is more reliable for testing

2. **Run the pipeline** with the bad revision injected

3. **Verify rejection output:**
   ```json
   {
     "status": "rejected",
     "reason": "recall_drop",
     "baseline_recall": 1.0,
     "revised_recall": 0.85,
     "events_lost": ["_cd_value_1", "_cd_value_2"],
     "explanation": "Proposed revision filters N true positive events. Recall drops from X to Y. Revision rejected."
   }
   ```

4. **Verify KV write** — the rejection is logged in `detection_lineage` with `decision=rejected`

5. **Verify no SPL change persists** — the original detection SPL is unchanged after rejection

#### Session Exit Gate
A bad revision is injected, the eval harness catches the recall drop, pipeline outputs a structured rejection with specific event IDs that would be lost, and the rejection is logged in KV store. The original SPL is untouched.

---

### Session 10: Safety-Net Video #1 + Bundle Close

**Goal:** Record insurance submission. Run bundle retrospective. Verify demo-fit.

#### Deliverables

1. **Safety-net video** (2 minutes)
   - Show: Detection 1 end-to-end through the full pipeline
   - Show: rejection case (bad revision caught)
   - This is insurance — if nothing else ships, this video + current code is a valid submission

2. **Bundle retrospective**
   - What took longer than expected?
   - What was easier than expected?
   - What's the actual velocity? (sessions used vs. planned)
   - Adjust Bundle 2 estimates if needed

3. **Demo-fit check**
   - Compare pipeline output format to what demo script expects per beat
   - Flag structural mismatches for Bundle 2+ resolution
   - Key question: is the clustering output shaped for multi-hypothesis display (Bundle 4)?

#### Session Exit Gate
Video recorded. Retro documented. Demo-fit gaps identified and logged.

---

## Key File Paths

| File | Purpose |
|---|---|
| `scripts/run_eval.py` | Eval harness CLI (exists, needs hardening) |
| `scripts/seed_notable.py` | Synthetic event seeder |
| `bin/squelch.py` (or equivalent) | Custom SPL command — all `mode=` paths live here |
| `default/collections.conf` | KV collection definitions (in squelch app) |
| `default/transforms.conf` | Lookup definitions including `detection_lineage_lookup` |
| `default/props.conf` | Field extractions for `squelch_notable` sourcetype |
| `default/savedsearches.conf` | Trigger saved search definition |
| `lookups/` | CSV lookups (golden dataset, scanner IPs, etc.) |

---

## Demo Alignment Notes

Bundle 1 builds for **clean synthetic data** only. The demo script shows messy data (Beat 1: "six label formats and thirty percent gaps"). That's Bundle 2 scope. Don't try to match demo numbers in Bundle 1.

What Bundle 1 MUST produce that the demo depends on:

| Demo Need | Bundle 1 Responsibility |
|---|---|
| Eval harness with precision/recall | Sessions 1–2 ✓ |
| FP clustering with explanatory power % | Sessions 3–4 ✓ |
| SPL revision via LLM | Sessions 5–6 ✓ |
| Pipeline runs as one command | Sessions 7–8 ✓ |
| Rejection case with explanation | Session 9 ✓ |
| Multi-hypothesis display | Bundle 4 — but clustering output must be shaped for it |
| Decision trail in PR body | Bundle 4 — but pipeline must log enough data |
| Git PR creation | Bundle 3 — not in scope |
| Label normalization | Bundle 2 — not in scope |
| Attack injection in eval | Bundle 2 — not in scope |

**Forward-compatibility requirement:** Sessions 3–4 clustering output should include ALL hypotheses (not just top-1), because Bundle 4 needs multi-hypothesis display. Design the data structure now; display it later.

---

## Risk Mitigations

| Risk | Trigger | Response |
|---|---|---|
| Eval harness hardening takes > 2 sessions | Not working by session 3 start | Simplify: skip golden dataset formalization, use raw index=notable as-is. Just add the recall-drop gate. |
| FP clustering finds wrong patterns | Top cluster isn't the scanner IPs | Start with src_ip only. If it still fails, the synthetic data seeding is wrong — re-verify with manual SPL first. |
| LLM generates invalid SPL | Syntax errors or logic rewrites | Keep revisions to NOT filters only. Pre-validate output format. One retry. If second fails, abort. |
| End-to-end wiring has integration bugs | Pipeline breaks at component boundaries | Sessions 7–8 are two sessions for this. Budget first session for debugging, second for hardening. |
| Bundle 1 overruns past session 10 | Any session slips | Record safety-net video at session 10 regardless of completion state. Ship what works. |

---

## What Comes After (Context Only — Do Not Build)

- **Bundle 2 (Sessions 11–18):** Noisy labels, label normalization lookup, attack injection in eval
- **Bundle 3 (Sessions 19–28):** Detection 2 (service account), Detection 3 ("don't tune"), Git PR/Issue creation
- **Bundle 4 (Sessions 29–37):** Multi-hypothesis display, decision trails, label perturbation, standalone eval command
- **Bundle 5 (Sessions 38–42):** Temporal holdout (CUT IF BEHIND — cut trigger: Bundle 4 closes after session 40)
- **Phase 9 (Sessions 43–50):** Architecture diagram, recording, Devpost, README, submit