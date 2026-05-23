# Direction Lock — Phase 4 Output

**Project:** Squelch — Automated Detection Tuning for Splunk
**Date:** 2026-05-21
**Status:** Phase 4 complete. Locked decisions below are the contract Phase 5 (Working Backwards / PRFAQ) writes against.

A locked decision is one we will **stop revisiting** unless the listed reversibility condition triggers. The PRFAQ commits to these; the demo is built around them; Phase 8 implementation references them by name.

---

## D1. Brain layer

**Decision.** Squelch's LLM call surface is **`| ai prompt="..."` in SPL**, backed by Gemini 2.5 Flash via the AI Toolkit's `aitk_llm_connection` KV. The custom-command outbound HTTP path (`| squelch mode="llm_probe"`) is the **fallback** for non-SPL contexts (e.g. an agent loop invoked from a script rather than from the search bar).

**Rationale.** SIEM engineers compose tunings in SPL; keeping the LLM call in SPL keeps the loop legible and reviewable. Both paths are proven; using `| ai` first means we inherit MLTK's provider config UI when we eventually need to rotate keys or swap models. The fallback path matters because `| ai` requires the user to be in a search context with the right capability; agent-driven invocations may not have that.

**Evidence.** [platform-shape.md § Phase 4 Session 1](platform-shape.md). `| ai` returned `"hello"` in 5.5s; outbound HTTP returned in 671ms.

**Reversible by:** Gemini 2.5 Flash quality is insufficient for SPL revision quality (Phase 8 builds will tell us); a provider outage forces us to add a second provider; or AITK's config surface changes shape in a future Splunk release.

---

## D2. MCP strategy — reads via MCP, writes via REST

**Decision.** Squelch **exposes** data-collection tools to other agents via Splunk_MCP_Server's BYOT mechanism (rows in the `mcp_tools` KV). Squelch **never** invokes its own custom command (`| squelch`) through MCP — that path is blocked by MCP's `safe_spl.json` allowlist and bypassing the allowlist is not on the table. All Squelch-internal writes (saved-search updates, KV upserts, index writes) go through splunklib REST oneshot in the squelch app context.

**Rationale.** MCP gives us a clean, well-documented surface for other agents to query Squelch's state without learning Splunk REST. But the allowlist makes MCP the wrong path for invoking our own custom command. The split keeps MCP as a read-oriented surface and REST as the write surface; this matches Splunk's own posture (MCP for "ask questions about your data," REST for "change configuration").

**Evidence.** [platform-shape.md § Phase 4 Session 1](platform-shape.md) — `squelch_fp_rates_by_search` registered and callable; `| squelch` blocked with `Forbidden command found`.

**Reversible by:** Splunk_MCP_Server adds a way to extend `safe_spl_commands`; we need other agents to *invoke* Squelch tunings (not just query state), in which case we register a non-`squelch`-prefixed tool that wraps the REST oneshot call.

---

## D3. Eval harness — golden dataset, recall preservation, metrics

**Decision.** Eval semantics are locked:

- **Golden dataset:** `search index=notable sourcetype=squelch_notable host=squelch-seed`, time range `-90d` → `now`. Defined in [eval/golden_dataset.conf](../eval/golden_dataset.conf).
- **Identity:** Splunk's `_cd` (internal event identifier) for set operations.
- **TP/FP/FN:** TP = detection fires on a `status_label=true_positive` event; FP = detection fires on `status_label=false_positive`; FN = `true_positive` event in golden but not in detection's fires.
- **Precision** = TP / (TP + FP); **Recall** = TP / (TP + FN); **FP rate** = FP / fires.
- **Recall-preservation gate:** any proposed tuning where `new_recall < baseline_recall` is **rejected**. This is non-negotiable.
- **Golden query is a parameter, not a hardcoded constant** — Bundle 2 (attack injection testing) will pass an alternate query that UNIONs the seeded set with injected synthetic TP events.

**Rationale.** SIEM engineers will not trust an automated tuner that drops their recall, no matter how much it improves precision. The recall gate is the load-bearing claim of the demo and the hackathon narrative. Parameterizing the golden query keeps Bundle 2 from needing a refactor.

**Evidence.** [platform-shape.md § Phase 4 Session 3](platform-shape.md), [eval/eval_lib.py](../eval/eval_lib.py), [eval/results/baseline_evals.csv](../eval/results/baseline_evals.csv) — baseline + tuned eval shows precision tripled (0.168 → 0.512), recall preserved exactly (0.0349 → 0.0349).

**Reversible by:** We discover that recall preservation alone isn't sufficient (e.g. tunings that preserve recall but blow up runtime); we'd add a runtime ceiling next to the recall floor.

---

## D4. Notable index — Squelch-owned, schema locked, seeded synthetically

**Decision.** Squelch owns `index=notable`. The schema is the 10 fields in [data-inventory.md](data-inventory.md): `_time, search_name, rule_name, urgency, status_label, owner, disposition, src_ip, dest, user`. The `status_label` enum is exactly `{true_positive, false_positive}`. Demo + eval seeding is via [scripts/seed_notable.py](../scripts/seed_notable.py). **We do not require Splunk Enterprise Security.**

**Rationale.** Without ES we'd have to invent something; with ES we'd inherit a schema that's overkill for hackathon scope. Owning the index means we control the labels, the cluster patterns, and the seed cadence. Hackathon judges shouldn't have to install ES to evaluate Squelch.

