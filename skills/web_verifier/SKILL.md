---
name: web_verifier
version: 0.1.0
model: us.anthropic.claude-sonnet-4-6
prompt: prompt.j2
quality_bar: corroboration_precision_min:0.9
trigger: post_call_fanout
---

# Web Verifier

Verifies one extracted claim against a single web page that the
mini-agent (`app/miniagents/web_verifier.py`) fetched in advance.

This is the speed-optimized single-skill design — it replaces the
three-skill (planner + adjudicator + reporter) pipeline. The mini-agent
does heuristic URL selection, fetches ONE page, and passes the snippet
to this skill for adjudication.

## Output verdicts

- `corroborated`  — page directly states the claim
- `unconfirmed`   — page is silent on the claim or fetch failed
- `contradicted`  — page directly refutes the claim

## Quality bar

`corroboration_precision_min:0.9` — saying "the web confirms this" when
it doesn't is the worst-case failure.
