# Squelch Demo Script — Final

**Total runtime:** 2:45 (15s buffer against 3:00 hard limit)
**Word budget:** ~375 words narration (~2:30 at 150 wpm, leaving ~15s for pauses/transitions)
**Opening card:** None. Persistent lower-third: "Squelch — Automated Detection Tuning for Splunk"
**Structure:** 8 beats. Three detections, three outcomes, escalating complexity. Detection 3 is the climax.

---

## Beat 1 — The Payoff (0:00–0:15)

**On screen:** Splunk search results. Browser zoomed to 140%. Two searches shown in quick sequence:
- BEFORE: `index=notable search_name="WindowsAuth_AnomalousLogonSource" | stats count by status_label` — 340 total, messy status_label values visible ("false_positive", "resolved", "FP - scanner", "fp", "closed", blank cells). The mess is visible even in the payoff frame.
- AFTER: Same search post-tune — 19 total. Clean.

The lower-third appears on frame one.

**Narrator says:**
"Eighty-three percent false positive rate. Three hundred forty notables a day on one rule, and your analysts stopped reading them weeks ago. After Squelch: nineteen. Precision from fourteen to eighty-seven. On data with six label formats and thirty percent gaps. Here's how."

*(43 words, ~17 seconds — narration starts at ~0:02 after the BEFORE numbers are visible)*

**Why this beat exists:** Payoff-first. The judge decides in 10 seconds whether to keep watching. Give them the result, then the credibility kicker ("on data with six label formats and thirty percent gaps") while the messy labels are still visible on screen. "Your analysts stopped reading them weeks ago" is the sentence that turns a number into a feeling. "Here's how" is the hook that earns the next 2:30.

**Framework component:** EVALS, SPLUNK-NATIVE

**Prize criteria served:** Potential Impact (the before/after), Quality of Idea (honest about data conditions from frame one)

---

## Beat 2 — The Trigger + Label Normalization (0:15–0:30)

**On screen:** Saved search configuration. SPL visible in the search bar — including a `| lookup disposition_normalization status_label OUTPUT normalized_label` step that maps the six label variants to two canonical values (true_positive / false_positive). Unlabeled events excluded. The search runs and returns three detections above 70% FP rate, shown as a table: search_name, fp_count, total, fp_rate.

**Narrator says:**
"Labels get normalized first — a lookup maps six formats to two. Unlabeled events excluded, not guessed. Then: false positive rate per detection, seven-day window. Three detections cross seventy percent. The agent fires."

*(33 words, ~13 seconds — leaves 2 seconds for screen to breathe)*

**Why this beat exists:** Label normalization addresses the #1 practitioner objection ("your data is too clean"). Showing it in the trigger beat communicates "this was designed for your environment" in 15 seconds. "The agent fires" closes the beat with a vivid verb — the system has selected its targets, now we see what it does with them.

**Framework component:** TRIGGER, SPLUNK-NATIVE

**Prize criteria served:** Technological Implementation (Splunk-native trigger with normalization), Design (invisible UX — it just runs), Developer Tools ($1K — saved search + scheduler + lookup)

---

## Beat 3 — Detection 1: The Obvious Pattern (0:30–0:50)

**On screen:** Splunk search bar executing `| squelch mode="tune" search_name="WindowsAuth_AnomalousLogonSource"` — show Splunk's native search progress bar filling for ~2 seconds, then cut to output.

Agent output shows:
1. Multi-hypothesis display: `src_ip cluster: 78% explanatory power ✓` / `user+time cluster: 11% ✗` / `sourcetype coverage: no gap ✗`
2. Revision: NOT filter on **two** CIDRs (not three — the third was excluded)
3. Eval table: `precision 14% → 87%, recall 100%, label perturbation PASS, attack injection — 10.0.1.51 excluded from filter`

**Narrator says:**
"First detection — scanner IPs. Three hypotheses tested, one wins. The agent proposes a NOT filter on two CIDRs — not three. The third range had a real attack hiding in the scanner traffic. The eval harness caught it. The agent narrowed the filter on its own. Precision: fourteen to eighty-seven."

