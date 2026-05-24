# Bundle 3 Safety-Net Video — Recording Recipe

Companion to [`docs/demo-script.md`](demo-script.md). The script is the narration; this file is the production setup.

Drift between the script and the pipeline is documented in the Demo-fit Gap Log at the bottom of [`docs/bundle-3-spec.md`](bundle-3-spec.md). **Resolve those gaps before recording** — see the "Critical" section in particular. The recipe below assumes the script has been reconciled.

---

## Pre-record checklist

- [ ] Demo-fit gaps from `bundle-3-spec.md` resolved in `demo-script.md` (or consciously accepted)
- [ ] D1 lead-detection decision made (PortScan recommended; Identity or DNS acceptable)
- [ ] All 8 detections have fresh KV rows from the same day (`./scripts/capture_tune_results.py` shows recent timestamps)
- [ ] `eval/results/tune_results_bundle_3.csv` regenerated — numbers in the narration match this file exactly
- [ ] Splunk Web logged in as admin, browser zoomed to **140%**
- [ ] All `squelch`-labeled GitHub PRs/Issues closed (clean slate so the recording-time artifacts are unambiguously new)
- [ ] `squelch/proposals` branch exists on origin, ≥1 commit ahead of `main`
- [ ] GitHub PAT stored at `realm=squelch_github`, `username=default` in Splunk's `storage/passwords`
- [ ] QuickTime Player ready (or your screen recorder of choice); macOS screen recording at **1920×1080**
- [ ] macOS notifications silenced (`Do Not Disturb` on), dock auto-hide, menu bar minimal
- [ ] Lower-third overlay PNG ready: "Squelch — Automated Detection Tuning for Splunk"
- [ ] Audio: external mic if available; record narration first per the audio-spine method (`demo-script.md` line 282)

---

## Window layout (per beat)

**All beats:** Browser primary. Splunk Web in one tab, `github.com/markbrazinski/Squelch` in another. Terminal in a separate window (used only for Beat 3 search execution if you want the typed command visible).

| Beat | Primary window | Notes |
|---|---|---|
| 1 — Payoff | Splunk search results page | Two searches in quick sequence — BEFORE / AFTER `stats count by status_label`. Pre-stage both as saved searches so you can switch in 1 click. **Use the D1-chosen detection (PortScan recommended).** |
| 2 — Trigger | Splunk savedsearches.conf view OR saved-search edit page | Show the FP-rate threshold and `disposition_normalization.csv` lookup |
| 3 — Detection 1 (Identity per recommended order) | Splunk search bar with `\| squelch mode="tune" search_name="Identity_PrivEscalation_Confirmed"` | Splunk's native progress bar fills for ~2s, then results table renders. Single-value filter → bypass branch narrative |
| 4 — Detection 2 (DNS per recommended order) | Splunk search bar with `\| squelch mode="tune" search_name="DNS_TunnelExfil_Heuristic"` | 3 scanner IPs proposed, 1 caught by attack injection, narrowed to 2 |
| 5 — Detection 3 (Endpoint) | Splunk search bar with `\| squelch mode="tune" search_name="Endpoint_NewServiceInstalled"` | Sub-second runtime — narration absorbs the silence; the decline-to-tune output is the climax |
| 6 — PRs + Issue | GitHub PR + Issue pages | Three artifacts in sequence, 3–4s each. Pre-open as three tabs. |
| 7 — Architecture | Static PNG (architecture diagram rendered from `docs/architecture.md`) | No live window |
| 8 — Close | Splunk notable queue (quiet) | Same as Beat 1's "AFTER" view |

---

## Browser tabs (pre-open in this order)

1. Splunk search bar (logged in, in the `squelch` app)
2. Splunk savedsearches.conf view (Beat 2)
3. GitHub: the **Identity** PR for Beat 4 reference (or whichever Detection 1 you choose)
4. GitHub: the **DNS** PR for Beat 4 reference
5. GitHub: the **Endpoint** Issue for Beat 5/6 reference
6. GitHub repo home (for the close)

**Pre-stage all three GitHub artifacts BEFORE recording.** The recording then relies on these tabs being scrollable. Don't record the artifact-creation moments live — the demo says they exist; the artifacts are the proof.

---

## Terminal setup (optional, Beats 3–5)

