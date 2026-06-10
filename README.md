# Squelch: Adversarial Eval Harness for Splunk

An adversarial eval harness for Splunk detection logic — proposes, validates, and sometimes refuses to tune.

**[Devpost](https://devpost.com/software/squelch)** · **[Demo video](https://youtu.be/u14nCE6buaQ)**

---

## What it does

Squelch analyzes false-positive patterns in Splunk alert queues, clusters them by field, proposes targeted SPL filters, and runs every proposal through an adversarial evaluation pipeline before anything ships. Three outcomes are possible: **tune** (PR with SPL diff), **decline to tune** (Issue with diagnosis), or **no action** (precision already acceptable).

The eval harness also ships standalone — `| squelch mode="eval"` gives you event-level precision and recall on any detection without running the agent.

---

## Quick start

### Prerequisites

- Splunk Enterprise or Developer License (tested on 10.x)
- Python 3.9+
- [Splunk MCP Server](https://splunkbase.splunk.com/) v1.1.3 installed
- GitHub personal access token (repo scope)
- Google Gemini API key

### Install

```
git clone https://github.com/markbrazinski/Squelch.git
cd Squelch
cp .env.example .env        # fill in your credentials
python -m venv .venv
source .venv/bin/activate
pip install splunk-sdk
```

Copy the Splunk app into your Splunk installation:

```
cp -r /Applications/Splunk/etc/apps/squelch /Applications/Splunk/etc/apps/
# or your Splunk $SPLUNK_HOME/etc/apps path
splunk restart
```

### Data

The demo runs against **BOTSv3** — Splunk's public attack simulation dataset (Frothly / Taedonggang). Labels come from the published attack scenario (coinhive cryptominer domains = true positive), so results are reproducible against data we didn't author. The two BOTSv3 detections (`DNS_SuspiciousResolution_Botsv3`, `Endpoint_RareProcess_Botsv3`) and their golden queries ship in the Splunk app's `default/savedsearches.conf` and in [`eval/golden_dataset.conf`](eval/golden_dataset.conf). Ingest BOTSv3 into an `index=botsv3`, then mirror the labeled events into `index=notable` with `scripts/seed_notable_botsv3.py` so the live `| squelch` command can see them.

For a quick local test **without** ingesting BOTSv3, seed the synthetic dataset:

```
python scripts/seed_notable.py --count 1000
```

Seeds labeled notable events across multiple detections with realistic noise (mixed label formats, unlabeled events, distinct FP root causes including a field-extraction gap).

### Run the pipeline

From Splunk Web (Search & Reporting):

```
| squelch mode="tune" search_name="DNS_SuspiciousResolution_Botsv3"
| table search_name decision recall_before recall_after attack_injection_excluded perturbation_pass
```

### Run standalone eval (no agent, no GitHub)

```
| squelch mode="eval" search_name="DNS_SuspiciousResolution_Botsv3"
| table search_name precision recall perturbation_pass holdout_pass
```

---

## Architecture

See [architecture_diagram.md](https://github.com/markbrazinski/Squelch/blob/main/architecture_diagram.md) for the full component diagram.

Five components in one horizontal flow:

1. **TRIGGER** — scheduled saved search ranks every detection by false-positive rate; the noisiest are selected for tuning. Label normalization via `disposition_normalization.csv`
2. **BRAIN** — Gemini 2.5 Flash proposes one `NOT {field} IN (...)` SPL clause; structural validator and syntax checker gate the output
3. **TOOLS** — Splunk MCP Server v1.1.3 (10 built-in tools) for reads; splunklib SDK for writes and command invocation; 1 custom BYOT tool (`squelch_fp_rates_by_search`)
4. **EVALS** — adversarial harness: event-level precision/recall, hard recall gate, attack injection, label perturbation, temporal holdout
5. **OUTPUT** — GitHub PR (tune accepted) or GitHub Issue (decline to tune) with full decision trail

---

## Demo results

Validated against **BOTSv3**. Source: live Splunk output — [PR #70](https://github.com/markbrazinski/Squelch/pull/70) and [Issue #71](https://github.com/markbrazinski/Squelch/issues/71).

| Detection | Decision | Baseline FP rate | Outcome |
| --- | --- | --- | --- |
| `DNS_SuspiciousResolution_Botsv3` | accepted → PR #70 | 99.8% | 10,236 → 2,726 FPs (73% fewer), recall 1.000 (all 21 threats kept) |
| `Endpoint_RareProcess_Botsv3` | declined → Issue #71 | 45.8% | field extraction gap — `src_ip` 0% populated across FPs; filed diagnosis instead of a filter |

Attack injection caught one unsafe IP in the DNS filter (`172.16.0.13` — true-positive traffic hiding among the filter candidates). 9 IPs proposed, 1 excluded, 8 shipped.

Perturbation on DNS returned **WARN** (21 true positives is too small a population for a meaningful label-flip test — reported honestly, not suppressed). Temporal holdout: PASS on both detections.

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
│   └── results/                 # verified CSV captures per run
├── scripts/
│   ├── seed_notable.py          # seed synthetic dataset into index=notable
│   ├── capture_tune_results.py  # capture run output to CSV
│   └── setup_github_secret.py   # store GitHub token in Splunk storage/passwords
├── lookups/
│   ├── disposition_normalization.csv  # label formats → 2 canonical values
│   ├── scanner_ips.csv               # known scanner IP context
│   └── service_accounts.csv          # known service account context
├── detections/                  # SPL files for detections
├── squelch_harness/             # standalone eval package — published on PyPI as squelch-harness v0.1.0
├── docs/                        # build documentation, specs, retros
├── screenshots/                 # demo artifacts (architecture, DNS PR, endpoint decline)
├── architecture_diagram.md      # component diagram
├── .env.example                 # required environment variables
└── pyproject.toml               # package config
```

The Splunk app lives at `/Applications/Splunk/etc/apps/squelch/` and is not included in this repo (Splunk app packaging requirements). The eval library is vendored into the app at `bin/lib/squelch_eval/`.

---

## Key design decisions

Every safety threshold is a named constant:

| Constant | Value | Controls |
| --- | --- | --- |
| `MIN_TOP_ENTRY_FP_PCT` | 0.20 | Minimum explanatory power for a cluster to be filterable |
| `PERTURB_RECALL_PASS_THRESHOLD` | 0.05 | Max recall delta allowed under 10% label flip |
| `HOLDOUT_SPLIT_PCT` | 0.70 | 70% training / 30% temporal holdout |
| `HOLDOUT_PRECISION_FLOOR_DELTA` | 0.0 | Holdout precision must not degrade vs training |
| `DIAGNOSE_EMPTY_THRESHOLD` | 0.30 | Field empty in >30% of FPs triggers diagnosis path |
| `DIAGNOSE_SOURCETYPE_THRESHOLD` | 0.80 | >80% of empties from one sourcetype → extraction gap |

See [docs/direction-lock.md](https://github.com/markbrazinski/Squelch/blob/main/docs/direction-lock.md) for the rationale behind each threshold.

---

## Limitations

- **NOT filters only.** The current agent generates one class of SPL revision. The eval harness validates any revision type.
- **Flat SPL only.** No macro resolution, eventtype expansion, or CIM field alias handling.
- **MCP reads only.** Splunk MCP Server's command allowlist blocks `| squelch`. Write paths use splunklib SDK directly.
- **Single-field filters.** Each proposal targets one field. Multi-field compound filters are not yet generated.
- **Production labels.** The demo uses BOTSv3's published scenario labels; production deployment requires real analyst dispositions in `index=notable`.

---

## Built with

- Python 3
- Splunk Enterprise
- Splunk MCP Server v1.1.3
- Splunk KV Store
- Splunk Python SDK
- Gemini 2.5 Flash
- GitHub REST API
- Claude Code

---

## License

MIT — see [LICENSE](https://github.com/markbrazinski/Squelch/blob/main/LICENSE).