*(46 words, ~18 seconds)*

**Why this beat exists:** The warm-up, not the headline. Establishes the pipeline works and shows the attack injection catching an edge case. "A real attack hiding in the scanner traffic" is visceral — the judge feels the consequence, the mechanism lives in the Devpost. The hypothesis display proves the agent evaluates alternatives.

**Framework component:** BRAIN (multi-hypothesis), EVALS (attack injection), TOOLS (MCP)

**Prize criteria served:** Technological Implementation (multi-hypothesis + adversarial eval), Quality of Idea (attack injection is novel), Potential Impact (safety proof)

---

## Beat 4 — Detection 2: The Behavioral Pattern (0:50–1:10)

**On screen:** Agent output for `PrivilegeEscalation_UnusualServiceAccess`. Show:
1. Multi-hypothesis display: `user cluster: 65% explanatory power ✓ (svc_backup)` / `src_ip cluster: 18% ✗` / `dest cluster: 9% ✗`
2. Cross-reference step: agent checks identity/service account lookup → confirms svc_backup is known infrastructure
3. Revision: NOT filter on `user="svc_backup"`
4. Eval: precision improved, recall held, label perturbation PASS

**Narrator says:**
"Second detection — different pattern. Sixty-five percent of false positives come from one account: svc_backup. Not an IP pattern — a simple frequency count would miss it. The agent cross-references the identity lookup, confirms it's a known service account, and proposes a user-level filter."

*(40 words, ~16 seconds — leaves 4 seconds of screen breathing room)*

**Why this beat exists:** The "it's smarter than a script" proof. Scanner IPs are the pattern any SIEM engineer handles in 20 minutes. A service account behavioral pattern requires the agent to look beyond IP clustering. "A simple frequency count would miss it" communicates this to both practitioners and non-practitioner judges.

**Framework component:** BRAIN (behavioral clustering), TOOLS (identity lookup cross-reference via MCP)

**Prize criteria served:** Quality of Idea (proves intelligence beyond trivial patterns), Technological Implementation (multi-field clustering + lookup cross-reference), MCP Server ($1K — agent uses MCP tools to read identity lookup)

---

## Beat 5 — Detection 3: "Don't Tune This" (1:10–1:40)

**On screen:** Agent output for `DNS_TunnelExfil_Heuristic`. Show:
1. Multi-hypothesis display: `dest_ip cluster: 22% ✗` / `src_ip cluster: 15% ✗` / `sourcetype coverage: 45% — FIELD EXTRACTION GAP DETECTED ✓`
2. Agent's reasoning: ~45% of FPs have `dest_ip=""` (empty field), ALL from `sourcetype=dns_proxy_v2`
3. Agent conclusion: "Detection FP rate driven by field extraction gap on sourcetype dns_proxy_v2, not by pattern in events. Recommend fixing props.conf, not tuning detection."
4. Output: GitHub **Issue** (not a PR) — filed against the field extraction gap with evidence: sourcetype, empty field percentage, affected events

**Narrator says:**
"Third detection. No single pattern dominates. But forty-five percent of false positives have an empty dest_ip field, all from one sourcetype. The detection isn't wrong. The data feeding it is broken. Squelch declines to tune. Files a GitHub Issue against the field extraction gap. Evidence attached. Because the worst thing a tuning system can do is mask a data quality problem with a filter."

*(59 words, ~24 seconds — the climax, paced for impact with a half-beat pause after "Squelch declines to tune.")*

**Why this beat exists:** The beat worth more than every other beat combined. Every other hackathon entry that uses an LLM to generate SPL is a filter generator. This one makes a diagnostic decision NOT to filter. A pipeline tunes everything it's pointed at. An agent decides whether tuning is the right action.

**Framework component:** BRAIN (diagnostic reasoning, decline-to-tune judgment), EVALS (hypothesis evaluation), MEMORY (decision logged in KV store)

