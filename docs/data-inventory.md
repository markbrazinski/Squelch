# Data Inventory — Phase 4 Session 2 Snapshot

**Date:** 2026-05-21
**Splunk:** Enterprise 10.4.0 at `/Applications/Splunk`

## Indexes in use by Squelch

| Index | Owner | Purpose | Sourcetype(s) | Approx events | Notes |
|---|---|---|---|---|---|
| `notable` | Squelch (synthetic) | Per-event FP/TP labels for the Trigger layer + eval harness | `squelch_notable` | 1000 (seeded) | Created in Bundle 0 via REST `POST /services/data/indexes`. Schema mirrors Splunk ES `notable` but **we own it**, no ES license required. |
| `_internal` | Splunk | Used only for sanity-check searches | many (mcp_server, mongod, splunkd, etc.) | live, growing | Not Squelch state. |

## `index=notable` schema

Fields extracted at search time by [`squelch/default/props.conf`](../../Applications/Splunk/etc/apps/squelch/default/props.conf) (`KV_MODE = auto` on sourcetype `squelch_notable`):

| Field | Type | Cardinality | Example | Purpose |
|---|---|---|---|---|
| `_time` | epoch | 1000 values, spread over last 30 days | parsed from leading epoch in `_raw` (`TIME_PREFIX=^ TIME_FORMAT=%s`) | bucket by recency |
| `search_name` | string | 8 distinct | `WindowsAuth_AnomalousLogonSource` | **join key** to `detection_lineage` KV |
| `rule_name` | string | 8 distinct | same as `search_name` in seed | reserved for ES interop |
| `urgency` | enum | `low\|medium\|high\|critical` | `medium` | UI display, not used by Squelch logic |
| `status_label` | enum | `false_positive\|true_positive` | `false_positive` | **primary signal** for FP rate computation |
| `owner` | string | 3 values: `analyst1\|2\|3` | `analyst2` | provenance |
| `disposition` | free text | ~7 distinct | `"FP: scanner noise"` | clustering input for Squelch's pattern-finder |
| `src_ip` | IPv4 | 200+ distinct; 3 "scanner" IPs heavily over-represented in FPs | `10.0.1.50` | cluster pattern that Squelch's eventual filter rule should match |
| `dest` | IPv4 | wide spread | `10.50.12.97` | reserved for future correlation |
| `user` | string | 5 values | `bob` | reserved for future correlation |

## Seeded distribution (per [scripts/seed_notable.py](../scripts/seed_notable.py))

8 detections × 125 events = 1000 events. Buckets:

- **Squelch-trigger band (fp_rate > 0.70)**: 3 detections (`WindowsAuth_AnomalousLogonSource` 0.83, `Network_PortScan_Detected` 0.74, `DNS_TunnelExfil_Heuristic` 0.71)
- **Healthy band (0.20-0.40)**: 3 detections (`Web_SuspiciousUserAgent` 0.34, `Process_RareParentChild` 0.27, `Endpoint_NewServiceInstalled` 0.22)
- **Pristine band (<0.05)**: 2 detections (`Data_BulkDownload_Sensitive` 0.03, `Identity_PrivEscalation_Confirmed` 0.03)

FP cluster pattern: **78% of FPs carry `src_ip in (10.0.1.50, 10.0.1.51, 10.0.1.52)`** (the "scanner" IPs). Random `192.168.x.x` makes up the rest. This is what Squelch's clustering step should discover and turn into a `NOT src_ip IN (...)` filter.

## KV store collections in use

| Collection | App | Purpose | Status |
|---|---|---|---|
| `detection_lineage` | `squelch` | Per-detection SPL history, FP rate, last-tuned timestamp. Memory layer. | Created in Bundle 0, empty. Schema in [`squelch/default/collections.conf`](../../Applications/Splunk/etc/apps/squelch/default/collections.conf). |
| `smoke_test_collection` | `squelch` | Phase 1 validation only. | Created in Bundle 0, empty. Can be deleted later. |
| `mcp_tools` | `Splunk_MCP_Server` | Custom MCP tool definitions (BYOT). | 2 Squelch tools registered: `squelch:tune_detection`, `squelch:fp_rates_by_search`. |
| `mcp_tools_enabled` | `Splunk_MCP_Server` | Per-tool enable toggle. | 16 rows (9 builtins + 4 saia_* + 2 squelch + 1 seeded marker). |
| `aitk_llm_connection` | `Splunk_ML_Toolkit` | LLM provider config (Brain layer). | 1 row: `gemini-default` → Gemini 2.5 Flash. |
| `aitk_llm_default_mappings` | `Splunk_ML_Toolkit` | Default LLM per user. | 1 row: `mark@brazinski.us` → `gemini-default`. |

## Splunk `storage/passwords` secrets in use

| Realm | Username | Purpose |
|---|---|---|
| `aitk_llm_secrets` | `gemini-default` | Google AI Studio API key for Gemini 2.5 Flash. Used by both `| ai` and `| squelch mode="llm_probe"`. |

## What's NOT in the inventory (deferred)

- **BOTSv3 dataset** — deferred per user direction (30 GB + ingest cost). Synthetic notable seeding is sufficient for the eval harness and demo. Future-session item.
- **Real Splunk ES notable index** — we don't have ES; our `index=notable` mimics the schema and is fully under our control.
- **Splunk Hosted Models** — unavailable on local Enterprise (SCS endpoint 404s). Not in inventory.

## Re-seeding

```bash
cd /Users/markbrazinski/Desktop/coding\ fun/Squelch
. .venv/bin/activate
python scripts/seed_notable.py --count 2952 --clear-first
```

`--count 2952` (369 events/detection) gives ~225 labeled FPs per demo detection at fp_rate=0.78,
producing the demo headline numbers (450 before → 260 after on DNS+Identity). Lower counts
have enough variance to flip the trigger threshold check on unlucky draws.

Takes ~2 seconds to ingest + 5-15 seconds before searchable. Wait for `index=notable sourcetype=squelch_notable | stats count` to equal the requested count before running eval queries.