**Evidence.** [platform-shape.md § Phase 1](platform-shape.md) (notable index creatable on Enterprise + trial license); [data-inventory.md](data-inventory.md) (schema + seeded distribution).

**Reversible by:** A future deployment runs alongside real ES — then we'd add a `source_index` field and let Squelch tune both ES notables and its own. The schema is a superset of ES's already.

---

## D5. Memory — KV store `detection_lineage`

**Decision.** Per-detection memory (current SPL, FP rate history, tuning lineage, CIM fields used, lookups used, revision history) lives in the KV collection `detection_lineage`, defined in [/Applications/Splunk/etc/apps/squelch/default/collections.conf](../../../Applications/Splunk/etc/apps/squelch/default/collections.conf). The transform mapping is in [/Applications/Splunk/etc/apps/squelch/default/transforms.conf](../../../Applications/Splunk/etc/apps/squelch/default/transforms.conf). Reads via `| inputlookup detection_lineage_lookup`; writes via `| outputlookup detection_lineage_lookup append=true` or splunklib REST.

**Rationale.** KV store is durable (proven in Bundle 0), fast (sub-second CRUD), and accessible from both SPL (lookups) and Python (splunklib). It survives restarts. The schema is intentionally loose — Phase 8 will pin specific fields once the agent loop writes them.

**Evidence.** [platform-shape.md § V5: Durable State](platform-shape.md) (KV survives restart); [/Applications/Splunk/etc/apps/squelch/default/collections.conf](../../../Applications/Splunk/etc/apps/squelch/default/collections.conf).

**Reversible by:** KV store performance degrades past N detections (unlikely under hackathon scale); we'd switch to a real index with summary-search rollups.

---

## D6. Secrets — `storage/passwords` realm `aitk_llm_secrets`

**Decision.** All LLM API keys (Gemini today; OpenAI/Anthropic/etc. if added) live in Splunk's `storage/passwords` under realm `aitk_llm_secrets`. The `.env` file at repo root holds **only** developer-local Splunk admin creds + the MCP token; it never holds LLM keys after Phase 4 Session 1 (the `GOOGLE_API_KEY` line is for the seed-script ingest, not for the agent loop).

**Rationale.** `storage/passwords` is the path `| ai` already uses; keeping LLM secrets there means both the SPL path and the custom-command path read from one location. It's also the path that Splunk admins know how to rotate.

**Evidence.** [platform-shape.md § Phase 4 Session 1](platform-shape.md) — both `| ai` and `| squelch mode="llm_probe"` read from the same `aitk_llm_secrets:gemini-default` entry.

**Reversible by:** We need a key that isn't an LLM key (e.g. GitHub token for the Phase 8 PR-creation path); we'd add a new realm rather than reuse `aitk_llm_secrets`.

---

## Phase 5 handoff notes — what the PRFAQ should and shouldn't commit to

**Safe to commit to in the PRFAQ:**

- "Squelch tunes noisy Splunk correlation searches without dropping recall." ([D3](#d3-eval-harness--golden-dataset-recall-preservation-metrics))
- "Squelch ships as a Splunk App; no Enterprise Security license required." ([D4](#d4-notable-index--squelch-owned-schema-locked-seeded-synthetically))
- "Other agents can query Squelch's state through MCP." ([D2](#d2-mcp-strategy--reads-via-mcp-writes-via-rest))
- "Squelch uses Splunk's `| ai` command on Enterprise + dev license." ([D1](#d1-brain-layer))
- "Every Squelch-proposed tuning is scored against a golden dataset before it's shown to the user." ([D3](#d3-eval-harness--golden-dataset-recall-preservation-metrics))

**Do NOT over-commit to in the PRFAQ:**

- Specific token costs or LLM latencies for the **agent loop** — only the probe latencies are measured (5.5s for `| ai`, 671ms for outbound). Real prompts will be larger.
- That Squelch works against real Splunk ES notables — we've only proven it against our Squelch-owned `index=notable`.
- That `| ai` works on **every** Splunk license tier — Splunk Hosted Models needs SCS entitlement; on Enterprise + trial we use Gemini via the AI Commander config which is set up manually (D6 secrets entry + 2 KV rows).
- BOTSv3 attack-realistic event ingestion — deferred to a later session.

**Open questions for Phase 5 to surface:**

1. Do we narrate "before Squelch" / "after Squelch" with a real customer scenario in the PRFAQ, or stay abstract? The demo already has concrete numbers (precision 0.168 → 0.512, recall preserved). Concrete is more credible but harder to write generically.
2. How do we frame the MCP prize narrative? Squelch is callable through MCP (D2) — but the MCP-callable surface is read-only data; the actual tuning loop runs through splunklib REST. The PRFAQ needs to be precise about which is which.
3. The Brain layer has two paths (D1). Do we feature both in the PRFAQ, or pick one as canonical? Featuring both is honest but dilutes the narrative.

---

## Architecture pointers

- One-page system diagram: [architecture.md](architecture.md)
- All findings + evidence: [platform-shape.md](platform-shape.md)
- Data schema + seeded distribution: [data-inventory.md](data-inventory.md)
- Eval semantics + usage: [../eval/README.md](../eval/README.md)
