---
name: classifier
version: 0.1.0
model: us.anthropic.claude-haiku-4-5-20251001-v1:0
prompt: prompt.j2
quality_bar: precision_min:0.85
trigger: intake_buffer_item_added
---

# Intake Classifier

Classifies a single `IntakeBufferItem` along two axes:

- **scope**: `ORG_WIDE` | `CALLER_SPECIFIC` | `BOTH` | `RAW_SOURCE`
- **kind**:  `account` | `person` | `product` | `playbook` | `theme`
             | `caller_identity` | `caller_style` | `raw_document`
             | `org_positioning` | `off_topic`

Returns a `confidence` in `[0, 1]`. Items below `0.7` are surfaced to the
Manager as `needs_review` rather than auto-ingested.

## When to fire

On every `IntakeBufferItem` write (onboarding) and on every Manager
correction (re-classification with elevated trust).

## Quality bar

- `precision_min:0.85` on the golden set in `evals/golden_set.jsonl`.
- Never invent `target_caller_id`; only set if the input text explicitly
  names a Field Rep on the roster passed in via `ctx.extra.roster`.

## Chains with

- `IntakeRouter` (consumer of the output)
- `brain_seeder` (when `kind == raw_document`)
- `NeedsReviewHandler` (when `confidence < 0.7`)
