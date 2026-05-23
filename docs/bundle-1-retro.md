# Bundle 1 Retrospective

**Date:** 2026-05-22
**Build spec:** [bundle-1-plan.md](bundle-1-plan.md)
**Execution plan:** [`~/.claude/plans/review-users-markbrazinski-desktop-codin-functional-pizza.md`](../../../.claude/plans/review-users-markbrazinski-desktop-codin-functional-pizza.md)
**Outcome:** Bundle 1 exit gate satisfied. `| squelch mode="tune"` runs end-to-end on Detection 1, accepts the LLM-proposed tuning, rejects a deliberately-bad force-injected revision, persists both to KV, never mutates the saved search.

---

## Velocity vs. plan

Spec budgeted 10 sessions (1–10); planned mapping:

| Spec session | Planned scope | What actually shipped | Sessions used |
|---|---|---|---|
| 1–2 | Eval harness hardening | `gate_revision`, `snapshot_baseline`, `as_metric_dict`, fired/golden id sets in `EvalResult` | 1 (compressed) |
| 3–4 | FP clustering | `pull_labeled_events`, `cluster_fps`, scanner_ips lookup wiring | 1 |
| 5–6 | SPL revision generation | `call_gemini`, `propose_revision`, `_llm_probe` refactor | 1 |
| 7–8 | End-to-end wiring | `_tune` method, KV schema extension, append-only writes | 1 |
| 9 | Rejection case | `force_revision` Option + branch | 1 |
| 10 | Safety-net video + retro | This doc (video deferred) | 1 (in progress) |

**Actual sessions: ~6 of 10 budgeted.** Spec assumed each numbered pair was real session-shaped work; in practice every "double" collapsed to one session because Bundle 0 / Phase 4 had already done more groundwork than the spec credited.

---

## What took longer than expected

**Not much, actually — none of this was painful.** The closest things to friction:

- **Reconciling spec paths against current repo state.** Spec said `scripts/run_eval.py` and `bin/squelch.py`; actuals were `eval/run_eval.py` and `/Applications/Splunk/etc/apps/squelch/bin/squelch_command.py`. Spent the first 10 minutes of Session 1 building the path-correction table at the top of the plan file. Worth the time — referenced it every subsequent session.
- **Vendoring discipline.** Five modules (`eval_lib`, `cluster`, `llm`, `revise`) now live in two places: `eval/` for offline CLI/testing and `bin/lib/squelch_eval/` for the custom command. Three times I edited the repo copy and forgot to `cp` to the vendor dir; each time the next self-test caught it within 30 seconds because the custom command kept seeing stale behavior. Mitigation worth keeping: every self-test that exercises the custom command (not just the eval CLI) implicitly checks vendoring is current.
- **The `from eval_lib import ...` vs `from .eval_lib import ...` dual-context import.** `cluster.py` needs to work both repo-side (siblings on sys.path) and vendored (inside a package). Solved with try/except absolute-vs-relative. Five minutes of thinking to land on the pattern, then trivial.

---

## What was easier than expected

- **The LLM converged on the right SPL on the first attempt, every time.** Sessions 5–6 budgeted a "second attempt on syntax error" retry path. Across all the Bundle 1 self-tests, `attempts` was always 1. Gemini 2.5 Flash with the "Output ONLY the SPL" prompt + the structured cluster context produced bit-identical `NOT src_ip IN ("10.0.1.52","10.0.1.51","10.0.1.50")` clauses (only order varies). 1.8–2.2s end-to-end. **The retry path is real code that's never been exercised in production runs.**
- **`evaluate_recall_preserved` had zero external callers**, so swapping it for the structured `gate_revision` was additive only. The back-compat shim added in Sessions 1–2 ([eval_lib.py](../eval/eval_lib.py)) is dead weight; can be deleted in Bundle 2.
- **transforms.conf reload via REST `_reload` worked first try.** The "What this plan does NOT do" reload-ladder note budgeted up to 3 attempts (`| debug refresh` → REST `_reload` → restart). REST returned 200 and `_reload` ladder step #2 succeeded; never needed step #3.
- **KV writes via `service.kvstore["..."].data.insert(payload)`** were one line. Spec implied raw REST plumbing; splunklib has a clean idiom that the spec's authors apparently didn't know about either.
- **`force_revision` was 12 lines.** Session 9's whole story is one new `Option` + one if/else branch in `_tune`. The full reject path (KV write with `events_lost`, structured result row, saved-search untouched) was already wired in Sessions 7–8 — Session 9 just needed a way to deterministically hit it.

