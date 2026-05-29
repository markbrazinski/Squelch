# Squelch: Adversarial Eval Harness for Splunk

An adversarial eval harness for Splunk detection logic — proposes, validates, and sometimes refuses to tune.

**[Devpost](https://devpost.com/software/squelch)** · **[Demo video](https://youtu.be/TODO)**

---

## What it does

Squelch analyzes false-positive patterns in Splunk alert queues, clusters them by field, proposes targeted SPL filters, and runs every proposal through an adversarial evaluation pipeline before anything ships. Three outcomes are possible: **tune** (PR with SPL diff), **decline to tune** (Issue with diagnosis), or **no action** (precision already acceptable).

The eval harness also ships standalone — `| squelch mode="eval"` gives you event-level precision and recall on any detection without running the agent.

---

## Quick start

### Prerequisites

- Splunk Enterprise or Developer License (tested on 9.x)
- Python 3.9+
- [Splunk MCP Server](https://splunkbase.splunk.com/) v1.1.3 installed
- GitHub personal access token (repo scope)
- Google Gemini API key

### Install

```bash
git clone https://github.com/markbrazinski/Squelch.git
cd Squelch
cp .env.example .env        # fill in your credentials
python -m venv .venv
source .venv/bin/activate
pip install splunk-sdk
```

Copy the Splunk app into your Splunk installation:

```bash
cp -r /Applications/Splunk/etc/apps/squelch /Applications/Splunk/etc/apps/
# or your Splunk $SPLUNK_HOME/etc/apps path
splunk restart
```

### Seed the golden dataset

```bash
python scripts/seed_notable.py --count 1000
```

Seeds 1,000 labeled notable events across 8 detections (~125 per detection) with realistic noise: 6 label formats, 20% unlabeled events, 3 distinct FP root causes.

### Run the pipeline

From Splunk Web (Search & Reporting):

```spl
| squelch mode="tune" search_name="DNS_TunnelExfil_Heuristic"
| table search_name decision decision_reason precision_before precision_after
```

### Run standalone eval (no agent, no GitHub)

```spl
| squelch mode="eval" search_name="DNS_TunnelExfil_Heuristic"
| table search_name precision recall perturbation_pass holdout_pass
```

---

## Architecture

See [architecture_diagram.md](architecture_diagram.md) for the full component diagram.

Five components in one horizontal flow:

1. **TRIGGER** — saved search fires when FP rate exceeds 0.70; label normalization via `disposition_normalization.csv`
2. **BRAIN** — Gemini 2.5 Flash proposes one `NOT {field} IN (...)` SPL clause; structural validator and syntax checker gate the output
3. **TOOLS** — Splunk MCP Server v1.1.3 (10 built-in tools) for reads; splunklib SDK for writes and command invocation; 1 custom BYOT tool (`squelch_fp_rates_by_search`)
4. **EVALS** — adversarial harness: event-level precision/recall, hard recall gate, attack injection, label perturbation, temporal holdout
5. **OUTPUT** — GitHub PR (tune accepted) or GitHub Issue (decline to tune) with full decision trail

---

## Demo results

Recording run (2026-05-27). Source: live Splunk output, PR #60 and Issue #61.

| Detection | Decision | Precision before | Precision after | Recall |
|---|---|---|---|---|
| DNS_TunnelExfil_Heuristic | accepted → PR #60 | 24% | 59% | held flat (6.5%) |
| Identity_PrivEscalation_Confirmed | accepted → PR #61 | 24% | 47% | held flat (6.7%) |
| Endpoint_NewServiceInstalled | declined → Issue | 21% | — | field extraction gap |

**415 notables → 115** across the two tunable detections after merging one PR.

Attack injection caught one unsafe IP in the DNS filter (192.168.40.81 — true positive hiding in scanner traffic). 10 IPs proposed, 1 excluded, 9 shipped.

---

## Project structure

```
Squelch/
├── eval/                        # eval harness library
│   ├── eval_lib.py              # evaluate_detection, gate_revision, perturb_and_eval, temporal_holdout_eval
│   ├── cluster.py               # cluster_fps, diagnose_fp_pattern, summarize_hypotheses
│   ├── attack_inject.py         # run_adversarial_eval, parse_not_filter
│   ├── revise.py                # propose_revision (LLM call + validation)
│   ├── github_integration.py    # create_pr_for_detection, create_issue, build_pr_body
│   ├── llm.py                   # call_gemini()
│   ├── utils.py                 # load_lookup()
│   ├── golden_dataset.conf      # golden dataset query definition
│   └── results/                 # verified CSV captures per bundle
├── scripts/
│   ├── seed_notable.py          # seed golden dataset into index=notable
│   ├── capture_tune_results.py  # capture run output to CSV
│   └── setup_github_secret.py   # store GitHub token in Splunk storage/passwords
├── lookups/
│   ├── disposition_normalization.csv  # 6 label formats → 2 canonical values
│   ├── scanner_ips.csv               # known scanner IP context
│   └── service_accounts.csv          # known service account context
├── detections/                  # SPL files for seeded detections
├── squelch_harness/             # PyPI package (squelch-harness v0.1.0)
├── docs/                        # build documentation, specs, retros
├── screenshots/                 # demo artifacts
│   ├── architecture-spine.png
│   ├── github-pr-60-dns.png
│   └── splunk-endpoint-declined.png
├── architecture_diagram.md      # component diagram
├── .env.example                 # required environment variables
└── pyproject.toml               # squelch-harness package config
```

The Splunk app lives at `/Applications/Splunk/etc/apps/squelch/` and is not included in this repo (Splunk app packaging requirements). The eval library is vendored into the app at `bin/lib/squelch_eval/`.

---

## Key design decisions

Every safety threshold is a named constant:

| Constant | Value | Controls |
|---|---|---|
| `MIN_TOP_ENTRY_FP_PCT` | 0.20 | Minimum explanatory power for a cluster to be filterable |
| `PERTURB_RECALL_PASS_THRESHOLD` | 0.05 | Max recall delta allowed under 10% label flip |
| `HOLDOUT_SPLIT_PCT` | 0.70 | 70% training / 30% temporal holdout |
| `HOLDOUT_PRECISION_FLOOR_DELTA` | 0.0 | Holdout precision must not degrade vs training |
| `DIAGNOSE_EMPTY_THRESHOLD` | 0.30 | Field empty in >30% of FPs triggers diagnosis path |
| `DIAGNOSE_SOURCETYPE_THRESHOLD` | 0.80 | >80% of empties from one sourcetype → extraction gap |

See [docs/direction-lock.md](docs/direction-lock.md) for the rationale behind each threshold.

---

## Limitations

- **Synthetic golden dataset.** The demo uses seeded data. Production deployment requires real analyst dispositions in `index=notable`.
- **NOT filters only.** The current agent generates one class of SPL revision. The eval harness validates any revision type.
- **Flat SPL only.** No macro resolution, eventtype expansion, or CIM field alias handling.
- **MCP reads only.** Splunk MCP Server's command allowlist blocks `| squelch`. Write paths use splunklib SDK directly.
- **Single-field filters.** Each proposal targets one field. Multi-field compound filters are not yet generated.

---

## Built with

- Python-3
- Splunk-Enterprise
- Splunk-MCP-Server-v1.1.3
- Splunk-KV-Store
- Splunk-Python-SDK
- Gemini-2.5-Flash
- GitHub-REST-API
- PyPI
- Claude-Code

---

## License

MIT — see [LICENSE](LICENSE).