**Prize criteria served:** Quality of Idea (the most differentiated moment in the demo), Design (the right answer is sometimes "don't do the thing you were asked to do"), Potential Impact (prevents masking real problems), Technological Implementation (multi-hypothesis with structural diagnosis)

---

## Beat 6 — The PRs + Decision Trail (1:40–2:00)

**On screen:** GitHub. Show three outputs in quick succession (3-4 seconds each):
1. **Detection 1 PR:** Title includes detection name. SPL diff visible — one NOT filter on two CIDRs. PR body shows eval numbers + decision trail: "3 hypotheses evaluated, 2 revision candidates considered, conservative selected (attack injection caught aggressive candidate)"
2. **Detection 2 PR:** SPL diff — NOT filter on user="svc_backup". Decision trail: "user cluster selected over IP cluster (65% vs 18% explanatory power)"
3. **Detection 3 Issue:** Not a PR — a GitHub Issue. Title: "Field extraction gap: dns_proxy_v2 missing dest_ip." Body: evidence, affected percentage, recommendation.

**Narrator says:**
"Here's what the engineer sees Monday morning. Two pull requests — SPL diffs, eval numbers, decision trails. One GitHub Issue — not a tune, a diagnosis. All three reviewed over coffee. Ten minutes instead of fifteen hours across three rules. Human in the loop, audit trail in Git."

*(43 words, ~17 seconds — leaves 3 seconds of screen time)*

**Why this beat exists:** The PR isn't just output — it's reviewable output. The decision trail is what makes a PR reviewable instead of just approvable. Detection 3's Issue — not a PR — visually reinforces that the agent adapts its response to the situation.

**Framework component:** MEMORY (detection_lineage feeds the decision trail), SPLUNK-NATIVE (integrates with real workflows)

**Prize criteria served:** Design (the PR IS the UX), Potential Impact (audit trail, version control, human review), Developer Tools ($1K — detection-as-code workflow)

---

## Beat 7 — Architecture (2:00–2:15)

**On screen:** Clean architecture diagram. Five framework components mapped to Splunk-native pieces:

```
TRIGGER                 BRAIN                    TOOLS                   EVALS                    MEMORY
Saved Search       →    | ai / | squelch    →    10 MCP + 2 BYOT   →    Golden Dataset       →   KV Store
(cron, FP rate          (Gemini Flash,           (reads via MCP,         (precision/recall,       (detection_lineage,
 >0.70, label           provider-agnostic        writes via REST,        attack injection,        revision history,
 normalization)          architecture)            identity lookup)        label perturbation)      decision trail)
                                        ↓
                    ┌─────────────────────────────────┐
                    │  Git PR (tune) or Issue (don't) │
                    │  SPL diff + eval + decision trail│
                    └─────────────────────────────────┘
```

**Narrator says:**
"The full stack. Scheduled trigger with label normalization. Provider-agnostic LLM architecture. Ten built-in MCP tools plus two custom via Bring Your Own Tool. Adversarial eval harness. KV store for detection memory. Everything inside Splunk. Ships as an App."

*(36 words, ~14 seconds — tight, factual, lets the diagram carry the detail)*

**Why this beat exists:** Every prize category in one frame. The diagram doubles as the required Devpost architecture submission. The eval harness enumeration (attack injection, label perturbation, recall-drop rejection) was cut from the narration — the audience has already seen these in action across Beats 3-5. "Adversarial eval harness" is sufficient.

**Framework component:** ALL

**Prize criteria served:**
- Security ($3K): detection tuning with recall preservation + diagnostic judgment
- MCP Server ($1K): 2 custom BYOT tools on the diagram
- Hosted Models ($1K): "provider-agnostic architecture" on the BRAIN node
- Developer Tools ($1K): App + custom SPL + KV store + saved searches
- Grand Prize ($7K): full agentic system with adversarial eval

---

## Beat 8 — The Close (2:15–2:45)

