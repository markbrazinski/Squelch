# eval/

Eval harness for Squelch. Two consumers:

1. **CLI:** `python eval/run_eval.py --all` — used by humans + scripts to benchmark detections against the golden dataset.
2. **`| squelch mode="validate"`** — Splunk custom command import path. Uses a **vendored copy** of `eval_lib.py` at:
   ```
   /Applications/Splunk/etc/apps/squelch/bin/lib/squelch_eval/eval_lib.py
   ```

## Re-vendoring after eval_lib.py changes

Single-source-of-truth lives here at `eval/eval_lib.py`. After editing:

```bash
cp eval/eval_lib.py /Applications/Splunk/etc/apps/squelch/bin/lib/squelch_eval/eval_lib.py
```

(No restart needed; Splunk custom commands import on each invocation.)

## Files

| File | Purpose |
|---|---|
| `eval_lib.py` | Core `evaluate_detection()` + `EvalResult`. Golden query is a parameter, not a hardcoded constant — Bundle 2 attack-injection testing needs to inject synthetic TP events without a refactor. |
| `run_eval.py` | CLI: `--search-name`, `--spl + --label`, `--all`. Writes a row per run to `--out` (default `eval/results/eval_results.csv`). |
| `golden_dataset.conf` | INI defining the golden dataset (`query`, `earliest`, `latest`). Bundle 2 may add stanzas; CLI selects with `--golden-stanza`. |
| `results/baseline_evals.csv` | Eval-all snapshot of the 8 seeded detections **as-is**. The "before" of the before/after demo. |
| `results/eval_results.csv` | Append-only log of every eval run. |

## Eval semantics

- **TP**: detection SPL returns an event whose `status_label="true_positive"`
- **FP**: detection SPL returns an event whose `status_label="false_positive"`
- **FN**: a `status_label="true_positive"` event in the golden dataset that the detection SPL does NOT return
- **Precision** = TP / (TP + FP)
- **Recall** = TP / (TP + FN)
- **Tuning gate** (`evaluate_recall_preserved`): proposed tuning is rejected if `new_recall < old_recall`.

## Identity

Set ops use Splunk's `_cd` (per-event internal identifier) — stable across re-reads of the same buckets. The eval wraps user-supplied SPL with `| fields _cd, status_label` so JSON results carry only what we need (search-time field extraction is otherwise omitted by `oneshot()`).
