# Recording Run Book

End-to-end commands and SPL for each beat, in order. Run top to bottom.

**Methodology: film first, lock numbers after.**
Record the screen run linearly (Mess → Normalize → Det 1 → Det 2 → Det 3 → Outputs → Stack).
Pull all numbers from the recording. Update the VO and slides to match what's on screen.
Film the cold open GitHub moment separately at the end (see Cold Open note below).

---

## Before you start

**Close any open squelch PRs on GitHub.** Go to the repo → Pull requests → close all open squelch PRs manually. This ensures the recording starts clean.

---

## Terminal — Re-seed (only needed if data has drifted or you want a fresh start)

```bash
cd /Users/markbrazinski/Desktop/coding\ fun/Squelch
. .venv/bin/activate
python scripts/seed_notable.py --count 2952 --clear-first
```

Wait 15 seconds before running anything in Splunk.

---

## FILM ORDER

Record in this order. The cold open is filmed last and edited to the front.

1. Title Slide (static card)
2. The Mess
3. Normalize + Trigger
4. Detection 1: Scanner IPs
5. Detection 2: Service Account
6. Detection 3: The Refusal
7. Outputs + Decision Trail
8. The Stack + Close
9. **Cold Open** — film after step 7, once PRs and Issue are open on GitHub

---

## Beat: The Mess (~12 sec)

**What to show:** slow scroll through the raw notable index. Six label formats visible, blank cells.

```spl
index=notable sourcetype=squelch_notable host=squelch-seed
| table _time search_name status_label src_ip user dest_ip
| sort - _time
```

Scroll slowly. The mess is the point — six different status_label values, blanks everywhere.

**Numbers to capture from screen:**
- Total event count
- How many distinct status_label values are visible

---

## Beat: Normalize + Trigger (~18 sec)

**What to show:** the normalization lookup firing, then three detections above threshold.

```spl
index=notable sourcetype=squelch_notable host=squelch-seed
| lookup disposition_normalization status_label OUTPUT normalized_label
| eval normalized_label=coalesce(normalized_label, status_label)
| stats count(eval(normalized_label="false_positive")) as labeled_fp,
        count(eval(normalized_label="true_positive")) as labeled_tp
  by search_name
| eval fp_rate=round(labeled_fp/(labeled_fp+labeled_tp),3)
| where search_name IN ("DNS_TunnelExfil_Heuristic","Identity_PrivEscalation_Confirmed","Endpoint_NewServiceInstalled")
| sort - fp_rate
| table search_name fp_rate labeled_fp labeled_tp
```

**Expected output:** 3 demo detections above 0.70:
- `DNS_TunnelExfil_Heuristic`
- `Identity_PrivEscalation_Confirmed`
- `Endpoint_NewServiceInstalled`

**Numbers to capture from screen:**
- `labeled_fp` for DNS (→ "before" FP count)
- `labeled_fp` for Identity (→ "before" FP count)
- `fp_rate` for all three (verify all ≥ 0.70)

> **VO fires here:** *"Three detections hit seventy percent. The agent fires."*

---

## Beat: Detection 1 — Scanner IPs (~20 sec)

**What to show:** tune command running, then output table.

```spl
| squelch mode="tune" search_name="DNS_TunnelExfil_Heuristic"
| table search_name decision precision_before precision_after recall_before recall_after hypothesis_summary attack_injection_excluded perturbation_pass
```