**On screen:** Return to Splunk. Notable queue — quieter. Hold for 2 seconds of silence, then narrator enters. Final frame: the GitHub repo URL (optional overlay).

**Narrator says:**
"Three detections above threshold. Three different root causes. One the agent filtered. One it diagnosed as a behavioral pattern. One it refused to tune — because the real problem was upstream — and filed the right ticket. Precision: fourteen to eighty-seven. Not on clean data. On simulated data with six label formats and thirty percent gaps. The eval harness ships standalone — install it Monday, even if you never run the agent. Squelch. Open source."

*(71 words, ~28 seconds — 2 seconds of silence on the quiet queue before narrator enters)*

**Why this beat exists:** The three-sentence summary (filtered / behavioral / refused) is the line the judge writes in their notes. "Not on clean data" pays off the thesis introduced in Beat 1. "Install it Monday, even if you never run the agent" lowers the adoption threshold. The close echoes the opening — honest numbers, messy conditions, real results.

**Framework component:** Full loop closure — returns to the notable queue from Beat 1

**Prize criteria served:** Potential Impact (the memorable summary), Quality of Idea (eval-harness-standalone positioning), Design (the close feels earned because it echoes the opening)

---
---

# WORD COUNT AUDIT

| Beat | Words | Seconds at 150 wpm | Allotted time | Buffer |
|---|---|---|---|---|
| 1 — The Payoff | 43 | ~17s | 15s | ~2s over — absorbed by global buffer |
| 2 — Trigger | 33 | ~13s | 15s | 2s ✅ |
| 3 — Detection 1 | 46 | ~18s | 20s | 2s ✅ |
| 4 — Detection 2 | 40 | ~16s | 20s | 4s ✅ |
| 5 — Detection 3 | 59 | ~24s | 30s | 6s (room for pauses around climax) ✅ |
| 6 — PRs + Trail | 43 | ~17s | 20s | 3s ✅ |
| 7 — Architecture | 36 | ~14s | 15s | 1s ✅ |
| 8 — The Close | 71 | ~28s | 30s | 2s ✅ |
| **TOTAL** | **371** | **~2:28** | **2:45** | **~17s global buffer ✅** |

**Verdict:** 371 words at 150 wpm = ~2:28 of narration. With pauses and transitions, lands at ~2:35–2:40. Seventeen seconds of buffer — enough for natural pacing, the half-beat pause after "Squelch declines to tune" in Beat 5, the 2 seconds of silence opening Beat 8, and breathing room if any beat runs slightly long in recording.

---

# THE OPENING 15 SECONDS

The judge is deciding whether to keep watching. What they see and hear:

**Frame 1 (0:00):** Splunk search results — 340 notables. The status_label column is visibly messy. The lower-third appears.

**Audio (0:02):** "Eighty-three percent false positive rate. Three hundred forty notables a day on one rule, and your analysts stopped reading them weeks ago."

The judge is now implicated. They know their FP rate is bad. They know the analyst behavior. This isn't a description of a problem — it's a mirror.

**Audio (0:07):** "After Squelch: nineteen. Precision from fourteen to eighty-seven."

The payoff lands while the judge is still feeling the pain. Before/after in one breath.

**Audio (0:11):** "On data with six label formats and thirty percent gaps. Here's how."

The credibility kicker — "not on clean data" — arrives before the judge has time to be skeptical. "Here's how" earns the next 2:30.

**Why this works at 1.5x speed:** The numbers are self-explanatory even at speed. The mess is visible on screen. By second 10 the judge has the before/after AND the honesty signal. Every other demo opens with "Hi, I'm..." or a title card. This one opens with an accusation and a result.

---

# THE CLOSING 15 SECONDS (2:30–2:45)

**What the judge sees:** Quiet notable queue. 2 seconds of silence. Then:

**The line the judge writes in their notes:**
> "Three detections — filtered one, behavioral pattern on second, refused to tune third and filed an issue instead. Eval harness ships standalone."

