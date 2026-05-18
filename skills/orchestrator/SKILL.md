---
name: orchestrator
version: 0.1.0
model: us.anthropic.claude-haiku-4-5-20251001-v1:0
prompt: turn_prompt.j2
quality_bar: manual
trigger: voice_turn
---

# Orchestrator

Drives the conversation on a live call. One invocation = one Rep utterance ->
one streamed agent reply.

The orchestrator is the **only** skill that streams. All others (classifier,
summarizer, ...) are one-shot JSON producers. The Orchestrator uses
LLMClient.stream_chat() directly rather than the LLMSkill.run() helper.

## Inputs

- `workspace_name` - for tone + first-person reference
- `caller` - the Field Rep on the line (name, role, profile summary if known)
- `conversation_history` - prior turns this call (capped at last 40)
- `caller_hits` - relevant Caller Memory entries
- `brain_hits` - relevant Workspace Brain pages
- `manager_whispers` - any Manager mid-call guidance (Phase 1; empty list in Phase 0)
- `available_tools` - JSON-schema list of OrchestratorTool definitions

## Output

Free-form text - the agent's spoken reply. The streamer wraps each token-group
in NDJSON `{"text": "...", "interim": true|false}` for AgentPhone.

## Tools

The Orchestrator emits tool calls inline (OpenAI tool-call shape). Phase 0
ships these tools (stub or real):

| Tool | Status | Section |
|---|---|---|
| request_manager_decision | real | §C6 |
| request_correction | stub | §C8 |
| mark_followup | stub | Phase 1 |
| fetch_account | stub | §C8 |
| end_call | real | §C4 |

## Quality bar

Manual eval for Phase 0 - the production proof is the load test in
tests/load (caller-perceived latency P95 < 1s with streaming on).