**Expected output (from PR #57):**

| Field | Value |
|---|---|
| decision | accepted |
| precision_before | 0.2351 |
| precision_after | 0.5943 |
| recall_before | 0.0653 |
| recall_after | 0.0653 |
| hypothesis_summary | src_ip: 80% ✓ / dest: 80% ✗ / user: 0% ✗ |
| attack_injection_excluded | 1 (192.168.40.81 caught, narrowed out) |
| perturbation_pass | 1 |

LLM proposed 10 IPs. Attack injection caught `192.168.40.81`. Final filter = 9 IPs.

> **VO:** *"Scanner IPs. Three hypotheses, one wins at eighty percent. The agent proposes a NOT filter on nine IPs, not ten. The harness attacks its own filter with synthetic true positives. The tenth had a true positive hiding in the scanner traffic — excluded. Precision: twenty-four to fifty-nine. Recall held flat, zero true positives dropped."*

---

## Beat: Detection 2 — Service Account (~20 sec)

**What to show:** same tune command, different detection, different winner in hypothesis_summary.

```spl
| squelch mode="tune" search_name="Identity_PrivEscalation_Confirmed"
| table search_name decision precision_before precision_after recall_before recall_after hypothesis_summary perturbation_pass
```

**Expected output (from PR #58):**

| Field | Value |
|---|---|
| decision | accepted |
| precision_before | 0.2364 |
| precision_after | 0.4745 |
| recall_before | 0.0674 |
| recall_after | 0.0674 |
| hypothesis_summary | user: 66% ✓ / src_ip: 80% ✗ / dest: 80% ✗ |
| perturbation_pass | 1 |

Single-value filter (`svc_backup`) — attack injection bypassed, recall gate is the safety net.

**What the hypothesis table means for the narrator:**
`src_ip` and `dest` show 80% cumulative power but lose because no single value dominates with zero TPs. `user` wins because `svc_backup` alone accounts for 66% of FPs with zero TPs under it.

> **VO:** *"Second detection, different root cause. Sixty-six percent of false positives from S-V-C backup. User-field pattern, not IP. Agent confirms via identity lookup. Proposes a user-level filter. Precision: twenty-four to forty-seven."*

---

## Beat: Detection 3 — The Refusal (~30 sec)

**What to show:** decline decision, diagnosis JSON visible.

```spl
| squelch mode="tune" search_name="Endpoint_NewServiceInstalled"
| table search_name decision decision_reason diagnosis
```

**Expected output (these numbers are stable — seeded, not stochastic):**

| Field | Value |
|---|---|
| decision | declined |
| decision_reason | field_extraction_gap |
| diagnosis | `{"type":"field_extraction_gap","field":"dest_ip","empty_pct":~0.44,"sourcetype":"svc_install_log","sourcetype_pct":1.0,...}` |

**What to point to:** `empty_pct` ≈ 44% of FPs have empty dest_ip. `sourcetype_pct: 1.0` = 100% of those empties come from one sourcetype. The agent cannot filter on a field that isn't there. It files an Issue instead.

> **VO (locked):** *"The detection isn't wrong. The data feeding it is broken. Squelch declines to tune. It files a GitHub Issue with the evidence attached. Because the worst thing a tuning system can do is mask a data quality problem with a filter."*

---

## Beat: Outputs + Decision Trail (~15 sec)

**What to show:** GitHub with two open PRs and one open Issue.

Go to: `https://github.com/markbrazinski/Squelch/pulls`

You should see:
- `[squelch] DNS_TunnelExfil_Heuristic: NOT src_ip filter (precision [X]→[Y])` — open
- `[squelch] Identity_PrivEscalation_Confirmed: NOT user filter (precision [X]→[Y])` — open

Then: `https://github.com/markbrazinski/Squelch/issues`

You should see:
- `[squelch] Endpoint_NewServiceInstalled: field_extraction_gap — dest_ip empty in [X]% of FPs` — open

> **VO:** *"Three outputs. Two P-Rs on separate branches — S-P-L diffs, hypothesis tables, validation badges. One GitHub Issue. Not a tune, a diagnosis. Your engineer reviews all three. Ten minutes, not fifteen hours. The math's all there."*

---

## COLD OPEN — film here, edit to front

**Film this after Outputs, while PRs and Issue are still open on screen.**

What to show: all three GitHub artifacts visible at once — two open PRs, one open Issue.

**Post-production options:**
- **Option A (simpler):** Show PRs and Issue open. VO says "two PRs, one Issue." Edit this clip to the front of the video. Merge the PRs in a separate short clip at the end if you want to show closure.
- **Option B (cleaner open):** After you finish filming everything else, merge the two PRs on GitHub. Then film a 5-second clip of the merged (green) PRs + open Issue side by side. Use that as the cold open. VO line "two merged PRs (green)" becomes accurate.

> **VO:** *"Three detections went in. Two came out tuned. The third, the agent refused. Said the data was broken, not the detection. Here's the data it walked away from."*

> **Pacing:** Pause after "refused." Full beat of silence. Hard cut to the messy notable index on "walked away from."

---

## Beat: The Stack + Close (~53 sec)

**What to show:** architecture diagram, then repo URL overlay.

Static diagram from `docs/architecture.md` or a slide — no SPL commands needed.

> **VO:** *"Here's the stack. The L-L-M writes the filter — that's the easy part. The eval harness proves it's safe — that's the hard part. L-L-M layer's provider-agnostic. Ten M-C-P tools built in, two custom bring-your-own — one triggers the tune, one returns false-positive rates. K-V store keeps detection memory. Whole pipeline runs inside Splunk, ships as an App. The eval harness ships standalone. Install it Monday, even if you never run the agent. Squelch. Open source."*

---

## Recording reset checklist

Run this sequence every time you want a clean take:

- [ ] Close all open squelch PRs on GitHub manually
- [ ] (Optional) Re-seed if data has drifted: `python scripts/seed_notable.py --count 2952 --clear-first` then wait 15s
- [ ] Run Beat: Normalize + Trigger — confirm 3 detections above 0.70
- [ ] Run Beat: Detection 1 (DNS tune) — confirm PR opens
- [ ] Run Beat: Detection 2 (Identity tune) — confirm PR opens
- [ ] Run Beat: Detection 3 (Endpoint tune) — confirm Issue opens
- [ ] Verify GitHub: 2 open PRs + 1 open Issue
- [ ] Record

---

## Numbers — fill in after recording

Pull these from the screen recording. Update VO and slides to match.

| Claim | Beat | Value |
|---|---|---|
| False positives before — DNS | Normalize + Trigger | 205 |
| False positives before — Identity | Normalize + Trigger | 210 |
| False positives before — total (DNS + Identity) | The Mess VO | 415 |
| False positives after — DNS | Detection 1 | 43 |
| False positives after — Identity | Detection 2 | 72 |
| False positives after — total | The Mess VO | 115 |
| DNS precision lift | Detection 1 | 24% → 59% |
| DNS explanatory power (src_ip) | Detection 1 | 80% |
| IPs in final filter | Detection 1 | 9 (not 10 — tenth caught by attack injection) |
| IP caught by attack injection | Detection 1 | 192.168.40.81 |
| Identity precision lift | Detection 2 | 24% → 47% |
| svc_backup explanatory power | Detection 2 | 66% |
| Empty dest_ip share (Endpoint) | Detection 3 | 45% (empty_pct: 0.455, 96/211 FPs) |
| Trigger threshold | Normalize + Trigger | 70% fp_rate (normalized) — fixed |
| Recall outcome | Detection 1 + 2 | Held flat — zero TPs dropped |
