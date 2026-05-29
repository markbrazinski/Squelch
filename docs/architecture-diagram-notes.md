# Architecture Diagram — Notes for README

Source image: provided by user during Devpost fact-check session (2026-05-28).
File to embed: architecture-spine.png (save image to docs/ or repo root when ready)

## Diagram title
SYS://SQUELCH · ARCH · 0x02
"architecture · spine"
// one horizontal flow. three differentiators. memory logs every decision.
SPINE LAYOUT — BRAIN ORCHESTRATES, EVALS GATES

## Five boxes (left to right)

01 · TRIGGER
- saved search · FP rate > 70% · normalized labels

02 · BRAIN
- gemini 2.5 flash · proposes SPL revision
- annotation: PROVIDER-AGNOSTIC VIA | AI

03 · TOOLS
- 10 MCP built-in + 1 BYOT custom
- annotation: BYOT — AGENTS CAN CALL SQUELCH

04 · EVALS  [highlighted green — the differentiator]
- adversarial gate · precision / recall
- annotation: * ADVERSARIAL HARNESS · SHIPS STANDALONE

05 · OUTPUT
- fork — judgment, not generation
- → PR: tune accepted — SPL diff + eval table
- → Issue: don't tune — diagnosis + evidence

## Bottom bar (memory)
↑↓ MEMORY · detection_lineage KV
writes every run · reads on next (dashed = temporal loop)

## Flow labels
fires → | queries / labeled events ↔ | proposed SPL / gate result ↔ | labeled events · FP clusters ↔ | fork →

## Headline stats (bottom of diagram — recording-locked numbers)
415 notables → 115
precision 24% → 59%
recall held at 100%

## Key claims the diagram supports
- "10 MCP built-in + 1 BYOT custom" — matches platform-shape.md verified count
- "24% → 59%" precision — matches recording run (DNS_TunnelExfil_Heuristic: 0.2351 → 0.5943)
- "415 → 115 notables" — FP count from the recording run (use this for Devpost, not "403 → 98")
- "recall held at 100%" — means zero true positives dropped (recall preservation gate held)
- Provider-agnostic via | ai — Splunk's native AI command as alternative LLM path