---

## What surprised me

- **`events_lost` is identity-stable across pipeline runs.** When Sessions 1–2 first found `_cd=1:9198` as the lost event from filtering `src_ip="10.97.229.104"`, I expected the value to drift between re-seeds. It didn't — the same `_cd` appeared in Session 9's KV row days later. Splunk's `_cd` is genuinely a stable bucket-internal identifier; the [direction-lock.md D3](direction-lock.md) "identity = `_cd`" decision is load-bearing in a way I didn't fully appreciate at lock time.
- **Total tune-pipeline wall time is dominated by the LLM call.** Sessions 7–8 measured 2727ms total; ~1800ms of that is `call_gemini`. The two `evaluate_detection` calls + cluster + KV write together are <900ms. Bundle 2's attack-injection eval will add a third `evaluate_detection` call but won't materially move the budget.
- **Reject-path is 3.6× faster than accept-path** (753ms vs 2727ms) because `force_revision` skips the LLM. Worth knowing for Bundle 4 if it ever wants to demo "we caught 100 bad revisions in N seconds" — that math works against the force path, not the LLM path.
- **The seed script's 78%-scanner-FP target hit 80.8% in the actual data.** Sampling noise on 104 FPs. Close enough that I never had to recalibrate the demo numbers, but worth flagging that the spec's "expect 0.78" is approximate.

---

## Architectural decisions that aged well (so far)

- **D1: `| ai` as primary, outbound HTTP as fallback** → Bundle 1 ended up using the outbound HTTP path inside `_tune` (faster, 671–1900ms vs 5.5s for `| ai`), with the same secret store. The fallback became the primary for the agent loop; `| ai` is the primary for SIEM-engineer-typed prompts. Both paths are alive and tested.
- **D3: golden query as a parameter, not hardcoded** → Bundle 1 never had to exercise this, but the function signature in `evaluate_detection` is ready for Bundle 2's attack-injection UNION query without a refactor. Cost: one extra arg. Worth it.
- **Append-only KV writes** → decided in Sessions 7–8, locked in plan-mode. Decision trail falls out for free; Bundle 4's UI can read `| inputlookup ... | sort -decision_timestamp` and have the whole history. No second collection needed.

## Architectural decisions worth revisiting

- **Hardcoded `/Applications/Splunk/etc/apps/squelch/lookups/scanner_ips.csv`** in [squelch_command.py](../../../Applications/Splunk/etc/apps/squelch/bin/squelch_command.py). Hackathon-machine-specific. Bundle 3 packaging needs to derive this from `self.metadata.searchinfo.app_root` or a relative path. Flagged in Sessions 3–4 plan, deferred per scope. Easy fix when needed.
- **`detection_lineage_lookup` `fields_list` carries 8 legacy fields (`detection_name, current_spl, fp_rate, tp_count, last_tuned, cim_fields_used, lookups_used, revision_history`)** that Bundle 1 never writes. They were placeholders from Bundle 0. KV store is schemaless so they cost nothing at runtime, but they pollute `| inputlookup` output. Bundle 2 cleanup item.
- **`evaluate_recall_preserved` shim** at [eval_lib.py](../eval/eval_lib.py:180) is the bool-returning predecessor of `gate_revision`. Zero callers exist. Bundle 2 deletion candidate.

---

## Demo-fit check

Comparing Bundle 1 output to the demo script's beat structure:

