# Recording Run Book

End-to-end commands and SPL for each beat, in order. Run top to bottom.
Numbers are locked to the current seed (2952 events, fp_rate=0.78).

---

## Before you start

**Close any open PRs on GitHub first.** Go to the repo → Pull requests → close all open squelch PRs manually. This ensures the recording starts clean.

---

## Terminal — Re-seed (only needed if data has drifted or you want a fresh start)

```bash
cd /Users/markbrazinski/Desktop/coding\ fun/Squelch
. .venv/bin/activate
python scripts/seed_notable.py --count 2952 --clear-first
```

Wait 15 seconds before running anything in Splunk.

---

## Beat 1 — The Mess

**What to show:** slow scroll through the raw notable index. Six label formats visible, blank cells.

```spl
index=notable sourcetype=squelch_notable host=squelch-seed
| table _time search_name status_label src_ip user dest_ip
| sort - _time
```

Scroll slowly. The mess is the point — six different status_label values, blanks everywhere.

---

## Beat 2 — The Trigger

**What to show:** the normalization lookup and the three detections above threshold.

**Step 1 — show the saved search with the lookup visible (Beat 2 on-screen moment):**

```spl
index=notable sourcetype=squelch_notable host=squelch-seed
| lookup disposition_normalization status_label OUTPUT normalized_label
| eval normalized_label=coalesce(normalized_label, status_label)
| stats count(eval(normalized_label="false_positive")) as labeled_fp,
        count(eval(normalized_label="true_positive")) as labeled_tp
  by search_name
| eval fp_rate=round(labeled_fp/(labeled_fp+labeled_tp),3)
| where fp_rate >= 0.70
| sort - fp_rate
| table search_name fp_rate labeled_fp labeled_tp
```

**Expected output:** 5 detections above 0.70. The demo story focuses on the three:
- `DNS_TunnelExfil_Heuristic` — ~0.70
- `Identity_PrivEscalation_Confirmed` — ~0.76
- `Endpoint_NewServiceInstalled` — ~0.74

> **VO fires here:** *"Three detections hit seventy percent. The agent fires."*

---

## Beat 3 — Detection 1: Scanner IPs

**What to show:** the tune command running, then the output table.

```spl
| squelch mode="tune" search_name="DNS_TunnelExfil_Heuristic"
| table search_name decision precision_before precision_after recall_before recall_after hypothesis_summary attack_injection_excluded perturbation_pass
```

**Expected output:**

| Field | Value |
|---|---|
| decision | accepted |
| precision_before | 0.2996 |
| precision_after | 0.6557 |
| recall_before | 0.0772 |
| recall_after | 0.0772 |
| hypothesis_summary | `[HYPOTHESIS] src_ip cluster: 80% explanatory power ✓` / `dest cluster: 5% ✗` / `user cluster: 0% ✗` |
| attack_injection_excluded | 1 |
| perturbation_pass | 1 |

**What attack_injection_excluded=1 means for the narrator:**
The agent initially proposed 4 IPs. It injected a synthetic attack event at the 4th IP, saw the detection would miss it if filtered, and dropped that IP. Final filter = 3 IPs, not 4. That's the self-narrowing behavior.

> **VO:** *"Scanner IPs. Three hypotheses tested, one wins at eighty percent. The agent proposes a NOT filter on three IPs, not four. The fourth had a true positive hiding in the scanner traffic. The agent narrowed the filter itself. Precision: thirty to sixty-six. Recall held flat — zero true positives dropped."*

---

## Beat 4 — Detection 2: Service Account

**What to show:** same tune command, different detection, different winner in hypothesis_summary.

```spl
| squelch mode="tune" search_name="Identity_PrivEscalation_Confirmed"
| table search_name decision precision_before precision_after recall_before recall_after hypothesis_summary perturbation_pass
```

**Expected output:**

| Field | Value |
|---|---|
| decision | accepted |
| precision_before | 0.2372 |
| precision_after | 0.4745 |
| recall_before | 0.0627 |
| recall_after | 0.0627 |
| hypothesis_summary | `[HYPOTHESIS] src_ip cluster: 80% ✗` / `[HYPOTHESIS] dest cluster: 80% ✗` / `[HYPOTHESIS] user cluster: 66% explanatory power ✓` |
| perturbation_pass | 1 |

**What the hypothesis table means for the narrator:**
src_ip and dest both show 80% cumulative power but are marked ✗ — they lost to user.
user wins at 66% because `svc_backup` alone accounts for 66% of FPs with zero TPs underneath it.
That single clean value is what makes it filterable. The IP fields have no such dominant value.

