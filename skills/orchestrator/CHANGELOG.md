# Orchestrator Skill — Changelog

## 0.1.0 — 2026-05-17

Initial Phase 0 release. Streaming-only skill (uses LLMClient.stream_chat
directly rather than LLMSkill.run). Separate system_prompt.j2 and
turn_prompt.j2 rendered by app/orchestrator/prompts.py. Quality bar is
manual for Phase 0; load-test latency is the production gate.