| Demo beat | Bundle 1 surface | Gap |
|---|---|---|
| "340 notables → 19 after tune. Precision 14% → 87%." | Real Bundle 1 numbers: 125 events for Detection 1, 21 TP + 104 FP → 21 TP + 20 FP. Precision 16.8% → 51.2%. | Bundle 2 re-seeds with noisier labels and recalibrates. Bundle 1 numbers are correct; just smaller because the synthetic data is cleaner. |
| `[HYPOTHESIS] src_ip cluster: 78% ✓ \| [HYPOTHESIS] user+time: 11% ✗` | `cluster_fps` returns `by_field["src_ip"]`, `by_field["user"]`, `by_field["dest"]`. Each row has `fp_pct` + `tp_pct` for the ✓/✗ derivation. | Display is Bundle 4. Data is here. |
| Decision trail in PR body | KV row carries `original_spl`, `revised_spl`, `eval_before`, `eval_after`, `decision_reason` (with `events_lost`). | PR body templating is Bundle 3 (Git output). |
| Rejection case with explanation | `| squelch mode="tune" search_name=... force_revision=<bad SPL>` → `decision="rejected"` with `events_lost=['1:9198']`. | None — works today. |
| Git PR creation | — | Bundle 3. |
| Label normalization | — | Bundle 2. |
| Attack injection in eval | — | Bundle 2 (golden_query parameter is ready). |

**Verdict:** Bundle 1's data shape supports the demo script. Display layer + Git output + noisy-data realism land in Bundles 2–4 as planned. No structural gaps.

---

## Bundle 2 estimates — adjust from Bundle 1 actuals

Bundle 2 spec is "noisy labels + label normalization + attack injection." Reusing the Bundle 1 velocity ratio (~1.7 spec-sessions per actual session):

- **Bundle 2 budget (per spec):** 8 sessions (11–18)
- **Bundle 2 estimate (per actuals):** 5–6 sessions, IF the same shape holds (every spec "double" is one actual session)

Risk factors that could push Bundle 2 longer:
1. **Label normalization is a new code path with no Bundle 0 groundwork**, unlike eval / cluster / revise which all had precursors. Probably 2 sessions on its own.
2. **Attack injection requires synthetic TP event generation**, which is new — `seed_notable.py` only generates labeled-historical data. Probably 1 session.
3. **Re-seeding with noisy labels means the existing baseline numbers in [baseline_evals.csv](../eval/results/baseline_evals.csv) drift** — every Bundle 1 acceptance check that asserts specific numbers needs recalibration. Annoying but mechanical, ~½ session.

**Net Bundle 2 estimate: 6–7 sessions.** Slightly above the 1.7× ratio because of the from-scratch label normalization. Still well inside the spec budget.

---

## Decisions to carry into Bundle 2

1. **Vendoring discipline:** every new module in `eval/` gets a sibling in `bin/lib/squelch_eval/` and gets re-exported from `__init__.py`. Established in Bundle 1; keep it.
2. **Self-test pattern:** every session ends with a Python script that exercises the new code against live Splunk. No mocks. The pattern caught 3 bugs in Bundle 1 that unit tests would have missed (vendoring drift, the `from eval_lib` import path, transforms.conf reload). Keep it.
3. **Plan mode discipline:** every session boundary is a fresh `plan mode` invocation that refines the existing plan block. The 4 user-clarification questions per session caught design ambiguities before code happened. Keep it.
4. **Append-only KV writes:** Bundle 2 should write its label-normalization decisions to the same `detection_lineage` collection (new fields, not new rows). Bundle 4 will then have one collection to read from.

---

## Open items at Bundle 1 close

- [ ] **Safety-net video (Session 10 item 1):** not recorded yet. Bundle 1's submission is shippable without it but spec asks for it as insurance.
- [ ] **No git commits.** All Bundle 1 code is uncommitted in `/Users/markbrazinski/Desktop/coding fun/Squelch` and the Splunk app dir. Bundle 2 should open with a `git init` + first commit; otherwise a single `rm -rf` of the wrong directory loses 6 sessions of work.
- [ ] **Bundle 2 kickoff:** plan mode against the bundle-1-plan.md follow-on, scope label normalization first since it gates the noisy-label re-seed.
