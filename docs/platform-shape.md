# Platform Shape — Bundle 0 Smoke Test Results

**Project:** Squelch — Automated Detection Tuning for Splunk
**Phase:** 1 (Platform Smoke Test) — complete
**Date:** 2026-05-21
**Hardware:** macOS, Apple M4
**Splunk:** Enterprise 10.4.0, trial license ("OK")

---

## TL;DR

**No hard vetoes.** All 5 veto checks score CLEAR/LOW/ALLOWED/WORKS/PERSISTS. The Splunk Enterprise + trial license platform is sufficient to build Squelch end-to-end, with two yellow caveats (one architectural, one cosmetic):

1. **`| squelch` cannot be invoked through MCP `splunk_run_query`** — the MCP Server hardcodes a command allowlist that excludes custom SPL commands. Squelch's agent loop must call the custom command via REST oneshot (splunklib SDK), not via MCP. MCP is still fine for read-only data-collection tools (`splunk_run_query` on built-in searches, `splunk_get_indexes`, KV store reads).
2. **`splunklib.ai` unusable on Apple Silicon** in Splunk's bundled Python 3.13 (macOS Gatekeeper blocks `pydantic_core`'s precompiled `.so` due to a Team ID mismatch). Doesn't block Phase 1; revisit if we need the SDK's agent helpers.
3. **`| ai` runs but has no default LLM configured.** After granting `apply_ai_commander_command` to admin (manual fix), `| ai prompt="..."` returns `No default LLM configuration found.` Command surface is alive across `Splunk_ML_Toolkit`, `squelch`, and `search` app contexts — just needs a model attached. Deferred to Phase 4 (model-attach work).

And one big architectural win: **the Trigger layer is buildable without ES**. We can create `index=notable`, ingest synthetic events with our chosen schema, and run `stats count by status_label` cleanly to compute FP rates — that was the largest open question coming in.

---

## Corrections to bundle-0-smoke-test.md

The doc has stale tool-name and API assumptions that would have cost hours of debugging on a fresh run. Listing them here so the doc gets fixed and future readers aren't misled.

### MCP Server v1.1.3 tool-name drift

| Doc claimed | Actual in v1.1.3 |
|---|---|
| `splunk_run_splunk_query` | **`splunk_run_query`** |
| `splunk_list_indexes` | **`splunk_get_indexes`** |
| `splunk_get_saved_searches` | **`splunk_run_saved_search`** + **`splunk_get_knowledge_objects`** |
| `splunk_list_kvstore_collections` | **`splunk_get_kv_store_collections`** |
| `splunk_run_query` arg `search_query` | **`query`** |

Full v1.1.3 tool set (10 tools, all enabled by default): `splunk_get_info`, `splunk_get_indexes`, `splunk_get_index_info`, `splunk_get_user_list`, `splunk_get_user_info`, `splunk_run_query`, `splunk_get_metadata`, `splunk_get_kv_store_collections`, `splunk_get_knowledge_objects`, `splunk_run_saved_search`.

The "saia_* tools" the doc mentioned do not appear (expected — no AI Assistant installed).

### Doc's `test_mcp.sh` is broken for v1.1.3

[/Applications/Splunk/etc/apps/squelch/bin/test_mcp.sh](file:///Applications/Splunk/etc/apps/squelch/bin/test_mcp.sh) calls `splunk_run_splunk_query` (404) and `splunk_list_indexes` (404). Update or delete. Same applies to the curl examples in S1.4 Test 2/3.

### Doc's `splunk-sdk` install assumption is wrong on PyPI

The doc says `pip install splunk-sdk` gets v3.x+ with `splunklib.ai`. Actually:
- PyPI tops out at **`splunk-sdk` 2.1.1**, no `splunklib.ai` and **has a JSON-parsing bug** (`Expecting value: line 1 column 1`) against Splunk 10.4's response stream unless you pass `output_mode='json'` explicitly to `oneshot()`.
- A separately-named PyPI package, `splunk_sdk` (underscore), ships **v3.0.0** with `splunklib.ai` — but **Splunk's bundled `pip` resolves `splunk-sdk`** (hyphen) to this one. Confusing.
- The GitHub master (`splunk-sdk @ git+https://github.com/splunk/splunk-sdk-python.git`) installs as `3.0.1a0` and requires Python ≥3.13, so it only installs in a venv built on Splunk's bundled Python (`/Applications/Splunk/bin/python3 -m venv --without-pip`, then bootstrap pip via `get-pip.py` — Splunk's Python ships without `ensurepip`).

