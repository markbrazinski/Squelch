# Squelch — Architecture Diagram

One horizontal flow. Three differentiators. Memory logs every decision.

```
┌─────────────────────────────────────────────────────────────────────────────────────────────┐
│                                    SPLUNK APP BOUNDARY                                       │
│                                                                                              │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐    ┌──────────────┐               │
│  │  01 TRIGGER  │    │  02  BRAIN   │    │  03  TOOLS   │    │  04  EVALS   │               │
│  │              │───▶│              │◀──▶│              │◀──▶│              │               │
│  │ Saved search │    │ Gemini 2.5   │    │ 10 MCP       │    │ Adversarial  │               │
│  │ FP rate>70%  │    │ Flash        │    │ built-in +   │    │ gate ·       │               │
│  │ Label norm   │    │ Proposes SPL │    │ 1 BYOT       │    │ Precision /  │               │
│  │              │    │ revision     │    │ custom       │    │ Recall       │               │
│  └──────────────┘    └──────────────┘    └──────────────┘    └──────────────┘               │
│                                                                      │                       │
│  ┌───────────────────────────────────────────────────────────────────┘                       │
│  │                                                                                           │
│  │  ┌──────────────┐                          ┌──────────────────────────────────────────┐  │
│  │  │  05  MEMORY  │                          │              05  OUTPUT                  │  │
│  │  │              │                          │                                          │  │
│  │  │ KV Store     │                          │  ┌──────────────┐  ┌──────────────────┐  │  │
│  └─▶│ detection_   │                          │  │   → PR       │  │   → Issue        │  │  │
│     │ lineage      │                          │  │ tune accepted│  │ don't tune       │  │  │
│     │ Writes every │                          │  │ SPL diff +   │  │ diagnosis +      │  │  │
│     │ run, reads   │                          │  │ eval table   │  │ evidence         │  │  │
│     │ on next      │                          │  └──────────────┘  └──────────────────┘  │  │
│     └──────────────┘                          └──────────────────────────────────────────┘  │
│                                                                                              │
└─────────────────────────────────────────────────────────────────────────────────────────────┘
                                          │                    │
                                          ▼                    ▼
                                   ┌─────────────┐    ┌──────────────┐
                                   │ Gemini API  │    │  GitHub API  │
                                   │ (HTTPS out) │    │  (REST out)  │
                                   └─────────────┘    └──────────────┘
```

## Components

### 01 · TRIGGER
- Saved search: `squelch_trigger_high_fp_rate`
- Fires when FP rate exceeds 0.70 threshold
- Label normalization via `disposition_normalization.csv` (6 formats → 2 canonical values)

### 02 · BRAIN
- **LLM:** Gemini 2.5 Flash via direct HTTPS
- **Interface:** `| squelch` custom Splunk command (5 modes: `test`, `tune`, `validate`, `llm_probe`, `eval`)
- **Job:** Given original SPL + FP cluster, produce one `NOT {field} IN (...)` clause
- Structural validator rejects any output that rewrites the original query or omits the NOT clause
- Syntax checker validates proposed SPL via `| head 0` before shipping

### 03 · TOOLS
- **Splunk MCP Server v1.1.3** — 10 built-in tools for read-only data collection:
  `splunk_run_query`, `splunk_get_indexes`, `splunk_get_index_info`, `splunk_get_metadata`,
  `splunk_get_kv_store_collections`, `splunk_get_knowledge_objects`, `splunk_get_user_list`,
  `splunk_get_user_info`, `splunk_get_saved_searches`, `splunk_get_info`
- **1 custom BYOT tool:** `squelch_fp_rates_by_search` — exposes live FP-rate data from `index=notable` to peer agents
- **splunklib SDK** — write paths and `| squelch` invocation (MCP allowlist blocks custom commands)

### 04 · EVALS
The adversarial harness. Ships standalone as `| squelch mode="eval"`.

| Function | What it does |
|---|---|
| `evaluate_detection()` | Event-level precision/recall using Splunk `_cd` for identity — not aggregate counts |
| `gate_revision()` | Hard recall-preservation veto: `proposed.recall >= baseline.recall` or reject |
| `run_adversarial_eval()` | Synthetic TP injection — picks a filter value, injects a matching TP, re-evaluates |
| `perturb_and_eval()` | 10% label flip across 3 SHA-256-seeded trials — measures stability under label noise |
| `temporal_holdout_eval()` | 70/30 time-based split — checks whether the filter generalizes to unseen data |
| `cluster_fps()` | Per-field FP clusters with explanatory power rankings and lookup annotations |
| `diagnose_fp_pattern()` | Field-coverage analysis for the decline-to-tune path |

### 05 · MEMORY
- KV Store collection: `detection_lineage`
- Writes every run: decision, metrics before/after, hypothesis rankings, attack injection results
- Reads on next run: prevents re-proposing rejected filters, informs hypothesis selection

### 06 · OUTPUT
- **Tune accepted → GitHub PR** on branch `squelch/tune/{slug}-{epoch}`: SPL diff, eval table (before/after precision/recall), hypothesis analysis, label sensitivity, temporal stability, attack injection results
- **Don't tune → GitHub Issue**: root cause, field coverage evidence, recommendation (e.g. fix `props.conf`)

## Safety constants

| Constant | Value | Controls |
|---|---|---|
| `MIN_TOP_ENTRY_FP_PCT` | 0.20 | Minimum explanatory power for a cluster to be filterable |
| `PERTURB_RECALL_PASS_THRESHOLD` | 0.05 | Max recall delta under 10% label flip |
| `HOLDOUT_SPLIT_PCT` | 0.70 | 70% training / 30% holdout |
| `HOLDOUT_PRECISION_FLOOR_DELTA` | 0.0 | Holdout precision must not degrade |
| `DIAGNOSE_EMPTY_THRESHOLD` | 0.30 | Field empty in >30% of FPs triggers diagnosis |
| `DIAGNOSE_SOURCETYPE_THRESHOLD` | 0.80 | >80% of empties from one sourcetype → extraction gap |

## Boundaries

| Path | Via |
|---|---|
| Read Splunk data (queries, indexes, metadata) | MCP Server (10 built-in tools) |
| Expose FP data to peer agents | MCP BYOT (`squelch_fp_rates_by_search`) |
| Invoke `\| squelch` command | splunklib SDK REST (MCP allowlist blocks custom commands) |
| LLM calls | Direct HTTPS to Gemini API |
| PR / Issue creation | GitHub REST API (12 endpoints) |
