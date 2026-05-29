# Squelch VO — Final Script

**Total: 354 words | Budget: 400 | Headroom: 46**

---

### Title Slide (0:00–0:05) — 15 words

**VO:**
Squelch is an adversarial validation harness that proves detection changes are safe before they ship.

**On screen:** Title card with one-liner.

---

### Cold Open — The Refusal (0:05–0:17) — 28 words

**VO:**
Three detections went in. Two came out tuned. The third, the agent refused. Said the data was broken, not the detection. Here's the data it walked away from.

**On screen:** All three GitHub artifacts — two merged PRs (green), one open Issue (yellow). All visible at once. On "the agent refused," the Issue pulses or the PRs dim. Hard cut to the messy notable index on "walked away from."

**Pacing:** Pause after "refused." Full beat of silence. The hook lives in the gap.

---

### The Mess (0:17–0:30) — 29 words

**VO:**
Four hundred fifteen false positives across two detections. After Squelch: one hundred fifteen. Precision: twenty-four to fifty-nine. Not on clean data — six label formats, gaps everywhere. Squelch works anyway.

---

### Normalize + Trigger (0:30–0:43) — 33 words

**VO:**
First step: normalize. A lookup collapses six label formats to two — true positive, false positive. Unlabeled events get excluded, not guessed. Then: false-positive rate per detection. Three detections hit seventy percent. The agent fires.

---

### Detection 1: Scanner IPs (0:43–1:05) — 51 words

**VO:**
Scanner IPs. Three hypotheses, one wins at eighty percent. The agent proposes a NOT filter on nine IPs, not ten. The harness attacks its own filter with synthetic true positives. The tenth had a true positive hiding in the scanner traffic — excluded. Precision: twenty-four to fifty-nine. Recall held flat, zero true positives dropped.

---

### Detection 2: Service Account (1:05–1:15) — 28 words

**VO:**
Second detection, different root cause. Sixty-six percent of false positives from S-V-C backup. User-field pattern, not IP. Agent confirms via identity lookup. Proposes a user-level filter. Precision: twenty-four to forty-seven.

---

### Detection 3: The Refusal (1:15–1:47) — 70 words

**VO:**
Here's that third detection. The harness rejects every cluster — IP, user, time, none clear the twenty-percent floor. But forty-five percent of false positives have an empty dest I-P, all from one sourcetype. The detection isn't wrong. The data feeding it is broken. Squelch declines to tune. It files a GitHub Issue with the evidence. Because the worst thing a tuning system can do is mask a data quality problem with a filter.

**Pacing:** Slow down on "The detection isn't wrong." Pause. "The data feeding it is broken." These two sentences are the emotional peak. Give them air.

---

### Outputs + Decision Trail (1:47–2:02) — 32 words

**VO:**
Three outputs. Two P-Rs on separate branches — S-P-L diffs, hypothesis tables, validation badges. One GitHub Issue. Not a tune, a diagnosis. Your engineer reviews all three. Ten minutes, not fifteen hours. The math's all there.

---

### The Stack + Close (2:02–2:55) — 68 words

*[Architecture diagram on screen]*

**VO:**
Here's the stack. The L-L-M writes the filter — that's the easy part. The eval harness proves it's safe — that's the hard part. L-L-M layer's provider-agnostic. Ten M-C-P tools built in, two custom bring-your-own — one triggers the tune, one returns false-positive rates. K-V store keeps detection memory. Whole pipeline runs inside Splunk, ships as an App. The eval harness ships standalone. Install it Monday, even if you never run the agent. Squelch. Open source.

**Pacing:** Rattle the specs briskly while the diagram's on screen. Slow back down on "The eval harness ships standalone." Pause before "Squelch. Open source." Let the last two words land in silence.

---

## WORD COUNT BY BEAT

| Beat | Words |
|------|-------|
| Title Slide | 15 |
| Cold Open | 28 |
| The Mess | 29 |
| Normalize + Trigger | 33 |
| Detection 1: Scanner IPs | 51 |
| Detection 2: Service Account | 28 |
| Detection 3: The Refusal | 70 |
| Outputs + Decision Trail | 32 |
| The Stack + Close | 68 |
| **Total** | **354** |

---

## THESIS TOUCHPOINTS

| Time | Beat | Language | Type |
|------|------|----------|------|
| 0:02 | Title | "adversarial validation harness" | Explicit — full phrase |
| 0:10 | Cold Open | "the agent refused" | Mechanical — adversarial outcome |
| 0:16 | Cold Open | "the data it walked away from" | Implicit — judgment, not automation |
| 0:52 | Detection 1 | "The harness attacks its own filter with synthetic true positives" | Explicit — names mechanic + technique |
| 1:18 | Detection 3 | "The harness rejects every cluster" | Explicit — harness as gatekeeper |
| 1:38 | Detection 3 | "Squelch declines to tune" | Mechanical — adversarial refusal |
| 1:52 | Outputs | "validation badges" | Implicit — echoes title |
| 2:08 | Close | "The eval harness proves it's safe — that's the hard part" | Explicit — the inversion |
| 2:45 | Close | "The eval harness ships standalone" | Explicit — harness as the product |

Nine touchpoints. No gap longer than 25 seconds after 0:43.

---

## PRIZE TARGETING

| Prize | Key beats | What the judge hears |
|-------|-----------|---------------------|
| **Grand Prize ($7K)** | Cold Open, Det 1, Det 3, Close | Mystery→evidence→verdict arc. Core inversion. Refusal as intelligence. |
| **Security ($3K)** | Det 1, Det 3, Outputs | Recall preservation, synthetic TP testing, diagnostic refusal, evidence trail. |
| **Best Use of MCP ($1K)** | Det 2, Close | Identity lookup during detection. "Ten built in, two custom — one triggers the tune, one returns false-positive rates." |
| **Best Use of Dev Tools ($1K)** | Normalize, Outputs, Close | Lookup table, SPL diffs, KV store, ships as a Splunk App. |

---

## READ-ALOUD FLAGS

1. **Cold Open:** "The third, the agent refused." — Test comma vs dash. If the comma doesn't create enough pause for TTS, switch to "The third — the agent refused." Same word count.

2. **Cold Open:** "Here's the data it walked away from." — Ending on a preposition. Sounds natural in speech. If it bugs you, "Here's the data it walked away from" is how people actually talk. Don't fix it.

3. **Detection 1:** "The harness attacks its own filter with synthetic true positives." — Sibilant chain in "attacks its" and "synthetic." Test at recording speed. If the mouth stumbles, insert a breath: "The harness attacks its own filter — with synthetic true positives." Same words, added dash.

4. **Detection 1:** "The tenth had a true positive hiding in the scanner traffic — excluded." — The dash before "excluded" needs a sharp delivery — it's a verdict, not an afterthought.

5. **Close:** "The L-L-M writes the filter — that's the easy part. The eval harness proves it's safe — that's the hard part." — Parallel structure. Same cadence both times, emphasis shifts from "easy" to "hard." If it sounds rehearsed, it fails. If it sounds like a realization, it's the best line in the demo.

6. **Close:** "Two custom bring-your-own — one triggers the tune, one returns false-positive rates." — Long breath group. Test whether you can deliver it in one pass or need a micro-pause after "bring-your-own."