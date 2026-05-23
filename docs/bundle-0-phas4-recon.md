# Bundle 1 — Phase 4 Deep Platform Recon

**Project:** Squelch — Automated Detection Tuning for Splunk
**Phase:** 4 (Deep Platform Recon)
**Predecessor:** Bundle 0 (Phase 1 smoke test) — complete, no vetoes
**Session budget:** 3-4 sessions
**Mode:** Plan-approve-execute per session
**Model:** Claude Code (Sonnet default; Opus if architectural ambiguity)

---

## Bundle 1 Goals

Targeted investigation of the 7 capabilities that gate the Squelch build.
Ordered by build impact — if session budget runs short, cut from the bottom.

1. **Brain layer resolution:** confirm `| ai` works end-to-end with a model,
   or determine the fallback (DSDL / outbound HTTP)
2. **MCP BYOT custom tool registration:** can we add `squelch_*` tools to
   the MCP Server tool namespace? Gates the MCP prize narrative.
3. **BOTSv3 ingestion + golden dataset setup:** gates the eval harness
   (eval harness is week 1 of build per Tariq's scoping)
4. **Notable index seeding at scale:** script that populates index=notable
   with realistic synthetic FP/TP disposition data for demo + eval
5. **Outbound LLM API call from custom command:** confirm httpx/urllib works
   inside Splunk's search pipeline (fallback Brain path)
6. **Eval harness scaffolding:** the directory structure, golden dataset
   format, and precision/recall/runtime script skeleton
7. **splunklib.ai pydantic workaround:** only if `| ai` path fails and we
   need the SDK's agent helpers

---

## Session locks (carry forward from Bundle 0)

| # | Lock | Source |
|---|------|--------|
| 1 | MCP for reads, splunklib REST for writes/invocation | Bundle 0 finding |
| 2 | Notable index is Squelch-owned, seeded synthetically | Bundle 0 finding |
| 3 | App ID = squelch, command = \| squelch | Phase 0 naming lock |
| 4 | Do not write passwords/tokens to disk in plaintext | Bundle 0 discipline |
| 5 | Plan-approve-execute; no execute without approved plan | Standard |

---

## Session 1 — Brain Layer + MCP BYOT (B1-S1)

**Date target:** First available session after `| ai` capability grant
**Priority:** CRITICAL — gates architecture for everything downstream

### Pre-requisite (user does manually before session)

Grant `apply_ai_commander_command` capability to admin role or user
`mark@brazinski.us` (Settings → Roles → admin → Capabilities → check
`apply_ai_commander_command` → Save). No restart needed.

### Scope

Resolve the Brain layer architecture. We need to know: can Squelch call
an LLM through Splunk's native `| ai` command on Enterprise + trial
license, or do we need an alternative path? This decision cascades into
every subsequent design choice.

Also: test whether the MCP Server supports custom tool registration
(BYOT pattern). This determines whether other agents can call into
Squelch via MCP, which is the core of the MCP prize narrative.

### What ships

- [x] `| ai` test results: **works** after configuring Gemini 2.5 Flash via direct KV writes (MLTK's official `aicommander` REST endpoint deadlocks; bypassed by writing to `storage/passwords` + `aitk_llm_connection` + `aitk_llm_default_mappings` directly). Returns "hello" in 5.5s.
- [x] `| ai` config setup steps documented in [platform-shape.md § Phase 4 Session 1](platform-shape.md). Supports OpenAI, Azure OpenAI, Anthropic, Groq, Gemini, Ollama, Bedrock, Splunk Hosted LLM.
- [x] Outbound HTTP from inside custom command (`| squelch mode="llm_probe"`): **works**, 671ms wall time to Gemini.
- [x] MCP BYOT: **works after restart**. Custom tool `squelch_fp_rates_by_search` registered to `mcp_tools` KV, returns live data via MCP `tools/call`. Caveats documented (safe_spl.json filter; `mcp_tools_enabled._key` must equal tool name).
- [x] Brain layer decision: **both paths viable**. Default to `| ai` (in-SPL) for SIEM-engineer-natural usage; custom-command outbound HTTP as backup for cases where `| ai` config is missing or for non-SPL contexts.
- [x] MCP prize narrative updated: Squelch exposes `squelch_*` tools as BYOT entries that wrap allowlisted SPL against our state (notable index + detection_lineage KV). Other agents call them like native tools.

### Tests

**T1: `| ai` end-to-end**
```spl
| makeresults | eval test="hello" | ai prompt="echo back the word hello"
```
Record: response content, model used, latency, errors.

**T2: `| ai` with explicit model (if T1 fails on model selection)**
```spl
| makeresults | eval test="hello" | ai prompt="echo hello" model="foundation-sec"
```
Try variants: `model="gpt-oss-120b"`, `model="gpt-oss-20b"`, no model param.

**T3: AI Toolkit model configuration UI**
Navigate to AI Toolkit app → Settings/Configuration → check what model
providers are available, whether external endpoints can be configured.
Screenshot or record exact options.

**T4: Outbound HTTP from custom command (fallback Brain test)**
Add a test mode to `squelch_command.py` (or a separate script) that does:
```python
import urllib.request
req = urllib.request.Request(
    "https://api.anthropic.com/v1/messages",
    headers={
        "x-api-key": os.environ.get("ANTHROPIC_API_KEY", "test"),
        "Content-Type": "application/json",
        "anthropic-version": "2023-06-01"
    },
    data=json.dumps({
        "model": "claude-sonnet-4-20250514",
        "max_tokens": 50,
        "messages": [{"role": "user", "content": "echo hello"}]
    }).encode()
)
resp = urllib.request.urlopen(req, timeout=15)
```
Record: does Splunk's Python sandbox allow outbound HTTPS during search?

**T5: MCP BYOT custom tool registration**
Research the actual mechanism for registering custom MCP tools:
- Check MCP Server app docs / README in the installed app directory
- Check if there's a `tools.conf` or registration API
- Check if custom tools can be shipped from inside a Splunk App
  (our squelch app registering `squelch_tune_detection` as an MCP tool)
- If docs are thin: check #splunk-ai-hackathon Slack for examples
- Test: attempt to register a minimal custom tool and call it via MCP

### Pre-flight questions for Claude Code

1. What's in the AI Toolkit's configuration directory — is there a
   `models.conf` or `providers.conf` that maps model names to endpoints?
2. What's in the MCP Server's app directory beyond `mcp.conf` — is there
   a tool registration mechanism for third-party apps?
3. Does Splunk's Python sandbox restrict `urllib`/`httpx` during search
   execution, or only restrict filesystem access?

### Out of scope this session
- BOTSv3 ingestion (Session 2)
- Notable seeding scripts (Session 2)
- Eval harness code (Session 3)
- DSDL / Foundation-Sec local deployment (only if `| ai` + outbound both fail)

---

## Session 2 — Data Foundation (B1-S2)

**Date target:** After Session 1 Brain decision is locked
**Priority:** HIGH — gates eval harness and demo

### Scope

Set up the data foundation that the eval harness and demo depend on.
Two workstreams: BOTSv3 as realistic security event data, and notable
index seeding with synthetic FP/TP dispositions.

### What ships

- [ ] BOTSv3 dataset installed and queryable in Splunk — **deferred** (cost vs. value for solo hackathon)
- [x] Notable index populated with 1000 synthetic events across **8** correlation searches, FP/TP distribution matches spec (within sampling tolerance)
- [x] Seeding script (rerunnable) committed: [`scripts/seed_notable.py`](../scripts/seed_notable.py)
- [x] **Three** correlation searches with FP rate >70%: `WindowsAuth_AnomalousLogonSource` (0.83), `Network_PortScan_Detected` (0.74), `DNS_TunnelExfil_Heuristic` (0.71)
- [x] Data inventory doc: [`docs/data-inventory.md`](data-inventory.md)

### Tests

**T1: BOTSv3 install**
Download BOTSv3 dataset (Splunk GitHub or Splunkbase). Expected format:
pre-indexed app that drops into `$SPLUNK_HOME/etc/apps/`. Restart Splunk.
```spl
index=botsv3 | stats count by sourcetype | sort -count | head 20
```
Record: total event count, sourcetypes, time range.

**T2: BOTSv3 data model acceleration**
Check which data models are populated by BOTSv3 data:
```spl
| datamodel Authentication search | head 10
| datamodel Network_Traffic search | head 10
```
Record: which data models have data (critical for tstats-based detections).

**T3: Notable index seeding script**
Write `seed_notable.py` (or SPL macro) that:
- Creates 500-1000 synthetic notable events
- Spreads across 5-8 named correlation searches
- Distribution: 2-3 searches with FP rate >70% (Squelch triggers),
  2-3 with FP rate 20-40% (healthy), 1-2 with FP rate <5% (pristine)
- Each event has: search_name, rule_name, urgency, status_label
  (true_positive | false_positive), owner, disposition (free text),
  _time (spread over 30 days), src_ip, dest, user
- FP clusters should have patterns (e.g., 78% of FPs from 3 scanner
  IP ranges) so Squelch's clustering step has signal to find

```spl
| makeresults count=200
| eval search_name="WindowsAuth_AnomalousLogonSource"
| eval status_label=if(random()%100 < 85, "false_positive", "true_positive")
| eval src_ip=case(
    status_label="false_positive" AND random()%100 < 78,
        mvindex(split("10.0.1.50,10.0.1.51,10.0.1.52", ","), random()%3),
    1=1,
        "192.168.".tostring(random()%254).".".tostring(random()%254))
| eval _time=now() - (random()%2592000)
| collect index=notable sourcetype=stash
```
Repeat for each search_name with different FP rate / cluster patterns.

**T4: FP rate computation from seeded data**
```spl
index=notable
| stats count(eval(status_label="false_positive")) as fp,
        count(eval(status_label="true_positive")) as tp,
        count as total by search_name
| eval fp_rate=round(fp/total, 2)
| sort -fp_rate
```
Confirm: FP rates match seeded distribution. At least one >0.70.

**T5: Seeded data at scale check**
After 500+ events ingested:
```spl
index=notable | stats count by status_label
```
Confirm: sub-second response time. At 1000 events this should be trivial;
the real question is whether the schema + field extraction works cleanly.

### Pre-flight questions for Claude Code

1. Where is the BOTSv3 dataset hosted? (GitHub? Splunkbase? S3?)
   If download requires registration, tell user to download manually.
2. Does BOTSv3 include pre-built correlation searches, or just raw events?
3. Will `| collect index=notable sourcetype=stash` properly extract all
   eval'd fields, or do we need `transforms.conf` INDEXED_EXTRACTIONS?

### Out of scope this session
- Eval harness code (Session 3)
- Agent logic (Phase 8)
- Demo video scripting (Phase 5/9)

---

## Session 3 — Eval Harness Scaffolding (B1-S3)

**Date target:** After Session 2 data foundation is in place
**Priority:** HIGH — Tariq says "eval harness before agent, or it never exists"

### Scope

Build the skeleton of the eval harness that every agent-generated detection
runs through before being shown to the user. This is the component that
earns a SIEM engineer's trust. Not the agent — the eval.

### What ships

- [x] `eval/` directory at repo root with:
  - [x] `golden_dataset.conf` (parameterized for Bundle 2 attack injection)
  - [x] `eval_lib.py` (shared core)
  - [x] `run_eval.py` CLI (`--all`, `--search-name`, `--spl + --label`)
  - [x] `results/eval_results.csv` (per-run append log)
  - [x] `results/baseline_evals.csv` (all 8 detections; the "before" snapshot)
- [x] Custom SPL command wired up: `| squelch mode="validate" search_name="..."` returns precision/recall/fp_rate/runtime as fields. Imports vendored `squelch_eval` module from `bin/lib/squelch_eval/`.

### What "precision" and "recall" mean in Squelch's context

- **True Positive (TP):** Detection fires AND event is labeled `true_positive`
  in the notable index (or matches a known-attack event in BOTSv3)
- **False Positive (FP):** Detection fires AND event is labeled `false_positive`
  in the notable index
- **False Negative (FN):** Detection does NOT fire AND event is a known-attack
  in the golden dataset
- **Precision** = TP / (TP + FP) — "when it fires, is it real?"
- **Recall** = TP / (TP + FN) — "does it catch all the real attacks?"

For Squelch's tuning use case: we MUST preserve recall (don't drop TPs)
while improving precision (reduce FPs). The eval harness enforces this:
a proposed tuning is rejected if recall drops below the original detection's
recall, even if precision improves.

### Tests

**T1: run_eval.py against a known detection**
Take one of the seeded correlation searches (e.g., WindowsAuth_AnomalousLogonSource).
Extract its SPL. Run `run_eval.py` against it. Confirm precision/recall
match the seeded FP/TP distribution.

**T2: run_eval.py against a modified detection**
Manually add a `NOT src_ip IN ("10.0.1.50","10.0.1.51","10.0.1.52")` clause.
Re-run eval. Confirm: precision improves (FPs from scanner IPs removed),
recall unchanged (TPs weren't from those IPs).

**T3: Runtime measurement**
Confirm run_eval.py captures search execution time (dispatch.duration or
job.runDuration from the REST API) and includes it in the output CSV.

**T4: `| squelch mode="validate"` integration**
```spl
| squelch mode="validate" search_name="WindowsAuth_AnomalousLogonSource"
```
Returns: precision, recall, fp_rate, runtime, tp_count, fp_count as fields
in the search results.

### Pre-flight questions for Claude Code

1. How does splunklib's `jobs.oneshot()` or `jobs.create()` expose runtime
   stats (dispatch duration, scan count, event count)?
2. Can we run a search "as if" it were a correlation search against the
   notable index, or do we need to reconstruct the search logic from
   the saved search's SPL?
3. What's the BOTSv3 labeling format — are attack events pre-labeled,
   or do we need a separate mapping file?

### Out of scope this session
- Agent tuning logic (Phase 8)
- FP clustering algorithm (Phase 8)
- Git PR generation (Phase 8)
- Demo polish (Phase 9)

---

## Session 4 — Remaining Recon + Findings Lock (B1-S4)

**Date target:** After Session 3
**Priority:** MEDIUM — cleanup and documentation

### Scope

Mop up any remaining Phase 4 items, document all findings, update project
artifacts for Phase 5 handoff.

### What ships

- [x] platform-shape.md updated with all Phase 4 findings (Sessions 1-4)
- [x] direction-lock.md created with 6 locked architecture decisions (D1-D6)
- [x] Phase 4 exit gate passed (only BOTSv3 deferred)
- [x] Clean handoff notes for Phase 5 in direction-lock.md § "Phase 5 handoff notes"

### Tests

**T1: End-to-end dry run**
Manually execute the Squelch workflow by hand (no agent, just human
running the steps):
1. Query `index=notable | stats ... by search_name` to find high-FP detection
2. Pull that detection's SPL
3. Query the FP events, eyeball the cluster pattern
4. Manually write a revised SPL with the filter
5. Run `| squelch mode="validate"` on the revised SPL
6. Confirm precision improves, recall preserved

This is the "pencil test" — if a human can't do it in Splunk, the agent
can't either. Document friction points for Phase 8.

**T2: Architecture diagram draft**
Sketch the component diagram (required for hackathon submission):
- Squelch App (Splunk) → MCP tools (reads) + REST (writes)
- Brain: `| ai` or outbound LLM call
- Memory: KV store detection_lineage
- Eval: golden dataset + run_eval.py
- Output: Git PR (via GitHub API)

### Pre-flight questions for Claude Code

1. Are there any untested items from the Phase 4 target list in
   platform-shape.md that we haven't covered?
2. Any yellow signals from Sessions 1-3 that need resolution before
   Phase 5 can start?

### Out of scope this session
- PRFAQ writing (Phase 5)
- Demo script (Phase 5)
- Devpost draft (Phase 5)

---

## Phase 4 Exit Gate

- [x] Brain layer architecture decided and tested (**both** `| ai` via Gemini 2.5 Flash AND outbound HTTP from custom command — see platform-shape.md § Phase 4 Session 1)
- [x] MCP BYOT status determined: **works after Splunk restart**; tools that wrap allowlisted SPL execute end-to-end; tools that wrap custom commands like `| squelch` hit `safe_spl.json` filter — wrap the SPL instead
- [ ] BOTSv3 installed and queryable — **deferred** per user direction (30 GB cost too high for solo hackathon; synthetic notable seeding sufficient for eval harness and demo)
- [x] Notable index seeded with 500+ events (**1000 events**, 8 detections, FP rates 0.83/0.74/0.71/0.34/0.27/0.22/0.03/0.03 — matches seeded distribution)
- [x] Seeding script committed and rerunnable (`scripts/seed_notable.py`)
- [x] Eval harness skeleton works (`run_eval.py` produces precision/recall/runtime for all 8 detections in `eval/results/baseline_evals.csv`)
- [x] `| squelch mode="validate"` returns eval results (identical numbers to CLI)
- [x] End-to-end dry run completed by hand (~1.5s total query time, see platform-shape.md § Phase 4 Session 4)
- [x] platform-shape.md updated with Phase 4 Sessions 1 + 2 + 3 + 4 findings
- [x] direction-lock.md updated with 6 locked decisions + Phase 5 handoff notes
- [x] All Session 1-4 architecture-gating questions answered
- [x] Clean handoff notes for Phase 5 in `direction-lock.md` § "Phase 5 handoff notes"

**If any critical gate fails:** stop, reassess in this thread before
proceeding to Phase 5. The PRFAQ cannot be written against an
architecture that hasn't been validated.

---

## What Phase 4 Hands Off to Phase 5

Phase 5 (Working Backwards) needs these inputs locked:

1. **Brain layer:** which model(s), called how, with what latency
2. **MCP story:** what MCP tools Squelch exposes vs consumes
3. **Eval story:** what metrics, what dataset, what thresholds
4. **Data story:** what's in the notable index, what's in BOTSv3
5. **Demo feasibility:** the dry run from S4-T1 confirms the workflow
   is demonstrable in <3 minutes

Phase 5 produces: PRFAQ, demo script (beat-by-beat), Devpost submission
draft, and the working-backwards narrative that the entire build
references. It is the most important non-build phase. Do not start it
with unanswered architecture questions.