> **VO:** *"Second detection, different pattern. Sixty-six percent of false positives come from S-V-C backup. Not an IP pattern, a user-field pattern. The agent checks the identity lookup, confirms it's a known service account, and proposes a user-level filter."*

---

## Beat 5 — Detection 3: Don't Tune

**What to show:** decline decision, diagnosis JSON visible.

```spl
| squelch mode="tune" search_name="Endpoint_NewServiceInstalled"
| table search_name decision decision_reason diagnosis
```

**Expected output:**

| Field | Value |
|---|---|
| decision | declined |
| decision_reason | field_extraction_gap |
| diagnosis | `{"type":"field_extraction_gap","field":"dest_ip","empty_pct":0.445,"sourcetype":"svc_install_log","sourcetype_pct":1.0,...}` |

**What to point to:** `empty_pct: 0.445` = 44% of FPs have empty dest_ip. `sourcetype_pct: 1.0` = 100% of those empties come from one sourcetype. The agent cannot filter on a field that isn't there. It files an Issue instead.

> **VO (locked):** *"The detection isn't wrong. The data feeding it is broken. Squelch declines to tune. It files a GitHub Issue with the evidence attached. Because the worst thing a tuning system can do is mask a data quality problem with a filter."*

---

## Beat 6 — PRs and Decision Trail

**What to show:** GitHub with two open PRs and one open Issue.

Go to: `https://github.com/markbrazinski/Squelch/pulls`

You should see:
- `[squelch] DNS_TunnelExfil_Heuristic: NOT src_ip filter (precision 0.30→0.66)` — open
- `[squelch] Identity_PrivEscalation_Confirmed: NOT user filter (precision 0.24→0.47)` — open

Then: `https://github.com/markbrazinski/Squelch/issues`

You should see:
- `[squelch] Endpoint_NewServiceInstalled: field_extraction_gap — dest_ip empty in 44% of FPs` — open

> **VO:** *"Three outputs. Two P-Rs on separate branches, S-P-L diffs, hypothesis tables, perturbation badges. One GitHub Issue, not a tune, a diagnosis. Your engineer reviews all three. Ten minutes, not fifteen hours. The math's all there."*

---

## Beat 7 — Architecture

**What to show:** static architecture diagram. No commands — just the diagram from `docs/architecture.md` or a slide.

---

## Beat 8 — The Close

**What to show:** quiet notable queue, then repo URL overlay.

```spl
index=notable sourcetype=squelch_notable host=squelch-seed
| stats count(eval(status_label="false_positive")) as fp, count as total by search_name
| eval fp_rate=round(fp/total,3)
| sort - fp_rate
| table search_name fp_rate fp total
```

Shows the queue with the tuned detections still noisy in the raw view (because the filter lives in the saved search, not the index) — the "quiet" is that your analyst's alert queue stops firing on the known FPs.

> **VO:** *"Three detections. Three different root causes. One got filtered. One got diagnosed as a behavioral pattern. One the agent refused to tune because the real problem was upstream. Three hundred ninety-six false positives on two detections — down to two hundred thirty-six. Precision: thirty to sixty-six, and not on clean data. Six label formats, thirty percent gaps. The eval harness ships standalone. Install it Monday, even if you never run the agent. Squelch. Open source."*

---

## Recording reset checklist

Run this sequence every time you want a clean recording take:

- [ ] Close all open squelch PRs on GitHub manually
- [ ] (Optional) Re-seed if data has drifted: `python scripts/seed_notable.py --count 2952 --clear-first` then wait 15s
- [ ] Beat 3: run DNS tune → confirm PR opens
- [ ] Beat 4: run Identity tune → confirm PR opens
- [ ] Beat 5: run Endpoint tune → confirm Issue opens
- [ ] Beat 6: screenshot GitHub with 2 PRs + 1 Issue open
- [ ] Record

---

## Numbers locked to this seed run

| Claim | Beat | Value |
|---|---|---|
| False positives before (DNS + Identity) | 1, 8 | 396 |
| False positives after tune | 1, 8 | 236 |
| DNS precision lift | 3, 8 | 30% → 66% |
| src_ip explanatory power | 3 | 80% |
| IPs in final filter | 3 | 3 (not 4 — one had a TP) |
| Identity precision lift | 4 | 24% → 47% |
| svc_backup explanatory power | 4 | 66% |
| Empty dest_ip share | 5 | 44% |
| Trigger threshold | 2 | 70% fp_rate (normalized) |
| Recall outcome | 3, 4 | Held flat — zero TPs dropped |