For Squelch: use GitHub master in a Splunk-Python-based venv for the standalone SDK work; **vendor `splunk-sdk` 3.0.0 into `bin/lib/`** for the custom SPL command (which uses Splunk's bundled Python at runtime). Both work; both are in place.

### Custom SPL command path

Doc says `| squelch mode="test"` runs from the search bar. True for Splunk Web. **It fails through MCP** (allowlist) and **needs the right REST endpoint** when called via curl: `/servicesNS/<user>/squelch/search/jobs/oneshot` (note: no `/v2/`, and the squelch app context in the path).

---

## 1. What works

| Capability | Status | Evidence |
|---|---|---|
| MCP Server initialize | ✓ | `protocolVersion: 2025-06-18`, `serverInfo.name=Splunk_MCP_Server`, version 1.1.3 |
| MCP `tools/list` | ✓ | 10 tools enumerated, all enabled |
| MCP `splunk_run_query` on built-in indexes | ✓ | 5 rows from `index=_internal` at 0.32s latency |
| MCP `splunk_get_indexes` | ✓ | Returns full index list including `_audit`, `_internal`, `_configtracker`, etc. |
| KV store CRUD via REST | ✓ | create=201, write=201, read=200, delete=200 |
| **KV store survives restart** | ✓ | Wrote `{k:"before_restart", v:42}`, restarted Splunk, re-read identical record |
| Scheduled saved searches on trial license | ✓ | 1-min cron alert fired twice in 130s window; `fired_alerts` registered both |
| Squelch app loads | ✓ | `/services/apps/local/squelch` returns `disabled=False, version=0.1.0`; no errors in splunkd.log |
| `\| squelch mode="test"` via REST | ✓ | Returns `{status: success, mode: test, version: 0.1.0, phase: smoke_test}` |
| `\| squelch mode="tune"` via REST | ✓ | Returns full stub payload with `search_name=test_detection`, `fp_threshold=0.70` |
| `\| inputlookup detection_lineage_lookup` | ✓ | Collection resolves; round-trip via `\| outputlookup append=true` works |
| splunklib SDK T1 (connect) | ✓ | Splunk 10.4.0, license OK |
| splunklib SDK T2 (SPL search) | ✓ | 5 rows from `index=_internal` (after `output_mode='json'` fix) |
| splunklib SDK T3 (KV CRUD) | ✓ | Create/read/delete round-trip on `smoke_test_collection` |
| splunklib SDK T5 (outbound HTTPS) | ✓ | github.com `/zen` endpoint reachable |
| splunklib SDK T6 (saved-search create) | ✓ | Programmatically created/deleted `smoke_test_fp_rate_monitor` |
| `\| fit LinearRegression` (PSC + MLTK) | ✓ | 10-row fit returns `predicted(y)` column; PSC for Apple Silicon (6785) loaded correctly |
| **`index=notable` creation + ingest** | ✓ | Created via REST 201, ingested 3 synthetic events, `stats count by status_label` returns 2 FP / 1 TP |

---

## 2. What doesn't work

| Capability | Status | Notes |
|---|---|---|
| `\| squelch` via MCP `splunk_run_query` | ✗ | `Forbidden command found: squelch`. MCP Server has hardcoded allowlist; not configurable in mcp.conf. **Architecture impact below.** |
| `\| ai` SPL command — default model | ✗ | After capability granted to admin, command runs but fails with `No default LLM configuration found.` from all app contexts tested (`Splunk_ML_Toolkit`, `squelch`, `search`). Needs an LLM provider attached via the AI Commander config — Phase 4 work. |

---

## 3. What's yellow

| Item | Yellow because |
|---|---|
| `splunklib.ai` import | Loads `pydantic` → `pydantic_core/_pydantic_core.cpython-313-darwin.so`, which macOS Gatekeeper rejects with `code signature ... different Team IDs`. Reproduces in both Splunk's bundled Python and a venv built from it. Workaround: build `pydantic_core` from source (`pip install --no-binary pydantic_core pydantic`) — untested. **Doesn't block any Phase 1 capability.** Only matters if Squelch's agent loop ends up using `splunklib.ai`'s helpers (vs. calling our own LLM client). |
| splunklib SDK on PyPI vs vendored | Two different SDKs called "splunk-sdk" with confusingly different feature sets and version numbers (see Corrections). For Phase 8 build, lock to a specific source-of-truth in a requirements file. |
| `| ai` admin permissions | **Resolved during smoke test** — capability `apply_ai_commander_command` granted to admin role via UI. Now the gate is LLM attachment, not auth. |
| MCP Server `mcp_user` role | Doc says role MUST be named exactly `mcp_user`. Confirmed present with `mcp_tool_admin` + `mcp_tool_execute`. But: my admin user (`mark@brazinski.us`) authenticates against MCP **using the encrypted token, not the role's capabilities** — so the role's mainly there for the token-issuance flow. Worth understanding for future deployments where the agent runs as a non-admin service identity. |

---

## 4. Veto check results

### V1: Seeding Burden — **LOW**
- BOTSv3: not tested in this bundle (Phase 4). Pre-indexed dataset, near-zero ingest cost.
- **Notable index simulation: confirmed working.** Created `index=notable`, ingested 3 synthetic events with `{search_name, rule_name, urgency, status_label, owner, disposition}` schema via `| collect index=notable sourcetype=stash`, queried back with `stats count by status_label` — clean 2 FP / 1 TP aggregation.
- Synthetic correlation searches with FP history: trivial to script (we can `| makeresults | streamstats | eval ... | collect`).
- Estimated seeding work for an end-to-end demo: **<2 hours**.

### V2: Auth Ceiling — **CLEAR**
| Capability | Works? | Notes |
|---|---|---|
| MCP Server | ✓ | All 4 smoke tests passed |
| AI Toolkit installed | ✓ | MLTK 5.7.4 + PSC Apple Silicon 6785 + `splunk-ai-canvas` 1.4.1 all loaded |
| `\| ai` command runs | ✓ (cap granted) | Reaches command body from all app contexts; next gate is `No default LLM configuration found` — model-attach is Phase 4 |
| `\| fit / \| apply` | ✓ | LinearRegression fit returns predictions |
| KV store | ✓ | Full CRUD + restart persistence |
| Scheduled saved searches | ✓ | Cron fires on trial license |
| Custom SPL command (`\| squelch`) | ✓ | Both modes return expected payloads |
| Splunk App install (squelch) | ✓ | App loads, collections.conf reloads cleanly |

**Gated count: 0/7 hard-gated. 0/7 yellow** (the `| ai` capability gate was cleared during smoke test by granting `apply_ai_commander_command`; the next gate is LLM-attach, which is Phase 4 work, not an auth ceiling.)

### V3: Outbound Network — **ALLOWED**
- `https://api.github.com/zen` reachable from the Splunk host via both `urllib.request` (SDK T5) and direct `curl`.
- No firewall or proxy interception observed.
- LLM API endpoints (Anthropic, OpenAI, etc.) not yet tested — Phase 4 work.

### V4: Deployment Path — **WORKS**
- App installs cleanly (already installed by hand for this bundle; install path = drop into `$SPLUNK_HOME/etc/apps/` + restart).
- Custom command (`| squelch`) registers via `commands.conf` and exec'd by Splunk's bundled Python; works when `bin/lib/` is populated with vendored deps.
- KV store collections defined in `collections.conf` (`detection_lineage`, `smoke_test_collection`) auto-reload on app install (`Conf level reloading succeeded for conf=collections Application = squelch` in splunkd.log).
- App skeleton already shipping a usable layout: [app.conf](file:///Applications/Splunk/etc/apps/squelch/default/app.conf), [commands.conf](file:///Applications/Splunk/etc/apps/squelch/default/commands.conf), [collections.conf](file:///Applications/Splunk/etc/apps/squelch/default/collections.conf), [transforms.conf](file:///Applications/Splunk/etc/apps/squelch/default/transforms.conf).

### V5: Durable State — **PERSISTS**
- KV store: empirically confirmed (write → `splunk restart` → read identical record).
- Saved searches: persist by default (Splunk standard behavior; confirmed via REST list-after-create).
- App config: persists in `$SPLUNK_HOME/etc/apps/squelch/`; survives restart trivially.
- `notable` index: created and durable on disk at `$SPLUNK_HOME/var/lib/splunk/notable/`.

---

## 5. Notable index strategy

**Verdict: simulate ES notables, do not require ES.**

- Created `index=notable` via `POST /services/data/indexes name=notable datatype=event` (HTTP 201).
- Ingested synthetic events using `| collect index=notable sourcetype=stash` with our chosen ES-compatible field set: `search_name, rule_name, urgency, status_label, owner, disposition`.
- Queried back: events searchable, fields extracted, `stats count by status_label` returns clean aggregation.

**Implications for Squelch architecture:**
- Trigger layer can compute FP rate per `search_name` via `index=notable | stats count(eval(status_label="false_positive")) as fp, count as total by search_name | eval fp_rate = fp/total`.
- For the demo: seed `index=notable` with a few hundred synthetic events spanning multiple correlation searches and FP rates. Script lives in Phase 4.
- For Phase 8 build: the eval harness can do the same — write expected-disposition events into a test `notable` index, run Squelch's tune flow, assert the FP rate drops.

**One sharp edge:** without ES, there's no `notable | adhoc_search` or analyst UI for dispositioning. Synthetic seeding **is** the only path to TP/FP labels in this environment. That's fine for hackathon scope.

---

## 6. Model access strategy

**`| ai` exists on Enterprise — better than expected.** Doc assumed it might be Cloud-only; it isn't. MLTK 5.7.4's `commands.conf` registers `[ai]`, `[aiagent]`, `[agentstatus]`, plus the older `[fit]`/`[apply]`/`[score]`/`[summary]`/`[listmodels]` ML primitives.

Gates we hit:
1. **Capability gate** — `apply_ai_commander_command` not granted to base `admin` role. **Resolved during smoke test** by granting the cap to `mark@brazinski.us`. Same fix will be needed for any service identity Squelch eventually runs as.
2. **Model attachment** — with the cap granted, `| ai prompt="echo back the word hello"` now returns `No default LLM configuration found.` across `Splunk_ML_Toolkit`, `squelch`, and `search` app contexts (also: `splunk-ai-canvas` is disabled — `Application is disabled: splunk-ai-canvas`). This is the actual remaining gate. **Phase 4 work:** wire up either Splunk Hosted Models (dev license is supposed to include them) or an external provider via the AI Commander config endpoints.

**DSDL (Deep Splunk Deep Learning) not investigated this bundle** — defer to Phase 4 if we end up needing Foundation-Sec-1.1-8B locally vs. via Splunk Hosted Models.

For now: assume Squelch's LLM calls will route through `| ai` *or* through an outbound HTTP call from the custom command. Outbound HTTPS is confirmed (V3), so either path is open.

---

## 7. Three things that surprised me

1. **MCP Server's command allowlist is hardcoded.** The doc reads as if MCP is the universal call path; in reality, MCP can only invoke a fixed set of "safe" tools. Any custom SPL command (including `| squelch`) bounces with `Forbidden command found`. **This means Squelch's agent loop cannot self-invoke via MCP** — it must use the splunklib SDK REST oneshot path. Architecturally fine, but a different shape than the doc implied.

2. **`| ai` actually exists on Enterprise.** Doc said "probably won't work without Cloud." Wrong — MLTK 5.7.4 ships it. Whether it runs end-to-end with a model attached is a separate question (capability + model setup), but the SPL command surface is there.

3. **`pydantic_core` on macOS + Splunk's bundled Python is a code-signing dead end.** Apple Silicon + macOS Gatekeeper + a precompiled wheel signed by PyPI's Team ID = `dlopen` refuses to load it. Same failure inside Splunk's Python *and* in a venv built from it. Anyone trying to use `splunklib.ai` (or any other pydantic-dependent module) on a Mac will hit this. Build-from-source workaround is plausible but untested.

---

## 8. Architecture implications

Things in [direction-lock.md](direction-lock.md) (not in this bundle, but the relevant decisions) that need to flex based on findings:

- **"MCP is the agent's primary interface to Splunk"** → revise to: **"MCP for read-only data/metadata; splunklib REST for write paths and custom-command invocation."** Tasks/calls the agent makes split into two buckets. Document the boundary so future contributors don't try to route `| squelch` through MCP.
- **"Trigger layer requires ES notable + disposition labels"** → revise to: **"Trigger layer reads from a Squelch-owned `index=notable` (schema mirrors ES); demo + eval harness seed this index synthetically."**
- **"Memory layer uses KV store"** → no change. Confirmed working, persistent, fast.
- **"Use `splunklib.ai` for agent helpers"** → defer. Phase 8 build should not depend on it until the pydantic_core issue is resolved or we explicitly choose a no-binary-wheel path. Recommend writing our own thin client around the LLM call surface instead.

---

## 9. Phase 4 target list

Specific things that need deeper testing now that V1–V5 are clear:

1. **Attach a default LLM to `| ai`** — capability is already granted; the next gate is `No default LLM configuration found.` Wire up Splunk Hosted Models (should be included in dev license) or an external provider via AI Commander config. Then re-run `| makeresults | eval test="hello" | ai prompt="echo back the word hello"` and capture the actual response + model name. (Also: re-enable `splunk-ai-canvas` if it offers useful config UI — it's currently disabled.)
2. **DSDL / Foundation-Sec-1.1-8B path** — only if `| ai` doesn't work or we want a local model. Likely an MLTK container deployment.
3. **BOTSv3 ingestion** — the doc plans to use this as the realistic-volume dataset. Validate the unpack-and-mount path, confirm correlation search re-creation works.
4. **MCP custom-tool registration (BYOT)** — can we add a `squelch_tune_detection` tool to the MCP allowlist? If yes, the agent loop simplifies dramatically. If no, the splunklib-REST split is permanent.
5. **Outbound LLM API call from inside a custom command** — does Splunk's Python sandbox allow `httpx.post()` to an external API from `squelch_command.py` at search time? T5 only confirmed `urllib` from the standalone SDK process, not from inside a search pipeline.
6. **`pydantic_core` source build** — confirm whether `pip install --no-binary pydantic_core pydantic` in Splunk's bundled Python produces a working `splunklib.ai`. If yes, unblocks the "use the SDK's agent helpers" path.
7. **Notable index at scale** — does `stats count by status_label` performance hold at 100K, 1M events?

---

## Exit gate (from bundle-0-smoke-test.md)

- [x] MCP Server initializes and lists tools
- [x] Can run SPL query via MCP
- [x] KV store CRUD works (both REST and SPL)
- [x] Squelch app skeleton installs and loads
- [x] `| squelch mode="test"` returns success (via REST oneshot, not MCP)
- [x] splunklib SDK connects and runs searches
- [x] splunklib.ai: yellow signal documented
- [x] `| ai` command: available, capability-gated, documented
- [x] Outbound HTTPS works
- [x] Saved searches schedule on dev/trial license
- [x] Notable index strategy determined
- [x] All 5 veto checks scored
- [x] No hard vetoes

**Proceed to Phase 4.**

---

# Phase 4 — Session 1 (Brain + MCP BYOT)

**Date:** 2026-05-21
**Source spec:** [docs/bundle-0-phas4-recon.md](bundle-0-phas4-recon.md) Session 1
**Outcome:** **Brain layer unblocked. MCP BYOT proven.** Two architectures available for LLM calls (native `| ai` and outbound HTTP from custom command), both demonstrated end-to-end. MCP custom-tool registration works after a Splunk restart.

## What works (new in Phase 4)

| Capability | Status | Evidence |
|---|---|---|
| Splunk Hosted LLM probe | ✗ (expected) | `/services/server/scs/tenantinfo` → 404. SCS endpoints don't exist on local Enterprise + trial license. Confirmed it's a Splunk Cloud-only surface. |
| `Gemini` provider attached via AITK | ✓ | Wrote secret to `storage/passwords` (realm=`aitk_llm_secrets`, name=`gemini-default`); wrote KV row to `aitk_llm_connection`; wrote default-mapping row to `aitk_llm_default_mappings`. |
| `\| ai prompt="echo back the word hello"` end-to-end | ✓ | Returns `ai_result_1="hello"` via Gemini 2.5 Flash in **5.5s** wall time. |
| `\| squelch mode="llm_probe"` (outbound HTTP from custom command) | ✓ | Reads Gemini API key from `storage/passwords` via REST, POSTs to `generativelanguage.googleapis.com`, returns response. **671ms** wall time. |
| MCP custom-tool registration (BYOT) | ✓ (with caveats) | Tools written to `[mcp_tools]` KV + `[mcp_tools_enabled]` KV appear in MCP `tools/list` after restart. Custom tool `squelch_fp_rates_by_search` returns live data from `index=notable` via MCP. |
| `splunk-ai-canvas` enable | ✓ | `POST /services/apps/local/splunk-ai-canvas/enable` → 200; `disabled=False`. |
| AITK `edit_ai_commander_config` + `list_ai_commander_config` caps granted | ✓ | Manual UI grant by user. |

## What doesn't work (new findings)

| Capability | Status | Notes |
|---|---|---|
| MLTK's `aicommander` REST `action=create` | ✗ | The persistent handler self-calls splunkd at `/storage/collections/data/aitk_llm_connection` and **deadlocks at 60s** (the same process holds the connection slot). Worked around by writing the 3 underlying records directly (storage/passwords + 2 KV collections). |
| BYOT: invoking custom SPL command (`\| squelch`) via MCP | ✗ | MCP's `safe_spl.json` allowlist (143 commands) rejects `squelch` with `Forbidden command found`. BYOT tools that wrap allowlisted SPL work fine — see `squelch_fp_rates_by_search` finding above. **Architecturally:** to expose Squelch tools through MCP, either (a) wrap them as SPL searches against `index=notable` (works) or (b) edit `safe_spl.json` to allowlist `squelch`. Path (a) is preferred — keeps the MCP-callable surface declarative. |
| MCP refresh-on-demand without restart | ✗ (in our test) | New rows in `mcp_tools` weren't picked up by `refresh_custom_tools` after a write — the MCP persistent process was stuck in a private-key-lookup loop (see deadlock above). After `splunk restart`, tools loaded cleanly. **Open question:** is this always restart-required, or only when the handler is in a bad state? Re-test in Phase 8. |

## What's yellow (new)

| Item | Yellow because |
|---|---|
| Splunk's persistent-handler pattern can self-deadlock | Both MLTK's `aicommander` and MCP Server's tool-list path called back into their own splunkd while holding the request slot, causing 60s timeouts. Triggered by KV writes that fan out to other endpoints. **Mitigation:** for our own code (custom commands, REST handlers), avoid in-handler self-calls; use background jobs or external scripts when possible. |
| `mcp_tools_enabled._key` must equal the tool **name** | Not the same as `mcp_tools._key` (which is `<external_app_id>:<tool_name>`). Confusing schema; easy to insert correctly but only by reading the source. Documented in [scripts/seed_notable.py](../scripts/seed_notable.py) and [`squelch_fp_rates_by_search`] tool row. |
| Gemini provider routing through AITK requires 3 separate KV writes | The official `aicommander` POST handler does all of this atomically when it works; bypassing it (because of the deadlock) means we have to keep all 3 in sync ourselves on any change. Acceptable for hackathon; would want a small helper in production. |
| `splunk-ai-canvas` enabled but unexamined | Toggled `disabled=False` for parity with AITK's expected UI surface. Did **not** click around or test UI features. Re-visit only if we end up wanting that surface. |

## MCP BYOT — how to register a Squelch-callable tool

(Reference for Phase 8.)

### Step 1: write the tool definition

POST to `https://localhost:8089/servicesNS/nobody/Splunk_MCP_Server/storage/collections/data/mcp_tools` (admin basic auth):

```json
{
  "_key": "squelch:fp_rates_by_search",
  "name": "squelch_fp_rates_by_search",
  "title": "squelch_fp_rates_by_search",
  "description": "Returns FP rate per correlation search from index=notable.",
  "inputSchema": {
    "type": "object",
    "properties": {"min_rate": {"type": "string", "pattern": "^[0-9.]{1,5}$", "_meta": {"formatting": {"needs_quoting": false}}}},
    "required": []
  },
  "_meta": {
    "external_app_id": "squelch",
    "tags": ["squelch","fp_rate"],
    "execution": {"type": "spl", "template": "search index=notable | stats ... | where fp_rate >= $min_rate$", "row_limiter": true, "time_range": true},
    "built_in": false
  }
}
```

### Step 2: enable it

POST to `https://localhost:8089/servicesNS/nobody/Splunk_MCP_Server/storage/collections/data/mcp_tools_enabled`:

```json
{"_key": "squelch_fp_rates_by_search", "tool_id": "squelch:fp_rates_by_search", "collision_ids": []}
```

**Note**: `_key` must equal `name` from the tool definition; `tool_id` must equal `_key` from the tool definition.

### Step 3: `splunk restart`

The `refresh_custom_tools` path *should* pick up new rows live, but in our test it didn't — restart is the reliable trigger.

### Step 4: verify

`POST /services/mcp` with `{"jsonrpc":"2.0","method":"tools/list"}` — new tool should appear. Then `tools/call` to invoke.

---

# Phase 4 — Session 2 (Data Foundation)

**Date:** 2026-05-21
**Source spec:** [docs/bundle-0-phas4-recon.md](bundle-0-phas4-recon.md) Session 2
**Outcome:** **Notable index seeded with 1000 synthetic events. FP rates verified against seeded distribution. FP-cluster pattern visible.** Eval-harness data foundation in place.

## BOTSv3 deferred

Skipped per user direction: 30 GB download + ingest time isn't worth it for a solo hackathon when synthetic notable seeding is sufficient for the eval harness and demo. If we need richer attack telemetry in a later phase, planned as a separate session.

## What works

| Capability | Status | Evidence |
|---|---|---|
| `scripts/seed_notable.py` rerunnable | ✓ | `python scripts/seed_notable.py --count 1000 --clear-first` produces consistent output. Uses splunklib SDK from `.venv`. |
| Ingest rate | ✓ | ~475 events/sec via `service.indexes['notable'].submit()`. 1000 events in 2.1s. |
| `squelch_notable` sourcetype + props.conf KV extraction | ✓ | Added [/Applications/Splunk/etc/apps/squelch/default/props.conf](../../../Applications/Splunk/etc/apps/squelch/default/props.conf) with `KV_MODE = auto` + `TIME_PREFIX/TIME_FORMAT`. All 9 fields (`search_name`, `rule_name`, `urgency`, `status_label`, `owner`, `disposition`, `src_ip`, `dest`, `user`) extracted on search. |
| FP rate stats per search_name | ✓ | 0.24s query latency on 1000 events |
| Total status_label aggregation | ✓ | 398 FP / 602 TP in 0.18s |
| FP-cluster pattern visibility | ✓ | Top 3 src_ips by FP count: **10.0.1.50 (113), 10.0.1.51 (107), 10.0.1.52 (96)**. Random non-scanner IPs trail at 1 each. **This is the literal cluster signal Squelch's tune pipeline will find.** |
| Free-text dispositions round-trip | ✓ | Multi-word strings with colons (`"FP: scanner noise"`, `"TP: confirmed lateral movement"`) survive ingest + extract + aggregate cleanly. |

## Seeded distribution (verified, not requested)

| search_name | fp | tp | total | fp_rate | notes |
|---|---|---|---|---|---|
| `WindowsAuth_AnomalousLogonSource` | 104 | 21 | 125 | **0.83** | Squelch trigger (>0.70) |
| `Network_PortScan_Detected` | 93 | 32 | 125 | **0.74** | Squelch trigger |
| `DNS_TunnelExfil_Heuristic` | 89 | 36 | 125 | **0.71** | Squelch trigger |
| `Web_SuspiciousUserAgent` | 42 | 83 | 125 | 0.34 | healthy |
| `Process_RareParentChild` | 34 | 91 | 125 | 0.27 | healthy |
| `Endpoint_NewServiceInstalled` | 28 | 97 | 125 | 0.22 | healthy |
| `Data_BulkDownload_Sensitive` | 4 | 121 | 125 | 0.03 | pristine |
| `Identity_PrivEscalation_Confirmed` | 4 | 121 | 125 | 0.03 | pristine |

3 detections cross Squelch's >0.70 trigger threshold — gives the agent loop something to chew on for the demo.

## Architecture implications

- **Trigger layer's source-of-truth lookup is now real**: `index=notable sourcetype=squelch_notable | stats count(eval(status_label="false_positive")) as fp, count as total by search_name | eval fp_rate=fp/total | where fp_rate >= 0.70`. This is the SPL Squelch's Trigger layer will run periodically (probably on a 5-min cron via saved search, per Bundle 0 finding).
- **Memory/lineage joins**: the `search_name` field is the join key for KV store `detection_lineage` lookups. Already wired in Bundle 0 (`| outputlookup detection_lineage_lookup`).
- **Demo seeding script lives at [scripts/seed_notable.py](../scripts/seed_notable.py)**, tracked in git. Rerunnable with `--count` for scale tests. `--clear-first` for clean state.

## Out of scope (for Phase 4 Sessions 3-4, separate plan)

- Eval harness scaffolding (`run_eval.py`, golden dataset format, `| squelch mode="validate"` integration) — Session 3
- End-to-end dry run by hand (pencil test) — Session 4
- Architecture diagram — Session 4
- `direction-lock.md` updates — Session 4

---

# Phase 4 — Session 3 (Eval Harness Scaffolding)

**Date:** 2026-05-21
**Source spec:** [docs/bundle-0-phas4-recon.md](bundle-0-phas4-recon.md) Session 3
**Outcome:** **Eval harness operational end-to-end.** `run_eval.py` CLI, `| squelch mode="validate"` custom-command, and the recall-preservation gate are all proven on real seeded data. Baseline + tuned eval shows the demo's load-bearing claim: precision triples, recall preserved exactly.

## What ships

| Capability | Status | Evidence |
|---|---|---|
| 8 saved searches in squelch app | ✓ | [/Applications/Splunk/etc/apps/squelch/default/savedsearches.conf](../../../Applications/Splunk/etc/apps/squelch/default/savedsearches.conf); reload via `_reload` endpoint succeeded |
| `eval/eval_lib.py` shared library | ✓ | `evaluate_detection(...)` works; golden query is a parameter (Bundle 2 prep) |
| `eval/golden_dataset.conf` | ✓ | `[default]` stanza references the seeded dataset |
| `eval/run_eval.py` CLI | ✓ | `--all`, `--search-name`, `--spl + --label` all work |
| `eval/results/baseline_evals.csv` | ✓ | 8 detections eval'd; FP rates match seeded distribution within sampling tolerance |
| `eval/results/eval_results.csv` | ✓ | Tuned variant appended; visible alongside baseline |
| `eval_lib` vendored into squelch app | ✓ | `/Applications/Splunk/etc/apps/squelch/bin/lib/squelch_eval/` |
| `\| squelch mode="validate" search_name="..."` via REST | ✓ | Returns identical numbers to CLI |

## Baseline eval (S3.4) — all 8 detections, golden = seeded `index=notable`

| detection | tp | fp | fn | precision | recall | fp_rate | runtime_ms |
|---|---:|---:|---:|---:|---:|---:|---:|
| `WindowsAuth_AnomalousLogonSource` | 21 | 104 | 581 | 0.168 | 0.035 | 0.83 | 132 |
| `Network_PortScan_Detected` | 32 | 93 | 570 | 0.256 | 0.053 | 0.74 | 140 |
| `DNS_TunnelExfil_Heuristic` | 36 | 89 | 566 | 0.288 | 0.060 | 0.71 | 142 |
| `Web_SuspiciousUserAgent` | 83 | 42 | 519 | 0.664 | 0.138 | 0.34 | 144 |
| `Process_RareParentChild` | 91 | 34 | 511 | 0.728 | 0.151 | 0.27 | 130 |
| `Endpoint_NewServiceInstalled` | 97 | 28 | 505 | 0.776 | 0.161 | 0.22 | 138 |
| `Identity_PrivEscalation_Confirmed` | 121 | 4 | 481 | 0.968 | 0.201 | 0.03 | 131 |
| `Data_BulkDownload_Sensitive` | 121 | 4 | 481 | 0.968 | 0.201 | 0.03 | 132 |

`fp_rate` column matches seeded distribution exactly: 0.83 / 0.74 / 0.71 / 0.34 / 0.27 / 0.22 / 0.03 / 0.03 (per [data-inventory.md](data-inventory.md)). All runtimes sub-200ms on the 1000-event dataset.

**Why is recall so low?** Each detection only catches TPs from *its own search_name*; the denominator is "all TPs across all detections" (602). For Squelch's tuning gate what matters is per-detection recall **before vs after** tuning, not the absolute number. The gate is `new_recall >= baseline_recall`.

## Tuned eval (S3.5) — `WindowsAuth_AnomalousLogonSource + NOT src_ip IN (scanners)`

| | baseline | tuned | delta |
|---|---:|---:|---|
| TP | 21 | 21 | preserved ✓ |
| FP | 104 | 20 | **−81%** |
| precision | 0.168 | 0.512 | **+205%** |
| recall | 0.0349 | 0.0349 | preserved ✓ |
| fp_rate | 0.832 | 0.488 | −41% |
| runtime_ms | 132 | 169 | +28% (filter overhead) |

**Recall-preservation gate: PASSES.** This is the demo's load-bearing claim. Scanner IPs `10.0.1.50/51/52` contributed 84 of 104 baseline FPs; the filter eats them without touching any TP.

## `| squelch mode="validate"` integration (S3.8)

`| squelch mode="validate" search_name="WindowsAuth_AnomalousLogonSource"` via REST oneshot returned:
```
tp=21, fp=104, fn=581, precision=0.168, recall=0.0349, fp_rate=0.832, runtime_ms=132
```

Identical to the CLI baseline. Custom command imports the vendored `squelch_eval` module, fetches the saved-search SPL via splunklib, calls `evaluate_detection()` with the golden query, yields one row.

## What's yellow (new)

| Item | Yellow because |
|---|---|
| oneshot returns no search-time-extracted fields by default | `status_label`, `src_ip`, etc. are extracted by `props.conf` at search time but **not surfaced to JSONResultsReader** unless you pipe through `\| fields ...`. `eval_lib.evaluate_detection` wraps both queries with `\| fields _cd, status_label` to fix this. **Tripwire for Phase 8**: any code that calls `oneshot()` expecting custom fields needs the same wrapper or it'll see only default `_bkt`/`_cd`/`_raw`/`_si`/`_sourcetype`/`_time`/`host`/`index`/`linecount`/`source`/`sourcetype`. |
| Vendoring `eval_lib.py` requires manual copy on changes | We document this in [eval/README.md](../eval/README.md). For hackathon scope this is fine; long-term we'd want a build step. |

---

# Phase 4 — Session 4 (Dry-run + Architecture + Direction Lock)

**Date:** 2026-05-21
**Source spec:** [docs/bundle-0-phas4-recon.md](bundle-0-phas4-recon.md) Session 4
**Outcome:** **End-to-end workflow demonstrated by hand via REST/SPL only.** Architecture diagram + direction lock written. Phase 4 exit gate met.

## S4.1 — Pencil-test results

Executed the full 6-step workflow with no agent, just REST/SPL calls. Each step's wall-time captured.

| Step | What | Latency | Result |
|---|---|---:|---|
| 1 | Find detections with fp_rate > 0.70 via stats query | 0.24s | 3 detections returned: WindowsAuth (0.83), Network_PortScan (0.74), DNS_Tunnel (0.71) |
| 2 | Pull saved-search SPL by name (`/saved/searches/X`) | 0.04s | SPL retrieved verbatim |
| 3 | Inspect FP cluster via `stats count by src_ip` on fp_only events | 0.17s | Top 3 src_ips: 10.0.1.52 (29), 10.0.1.51 (28), 10.0.1.50 (27); next IP at 1 |
| 4 | Author tuned SPL (`NOT src_ip IN (...)`) | manual | n/a |
| 5 | Register tuned saved-search + invoke `\| squelch mode="validate"` via REST | 0.64s | precision=0.512, recall=0.0349, fp_rate=0.488 |
| 6 | Compare to baseline_evals.csv | manual | Precision 0.168 → 0.512 (+205%); recall preserved exactly |

**Total active query time: ~1.5 seconds across the 6 steps.** No friction worth flagging for Phase 8 — the workflow is fully demonstrable.

**Friction points captured for Phase 8 reference:**

- Step 4 ("author tuned SPL") is the **only manual step**. It's exactly where Squelch's Brain layer will replace the human — the clustering step (S4.1 Step 3 output) gives the LLM a structured input ("most FPs come from these 3 src_ips"), and the LLM produces the `NOT src_ip IN (...)` filter as output. The agent loop wires these together; everything else is mechanical.
- Step 5's "register tuned saved-search" is a Phase 8 question of taste: does Squelch write the tuned variant as a new saved search next to the original (low-risk, reviewable), or amend the existing one (in-place)? The pencil test used the former; **direction-lock.md ([D5](direction-lock.md#d5-memory--kv-store-detection_lineage)) implicitly assumes the former** since lineage tracking benefits from versioned variants.

## S4.2 — Architecture diagram

Written to [docs/architecture.md](architecture.md). ASCII + Mermaid. 6 boxes (Trigger, Brain, Memory, Eval, MCP, Output) with per-box status + repo file links.

## S4.3 — Direction lock

Written to [docs/direction-lock.md](direction-lock.md). 6 locked decisions:

| | Decision | Status |
|---|---|---|
| D1 | Brain layer = `\| ai` primary, outbound HTTP fallback (Gemini 2.5 Flash) | locked |
| D2 | MCP for reads, REST for writes; `\| squelch` never routes through MCP | locked |
| D3 | Eval semantics + recall-preservation gate + golden query as parameter | locked |
| D4 | Squelch-owned `index=notable`; no ES required | locked |
| D5 | Memory in KV `detection_lineage` | locked |
| D6 | Secrets in `storage/passwords` realm `aitk_llm_secrets` | locked |

Plus Phase 5 handoff notes: what the PRFAQ should and shouldn't commit to.

## Phase 4 exit gate — closed

Every box on [bundle-0-phas4-recon.md](bundle-0-phas4-recon.md) Phase 4 Exit Gate is either ticked or annotated as deferred (BOTSv3 only). Phase 5 is unblocked.