**Why this sticks:** The three-outcome summary is structurally parallel, escalates in sophistication, and ends on the strongest capability (refusing to act). Judges can repeat this in deliberation without rewatching. "Install it Monday, even if you never run the agent" gives them a deployment mental model — the eval harness alone is worth installing. "Squelch. Open source." — four syllables, done.

---

# BEAT-BY-BEAT PRIZE COVERAGE

| Beat | Tech Impl. | Design | Impact | Idea | Prize Categories |
|---|---|---|---|---|---|
| 1 — The Payoff | | ✓ | ✓ | ✓ | Security |
| 2 — Trigger | ✓ | ✓ | | | Dev Tools |
| 3 — Det 1 (scanner) | ✓ | | ✓ | ✓ | Security, MCP |
| 4 — Det 2 (behavioral) | ✓ | | | ✓ | MCP |
| 5 — Det 3 (don't tune) | ✓ | ✓ | ✓ | ✓✓ | Security, Grand |
| 6 — PRs + Trail | | ✓ | ✓ | | Dev Tools |
| 7 — Architecture | ✓ | | | | ALL categories |
| 8 — Close | | ✓ | ✓ | ✓ | Security, Grand |

**Coverage check:**
- Tech Implementation: Beats 2, 3, 4, 5, 7 (5 beats) ✅
- Design: Beats 1, 2, 5, 6, 8 (5 beats) ✅
- Potential Impact: Beats 1, 3, 5, 6, 8 (5 beats) ✅
- Quality of Idea: Beats 1, 3, 4, 5, 8 (5 beats) ✅
- MCP Server: Beats 3, 4, 7 ✅
- Hosted Models: Beat 7 (provider-agnostic architecture callout) ✅
- Developer Tools: Beats 2, 6, 7 ✅
- Security: Beats 1, 3, 5, 8 ✅
- Grand Prize: Beats 5, 7, 8 ✅

---

# BUILD DEPENDENCIES

Ordered by criticality to this script:

| # | Component | Status per approved scope | Required by beat | Risk if late |
|---|---|---|---|---|
| 1 | **Messy notable data + label normalization lookup** | APPROVED, will be built | Beats 1, 2 | HIGH — without it, the opening thesis collapses |
| 2 | **Eval harness with attack injection + label perturbation** | APPROVED, will be built | Beats 3, 4, 5 | HIGH — the eval numbers are the proof layer |
| 3 | **Multi-hypothesis display (2-3 hypotheses per detection)** | APPROVED, will be built | Beats 3, 4, 5 | MEDIUM — without it, agent looks like single-pass pipeline |
| 4 | **Detection 3: field extraction gap diagnosis + decline-to-tune** | APPROVED, will be built | Beat 5 (THE CLIMAX) | CRITICAL — single beat worth more than all others |
| 5 | **Git PRs with decision trail + GitHub Issue for Det 3** | APPROVED (can be pre-staged) | Beat 6 | LOW — can be pre-staged manually |
| 6 | **Architecture diagram** | Not yet done | Beat 7 | LOW — static image, 30 minutes |
| 7 | **Temporal holdout (Bundle 5)** | MAY exist — cut if behind | Not scripted | NONE — deliberately not in the script |

**Build order recommendation:** Items 1 and 2 first (they affect every beat). Item 4 next (it's the climax). Items 3 and 5 can be built or staged last.

---

# RECORDING NOTES

**Audio-spine method:** Record all narration FIRST as an audio track. Then record screen captures to match the audio.
- Narration pacing controls the edit, not the other way around
- You can re-record individual beats without re-doing screen captures
- The audio track becomes your editing timeline — lay screen recordings on top

**Screen capture settings:**
- 1920×1080 native resolution
- Splunk browser: zoom to 140% (default table font is ~12px — illegible in compressed video)
- Terminal: 16px font, dark theme, high contrast
- GitHub: dark mode, zoomed to diff view
- Close all tabs, notifications, dock, menu bar

**Agent execution visibility:** During recording of Beat 3, capture the Splunk search bar executing `| squelch mode="tune" search_name="WindowsAuth_AnomalousLogonSource"` with the native search progress bar visible for ~2 seconds before cutting to output. This proves the command runs live without requiring the audience to parse terminal output. Same approach for Beats 4 and 5 if time permits — Beat 3 is the priority.

**Beat-by-beat recording order:**
1. Beat 5 (Detection 3) — hardest, most important, record first while sharp
2. Beats 3 + 4 (Detections 1 + 2) — the agent pipeline, record together
3. Beat 2 (trigger) — straightforward Splunk saved search screen
4. Beat 1 (the payoff) — before/after search results with messy labels visible
5. Beat 6 (PRs) — GitHub recordings, independent of Splunk
6. Beat 7 (architecture) — static image, drop in during edit
7. Beat 8 (close) — return to notable queue, just the quiet screen

**Editing:**
- Jump cut between every beat. No transitions, no fades. Hard cuts.
- Do NOT show Splunk loading bars (except the 2-second progress bar in Beat 3), search progress, or HTTP wait times. Cut to the result.
- Beat 1: narrator enters at ~0:02 after the BEFORE numbers are visible on screen.
- Beat 5 (climax): half-beat pause after "Squelch declines to tune." Let it land.
- Beat 8: 2 seconds of silence on the quiet queue before narrator enters.
- 0.5-second audio pause between Beats 3 and 4 — the tonal shift from "the pipeline works" to "here's where it gets smarter" needs a breath.

**The 1.5x test:** After first edit, watch at 1.5x speed. If:
- Any text on screen is illegible → increase zoom
- Any beat feels boring → shorten it by 2-3 seconds
- The narrative arc is unclear → the cuts between beats aren't clean enough
- Detection 3 doesn't land as the climax → it needs more silence around it

**Lower-third:** White or light gray text on semi-transparent dark bar. Bottom-left. "Squelch — Automated Detection Tuning for Splunk." Appears frame one, stays entire video. Add in post-production.

**Energy and tone:** You're showing the math, not selling the dream. The narrator voice is a senior engineer walking a colleague through their work — not a pitch, not a presentation. Slightly conversational. The confidence comes from the numbers, not the delivery. When you say "Squelch declines to tune," say it the way you'd tell a coworker something interesting, not the way you'd close a keynote.

---

# DEVPOST MUST-ADDRESS

Three things the demo can't carry in 2:45 but the written submission must address honestly.

### 1. Synthetic data framing

> "Squelch was validated against a synthetic notable index designed to simulate real SOC conditions — six disposition label formats, 30% unlabeled events, three distinct FP root causes including a field extraction gap. Production deployment requires real analyst dispositions; the architecture handles that input natively. The label normalization layer, the eval harness, and the decline-to-tune logic were all designed for the inconsistencies of production data, not the cleanliness of test data."

### 2. Macro/lookup/eventtype limitations

> "The current build handles flat SPL correlation searches. Production detections reference macros, eventtypes, lookup tables with staleness concerns, CIM field aliases, and nested search constructs. Extending the triage step to parse macro definitions, check lookup freshness, and resolve field aliases is the primary next-tier engineering challenge."

### 3. Label noise tolerance

> "The normalization lookup maps analyst labeling variants to two canonical values. Unlabeled events are excluded from the golden dataset, not imputed. Label perturbation testing (flipping 10% of labels and re-running the eval) quantifies how sensitive each revision is to label noise. For shops with low-quality labels, the monitoring layer — which surfaces FP rates per detection — delivers value even before the tuning agent runs."

### 4. Complex SPL acknowledgment

> "Beyond flat SPL: macros (resolving definitions at tune time), nested lookups (detecting stale enrichment data), field aliases (CIM normalization gaps across sourcetypes), and multi-stage correlation searches (where the FP pattern originates in an earlier pipeline stage, not the final search). These represent the cases Squelch's architecture is designed to grow into."