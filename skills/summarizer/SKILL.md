---
name: summarizer
version: 0.2.0
model: us.anthropic.claude-sonnet-4-6
prompt: prompt.j2
quality_bar: entity_recall_min:0.85,topic_coverage_min:0.8
trigger: call_ended
---

# Call Summarizer (Phase 1)

Extends the Phase 0 summarizer with:
  - `verbatim_quotes`: direct caller quotes worth surfacing in the brief
  - `topics`: normalized topic tags for cross-call rollups (used by F8)
  - input includes `brain_context` — top brain hits to disambiguate entities

Quality bar raised from `0.6` → `0.85` entity recall over a 30-call golden
set; `topic_coverage ≥ 0.8` added. The output is a superset of v0.1, so
Phase 0 callers keep working.

## Inputs

  - `call_id`, `started_at`
  - `caller.name`, `caller.role`
  - `transcript`: full caller+agent turn-by-turn
  - `provider_summary`: AP's own post-call summary (optional)
  - `brain_context`: short list of pages the call referenced

## Output

Strict JSON conforming to `Output` in `schema.py`.