If showing the typed `| squelch` command alongside the Splunk search bar:
- 16px monospace font, dark background, high contrast (white-on-black or `solarized-dark`)
- Title bar hidden if possible
- The demo script suggests cutting to results immediately after Splunk's 2-second progress bar — terminal is supplementary context, not the main view

---

## The 422 workaround — recommended approach

Bundle 3's `squelch/proposals` head-branch sharing means a second open PR will 422. Two paths:

### **Recommended: Swap detection order to Identity → DNS → Endpoint**

- **Beat 3 (Identity, user pattern):** No prior PR open, no 422 risk. Single-value bypass is the talking point — the agent didn't need attack injection.
- **Beat 4 (DNS, scanner IPs):** Before recording this beat, **close the Identity PR** via a separate browser tab. The 5-second jump cut between beats covers it. DNS gets the 3→2 narrowing narrative.
- **Beat 5 (Endpoint, decline):** Issue creation, no PR-branch conflict.

This swap actually tells a stronger story: behavioral pattern first (the "it's smarter than a script" proof early), then IP pattern (the more familiar SIEM-engineer territory), then the climax (decline-to-tune). It also lets Beat 4's attack-injection-narrowing be the more sophisticated mechanism, building on Beat 3's bypass discussion.

### Alternative: Keep script order (DNS → Identity → Endpoint)

If you prefer the original script order, between beats 3 and 4 close the DNS PR via a separate browser tab. Same orchestration cost; weaker arc.

Bundle 4's per-detection-branch upgrade eliminates the workaround entirely.

---

## Beat recording order

Per `demo-script.md` line 296–303, record in this order (not script order):

1. **Beat 5 first** — climax, record while sharp
2. **Beats 3 + 4 together** — the pipeline runs (whichever order you chose above)
3. **Beat 2** — trigger / saved-search screen
4. **Beat 1** — the payoff (before/after numbers visible)
5. **Beat 6** — GitHub PRs/Issue review
6. **Beat 7** — architecture (static, drop in during edit)
7. **Beat 8** — close, return to notable queue

**Audio-spine method:** record all narration as a single audio pass first, then lay screen captures on top. Pacing controls the edit, not the other way around. Per-beat re-records don't require re-doing screen captures.

---

## Numbers to verify before each beat

Pull these from `eval/results/tune_results_bundle_3.csv` and have them visible during narration. **The script's numbers must match what's on screen.**

| Beat | Detection | Numbers narrator says |
|---|---|---|
| 1 (Payoff) | PortScan (recommended) | FP rate 78% → 41%; precision 22% → 59%; **2.6× precision lift** |
| 3 (Det 1, Identity) | Identity_PrivEscalation_Confirmed | `svc_backup` at 65% of FPs; precision 20% → 42% (**2.1× lift**); recall preserved |
| 4 (Det 2, DNS) | DNS_TunnelExfil_Heuristic | 3 scanner IPs proposed, 1 narrowed by attack injection; precision 29% → 47% |
| 5 (Det 3, Endpoint) | Endpoint_NewServiceInstalled | 46% empty `dest_ip`, 100% from `sourcetype_tag=svc_install_log`; agent declines to tune; Issue filed |

If any narrated number doesn't match the CSV, the script needs updating before recording.

---

## Post-record sanity (the 1.5× test, per `demo-script.md` line 313)

After first edit, watch at **1.5× speed**:

- [ ] Every text on screen is legible (increase zoom if not)
- [ ] No beat feels boring (shorten by 2–3s if so)
- [ ] Narrative arc is clear (jump cuts between beats aren't ambiguous)
- [ ] Beat 5 climax has the half-beat pause after "Squelch declines to tune"
- [ ] Beat 1 narrator enters at ~0:02 after the BEFORE numbers are visible
- [ ] Beat 8 has 2 seconds of silence before narrator enters
- [ ] Lower-third visible on every frame
- [ ] Total runtime **2:30–2:45**
- [ ] Numbers spoken match numbers visible on screen

---

## What this recipe doesn't cover

- **The actual recording.** I (Claude) can't drive a screen recorder. You record; share the final cut for a 1.5× review against the script.
- **The narration script itself.** That's `docs/demo-script.md`. This file is just production setup.
- **The architecture diagram PNG.** Render from `docs/architecture.md`; static image in Beat 7.
- **Devpost submission text.** Lives in the project Devpost; references the must-address points already in `demo-script.md` lines 325–344.
