---
name: dashboard_rollup_writer
version: 0.1.0
model: us.anthropic.claude-sonnet-4-6
prompt: prompt.j2
quality_bar: manual
trigger: dashboard_rollup
---

# Dashboard Rollup Writer

Turns the structured rollup data (`RollupAggregate`) produced by the
`dashboard_rollup` mini-agent into the natural-language daily brief
that the Manager reads in the FE and receives by email.

This is the ONLY skill in F8. The mini-agent computes intermediates and
writes `DashboardSnapshot` rows; this skill produces the prose sections.

## Sections produced

1. Yesterday at a glance
2. Decisions you missed
3. Account movement
4. Reps in motion
5. Stub-to-real escalations

Each section is a markdown block. The skill must NEVER invent facts —
it only restates the structured input. If a section has no data, render
"No activity yesterday."
