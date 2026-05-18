# Voice of the Field — High-Level Design

**Version:** 0.6 (Draft — independent smoke-test framework for every third-party + infrastructure integration)
**Status:** Design Review
**Owners:** Engineering

> **What changed since v0.5:** added §12 (Verification & Smoke Tests for Third-Party Integrations) — a standardized `Probe` base class, one independent smoke script per integration (AgentPhone, Supermemory, LLM, Postgres × 2, Redis, Object Storage), three operating modes (`check` / `smoke` / `repair`), four-value exit codes, JSON+pretty dual output. The LLM probe is written against the **OpenAI chat-completions API shape** so swapping providers (Anthropic via compat endpoint, OpenAI, vLLM, Ollama, Groq, Together) is a config change in the smoke env. Aggregating runner with parallel execution, manifest-driven probe registry, CI integration at three stages (pre-merge, pre-deploy, post-deploy) plus hourly production cron. Phase Map (§13, renumbered) gained a new Phase 0 priority for the smoke framework. Subsequent sections renumbered (Phase Map 13, Open Questions 14, Appendix 15).
>
> **v0.5:** streaming hot path, multi-call live view, Phase 1 Manager whisper-mode intervention, daily-brief flagging of missed decisions, local+cloud deployment profiles.
>
> **v0.4:** §11 Third-Party Integration Contracts; AgentPhone event names and webhook security; "Agent" naming-collision convention.
>
> **v0.3:** terminology unified on Workspace / Field Rep; brain schema `brain_w_{workspace_id}`; §8 extension-point summary.

---

## 1. Overview

**Voice of the Field (VotF)** is a phone-first intelligence layer that turns every customer-facing conversation into structured, actionable knowledge for leadership. After a meaningful customer touch, a Field Rep calls a number. An AI agent — modeled on the questions a great manager asks on a ride-along — interviews them in five minutes. The output is a live, multi-source brain the Manager can query, act on, and trust as a more honest signal than CRM hygiene or weekly status meetings.

The system is **multi-tenant by design** with the unit of isolation called a **Manager Workspace**. Each Manager who signs up gets their own Workspace: their own brain, their own roster of Field Reps, their own data sources, their own AgentPhone number, their own action stream. The shared platform handles telephony, transcription, orchestration, and persistence.

**Core stack:** AgentPhone (telephony), Supermemory (per-caller memory & ingested raw sources), a GBrain-inspired Workspace Brain (operational knowledge per Manager), Python services with FastAPI for the API, Postgres + pgvector for Workspace-owned data, Redis for queues / pub-sub / session state, and an LLM provider (Anthropic by default).

---

## 2. Glossary, Hierarchy & Terminology

The system is structured around a **three-level hierarchy**. Phase 0 implements the middle level (Manager Workspace) and reserves the top and bottom (Organization, Field Rep User) for later phases.

```
Organization                    (future: many Managers under one Org with shared rollups)
   └── Manager Workspace        (today: the unit of isolation; one Manager, one brain, one number)
         ├── Field Rep          (today: callers + data subjects; future: also FE users)
         ├── Field Rep
         └── ...
```

**Phase 0 reality.** Every Manager who signs up gets an Organization (auto-created, single-Manager, invisible) and one Manager Workspace beneath it. Field Reps exist as callers and as data subjects in the Manager's Workspace Brain, but they do not yet have Front-End logins.

**Architectural commitment.** The schema, the API path structure, the auth model, the brain isolation boundaries, and every extension point are designed *as if* multi-Manager Organizations and Rep-side Front-End access already existed. They are not implemented in Phase 0, but they are not blocked either. Lighting them up in later phases is a feature flip, not a refactor.

### 2.1 Terminology Conventions (single source of truth)

| Term | Definition |
|---|---|
| **Organization** | The top-level container. Phase 0: auto-created at Manager signup, single-Manager, invisible. Future: a company with multiple Workspaces, org-level admins, shared rollups. |
| **Manager Workspace** (often shortened to *Workspace*) | The unit of isolation. One Manager, one Workspace Brain, one AgentPhone number, one roster of Field Reps. **`workspace_id` is the canonical scope column on every workspace-owned entity.** Where the term *tenant* appears in this doc, it always refers to a Workspace; we standardize on `workspace_id` in code. |
| **Manager / Main User** | The human who signs up. Owns one Workspace. Configures data sources, sees the Front-End dashboard, makes live decisions during calls. |
| **Field Rep** (class name: `FieldEmployee`) | A member of the Manager's team. Calls the Workspace's number after customer touches. Phase 0: a data subject + caller identity inside the Workspace. Future: also a `User` with FE login. The class name `FieldEmployee` is retained for code; prose says *Field Rep*. |
| **User** (auth principal) | An authenticated account. `role` determines access: `manager` (Phase 0), `org_admin` / `rep` / `viewer` (schema-supported, FE not yet built). |
| **Customer / Account** | The third-party person/company the Field Rep met with. Never logs in, never calls. Appears as a data subject in the Workspace Brain. |
| **Orchestrator Agent** | The conversational agent that handles one live call. One per call, scoped to one Workspace. |
| **Mini Agent** | A specialized, non-conversational agent invoked by the Orchestrator (hot path, HTTP) or by post-call workers (queue). |
| **Workspace Brain** (or just *Brain*) | The Manager's operational knowledge base. Markdown-backed pages, hybrid search, typed entity graph. GBrain-inspired. Lives in Postgres schema `brain_w_{workspace_id}`. One per Workspace. |
| **Caller Memory** | Per-Field-Rep history in Supermemory, keyed `workspace:{workspace_id}:caller:{field_employee_id}`. |
| **Decision Loop** | The mid-call mechanism by which the Orchestrator pushes a question/option to the Manager and consumes their response. Phase 0: only the Manager is paged. |
| **Privacy posture (Phase 0)** | All content in a Workspace is visible only to that Workspace's Manager. There are no peer, team, or org-level visibility tiers yet. |

---

## 3. Goals and Non-Goals

### 3.1 Goals

1. Every call is captured, transcribed live, and persisted as a first-class artifact.
2. The Orchestrator conducts a ride-along-quality interview, drawing on the Workspace Brain + Caller Memory.
3. The Manager can be pinged mid-call for live decisions and the Orchestrator adapts.
4. The Workspace Brain compounds: every call enriches accounts, people, products, and themes.
5. Mini agents, tools, and skills are pluggable — adding a new capability is a single registry entry plus a directory on disk.
6. Front-End consumes a stable FastAPI surface; backend can evolve without breaking it.
7. Workspace isolation: no Workspace ever sees another Workspace's data, brain, or transcripts.
8. The architecture commits to (but does not implement) multi-Manager Organizations and Rep-side Front-End access; these light up in later phases without schema or API restructuring.

### 3.2 Non-Goals (initial release)

- A custom telephony stack (we lease the capability from AgentPhone).
- A full CRM replacement. We integrate with CRMs as a data source; we don't try to be one.
- Outbound campaign calling, IVR menus, or call center features beyond what the product needs.
- A custom LLM. We consume LLM-as-a-service.
- Org-level dashboards and Rep-side Front-End (Phase 1+ work, *designed for* but not implemented).

---

## 4. System Architecture

```
                         ┌──────────────────────────────────────────────┐
                         │                  FRONT-END                    │
                         │  (Manager web app: dashboard, live call view,│
                         │   decision prompts, transcripts, action      │
                         │   items, brain explorer)                     │
                         └──────────────┬───────────────────────────────┘
                                        │  HTTPS + WebSocket
                                        │
                         ┌──────────────▼───────────────────────────────┐
                         │           FastAPI Gateway                     │
                         │  Auth · Workspace scoping · Routers · WS hub │
                         └──┬──────────┬──────────┬──────────┬──────────┘
                            │          │          │          │
        ┌───────────────────┘          │          │          └─────────────────────┐
        │                              │          │                                │
   ┌────▼──────┐              ┌────────▼─────┐ ┌──▼────────────┐         ┌────────▼────┐
   │ Telephony │              │ Orchestrator │ │ Mini-Agent    │         │ Background   │
   │  Adapter  │              │   Service    │ │  Runtime      │         │  Workers     │
   │(AgentPhone│◄──webhook────│  (per call)  │ │ (summarize,   │         │  (post-call, │
   │ unified)  │              │              │ │ research,     │         │  brain sync, │
   └────┬──────┘              └──┬──────┬────┘ │ schedule,     │         │  enrichment) │
        │                        │      │      │ rollup, etc.) │         └──────┬───────┘
        │ voice + SMS            │      │      └───┬───────────┘                │
        │                        │      │          │                            │
        │                        │      │          │  HTTP / Queue              │
        │                        │      │          │                            │
        │                ┌───────▼──────▼──────────▼────────────────────────────▼───┐
        │                │                    Memory & Brain Layer                    │
        │                │                                                            │
        │                │   ┌──────────────────┐    ┌───────────────────────────┐  │
        │                │   │   Supermemory     │    │   Workspace Brain         │  │
        │                │   │   (managed SaaS)  │    │   (per Workspace)         │  │
        │                │   │                   │    │   GBrain-inspired          │  │
        │                │   │ - Caller Memory   │    │   Postgres + pgvector      │  │
        │                │   │ - ingested raw    │    │   Markdown pages           │  │
        │                │   │   sources         │    │   Hybrid search + RRF      │  │
        │                │   │                   │    │   Typed entity graph       │  │
        │                │   └──────────────────┘    └───────────────────────────┘  │
        │                └────────────────────────────────────────────────────────────┘
        │
        │  PSTN  ┌────────────────┐
        └───────►│  AgentPhone     │
                 │  (numbers, STT, │
                 │   TTS, threads) │
                 └────────────────┘

   Cross-cutting:
   - Postgres (app state: workspaces, users, calls, decisions, action items, transcripts)
   - Redis (queue, pub/sub, transcript bus, session state)
   - Object storage (recordings, raw transcripts, ingested files)
   - LLM provider (Anthropic) · Observability (logs, traces, metrics)
```

---

## 5. Core Components

### 5.1 Telephony Layer — AgentPhone Adapter

AgentPhone is the right primitive for this product. It exposes a single webhook for both voice and SMS, transcribes voice calls in real time and delivers them to that webhook as text, accepts text replies which it speaks back via TTS, and threads the conversation automatically. That removes a meaningful amount of telecom plumbing compared to raw Twilio.

**The AgentPhone event model.** Inbound events (defined in §11.2.3 in detail):

- `agent.message` with `channel ∈ {sms, mms, imessage}` — inbound text message.
- `agent.message` with `channel = voice` — a transcribed voice turn during an active call.
- `agent.call_ended` — call has ended; includes the full transcript and an AgentPhone-side summary that we use as a signal (our own `summarizer` mini-agent produces the canonical post-call summary, since AP doesn't have Workspace Brain context).

**Responsibilities of our adapter:**

- Verify the AgentPhone webhook HMAC signature on every delivery (`X-Webhook-Signature` = `sha256=<hex>` over `{timestamp}.{raw_body}` with the per-webhook secret); reject deliveries older than 5 minutes; deduplicate by `X-Webhook-ID`.
- Translate AgentPhone webhook events into internal `MessageEvent` and `CallEvent` types.
- Resolve the inbound number → Workspace → Orchestrator session. As an optimization, we store `{workspace_id, call_id, field_employee_id}` in the AgentPhone `conversationState` per conversation, so AP echoes our scope back on every webhook hit and we skip a DB lookup.
- Stream transcript fragments to the live transcription bus.
- For voice turns: return NDJSON streaming responses to AP (interim chunks first to start TTS early, final chunk closes the turn).
- Send outbound TTS replies (synchronous, via webhook response) and outbound SMS (via REST).
- Handle call lifecycle by reacting to `agent.message:voice` (in-progress) and `agent.call_ended` (post-call).

**Numbering strategy.** Phase 0 provisions **one dedicated AgentPhone number per Workspace**, attached to **one AgentPhone Agent per Workspace** (an "AgentPhone Agent" is AP's persona concept — see §11.1 on the naming collision). Workspace resolution is a single DB lookup: `Workspace.where(primary_number=incoming_number)`, with `conversationState` echo as the fast path on subsequent webhooks for the same conversation. Shared-pool routing is *not* built in Phase 0; it is a deferred option in §13.3.

**Why not Twilio directly.** AgentPhone's unified webhook and built-in transcription mean roughly half the plumbing. We retain the option to add a Twilio adapter behind the same `TelephonyProvider` interface (§8.5) without changing the rest of the system.

### 5.2 Identity, Hierarchy & Caller Profiling

**Scoping.** Every workspace-owned entity carries `workspace_id` (the primary scope) plus `organization_id` (denormalized for fast org-level queries when those features ship). All Postgres queries are scoped to the Workspace at the repository layer; the FastAPI auth dependency resolves both IDs from the JWT and enforces them on every query. Cross-Workspace access is impossible by construction, not by convention.

**Auto-created Organization.** In Phase 0 every Manager signup creates an `Organization` (single-Manager, invisible in the UI) and one `ManagerWorkspace` beneath it. The Manager's JWT carries both IDs. The Organization is recorded but unused in the API; when org-level rollups ship, the API just starts honoring `/organizations/{org_id}/...` endpoints without touching the existing Workspace endpoints.

**Field Rep identity has two tiers (Phase 0):**

1. **Profiled Reps.** Number is on the Manager's roster. We greet by name, load Caller Memory immediately, skip verification.
2. **Unprofiled callers.** Number is unknown to the Workspace. We run a dynamic profiling flow:
   - Confirm Workspace association (a Manager-issued passcode, an invite link, or a question the Orchestrator asks) so we don't accept callers from outside the Manager's team
   - Capture name, role, region / team
   - Optionally ping the Manager: "New caller XYZ from number ABC, add to roster?"
   - On confirmation, create the `FieldEmployee` record and start the interview

The profiling flow is a sub-skill of the Orchestrator, not a separate IVR.

**Future: Field Rep `User` accounts.** When rep-side FE access ships, a Rep gains a `User` row with `role=rep` linked 1:1 to their existing `FieldEmployee` row via `FieldEmployee.user_id`. They authenticate normally, but their visibility is scoped to their own calls and to brain pages the Manager has explicitly permitted them to see. The schema is already shaped for this (§6); the FE just doesn't expose it yet.

**Authentication & roles.**

*Phase 0 implemented:*
- `manager` — full access to one Workspace; the human who signed up.

*Phase 0 schema-supported but not exposed (future):*
- `org_admin` — spans Workspaces in an Organization.
- `rep` — scoped to own calls + Manager-permitted brain pages.
- `viewer` — read-only.

Auth is JWT-based with refresh tokens. Every JWT carries `{user_id, organization_id, workspace_id, role}`. The FastAPI auth dependency rejects any request whose `workspace_id` doesn't match the requested resource. Adding the future roles is a role-check addition, not an auth-layer change.

### 5.3 Memory & Brain Layer

The most consequential design decision in the system. We use **two separate memory systems** with different semantics:

#### 5.3.1 Supermemory — Caller Memory and Ingested Raw Sources

Supermemory's strengths fit the caller side: hands-off ingestion, automatic profile extraction with temporal updates, multi-tenancy by user ID, and managed retrieval. We use Supermemory for:

- **Caller Memory.** Per-Field-Rep history, keyed `workspace:{workspace_id}:caller:{field_employee_id}`. Every call's transcript and extracted facts feed back in.
- **Ingested raw sources** that the Manager provides during onboarding: CRM exports, prior call notes, product docs, account briefs. Stored under keys like `workspace:{workspace_id}:source:{source_type}:{document_id}` so the Orchestrator can retrieve relevant context per call and filter by source type.

We use Supermemory's **API/SDK mode**, not the proxy/Router. The Router would simplify integration but adds latency on the hot path and forfeits ranking control, which matters on a real-time voice call.

#### 5.3.2 Workspace Brain — GBrain-Inspired, Multi-Workspace

The Workspace Brain is where the system's compounding intelligence lives: accounts, people, products, deal patterns, playbooks, themes that recur across the Manager's team's calls. GBrain has the right *patterns* for this — markdown source of truth, hybrid vector + keyword search with RRF fusion, a self-wiring typed entity graph extracted with zero LLM calls, compiled-truth-plus-timeline page model — but it's designed as a single-operator system. Running raw GBrain per Workspace doesn't scale operationally.

**Our approach.** Implement a GBrain-inspired Brain service in Python, multi-Workspace from day one. We borrow:

- **Page format:** `compiled truth` (current understanding, rewritable) above a separator, `timeline` (append-only events with citations) below.
- **Hybrid search:** pgvector HNSW for embeddings + Postgres `tsvector` for keyword + Reciprocal Rank Fusion.
- **Typed graph:** regex-based entity extraction on every write, building edges like `mentioned_in`, `works_at`, `attended`, `discussed`. Zero LLM calls on the write path.
- **Backlink-boosted ranking** so well-connected entities surface first.
- **Cron-driven enrichment** ("dream cycle"): consolidate, deduplicate, fix citations, escalate stub entities to full pages once they're mentioned across multiple calls.

**Multi-Workspace isolation.** Schema-per-Workspace in a shared Postgres cluster (`brain_w_{workspace_id}`). Connection pooling and a router select the schema by `workspace_id`. This gives clean isolation, easy backup/restore per Workspace, and clear cost attribution, without the operational pain of one DB cluster per Workspace.

**Why not just call GBrain over its MCP server.** We'd be embedding a TypeScript single-operator brain into a Python multi-Workspace product. The integration surface (per-Workspace brain processes, file watching, sync, auth on the MCP layer) ends up larger than implementing the patterns ourselves. We can still use GBrain as a prototype/reference during early development to validate the approach.

#### 5.3.3 The Two Together

```
Caller side                                  Workspace side
─────────────────────────                    ─────────────────────────
Supermemory                                  Workspace Brain (Postgres)
- Caller Memory (per Rep)                    - accounts, people, products
- ingested raw sources                       - playbooks, themes
                                             - self-updating learnings
keyed by:                                    schema:
  workspace:{wid}:caller:{eid}                 brain_w_{workspace_id}
  workspace:{wid}:source:{type}:{id}
```

On every call, the Orchestrator pulls from both: caller context (who am I talking to, what have they said before?) and Workspace Brain (what do we know about this account, this product, this pattern?). After the call, post-call workers write back to both.

### 5.4 Orchestrator & Mini-Agent Runtime

**Orchestrator (one per live call):**

- Spun up on inbound call
- Loads Workspace config, Caller Memory profile (from Supermemory), and the "interview playbook" (from Workspace Brain)
- Drives the conversation in turns; each turn:
  1. Receive transcribed user utterance from AgentPhone webhook
  2. Update transcript bus (live)
  3. Retrieve relevant context (Caller Memory + Workspace Brain hybrid search, in parallel)
  4. LLM call with system prompt + retrieved context + conversation history + tool schemas
  5. Decide: speak back, invoke tool, request Manager decision, end call
  6. Send reply text to AgentPhone (it speaks)

The Orchestrator is **stateful per call**, with state in Redis keyed by `call_id`. State includes: conversation history, retrieved-context cache, pending decisions, tool invocations in flight.

**Mini-Agent Runtime.** Mini agents are small, single-purpose services invoked over HTTP (hot path) or via queue (cold path). Each implements the common interface in §8.2. Initial roster:

| Mini Agent | When invoked | Purpose |
|---|---|---|
| `summarizer` | Post-call (queue) | Produce structured summary + action items |
| `brain_updater` | Post-call (queue) | Extract entities, update Workspace Brain pages |
| `brain_seeder` | Onboarding (queue) | Seed brain from uploaded documents during F1 |
| `researcher` | Mid-call (HTTP) or post-call | Web browse to verify a claim or pull product info |
| `scheduler` | Approved action item | Draft email or calendar invite, await approval |
| `dashboard_rollup` | Nightly cron | Roll up Workspace-wide trends into a daily brief |
| `caller_profiler` | First-call (mid-call) | Build a Field Rep profile from a new unprofiled caller |

Mini agents do **not** drive the conversation. The Orchestrator owns the user-facing turn; mini agents are tools or post-processors.

**Communication.**

- Hot path (mid-call): HTTP, with strict timeouts (~1.5s for in-conversation calls).
- Cold path (post-call, async): Redis queue, idempotent job handlers.

### 5.5 Real-Time Layer

The real-time layer covers four concerns: (a) end-to-end **streaming** so caller-perceived latency is minimized, (b) the **transcript bus** that powers live FE views, (c) the **Decision Loop** for mid-call Manager prompts, and (d) **Manager intervention** in live calls (Phase 1).

#### 5.5.1 End-to-End Streaming (Rep ↔ LLM ↔ Rep)

The hot path is **streamed at every stage** to minimize the silence the Rep hears between finishing their utterance and the agent starting to speak.

```
Rep finishes speaking
  │
  ▼  ~50ms
AgentPhone delivers full transcript for the turn (agent.message:voice)
  │
  ▼  ~10ms
Adapter publishes to transcript bus + WS hub (Manager sees it live)
  │
  ▼  ~100-300ms
Orchestrator: parallel retrieval (CallerMemory + Brain hybrid search)
                  │
                  │  If retrieval will take >300ms:
                  │  emit interim NDJSON chunk to AP first:
                  │  {"text":"Let me check on that...","interim":true}
                  ▼
Orchestrator: streaming LLM call (Anthropic client.messages.stream())
  │
  ▼  first token at ~400-600ms after retrieval
For each token-group from the LLM:
  emit NDJSON chunk to AP: {"text":"<token-group>","interim":true}
  → AP starts TTS on first chunk
  │
  ▼
Last chunk (no interim flag) closes the turn
  │
  ▼  AP speaks the full reply, having started ~700ms after Rep finished
```

**The key wins are token-streaming and the bridge chunk:**

- **Token-streaming the LLM → TTS.** Anthropic's `client.messages.stream()` yields tokens as they're generated. We forward each token-group to AP as an interim NDJSON chunk; AP's TTS begins on the first chunk while the LLM is still generating. Caller hears the agent start speaking ~700ms after they finished — vs. ~2s if we waited for the full LLM completion.
- **Bridge chunk before slow work.** If retrieval, a tool call, or a manager-decision request will exceed ~300ms, the Orchestrator emits a short interim chunk *before* the slow operation. AP speaks "Let me check on that..." while we work. AgentPhone's 30s voice-webhook timeout is on response *start*, not response *finish*, so streaming chunks early keeps the turn alive indefinitely up to the configured ceiling.
- **Tool-call interleaving.** If a turn requires a tool call (e.g., `web_research`), the Orchestrator emits the bridge chunk → runs the tool → calls the LLM again with the tool result → streams the final answer. All within the same voice turn.

This is the single most important latency optimization in the system. The §14 Appendix has the per-millisecond breakdown.

#### 5.5.2 Live Transcript Bus & Multi-Call Live View

**Internal bus.** Redis pub/sub, channel-per-call: `call:{call_id}:transcript`. The telephony adapter publishes transcript fragments + lifecycle events as they arrive; multiple subscribers can consume the same channel.

**WebSocket model for the Front-End.** A Manager often has multiple Reps making calls at the same time. Rather than asking the FE to open one WebSocket per call, we use **one WebSocket per Manager session** that multiplexes all of the Manager's Workspace's active calls.

```
/api/v1/workspaces/{workspace_id}/ws/live
```

The server subscribes to all `call:*:transcript` channels for that Workspace and forwards each frame to the WS, tagged with `call_id`. The FE routes each frame to the correct call pane. Frames the WS emits:

| Frame type | Payload | When |
|---|---|---|
| `call.started` | `{call_id, field_employee_id, started_at}` | New inbound call begins |
| `transcript.fragment` | `{call_id, speaker, text, ts}` | Each transcribed turn (Rep or agent) |
| `decision.opened` | `{call_id, decision_id, prompt, options, decision_class, timeout_at}` | Orchestrator requests a manager decision |
| `decision.resolved` | `{call_id, decision_id, response, responded_via}` | Decision answered or timed out |
| `call.ended` | `{call_id, ended_at}` | Call completes |
| `takeover.granted` | `{call_id, taken_over_by_user_id, mode}` | Manager intervention activated (Phase 1, §5.5.4) |
| `takeover.released` | `{call_id}` | Manager hands control back |

The FE maintains an "Active Calls" panel populated by these frames. A separate REST endpoint `GET /api/v1/workspaces/{wid}/calls?status=in_progress` provides the initial list on page load.

Per-Workspace fan-out is unbounded in principle (a Manager with 50 simultaneous calls would see 50 panes); in practice we cap the FE rendering to the most recent N and rely on virtualization. The server-side WS sends everything; the FE decides what to render.

#### 5.5.3 Decision Loop (Mid-Call Manager Prompt)

The Orchestrator has a tool `request_manager_decision(prompt, options, decision_class)`. The `decision_class` is one of three values that drive timeout and conversational behavior:

| Class | Default timeout | Typical use | What Orchestrator does while waiting |
|---|---|---|---|
| `inline` | 45s | Rep needs an answer to continue the same thread | Emits an interim "let me check on that" chunk, then bridges to an adjacent question: *"While I do, what did the buyer say about timeline?"* |
| `bridged` | 2 min | Decision can be deferred a few turns without blocking | Moves to a different topic; weaves the answer in when it arrives |
| `async` | no live wait | Decision doesn't need to land during the call | Creates a `DecisionRequest`, continues call normally, surfaces post-call |

When invoked (`inline` or `bridged`):

1. Persist `DecisionRequest` (`status=open`, `target_user_id=manager`, `timeout_at=now+class_timeout`).
2. Push `decision.opened` frame over the Manager's live WS (§5.5.2).
3. Fire an SMS to the Manager's mobile in parallel; whichever surface the Manager taps first wins.
4. Orchestrator continues the conversation with class-appropriate bridging.
5. When the Manager taps an option (FE) or replies (SMS), the response is published to the Orchestrator's call session and consumed in the next LLM turn. A `decision.resolved` frame is emitted on the WS.

**On timeout with no response (Phase 0).** The Orchestrator tells the Rep, plainly, that the Manager is unavailable, and **moves on** — the rest of the meeting still needs to be captured:

> *"I tried to check with [Manager] on that and they're not available right now. I'll flag it for them and we'll get back to you. Now, was there anything else the customer brought up that we haven't covered?"*

The `DecisionRequest` is marked `timed_out` and:

1. Surfaces in the post-call review as an unresolved item.
2. **Flagged on the Manager's next daily brief** (produced by `dashboard_rollup` mini-agent) with a dedicated "Decisions you missed" section listing the prompt, the call context, the original options, and a one-click "Resolve now" CTA that fires whatever delayed action is needed.

The point: a timed-out decision is not lost. It's not silently buried in a review pile either. It surfaces explicitly in the next brief so the Manager can act on it the next morning.

**Future delegation (deferred).** The same `DecisionRequest` model supports delegation via `target_user_id` rotation. A delegation worker can re-target an open request to an `org_admin` after a sub-timeout. Data model, tool schema, and WS frame structure already accommodate this; only the routing logic needs to be added.

#### 5.5.4 Manager Intervention in Live Calls (Phase 1)

Beyond answering a discrete decision prompt, a Manager sometimes wants to actively shape the conversation while it's happening. Phase 1 supports **two intervention modes**, ordered by implementation complexity:

| Mode | What the Rep experiences | What the Manager does | Phase |
|---|---|---|---|
| `whisper` | No change — Rep still hears the agent. Agent's next reply incorporates Manager's guidance. | Types a guidance message into the call pane | **1** |
| `takeover` | Agent goes silent; Manager's voice replaces the agent's | Manager activates takeover; speaks via FE (WebRTC) which is bridged into the AP call leg | 2+ |

Phase 1 ships `whisper` only. `takeover` is documented as a designed extension but is not built (real-time WebRTC ↔ AP audio bridging is a substantial telecom integration in its own right).

**Whisper mode flow:**

```
Manager (FE):
  Active call pane → "Whisper to Orchestrator"
  Types: "Push them on the integration timeline — the buyer mentioned
          they have a board check-in next week. Use that urgency."
  Submits
   │
   ▼
POST /api/v1/workspaces/{wid}/calls/{call_id}/whisper
  body: {"guidance": "..."}
   │
   ▼
Orchestrator session in Redis: append guidance to a "manager_whispers"
  buffer scoped to this call. Mark the next LLM turn as "supervised".
   │
   ▼  next Rep utterance arrives
LLM turn includes additional system-prompt section:
  ## Manager Guidance (private — do not repeat verbatim to caller)
  - "Push them on the integration timeline — the buyer mentioned they have
     a board check-in next week. Use that urgency."

  Use this guidance to shape your next reply. Do NOT acknowledge that the
  manager has spoken; respond naturally as if this were your own judgment.
   │
   ▼
Streaming reply emitted as normal (§5.5.1)
   │
   ▼
WS frame to Manager: takeover.granted (mode=whisper) — confirms guidance was applied
```

**Why whisper before takeover.** Whisper handles ~90% of the "Manager wants to intervene" cases — coaching, course-correcting, providing context the agent couldn't have known. It's a single REST POST + a prompt-injection change in the Orchestrator. No telephony work. `takeover` requires WebRTC audio bridging through our backend into AP's call leg, which is a much bigger undertaking and lower marginal value over whisper for most situations.

**Data model addition** (Phase 1):

```python
class ManagerIntervention(Base):
    id: UUID
    call_id: UUID
    workspace_id: UUID
    user_id: UUID                # the Manager who whispered/took over
    mode: Literal["whisper", "takeover"]
    started_at: datetime
    ended_at: datetime | None    # null while active; for takeover only
    payload: dict                # whisper: {guidance: "..."}; takeover: session metadata
```

Every intervention is **audited**: post-call review shows when the Manager intervened, what they whispered, and how the conversation changed afterward. This matters for trust and for later coaching of the Orchestrator's behavior.

#### 5.5.5 Inbound SMS for the Manager

The Workspace's AgentPhone number also accepts inbound SMS. The webhook routes:

- SMS *from* a roster Field Rep → text-based field report, ingested into Caller Memory + Workspace Brain.
- SMS *from* the Manager → if there's an open `DecisionRequest`, it's the response; otherwise treated as a brain-write command (e.g., *"note: customer X said Y"* → new brain page).
- SMS *from* an unknown number → profiling flow.

### 5.6 API Layer — FastAPI

The API is the single contract with the Front-End. Path structure is **future-ready from Phase 0**:

```
/api/v1/
  auth/...                                # signup, login, refresh — always available
  me/...                                  # current user

  /workspaces/{workspace_id}/...          # Manager-scoped (Phase 0)
      config
      data-sources
      field-employees
      calls
      decisions
      action-items
      brain
      dashboards
      ws/...

  /organizations/{org_id}/...             # Org-scoped (schema-supported, reserved namespace)
  /rep/...                                # Rep-scoped (schema-supported, reserved namespace)
```

Phase 0 implements `/workspaces/{workspace_id}/...`. The `/organizations/...` and `/rep/...` prefixes are reserved — empty routers are registered for them at Phase 0 to reserve the namespace and to power the §12.4 guard test that asserts a stub `org_admin` and stub `rep` user are correctly rejected from endpoints they shouldn't access.

**Module structure:**

```
api/
  main.py                  # app factory, middleware, startup hooks
  deps.py                  # auth, scope, db, current_user dependencies
  routers/
    auth.py
    me.py
    workspaces/            # subpackage; Phase 0
      __init__.py
      config.py
      data_sources.py
      field_employees.py
      calls.py
      decisions.py
      action_items.py
      brain.py
      dashboards.py
      ws.py
    organizations/         # subpackage; placeholder for Phase 1+
      __init__.py          # empty router registered for namespace reservation
    rep/                   # subpackage; placeholder for Phase 1+
      __init__.py          # empty router registered for namespace reservation
  schemas/                 # Pydantic DTOs
  services/                # business logic, called by routers
```

**Scope enforcement.** A FastAPI dependency `require_workspace_access(workspace_id)` is applied to every Workspace-scoped route. It checks that the JWT's `workspace_id` matches the path parameter and that the user's `role` permits the operation. The equivalent dependencies for org and rep scopes ship when those endpoints do.

**Router auto-discovery.** `api/routers/__init__.py` walks the package, imports each module, and registers each module's `router` object onto the FastAPI app. Adding a new endpoint group is dropping a file into the appropriate subpackage.

**Versioning.** All routes mount under `/api/v1/...`. Breaking changes get a new version namespace.

**Real-time.** WebSocket endpoints `/api/v1/workspaces/{workspace_id}/ws/calls/{call_id}` and `/api/v1/workspaces/{workspace_id}/ws/decisions` push live transcript fragments and decision prompts. Auth via short-lived token in the query string.

### 5.7 Background Workers

A worker pool (start with `arq` on Redis; upgrade to Temporal if workflow durability becomes critical) consumes Redis queues.

**Queues:**

- `post_call` — triggered on `call.ended`. Fans out to `summarizer`, `brain_updater`, then computes action items.
- `brain_maintenance` — nightly per Workspace. Runs the "dream cycle": entity consolidation, citation fixing, backlink reconciliation.
- `data_source_sync` — initial ingest and recurring sync for connected sources.
- `correction_cascade` — runs after every correction commit; propagates changes through dependent edges and denormalizations (see §9.4).
- `action_item_followup` — fires scheduled action items (send the email at T+1d, etc.).

All handlers are **idempotent** and keyed by stable IDs so retries are safe.

### 5.8 Storage

| Store | Purpose | Notes |
|---|---|---|
| Postgres (app DB) | Workspaces, users, rosters, calls, decisions, action items, transcripts, intake | Row-level `workspace_id`; indexed per query path |
| Postgres (brain) | Brain pages, embeddings, graph edges | Schema-per-Workspace: `brain_w_{workspace_id}`; pgvector + tsvector |
| Supermemory (cloud) | Caller Memory + ingested raw sources | `workspace:{workspace_id}:caller:{id}` and `workspace:{workspace_id}:source:{type}:{id}` keys |
| Redis | Session state, queues, pub/sub, transcript bus | Single cluster, namespaced keys |
| Object storage (S3 / R2) | Call recordings, raw transcripts, ingested files | Per-Workspace key prefixes; signed URLs to FE |

---

## 6. Data Models

Python sketches (Pydantic for DTOs, SQLAlchemy / SQLModel for ORM). Showing the essentials only.

**Hierarchy note.** Every Workspace-owned entity carries `workspace_id` (the primary scope) plus `organization_id` (denormalized, for fast org-level queries when those features ship).

```python
class Organization(Base):
    id: UUID
    name: str
    created_at: datetime
    # Phase 0: one Workspace per Org (auto-created at signup)
    # Future: many Workspaces, org-level admins, shared rollups

class ManagerWorkspace(Base):
    id: UUID                          # what `workspace_id` references everywhere
    organization_id: UUID
    manager_user_id: UUID             # the Manager who owns this Workspace
    name: str
    primary_number: str               # AgentPhone-provisioned, unique
    created_at: datetime
    config: dict                      # Workspace-level settings (timeouts, retention, defaults)
    # Brain lives in Postgres schema brain_w_{id}, keyed off this row

class User(Base):
    id: UUID
    organization_id: UUID
    workspace_id: UUID | None         # null for org_admin spanning the Org
    field_employee_id: UUID | None    # set when role=rep, links to FieldEmployee
    email: str
    role: Literal[
        "manager",                    # Phase 0: implemented
        "org_admin",                  # schema-supported, FE not built yet
        "rep",                        # schema-supported, FE not built yet
        "viewer",                     # schema-supported, FE not built yet
    ]
    front_end_push_token: str | None
    created_at: datetime

class FieldEmployee(Base):
    id: UUID
    workspace_id: UUID
    organization_id: UUID             # denormalized
    user_id: UUID | None              # future: link to User when rep gets FE access
    name: str
    phone: str                        # E.164
    role: str | None
    team: str | None
    profiled: bool                    # False = captured dynamically via profiling flow
    supermemory_user_id: str          # "workspace:{wid}:caller:{eid}"

class Call(Base):
    id: UUID
    workspace_id: UUID
    organization_id: UUID
    field_employee_id: UUID | None    # null until profiling completes
    agentphone_call_id: str
    started_at: datetime
    ended_at: datetime | None
    status: Literal["ringing", "in_progress", "ended", "failed"]
    recording_uri: str | None
    transcript_uri: str | None

class TranscriptFragment(Base):
    id: UUID
    call_id: UUID
    workspace_id: UUID
    speaker: Literal["caller", "agent"]
    text: str
    ts: datetime
    seq: int

class DecisionRequest(Base):
    id: UUID
    call_id: UUID
    workspace_id: UUID
    target_user_id: UUID              # Phase 0: always the Manager. Future: delegate.
    prompt: str
    options: list[str]
    decision_class: Literal["inline", "bridged", "async"]
    timeout_at: datetime
    status: Literal["open", "answered", "timed_out", "cancelled"]
    response: str | None
    responded_at: datetime | None
    responded_by_user_id: UUID | None # who actually answered; Phase 0 == target_user_id
    responded_via: Literal["websocket", "sms"] | None

class ActionItem(Base):
    id: UUID
    workspace_id: UUID
    organization_id: UUID
    call_id: UUID
    field_employee_id: UUID | None    # the Rep this relates to, if any
    title: str
    description: str
    due_at: datetime | None
    status: Literal["pending_approval", "approved", "rejected", "done"]
    handler: str                      # which mini-agent handles execution
    payload: dict

class BrainPage(Base):                # in brain_w_{workspace_id} schema
    slug: str                         # path-like: "accounts/acme-corp"
    type: str                         # account, person, product, theme, ...
    title: str
    compiled_truth: str               # rewritable, versioned per §9.3
    timeline: list[TimelineEntry]     # append-only
    tags: list[str]
    updated_at: datetime

class BrainEdge(Base):                # in brain_w_{workspace_id} schema
    src_slug: str
    dst_slug: str
    edge_type: str                    # works_at, attended, mentioned_in, owns, ...
    weight: float
    extracted_from: str               # source page slug or call_id
```

---

## 7. Key Flows

### 7.1 F1 — Manager Onboarding & Initial Brain Seeding (Phase 0)

The most consequential flow in Phase 0. The Manager arrives with knowledge in their head, in their documents, and in their prior call notes. The backend must route each piece of information correctly into **two distinct memory layers** without making the Manager think about routing themselves.

#### 7.1.1 The Two Memory Layers

| Layer | Scope | Lives in | Examples |
|---|---|---|---|
| **Workspace Brain** | One per Workspace. Shared across all the Workspace's calls. Self-updates from every Rep's calls. | Postgres schema `brain_w_{workspace_id}` (GBrain-inspired pages, hybrid search, typed graph) | Accounts, products, playbooks, themes, ICP, competitive positioning, common objections |
| **Caller Brain** (per Field Rep) | One per Field Rep within the Workspace | Two stores joined by `field_employee_id`: structured fields in `field_employees` and `caller_profiles`; free-form memory in Supermemory keyed `workspace:{wid}:caller:{eid}` | Identity, role, region, communication style, accounts owned, Manager's notes, call history |

A single piece of information from the Manager can belong to **only one layer, both layers, or neither**, depending on its scope. The backend classifies and routes; the Manager just dumps knowledge.

#### 7.1.2 The Five Stages

```
Stage 1: SIGNUP & WORKSPACE PROVISIONING
   └─► Stage 2: GUIDED INTAKE (manager provides info via 3 channels)
         └─► Stage 3: CLASSIFICATION (scope + kind + target)
               └─► Stage 4: INGESTION (typed handlers write to the right layer)
                     └─► Stage 5: VERIFICATION (manager confirms what we extracted)
```

**Stage 1 — Signup & Workspace Provisioning.** Backend creates: `Organization` row (auto-created, invisible), `ManagerWorkspace` row, `User` row (`role=manager`), an empty Brain schema (`brain_w_{workspace_id}`), a Supermemory namespace, and an AgentPhone number provisioned. Mechanical; seconds.

**Stage 2 — Guided Intake.** Three parallel channels into a single Workspace-scoped `IntakeBuffer`:

1. **Structured forms** in the Front-End. Short, specific, high-signal:
   - Workspace-level: *"What does your team sell?"*, *"Top accounts?"*, *"What's your ICP?"*
   - Per-Field-Rep on the roster:
     - **Structured (required):** name, phone, role, team, region
     - **Free-form (optional, 1–2 paragraphs each):** *"How does this person sell?"*, *"What do they tend to under-report?"*, *"What kind of customer are they best with?"*, *"Anything I should always remind the agent to probe with them?"*
2. **Document uploads.** CRM exports, account briefs, product docs, prior call notes, org chart, sales playbook.
3. **Guided voice intake call.** Same phone agent the Field Reps will use, but in "onboarding mode." 20-minute interview. High-bandwidth, produces the best signal because it's the Manager talking, not filling out forms.

#### 7.1.3 Stage 3 — Classification & Routing

An `IntakeProcessor` service walks the `IntakeBuffer` and classifies each item along **two axes**:

**Axis 1 — Scope:**
- `ORG_WIDE` — true regardless of which Field Rep is involved (e.g., *"Acme uses Salesforce"*)
- `CALLER_SPECIFIC` — only relevant to one Field Rep's behavior or history (e.g., *"Sarah always opens with a personal story"*)
- `BOTH` — Workspace-truth and caller-truth simultaneously (e.g., *"Sarah owns Acme"*) → fans out to both layers with a cross-reference edge
- `RAW_SOURCE` — bulk content for semantic retrieval, plus entity extraction (e.g., a CRM export)

**Axis 2 — Kind:**
`account` · `person` · `product` · `playbook` · `theme` · `caller_identity` · `caller_style` · `raw_document` · `org_positioning` · `off_topic`

The classifier is a cheap LLM call (Haiku-tier) with strict JSON output: `{scope, kind, target_caller_id?, suggested_slug, extracted_entities[], confidence, reasoning}`. Below confidence threshold 0.7 → `NeedsReview` queue, surfaced to the Manager in Stage 5. Full skill definition lives in `skills/classifier/` per §8.7.

**Routing table:**

| Manager provides | Scope | Lands in |
|---|---|---|
| "Acme is our biggest renewal Q3" | `ORG_WIDE` | Workspace Brain page `accounts/acme-corp` |
| "Our Pro tier is $50k, common objection is integration time" | `ORG_WIDE` | Workspace Brain page `products/pro-tier` |
| "We sell into healthcare and fintech, ICP 500–2000 employees" | `ORG_WIDE` | Workspace Brain page `org/positioning` |
| "Sarah is on my team, covers West, 3 years tenure" | `CALLER_SPECIFIC` | Sarah's Caller Brain (`field_employees` + `caller_profiles` rows) |
| "Sarah is great at discovery, weak on multi-threading" | `CALLER_SPECIFIC` | Sarah's Caller Brain (Supermemory, tag: `seeded_by_manager`) |
| "Sarah owns Acme, Initech, Globex" | `BOTH` | Sarah's `owned_accounts` list **and** `owned_by → callers/sarah` edge on each account page |
| CRM export (200 accounts, 340 contacts) | `RAW_SOURCE` | Fan-out (§7.1.4) |
| "Sarah's last 30 call notes" | `RAW_SOURCE` + `CALLER_SPECIFIC` | Fan-out keyed to Sarah |

#### 7.1.4 Stage 4 — Ingestion via Typed Handlers

For each classified item, a typed handler runs. The handlers use the same `MiniAgent` and `DataSourceConnector` interfaces from §8 — onboarding just exercises them at higher volume.

```python
class IntakeProcessor:
    async def process(self, item: IntakeItem) -> None:
        classification = await self.classifier.classify(item)
        handler = self.handler_registry.get(classification.scope, classification.kind)
        await handler.ingest(
            workspace_id=item.workspace_id,
            content=item.content,
            classification=classification,
        )
```

**Handler responsibilities:**

`OrgBrainHandler` (`ORG_WIDE` items):
1. Fuzzy-match slug against existing pages (so re-mentions update, not duplicate)
2. Write `BrainPage` with `compiled_truth` from source, `timeline` starting `[date]: Captured during onboarding from {source}`
3. Run regex entity extractor: people, products, other accounts referenced → stub pages and typed graph edges
4. Compute embeddings, index for hybrid search
5. Track source citation for auditability (see §9)

`CallerBrainHandler` (`CALLER_SPECIFIC` items):
1. Structured fields → update `field_employees` / `caller_profiles` rows
2. Free-form text → push to Supermemory under caller's key with `seeded_by_manager` tag
3. Does **not** write to Workspace Brain — this is the Manager's view of one person, not Workspace truth

`CrossRefHandler` (`BOTH` items):
1. Invoke `OrgBrainHandler` for the Workspace side
2. Invoke `CallerBrainHandler` for the caller side
3. Create bidirectional edges (`owns`, `owned_by`) so traversal works in both directions

`RawSourceHandler` (`RAW_SOURCE` items) — the fan-out pattern. A single CRM export triggers three writes:

1. **Whole document → Supermemory** under `workspace:{wid}:source:crm:{export_id}`. Enables semantic search across all Workspace sources later.
2. **Entity extraction → Workspace Brain.** The `brain_seeder` mini-agent walks rows: each Account → `accounts/{slug}`, each Contact → `people/{slug}`, ownership becomes `owned_by → callers/{caller_id}` edges.
3. **Ownership rollup → Caller Brain.** Each affected caller's `owned_accounts` denormalized list is updated, so the Orchestrator can pull "Sarah owns these 14 accounts" in one query at call start.

For prior call notes uploaded by the Manager (e.g., "Sarah's last 30 call notes"):

1. Each note → Supermemory under Sarah's caller key (tag: `historical_call_note`).
2. Each note → entity extraction into Workspace Brain. The account discussed gets a timeline entry (`2025-03-15: Sarah discussed pricing with Acme — see source`). The brain learns about accounts from past calls without the Manager re-typing.
3. The typed-graph extractor builds the cross-references automatically.

#### 7.1.5 The Cross-Reference Graph

Once both layers exist they must be navigable in both directions:

- **Caller → Workspace edges:** `callers/sarah --[owns]--> accounts/acme-corp`, stored as a graph edge in the Workspace Brain. Caller profile also carries a denormalized list for fast call-start lookup.
- **Workspace → Caller edges:** `accounts/acme-corp` timeline entries cite `callers/sarah on 2025-03-15` with a backlink to the call record.

When Sarah calls in about Acme, the Orchestrator pulls **both directions** in a single retrieval step.

#### 7.1.6 Stage 5 — Verification

The most-important and most-skipped step. After ingestion completes, the Front-End shows the Manager a "What we learned" view:

- *"We created 47 account pages. Top 10 by mention frequency: [list]. Review?"*
- *"We extracted these themes from your prior notes: [list]. Confirm or remove?"*
- *"We assigned account ownership for 200 accounts to 7 callers. Review distribution?"*
- *"We have low confidence about these 12 items — please clarify."*
- *"Here's the Caller Brain we built for Sarah. Edit anything wrong."*

Corrections flow back as `CorrectionIntake` items per §9.2 — they re-enter classification with elevated trust and overwrite the original entries (with full audit trail and cascading).

#### 7.1.7 Retroactive Caller Seeding

The Manager doesn't have to pre-seed every Field Rep. If a Field Rep calls in and isn't on the roster (the unprofiled flow from §7.2):

1. Caller Brain is created from scratch — structured fields from the in-call profiling sub-flow, free-form memory built from the call transcript itself.
2. Manager gets a Front-End notification: *"New caller Maya joined. Want to add context about her?"*
3. If the Manager fills in the optional free-form sections later, those feed Maya's Caller Brain the same way pre-seeded ones did.

#### 7.1.8 Sample Sequence — CRM Export Upload

```
T+0:    File received, stored to object storage, IntakeBuffer entry created
T+1s:   Classifier samples rows → "scope: RAW_SOURCE, kind: raw_document/crm"
T+2s:   RawSourceHandler ships whole file to Supermemory
            (workspace:{wid}:source:crm:{export_id})
T+5s:   brain_seeder mini-agent enqueued
T+10s:  brain_seeder walks 200 rows:
          → 200 account pages created/updated in Workspace Brain
          → 340 person pages (contacts) created
          → 200 ownership edges to caller IDs
          → Each affected caller's owned_accounts list updated
T+30s:  Embedding job runs over new brain pages
T+60s:  Manager sees in FE: "Created 200 accounts, 340 contacts.
                              Assigned to 7 callers. Review?"
T+...:  Manager corrects ownership for 3 accounts → corrections fan
        back through Router as CorrectionIntake (per §9)
```

The Caller Brain side gets populated *as a side effect* of Workspace-level data ingestion, plus directly from per-Rep intake forms. The Workspace Brain gets populated directly from Workspace-level data, plus *as a side effect* of every Caller Brain write that mentions a Workspace entity. That symmetry is what makes the two layers compound together rather than diverge.

### 7.2 F2 — Inbound Call (Hot Path) (Phase 0)

```
Field Rep dials Workspace number
   │
   ▼
AgentPhone receives, opens webhook with call event
   │
   ▼
Telephony Adapter:
  - Resolve Workspace by inbound number
  - Identify caller:
    - If profiled: load FieldEmployee + Caller Memory profile
    - If unprofiled: spawn ProfilingSubFlow (collect identity)
  - Create Call row, open session in Redis
   │
   ▼
Orchestrator session starts
  - Load interview playbook from Workspace Brain
  - Load caller's prior calls and themes (Supermemory)
  - Greet by name (or run profiling)
   │
   ▼
Conversational turns (loop until end):
  - Receive transcribed utterance from AgentPhone webhook
  - Append TranscriptFragment + publish to transcript bus
  - Retrieve context (Supermemory + Workspace Brain hybrid search, parallel)
  - LLM call → reply text + optional tool calls
  - Tools: request_manager_decision, fetch_account, web_research,
    mark_followup, request_correction, end_call
  - Send reply text → AgentPhone TTS
   │
   ▼
Call ends
  - Telephony Adapter receives call.ended
  - Mark Call row ended; flush transcript to object storage
  - Enqueue post_call job
```

**Hot-path latency budget** per turn is roughly 1.5–2.5 seconds end-to-end (transcription → retrieval → LLM → TTS). To stay inside it, the Orchestrator **pre-warms retrieval at call start**: it pulls a "starter pack" (top 20 brain pages + Caller Memory summary) before the first turn, caches it in Redis, and only does targeted retrieval per turn beyond that.

### 7.3 F3 — Manager Decision Request (Phase 0)

Triggered when the Orchestrator's LLM determines a question needs the Manager's judgment.

```
Orchestrator invokes tool:
  request_manager_decision(
    prompt   = "Caller says Acme wants a 20% discount. Approve a counter at 10%?",
    options  = ["Approve 10%", "Hold firm at list", "Defer to me later"],
    decision_class = "inline"    # 45s timeout — Rep is mid-thread
  )
   │
   ▼
DecisionRequest persisted:
  status=open, target_user_id=manager,
  decision_class=inline, timeout_at=now+45s
   │
   ▼
Push to Manager's surfaces in parallel:
  - WebSocket: workspace:{wid}:decisions channel
  - SMS to Manager's mobile via AgentPhone
   │
   ▼
Orchestrator continues the conversation with class-appropriate bridging:
  - inline:  "Let me check on that — while I do, what did the buyer
             say about timeline?"
  - bridged: moves to a different topic; weaves answer in when it arrives
   │
   ▼
Manager taps option in FE OR replies via SMS (first-responder-wins)
   │
   ▼
API receives response; DecisionRequest updated:
  status=answered, response=<choice>, responded_at, responded_via
Notification published to the Orchestrator's call-session channel
   │
   ▼
Orchestrator's next LLM turn receives the decision and weaves it in:
  "Got it — leadership says 10% counter is fine. Did you sense the
   buyer would respond well to that?"

— OR —

On timeout with no response (Phase 0 behavior):
   - DecisionRequest set to timed_out
   - Orchestrator tells the Rep plainly:
     "I tried to check with [Manager] on that and they're not available
      right now. Let me flag it for them and we'll get back to you —
      anything else come up in the meeting I should capture?"
   - The DecisionRequest surfaces in post-call review as a pending item
```

### 7.4 F4 — Post-Call Processing (Phase 1)

On `agent.call_ended` (AgentPhone's call-ended webhook), the adapter persists AP's payload — full transcript, AP-side summary, `userSentiment`, `callSuccessful` — onto the `Call` row as `provider_summary` metadata, then enqueues the `post_call` job:

1. **`summarizer` mini-agent** produces the **canonical** structured summary with sections: what was discussed, what's blocking, what the customer said in their own words, action items. AP's `provider_summary` is included as a hint in the prompt but the summarizer has Workspace Brain context AP doesn't, so its output is the one the Manager sees.
2. **`brain_updater` mini-agent** extracts entities (people, companies, products, themes), upserts brain pages, appends timeline entries with citation back to the call, runs the typed-graph extractor.
3. **`action_item_extractor`** derives candidate action items, marks them `pending_approval`, surfaces to FE.
4. **Caller Memory write**: transcript + extracted facts pushed to Supermemory for the Field Rep.
5. Push notification to Front-End: *"Call from [Rep name] is ready to review."*

### 7.5 F5 — Brain Self-Update (Phase 1)

The compounding loop. Runs on the `post_call` path (immediate) and on the nightly `brain_maintenance` job (consolidation).

**Per-call updates:**
- New mentions of an account → timeline entry on the account page.
- Person mentioned 3+ times across calls → escalates from stub to enriched page (background `researcher` mini-agent fetches public info).
- Themes recurring across multiple Field Reps → new theme page, auto-linked.

**Nightly:**
- Stale pages flagged for review.
- Citations audited and repaired.
- Duplicate entities reconciled.
- Backlink graph rebuilt for ranking.
- `dashboard_rollup` mini-agent produces the daily brief.

### 7.6 F6 — Action Item Execution (Phase 2)

1. After a call, action items appear on the FE with `status=pending_approval`.
2. Manager reviews, optionally edits, approves.
3. Approval triggers the assigned `handler` (e.g., `scheduler`, `email_drafter`).
4. Mini-agent drafts the artifact (calendar invite, email body), shows preview, Manager confirms send.
5. On send, action item moves to `done`; outcome is written back to the brain timeline.

---

## 8. Modularity & Extension Points

The system has **seven extension points**, each with the same shape: an abstract base class, a registry, and a config-driven loader. Adding a new capability is one file (or one directory, for Skills).

### 8.0 Summary Table

| # | Extension point | How you extend it | Used for |
|---|---|---|---|
| 8.1 | **OrchestratorTool** | Subclass + register | Tools the Orchestrator can call mid-conversation (`request_manager_decision`, `web_research`, …) |
| 8.2 | **MiniAgent** | Subclass + register | Specialized agents invoked over HTTP or queue (`summarizer`, `brain_updater`, …) |
| 8.3 | **DataSourceConnector** | Subclass + register | Onboarding-time and ongoing sync from external sources (Salesforce, HubSpot, Notion, …) |
| 8.4 | **API Router** | Drop a module into `api/routers/...` | New FastAPI endpoint groups |
| 8.5 | **TelephonyProvider** | Subclass + bind in config | AgentPhone today; Twilio etc. tomorrow |
| 8.6 | **CallerMemoryProvider / BrainProvider** | Subclass + bind in config | Swap Supermemory or the Workspace Brain implementation |
| 8.7 | **Skill** (prompts + schemas) | Drop a directory into `skills/<name>/` with `SKILL.md`, `prompt.j2`, `schema.py`, fixtures, evals, CHANGELOG | Every LLM prompt in the system, versioned and evaluable |

The seventh — Skills — is the most distinctive: prompts are not strings in Python code, they are first-class artifacts on disk with their own SKILL.md, schema, eval fixtures, and version history. This follows GBrain's "skills are code" philosophy.

### 8.1 OrchestratorTool

```python
class OrchestratorTool(ABC):
    name: str                       # e.g., "request_manager_decision"
    description: str                # LLM-visible
    input_schema: type[BaseModel]   # Pydantic

    @abstractmethod
    async def run(self, ctx: CallContext, inputs: BaseModel) -> ToolResult: ...

class ToolRegistry:
    _tools: dict[str, OrchestratorTool] = {}

    @classmethod
    def register(cls, tool: OrchestratorTool) -> None: ...
    @classmethod
    def get(cls, name: str) -> OrchestratorTool: ...
    @classmethod
    def schema_for_llm(cls) -> list[dict]: ...   # function-calling schemas
```

Adding a new tool is one file. Tools can also be exposed as MCP tools via an MCP server adapter, so external MCP clients can hit them with proper auth.

### 8.2 MiniAgent

```python
class MiniAgent(ABC):
    name: str
    trigger: Literal["http", "queue", "cron"]

    @abstractmethod
    async def run(self, ctx: AgentContext, inputs: BaseModel) -> AgentResult: ...

class MiniAgentRegistry:
    _agents: dict[str, MiniAgent] = {}
    # register / get / list
```

Workers and the Orchestrator both resolve mini-agents by name via the registry. `trigger` determines how the mini-agent is invokable (HTTP endpoint, queue handler, cron job).

### 8.3 DataSourceConnector

```python
class DataSourceConnector(ABC):
    source_type: str                # "salesforce", "hubspot", "gdrive", ...

    @abstractmethod
    async def authenticate(self, workspace_id: UUID, credentials: dict) -> Auth: ...
    @abstractmethod
    async def initial_sync(self, workspace_id: UUID, auth: Auth) -> AsyncIterator[Document]: ...
    @abstractmethod
    async def incremental_sync(
        self, workspace_id: UUID, auth: Auth, since: datetime,
    ) -> AsyncIterator[Document]: ...

class ConnectorRegistry: ...        # same pattern
```

Each connector is independent. Adding "Notion" is adding one class + one config entry. The ingestion pipeline (Supermemory writes, brain seeding) is shared downstream.

### 8.4 API Router Auto-Discovery

`api/routers/__init__.py` walks the `workspaces/`, `organizations/`, and `rep/` subpackages, imports each module, and registers each module's `router` onto the FastAPI app. Adding a new endpoint group is dropping a file into the appropriate subpackage. Each router declares its scope dependencies (`require_workspace_access`, etc.) at module level.

### 8.5 TelephonyProvider

```python
class TelephonyProvider(ABC):
    @abstractmethod
    async def provision_number(self, country: str) -> PhoneNumber: ...
    @abstractmethod
    async def reply_voice(self, call_id: str, text: str) -> None: ...
    @abstractmethod
    async def send_sms(self, to: str, from_: str, body: str) -> None: ...
    @abstractmethod
    def parse_webhook(self, raw: dict) -> TelephonyEvent: ...
```

AgentPhone is the first implementation. Twilio can be added later behind the same interface.

### 8.6 Memory & Brain Providers

```python
class CallerMemoryProvider(ABC):
    async def add(self, user_id: str, content: str, metadata: dict) -> None: ...
    async def search(self, user_id: str, query: str, k: int) -> list[Memory]: ...
    async def get_profile(self, user_id: str) -> Profile: ...

class BrainProvider(ABC):
    async def put_page(self, workspace_id: UUID, page: BrainPage) -> None: ...
    async def get_page(self, workspace_id: UUID, slug: str) -> BrainPage | None: ...
    async def hybrid_search(
        self, workspace_id: UUID, query: str, k: int, types: list[str] | None,
    ) -> list[SearchHit]: ...
    async def graph_query(
        self, workspace_id: UUID, slug: str, edge_type: str | None, depth: int,
    ) -> list[GraphNode]: ...
```

Supermemory implements `CallerMemoryProvider`. Our internal Brain service implements `BrainProvider`. Both can be swapped (Mem0, Letta, a hosted Brain) without touching the Orchestrator.

### 8.7 Skills — Prompts as First-Class Artifacts

Every prompt in the system — the classifier, the Orchestrator's system prompt, the summarizer, the brain seeder, the action-item extractor — is a **directory on disk**, not a string buried in a Python module. This follows GBrain's "skills are code" philosophy: a prompt that drives non-trivial behavior deserves a directory, a version, an input/output schema, fixtures, and a changelog. Treating prompts as code is what makes them auditable, testable, and safe to iterate on.

**Directory layout:**

```
skills/
  classifier/
    SKILL.md                # human + LLM readable: purpose, triggers, quality bar
    prompt.j2               # the actual prompt template (Jinja2)
    schema.py               # Pydantic input + output schemas
    fixtures/               # representative inputs for offline checks
      org_wide_account.json
      caller_specific_style.json
      both_ownership.json
      ambiguous_low_confidence.json
    evals/
      golden_set.jsonl      # input → expected classification
      run.py                # eval harness
    CHANGELOG.md
  orchestrator/
    SKILL.md
    system_prompt.j2
    turn_prompt.j2
    schema.py
    fixtures/
    evals/
    CHANGELOG.md
  summarizer/  ...
  brain_seeder/  ...
  action_item_extractor/  ...
```

**Runtime contract.** Each skill exposes one callable. The body lives in `prompt.j2` and `schema.py`; the loader assembles them:

```python
class Skill(ABC):
    name: str
    version: str
    input_schema: type[BaseModel]
    output_schema: type[BaseModel]
    model: str                       # which LLM tier: haiku / sonnet / opus

    @abstractmethod
    async def run(self, inputs: BaseModel, ctx: SkillContext) -> BaseModel: ...

class SkillRegistry:
    _skills: dict[str, Skill] = {}
    # register / get / list_versions

class LLMSkill(Skill):
    """Default impl: renders prompt.j2 with inputs, calls LLM with JSON-mode
    pinned to output_schema, validates, retries on schema failure."""
    prompt_path: Path
```

**Worked example — the Classifier skill** (`skills/classifier/`):

`SKILL.md`:

```markdown
---
name: classifier
version: 0.3.0
model: claude-haiku
trigger: intake_buffer_item_added
quality_bar: ">= 0.85 precision on golden_set (current: 0.91)"
---

# Intake Classifier

Classifies a single IntakeBufferItem along two axes:

- **scope:** ORG_WIDE | CALLER_SPECIFIC | BOTH | RAW_SOURCE
- **kind:**  account | person | product | playbook | theme |
             caller_identity | caller_style | raw_document |
             org_positioning | off_topic

Returns confidence in [0, 1]. Items below threshold 0.7 route to NeedsReview.

## When to fire
On every IntakeBuffer write (onboarding) and on every Manager correction
(re-classification with elevated trust).

## Quality bar
- 0.91 precision on golden_set as of v0.3.0
- Never invent target_caller_id; only set if the input text explicitly
  names a Field Rep on the roster
- ambiguous_with_pii: redact before logging

## Chains with
- IntakeRouter (consumer of the output)
- brain_seeder (when kind=raw_document)
- NeedsReviewHandler (when confidence < 0.7)
```

`prompt.j2`:

```jinja2
You classify intake items for a multi-Workspace field-intelligence platform.

CONTEXT
- Workspace: {{ workspace.name }}
- Known Field Reps (roster):
{% for fe in roster %}  - {{ fe.id }} :: {{ fe.name }} ({{ fe.role }}){% endfor %}
- Known account slugs (top-50 by recency):
{% for acc in known_accounts %}  - {{ acc.slug }} :: {{ acc.title }}{% endfor %}

DEFINITIONS
- ORG_WIDE: true regardless of which Field Rep is involved
- CALLER_SPECIFIC: only relevant to one Field Rep
- BOTH: Workspace-truth AND caller-truth (e.g., ownership assignment)
- RAW_SOURCE: bulk document for semantic retrieval + entity extraction

ITEM TO CLASSIFY
Source: {{ item.source }}
Content:
"""
{{ item.content }}
"""

OUTPUT (strict JSON, conforming to ClassificationOutput schema):
{
  "scope": "ORG_WIDE" | "CALLER_SPECIFIC" | "BOTH" | "RAW_SOURCE",
  "kind": "...",
  "target_caller_id": <UUID or null>,
  "suggested_slug": <string or null>,
  "extracted_entities": [{"type": "...", "name": "..."}, ...],
  "confidence": <float 0..1>,
  "reasoning": "<one sentence>"
}

Rules:
- Only set target_caller_id when the input explicitly names a roster member.
- For BOTH, suggested_slug refers to the Workspace side (e.g., accounts/acme-corp).
- If confidence < 0.7, still produce a best-effort classification; the
  router will queue it for Manager review.
- Do NOT hallucinate entities not present in the text.
```

`schema.py`:

```python
class ClassificationInput(BaseModel):
    item: IntakeItem
    workspace: ManagerWorkspaceRef
    roster: list[FieldEmployeeRef]
    known_accounts: list[AccountRef]      # top-50 for fuzzy matching

class ExtractedEntity(BaseModel):
    type: Literal["person", "company", "product", "theme"]
    name: str

class ClassificationOutput(BaseModel):
    scope: Literal["ORG_WIDE", "CALLER_SPECIFIC", "BOTH", "RAW_SOURCE"]
    kind: Literal[
        "account", "person", "product", "playbook", "theme",
        "caller_identity", "caller_style", "raw_document",
        "org_positioning", "off_topic",
    ]
    target_caller_id: UUID | None = None
    suggested_slug: str | None = None
    extracted_entities: list[ExtractedEntity] = []
    confidence: float = Field(ge=0.0, le=1.0)
    reasoning: str
```

**Why this matters operationally:**

- **Versioning.** `skills/classifier/CHANGELOG.md` tracks every prompt change. The deployed version is pinned in config. Rolling back a bad prompt is a config flip, not a code deploy.
- **Evals are required.** `skills/classifier/evals/run.py` runs `golden_set.jsonl` against the current prompt. CI blocks merges that drop precision below the `quality_bar` in SKILL.md.
- **Workspace overrides.** A Workspace can override any skill with their own version (e.g., a custom Orchestrator system prompt with their brand voice). Stored in DB, layered on top of the base skill at runtime: `Skill.load("orchestrator", workspace_id=...)`.
- **Discoverability.** Every skill is documented the same way. New engineers read `SKILL.md`, not source code, to understand what a prompt does.
- **MCP exposure.** Skills can also be exposed as MCP tools, so external clients can invoke them with the same schema guarantees.

---

## 9. Correction & Provenance

A core product principle: **information can always be corrected**. The Manager is the source of truth for their own Workspace Brain; the system is never permitted to "lose" or "lock in" an extracted fact in a way that prevents revision. This applies during Stage 5 verification *and* at any later point in the product's life.

Three things must be true throughout the system: every write is **provenance-tagged**, every entity is **versioned**, and corrections **cascade** through dependent edges.

### 9.1 Provenance on Every Write

Every brain page, edge, and Caller Brain entry carries an immutable **provenance record** describing where it came from:

```python
class Provenance(BaseModel):
    source_type: Literal[
        "manager_form", "manager_upload", "manager_voice_intake",
        "manager_correction", "field_call", "automated_extraction",
        "external_research", "system_seed",
    ]
    source_id: UUID                    # the IntakeBufferItem / Call / etc.
    extracted_by: str | None           # which skill version: "classifier@0.3.0"
    extracted_at: datetime
    confidence: float | None           # from the original extraction
    cites: list[Citation] = []         # specific quotes/spans that support this
```

For Postgres-backed rows (`BrainPage`, `BrainEdge`, app DB rows), `provenance` is a column. For Supermemory entries, the same record is attached as metadata on the write.

Compiled-truth assertions on a page carry per-claim provenance, not just per-page, so the system knows *which specific sentence* came from where. (Phase 0 may ship per-page only; per-claim is a §12.2 open question.)

This makes the system answerable to:
- *"Why does the brain think Sarah owns Acme?"* → click the claim, see the CRM export row that produced it.
- *"What did the classifier think when it tagged this as ORG_WIDE?"* → see the version, the confidence, and the reasoning string.

### 9.2 Manager Corrections Always Win

When the Manager submits a correction (Stage 5 verification or any later edit surface), the correction is a **first-class intake item** with elevated trust:

```python
class CorrectionIntake(IntakeItem):
    source_type: Literal["manager_correction"] = "manager_correction"
    target_entity: EntityRef            # which page/edge/profile is being corrected
    correction_kind: Literal[
        "replace_compiled_truth",
        "delete_edge",
        "add_edge",
        "merge_entities",
        "split_entity",
        "set_profile_field",
        "soft_delete_page",
    ]
    payload: dict
    rationale: str | None
```

Corrections re-enter the classifier with `source_type=manager_correction`, which **elevates trust** (confidence floor 1.0, never queued for review, never gated by the auto-extraction quality bar). The Router dispatches to a `CorrectionHandler` instead of the normal typed handlers.

**Resolution rule** when a Manager correction contradicts an existing automated extraction:

1. The new value **replaces** the `compiled_truth` immediately.
2. The old value is **not deleted** — it's appended to the page's `timeline` as a corrected event:
   ```
   - 2025-04-15: [CORRECTED by manager] Previously: "owned by Sarah".
     Reason: "Bob took over this account in March." See correction:{id}.
   ```
3. The original extraction's provenance record is retained for audit.
4. Dependent edges and denormalizations cascade (§9.4).

Not "soft-delete and re-extract," not "merge," but **overwrite-with-audit-trail-and-cascade**. The current truth is always the most recent assertion; history is always preserved.

### 9.3 Versioning of Brain Pages

Brain pages are **append-only-versioned**:

```python
class BrainPageVersion(Base):           # in brain_w_{workspace_id} schema
    id: UUID
    page_slug: str
    version: int                        # monotonic per slug
    compiled_truth: str
    provenance: Provenance
    superseded_by: UUID | None          # next version, or null if current
    created_at: datetime
```

The "live" page is a view over the latest non-superseded version per slug. Older versions are queryable: *"show me what the brain said about Acme on 2025-03-01."*

Storage cost is bounded: timeline entries are append-only by design (they don't version), and compiled_truth versions are typically short paragraphs. For a Workspace with 10k pages averaging 5 corrections per year, that's 50k extra rows annually — negligible at Postgres scale.

### 9.4 Cascading Corrections

The hardest part of "always correct information" is making sure a correction propagates through everything that referenced the corrected entity. A `correction_cascade` worker (§5.7) triggers after every correction commit.

Example: Manager corrects "Sarah owns Acme" → "Bob owns Acme":

```
1. CorrectionHandler.apply():
   - Find edge: callers/sarah --[owns]--> accounts/acme-corp
   - Mark edge as superseded; create new edge callers/bob --[owns]--> accounts/acme-corp
   - Append timeline entry on accounts/acme-corp:
     "2025-04-15: Ownership corrected from Sarah to Bob (manager)"

2. correction_cascade worker:
   - Update Sarah's caller_profiles.owned_accounts: remove acme-corp
   - Update Bob's caller_profiles.owned_accounts: add acme-corp
   - Find timeline entries on accounts/acme-corp authored by Sarah's calls
     — DO NOT delete them (Sarah did discuss this account on those dates),
     but tag them: "context: ownership at time of call was Sarah; current owner is Bob"
   - Find Sarah's Caller Brain entries referencing acme-corp — retain
     (they're her history) but add an "ownership_changed" marker
   - Re-run embeddings for any page where text changed
   - Invalidate retrieval cache for queries that hit acme-corp,
     callers/sarah, or callers/bob
```

The cascade is intentionally **conservative about deletion**: nothing factual is removed, only the *current* truth is updated. A call from three months ago where Sarah discussed Acme is still in Sarah's history — that *happened*.

### 9.5 Correction Surfaces Beyond Stage 5

Stage 5 of onboarding is the *first* time the Manager corrects, not the last. Every page and edge in the Front-End has an "Edit" affordance that opens the same `CorrectionIntake` flow. Corrections can be submitted from:

- The Stage 5 verification view (onboarding).
- The brain explorer (any time, any page).
- The post-call review screen (correct things extracted from a specific call).
- The dashboard (correct trend rollups, edit themes).
- Voice mid-call: *"Hey, I want to correct something about the Acme account…"* — the Orchestrator has a `request_correction` tool that opens the same flow.

All paths produce the same `CorrectionIntake` shape and go through the same handler, so corrections from any surface behave identically.

### 9.6 What "Always Correctable" Doesn't Mean

- **It doesn't mean "silently rewriteable."** Call transcripts are append-only — we don't let anyone retroactively edit what a Field Rep said. We can correct *extracted assertions about that transcript*; the transcript itself is evidence.
- **It doesn't mean "no consistency."** The system rejects corrections that would create graph inconsistencies (e.g., an edge to a slug that doesn't exist), with a clear error to the Manager.
- **It doesn't mean "no audit."** Every correction logs *who* corrected *what* *when* and *why* (if a rationale was provided). In Phase 0 the "who" is always the Workspace's Manager; the schema records `corrected_by_user_id` so the audit trail keeps working unchanged when multi-Manager Organizations and Rep-level correction surfaces ship.
- **It doesn't mean the LLM gets to correct itself.** The automated extraction pipeline cannot retroactively overwrite Manager-corrected fields. Once a Manager has touched a field, it's marked `manager_authoritative=true` and the auto-extractor can only propose changes through the correction queue.

---

## 10. Tech Stack Summary

### 10.1 Stack Choices

| Layer | Choice | Notes |
|---|---|---|
| Telephony | AgentPhone | Voice + SMS unified; live STT included |
| Backend language | Python 3.12 | Async-first |
| API framework | FastAPI | Pydantic v2, async, WebSockets native |
| Worker | `arq` (Redis-backed) | Upgrade to Temporal if workflow durability becomes critical |
| LLM | Anthropic (Claude) | Haiku tier for classify/extract; Sonnet/Opus for Orchestrator; streaming via `client.messages.stream()` for the hot path |
| Caller memory | Supermemory | SDK mode, not Router |
| Workspace Brain | Custom Python service | Postgres + pgvector, schema-per-Workspace (`brain_w_{id}`) |
| App DB | Postgres 16 | Single cluster; rows carry `workspace_id` + `organization_id` |
| Cache / queue / pub-sub | Redis 7 | Single cluster, namespaced keys |
| Object storage | S3-compatible | Per-Workspace key prefixes |
| Auth | JWT (OAuth2 password / refresh) | Manager role at Phase 0; SSO later |
| Observability | OpenTelemetry → Honeycomb or Grafana | Trace every call end-to-end |
| Frontend | React + WebSocket (out of scope for this HLD) | API contract via OpenAPI generated by FastAPI |

### 10.2 Deployment Profiles — Local vs Cloud

Every infrastructure component is either **fully portable between local and cloud** or **inherently cloud-only**. The system supports two profiles, switched by environment variables alone — no code changes:

| Component | Local option | Cloud option | Switching mechanism |
|---|---|---|---|
| App DB (Postgres 16) | Container (Docker/Podman) with persistent volume | Managed (AWS RDS, Supabase, Neon, Render Postgres) | `DATABASE_URL` env var |
| Workspace Brain DB (Postgres 16 + pgvector) | Container with `pgvector` extension preloaded | Managed Postgres with pgvector enabled (Supabase, Neon, RDS) | `BRAIN_DATABASE_URL` env var (separate from App DB for ops clarity) |
| Redis 7 | Container | Managed (Upstash, ElastiCache, Redis Cloud) | `REDIS_URL` env var |
| Object storage | **MinIO** container (S3-compatible) | AWS S3 / Cloudflare R2 | `S3_ENDPOINT_URL`, `S3_BUCKET`, `S3_ACCESS_KEY`, `S3_SECRET_KEY` |
| Skill files | Local filesystem (`./skills/`) | Same — they're code, version-controlled | (always local-to-deployment) |
| **Supermemory** | **Cloud only** | Managed SaaS | (no local switch) |
| **AgentPhone** | **Cloud only** (telephony needs carrier relationships) | Managed SaaS | (no local switch) |
| **Anthropic** | **Cloud only** (closed model) | API | (no local switch) |

**The three cloud-only items** are inherent to the product:

- **Supermemory** has an open-source repo but the production product is the managed service. Self-hosting is theoretically possible but not pragmatic for Phase 0 — running a Cloudflare-Workers + Durable-Objects + vector-search stack in-house is its own project. Treat Supermemory as a hard cloud dependency.
- **AgentPhone** can't be self-hosted because telephony requires carrier relationships, number provisioning agreements, and PSTN connectivity. No local substitute exists.
- **Anthropic** is a hosted LLM. (If you ever need a fully-local stack, swap the LLM provider abstraction in §8.6 for an Ollama or vLLM backend — but model quality drops dramatically, and the Orchestrator's behavior will need re-tuning. Not Phase 0 work.)

**Profile configuration:**

```bash
# .env.local (dev)
DEPLOYMENT_PROFILE=local
DATABASE_URL=postgresql://votf:votf@localhost:5432/votf_app
BRAIN_DATABASE_URL=postgresql://votf:votf@localhost:5432/votf_brain
REDIS_URL=redis://localhost:6379/0
S3_ENDPOINT_URL=http://localhost:9000     # MinIO
S3_BUCKET=votf-local
S3_ACCESS_KEY=minioadmin
S3_SECRET_KEY=minioadmin
# These remain cloud regardless of profile:
SUPERMEMORY_API_KEY=sm_...
AGENTPHONE_API_KEY=...
AGENTPHONE_WEBHOOK_SECRET=...
ANTHROPIC_API_KEY=sk-ant-...
```

```bash
# .env.production
DEPLOYMENT_PROFILE=cloud
DATABASE_URL=postgresql://...@<rds-host>:5432/votf_app
BRAIN_DATABASE_URL=postgresql://...@<rds-host>:5432/votf_brain
REDIS_URL=rediss://...@<upstash>:6379
S3_ENDPOINT_URL=                          # empty → boto3 uses real S3
S3_BUCKET=votf-prod
S3_ACCESS_KEY=AKIA...
S3_SECRET_KEY=...
# Same cloud services as local:
SUPERMEMORY_API_KEY=sm_...
AGENTPHONE_API_KEY=...
AGENTPHONE_WEBHOOK_SECRET=...
ANTHROPIC_API_KEY=sk-ant-...
```

A single `docker-compose.local.yml` brings up Postgres + Redis + MinIO with one command for dev work; production switches `DATABASE_URL` / `REDIS_URL` / S3 settings without code changes.

**Local-only caveat for AgentPhone webhooks during dev.** Because AgentPhone can't reach `localhost`, local development uses an `ngrok` (or `cloudflared`) tunnel pointing at the local FastAPI server. The tunnel's HTTPS URL is registered as the AgentPhone webhook URL for the dev tenant. Production uses the real deployment URL. This is the one local-dev gotcha worth flagging.

**Why this matters operationally.** The Manager-Workspace isolation story (schema-per-Workspace, per-Workspace S3 prefixes, namespaced Redis keys, scoped Supermemory user IDs) works identically against local containers and against cloud managed services. Engineers can run a full Workspace end-to-end on a laptop. Production deploys exercise the exact same code paths.

---

## 11. Third-Party Integration Contracts

This section pins down the real-world API and MCP contracts for every external service VotF depends on, where the API surface and the MCP surface diverge, which one we use and why, and what the Operator (you) needs to do to enable each one before launch.

### 11.1 Approach, and the "Agent" Naming Collision

Two cross-cutting principles for every third-party integration:

1. **Backend uses REST/SDK; MCP is for external consumers only.** Where a third-party offers both an HTTP/SDK surface and an MCP server, our Python backend always uses the REST/SDK. The MCP server is for third-party consumers like Claude Desktop, Cursor, or another agent invoking the third-party's tools — not for our server-to-server traffic. MCP adds a hop, surrenders control of batching/metadata/retry, and is shaped for agent clients, not backend services. We may *expose our own skills* as MCP for external consumers (§8.7) but we do not *call* third-party MCP servers from inside VotF.

2. **"Agent" disambiguation.** AgentPhone calls its AI personas *Agents* (the entity that owns a phone number, has a voice, can be in "webhook mode" or "hosted mode"). VotF also has Agents (the Orchestrator, mini-agents). To avoid confusion:

   - **AgentPhone Agent** (sometimes "AP Agent" in code comments): AP's persona concept. One AP Agent per Manager Workspace; the AP Number is attached to that AP Agent.
   - **Orchestrator** / **Mini Agent**: VotF's agents (unchanged terminology).

   In our code, AP's concept is wrapped behind `TelephonyProvider.AgentPhoneAdapter`; the term "AP Agent" never leaks out of the adapter into the rest of the codebase.

### 11.2 AgentPhone

#### 11.2.1 Capabilities we use

| Capability | Used for | Phase |
|---|---|---|
| Provision US/Canada phone numbers | One number per Workspace | 0 |
| Inbound voice with real-time transcription | The Orchestrator turn loop | 0 |
| Inbound SMS | Manager decision responses; Rep text reports | 0 |
| Outbound SMS | Action item alerts, decision pings to the Manager's mobile | 0 |
| Outbound voice | (Not used in Phase 0; available in Phase 2+ for automated callbacks) | — |
| Voice TTS response per turn | Speaking the Orchestrator's reply | 0 |
| Per-conversation metadata (`conversationState`) | Carrying `workspace_id`/`call_id` to skip per-webhook DB lookups | 0 |
| AP-side post-call summary | Recorded as `Call.provider_summary`; signal-only, our `summarizer` produces the canonical one | 1 |

#### 11.2.2 REST API (we consume from server)

- **Base URL:** `https://api.agentphone.ai/v1`
- **Auth:** `Authorization: Bearer YOUR_API_KEY` header
- **Python SDK:** `pip install agentphone` → `from agentphone import AgentPhone; client = AgentPhone(api_key=...)`

Key endpoints we use (subset of full API):

| Operation | Endpoint | Used by |
|---|---|---|
| Create AP Agent (persona) | `POST /v1/agents` | Workspace provisioning at signup |
| Provision a number | `POST /v1/numbers` | Workspace provisioning at signup |
| Attach number to AP Agent | `POST /v1/agents/{agent_id}/numbers` | Workspace provisioning at signup |
| Configure master webhook | `POST /v1/webhooks` (returns signing secret) | One-time deployment setup |
| Set conversation metadata | `PATCH /v1/conversations/{id}` | Telephony adapter, on first turn of each call |
| Send outbound SMS | `POST /v1/conversations/{id}/messages` (SDK: `client.conversations.send_message`) | `outbound_sms` mini-agent |
| Get call detail | `GET /v1/calls/{id}` | Diagnostics |
| Get conversation history | `GET /v1/conversations/{id}` | Diagnostics |
| Test webhook | `POST /v1/webhooks/test` | Operator setup verification |

We choose **webhook mode** (our backend owns conversation logic) over **hosted mode** (AP's built-in LLM). Hosted mode would give up the Workspace Brain integration that's the whole point.

#### 11.2.3 Webhook Contract (AgentPhone calls us)

Events delivered to our configured webhook URL:

| Event | Channel | Triggers |
|---|---|---|
| `agent.message` | `sms` / `mms` / `imessage` | Inbound text message received |
| `agent.message` | `voice` | Real-time voice transcript ready during an active call |
| `agent.call_ended` | `voice` | Call completed; payload includes full transcript + AP-side summary |
| `agent.reaction` | `imessage` | iMessage tapback (not used in Phase 0) |

**Webhook payload structure** (unified envelope; `data` shape varies by channel):

```json
{
  "event": "agent.message",
  "channel": "voice",
  "timestamp": "2025-01-15T14:00:05Z",
  "agentId": "agt_abc123",
  "data": {
    "callId": "call_abc123",
    "numberId": "num_xyz789",
    "from": "+15559876543",
    "to": "+15551234567",
    "status": "in-progress",
    "transcript": "I need help with my order",
    "confidence": 0.95,
    "direction": "inbound"
  },
  "conversationState": {
    "workspace_id": "ws_...",
    "call_id": "call_...",
    "field_employee_id": "fe_..."
  },
  "recentHistory": [...]
}
```

**Security on every webhook delivery:**

| Header | Purpose |
|---|---|
| `X-Webhook-Signature` | `sha256=<hex>`. HMAC-SHA256 over `{timestamp}.{raw_body}` with the per-webhook secret |
| `X-Webhook-Timestamp` | Unix timestamp; we reject deliveries older than 5 minutes |
| `X-Webhook-ID` | Unique delivery ID; we deduplicate on this for idempotency |
| `X-Webhook-Event` | Event type for fast filtering before parse |

Adapter pseudocode:

```python
async def handle_agentphone_webhook(request):
    raw_body = await request.body()
    sig = request.headers["X-Webhook-Signature"]
    ts = request.headers["X-Webhook-Timestamp"]
    wid = request.headers["X-Webhook-ID"]

    if not verify_hmac(raw_body, sig, ts, secret=AP_WEBHOOK_SECRET):
        return 401
    if abs(time.time() - int(ts)) > 300:
        return 400  # replay window exceeded
    if await redis.sismember("seen_webhooks", wid):
        return 200  # already processed, idempotent
    await redis.sadd("seen_webhooks", wid)  # TTL ~7 days

    payload = json.loads(raw_body)
    scope = payload.get("conversationState") or {}
    workspace_id = scope.get("workspace_id") or resolve_by_number(payload["data"]["to"])
    # ... dispatch by event/channel
```

**Voice turn response format.** When we receive an `agent.message:voice`, the HTTP response *is* the agent's reply. NDJSON streaming is strongly recommended:

```
{"text": "Let me check on that for you.", "interim": true}
{"text": "Here's what I see — the deal is in stage 3 and was last touched Tuesday."}
```

- Interim chunks start TTS immediately; final chunk (no `interim: true`) closes the turn.
- Default 30s timeout, configurable 5–120s per webhook.
- **Always stream an interim chunk before slow work** (LLM call, brain retrieval) or the caller hears silence.
- Other response fields: `hangup: true` ends the call; `action: "transfer"` cold-transfers; `digits: "1*#"` for IVR navigation.

**Retry behavior.** 6 attempts over ~21 hours with exponential backoff (5min → 30min → 2h → 6h → 12h). We **must** return 200 quickly and process async if needed.

#### 11.2.4 MCP Contract (and why we don't use it)

AgentPhone publishes an MCP server as the npm package `agentphone-mcp`:

```json
{ "mcpServers": { "agentphone": { "command": "npx", "args": ["agentphone-mcp"] } } }
```

Designed so MCP clients (Claude Desktop, Cursor, Windsurf, OpenClaw) can provision numbers, send messages, and manage calls via native tool use during a chat. The tools it exposes mirror the REST API.

**We don't use this from VotF's backend.** Our adapter calls the REST API/SDK directly. If we ever expose VotF-side tooling for an external agent to consume (e.g., a Claude Desktop plugin that lets a power-user query their own Workspace Brain), we'd write that as our own MCP server (§8.7) — not by wrapping AgentPhone's.

#### 11.2.5 Contract Agreement: API ↔ Webhook ↔ MCP

| Operation | REST/SDK | Webhook delivers | MCP tool |
|---|---|---|---|
| Provision number | `POST /v1/numbers` | — | yes |
| Create AP Agent persona | `POST /v1/agents` | — | yes |
| Attach number to AP Agent | `POST /v1/agents/{id}/numbers` | — | yes |
| Inbound SMS received | — | `agent.message` channel=sms | — |
| Voice turn transcript ready | — | `agent.message` channel=voice | — |
| Reply to voice turn | (synchronous webhook response, NDJSON) | — | — |
| Send outbound SMS | `POST /v1/conversations/{id}/messages` | — | yes |
| Call ended (full transcript + summary) | — | `agent.call_ended` | — |
| Per-conversation metadata | `PATCH /v1/conversations/{id}` | echoed on every webhook as `conversationState` | — |

The three surfaces are **complementary, not overlapping**: REST/SDK is push-to-AP, webhooks are AP-to-us, and MCP is a wrapper-for-other-agents. The contracts agree (same operations, same data shapes); MCP just exposes a subset via tool-call style.

#### 11.2.6 Mapping to our internal types

```python
class AgentPhoneAdapter(TelephonyProvider):
    """One adapter instance per VotF deployment, shared across all Workspaces."""

    def __init__(self, api_key: str, webhook_secret: str):
        self.client = AgentPhone(api_key=api_key)
        self.webhook_secret = webhook_secret

    async def provision_workspace(self, workspace: ManagerWorkspace) -> str:
        ap_agent = await self.client.agents.create(
            name=f"VotF / {workspace.name}",
            voice_mode="webhook",   # we own orchestration
        )
        number = await self.client.numbers.buy(agent_id=ap_agent.id)
        # store ap_agent.id and number.id on the Workspace row
        return number.phone_number

    async def reply_voice(self, call_id: str, chunks: AsyncIterator[VoiceChunk]) -> StreamingResponse:
        # NDJSON streaming response back to AP's webhook call
        ...

    async def send_sms(self, conversation_id: str, body: str) -> None:
        await self.client.conversations.send_message(
            conversation_id=conversation_id, content=body,
        )

    async def set_conversation_state(self, conversation_id: str, state: dict) -> None:
        await self.client.conversations.update(
            conversation_id=conversation_id, metadata=state,
        )

    def parse_webhook(self, raw: bytes, headers: dict) -> TelephonyEvent:
        # HMAC verify, replay-window check, dedupe by X-Webhook-ID,
        # then translate event+channel into one of:
        #   InboundVoiceTurn | InboundSMS | CallEnded | ReactionReceived
        ...
```

Our `Call.agentphone_call_id` ← AP's `data.callId`. Our `TranscriptFragment` rows ← voice `agent.message` events. Our `Call.provider_summary` ← `agent.call_ended.data.summary`. `conversationState` carries our `{workspace_id, call_id, field_employee_id}` so per-webhook scope resolution is metadata-driven rather than DB-lookup-driven.

#### 11.2.7 Operator Setup Checklist (AgentPhone)

To enable AgentPhone in a VotF deployment:

1. **Create an AgentPhone account** at https://agentphone.ai.
2. **Fund the account** (pay-as-you-go: ~$1–2/month per number; voice minutes + SMS billed per use).
3. **Generate an API key** from the AP dashboard.
4. **Store the API key** in the VotF deployment's secret manager as `AGENTPHONE_API_KEY`. Never commit to source.
5. **Configure the master webhook**: `POST https://api.agentphone.ai/v1/webhooks` with `url=https://<your-votf-deployment>/integrations/agentphone/webhook`, `contextLimit=10`, `timeout=30`. **Save the returned `secret`** as `AGENTPHONE_WEBHOOK_SECRET`.
6. **Verify the webhook**: `POST /v1/webhooks/test` — confirm our endpoint receives the test payload and HMAC verification passes.
7. **Smoke-test one Workspace end-to-end**: complete onboarding for a test Manager, confirm a number is provisioned, call the number from a phone, confirm the webhook fires, confirm the Orchestrator replies via NDJSON, hang up, confirm `agent.call_ended` is received.
8. **Production readiness checks**: HMAC verification active on all webhook handlers; idempotency via `X-Webhook-ID` enforced (Redis set with ≥24h TTL); the 5-minute replay window check is active; voice handler streams an interim chunk before any retrieval/LLM work.
9. **Operational monitoring**: dashboard the `agent.message:voice` round-trip latency (target P50 <1.5s, P95 <2.5s); track webhook deliveries via `GET /v1/webhooks/deliveries` for failed-delivery alerts.

### 11.3 Supermemory

#### 11.3.1 Capabilities we use

| Capability | Used for | Phase |
|---|---|---|
| Per-user persistent memory (write) | Caller Memory writes after every call; ingested-source writes during onboarding | 0 |
| Semantic search over user-scoped memories | Orchestrator retrieval at call start and per-turn | 0 |
| Automatic profile extraction | Caller profile inference over time | 1 |
| File upload + auto-chunking | Onboarding raw-source ingestion (PDFs, CSV, docs) | 0 |
| Memory deletion | Right-to-deletion compliance workflows | 1 |

#### 11.3.2 REST API + Python SDK

- **Base URL:** `https://v2.api.supermemory.ai`
- **Auth:** `x-api-key: YOUR_API_KEY` header (note: **not** Bearer, unlike AgentPhone)
- **Python SDK:** `pip install supermemory` → `from supermemory import Supermemory, AsyncSupermemory`
- **Default env var:** `SUPERMEMORY_API_KEY` is read automatically by the SDK

Key SDK methods we use:

| Operation | SDK call | Underlying REST |
|---|---|---|
| Add a memory | `client.add(content=..., user_id=..., metadata=...)` | `POST /add` |
| Search memories | `client.search.execute(q=..., user_id=..., limit=k)` | `POST /search` |
| Upload a file | `client.documents.upload_file(file=..., user_id=..., metadata=...)` | `POST /documents` |
| Get user profile | `client.profile.get(user_id=...)` | `GET /profile` |
| Delete a memory | `client.delete(id=...)` | `DELETE /memories/{id}` |

All operations are user-scoped by `user_id`. We use:
- `workspace:{workspace_id}:caller:{field_employee_id}` for Caller Memory.
- `workspace:{workspace_id}:source:{source_type}:{document_id}` for ingested raw sources.

#### 11.3.3 MCP Contract

Hosted MCP server at `https://mcp.supermemory.ai` (Cloudflare Worker). Two auth paths: API key validation (tokens prefixed `sm_` hit `/v3/session`) or OAuth.

Tool surface exposed via MCP:

| MCP tool | Behavior |
|---|---|
| `addMemory` / `save` | Write a memory for the authenticated user (with optional `forget` action variant) |
| `search` / `recall` | Semantic search; `recall` optionally includes a user profile via `includeProfile=true` |
| `forget` | Soft-delete a memory |
| `getProjects` | List the user's memory "containers" / projects |
| `whoAmI` | Identity check |

#### 11.3.4 Contract Agreement: SDK ↔ MCP

The functional operations agree but the **naming diverges**:

| Operation | SDK name | MCP tool name |
|---|---|---|
| Write a memory | `client.add(...)` | `addMemory` / `save` |
| Search | `client.search.execute(q=...)` | `search` / `recall` |
| Search + profile bundle | `client.profile.get(...)` + `client.search.execute(...)` | `recall(includeProfile=true)` (single bundled call) |
| Delete | `client.delete(id=...)` | `forget` |
| File upload | `client.documents.upload_file(...)` | (limited via MCP) |

**Two real differences worth flagging:**

1. **The MCP `recall(includeProfile=true)` is a bundled "search + profile" call** that has no single-SDK equivalent — you'd call both endpoints. For our backend we call them separately (we want control over caching the profile).
2. **MCP's `forget` accepts a content-shaped argument**, while the SDK's `delete` takes an explicit memory ID. We use the ID-based path.

We standardize on the SDK for backend traffic. If we ever build a VotF Claude Desktop integration, the MCP server is available for end-users to point Claude at their VotF-managed memory directly — but that's out of scope for Phase 0.

#### 11.3.5 Mapping to our internal types

```python
class SupermemoryCallerMemoryProvider(CallerMemoryProvider):
    def __init__(self, api_key: str):
        self.client = AsyncSupermemory(api_key=api_key)

    async def add(self, user_id: str, content: str, metadata: dict) -> None:
        await self.client.add(content=content, user_id=user_id, metadata=metadata)

    async def search(self, user_id: str, query: str, k: int) -> list[Memory]:
        result = await self.client.search.execute(q=query, user_id=user_id, limit=k)
        return [Memory(id=r.id, content=r.content, score=r.score, metadata=r.metadata)
                for r in result.results]

    async def get_profile(self, user_id: str) -> Profile:
        return await self.client.profile.get(user_id=user_id)
```

This is the `CallerMemoryProvider` implementation backing §8.6. Swapping to Mem0 / Letta later is implementing the same interface against a different SDK.

#### 11.3.6 Operator Setup Checklist (Supermemory)

1. **Create a Supermemory account** at https://supermemory.ai.
2. **Generate an API key** from the developer platform.
3. **Choose pricing tier** appropriate to expected volume. Estimate at launch: per Workspace, expect ~5–50 writes/call (transcript chunks + extracted facts) and ~10–30 queries/call (retrieval per turn). For 100 calls/month/Workspace, that's ~500–5,000 writes and ~1,000–3,000 queries per Workspace per month.
4. **Store the API key** in the VotF deployment's secret manager as `SUPERMEMORY_API_KEY`. The Python SDK reads this env var automatically.
5. **Verify connectivity** from a deployment shell:
   ```bash
   python -c "from supermemory import Supermemory; \
              print(Supermemory().search.execute(q='ping').results)"
   ```
   Expect an empty result set or a sample — not an auth error.
6. **Decide retention defaults** (ties to §13.2 PII / compliance open question). Defaults like "transcripts retained 3 years; raw sources retained until Workspace deletes them" need to be reflected in `workspace.config.retention_*`.
7. **Confirm deletion path** works end-to-end: write a test memory, delete it via `client.delete(id=...)`, confirm subsequent search doesn't return it. Required before going live for compliance.

### 11.4 Anthropic (LLM Provider)

- **Base URL:** `https://api.anthropic.com/v1`
- **Auth:** `x-api-key: YOUR_KEY` header + `anthropic-version: 2023-06-01`
- **Python SDK:** `pip install anthropic` → `from anthropic import AsyncAnthropic`
- **Models we use** (pinned per skill in `skills/<name>/SKILL.md`):
  - `claude-haiku-*` for the classifier, action-item extractor, entity extraction passes — cheap, fast, structured-output-good
  - `claude-sonnet-*` for the Orchestrator's turn loop — better reasoning, still fast enough for the 1.5–2.5s budget
  - `claude-opus-*` for nightly synthesis (dashboard rollups, dream cycle) — quality matters, latency doesn't

**Operator setup:**

1. Create an Anthropic Console account at https://console.anthropic.com.
2. Generate an API key.
3. Store as `ANTHROPIC_API_KEY` in the secret manager.
4. Set per-tier rate limits matching expected call volume (Orchestrator calls = concurrent live calls × turns per call; classifier calls scale with onboarding upload volume).
5. Set per-tier spend caps as a budget guardrail.
6. Pin model strings in each `skills/<name>/SKILL.md` so model upgrades go through the skill versioning + eval CI gate, not via silent env var changes.

### 11.5 Object Storage (S3-Compatible)

- **Choice:** AWS S3 or Cloudflare R2 (R2 has no egress fees, attractive for FE signed-URL delivery)
- **SDK:** boto3 against the S3 API
- **Key layout:** `s3://votf-{env}/workspaces/{workspace_id}/calls/{call_id}/{kind}/...`
  where `kind ∈ {recording, transcript, source_uploads}`
- **Access pattern:** signed URLs with 15-minute TTL for FE consumption; backend writes use IAM credentials

**Operator setup:**

1. Provision a bucket per environment (dev / staging / prod).
2. Create an IAM principal scoped to `PutObject`, `GetObject`, `DeleteObject` on that bucket only.
3. Store credentials as `S3_ACCESS_KEY`, `S3_SECRET_KEY`, `S3_BUCKET`, `S3_REGION`, `S3_ENDPOINT_URL` (the last needed for R2 / MinIO).
4. CORS: allow `GET` from the FE origin for signed-URL fetches.
5. Lifecycle rules per the retention defaults (§13.2): recordings auto-expire at the configured retention horizon.

### 11.6 Future Connectors (Phase 1+)

The §8.3 `DataSourceConnector` extension point absorbs all future third-party data sources without HLD changes. Anticipated Phase 1+ connectors:

| Connector | Auth | Used for |
|---|---|---|
| Salesforce | OAuth 2.0 | CRM data ingestion + write-back |
| HubSpot | OAuth 2.0 | CRM alternative |
| Google Workspace (Gmail, Calendar, Drive) | OAuth 2.0 | Email/calendar context, document ingestion |
| Microsoft 365 | OAuth 2.0 | Same for the Microsoft ecosystem |
| Notion | OAuth 2.0 / integration token | Knowledge base ingestion |
| Slack | OAuth 2.0 | Manager notifications + decision pings (alt channel) |

Each follows the same shape: an `OAuth dance` initiated from the FE during onboarding stores per-Workspace credentials encrypted at rest, the connector implements `initial_sync` + `incremental_sync` via `DataSourceConnector`, ingested documents flow through the same Stage 3 classifier as manual uploads.

Operator setup is per-connector but always involves: register an OAuth app with the provider, store the client ID + secret, configure the redirect URI to point at the VotF FE.

---

## 12. Verification & Smoke Tests for Third-Party Integrations

Every third-party integration in §11 is also a *failure surface* — credentials expire, APIs drift, rate limits change, webhook URLs go stale. The system must be **independently verifiable per integration**: a single command tells you whether AgentPhone, Supermemory, the LLM provider, Postgres, Redis, and object storage are each correctly configured and reachable, *without* spinning up the whole VotF stack.

This section specifies a standardized framework for independent smoke-test scripts: one per integration, runnable solo from the command line, runnable together in CI, and structured so adding a new integration is one new file following the same shape.

### 12.1 Design Principles

1. **Independent.** Each script runs alone with no shared fixtures and no test-framework lock-in. `python -m smoke.agentphone` works on a freshly-cloned repo with just `.env` configured. A new engineer can debug one integration in isolation without understanding the rest of the system.

2. **Real services, not mocks.** Smoke tests hit the actual third-party APIs. Their purpose is to verify that *our credentials and contracts* work against the live service, not to test our own code in isolation (that's what unit tests are for).

3. **No production data touched.** Each script creates ephemeral resources under a `smoketest:*` scope (test workspace, test memory user_id, test object-storage prefix) and cleans up on exit. Where ephemeral creation isn't free (AgentPhone phone numbers cost money), the script reads a pre-provisioned test resource from config.

4. **Three operating modes**, selected by CLI flag:

    | Mode | Flag | What runs | Latency | Use case |
    |---|---|---|---|---|
    | Check | `--check` (default) | Auth + connectivity only | <2s | Deploy gate, CI pre-flight |
    | Smoke | `--smoke` | Every feature VotF actually uses | <30s | Pre-release, post-incident |
    | Repair | `--repair` | Smoke + diagnostic output for failures | <30s | Operator troubleshooting |

5. **Exit codes carry semantics:**

    | Code | Meaning |
    |---|---|
    | `0` | Pass |
    | `1` | Functional failure (the integration is broken on our end — wrong key, wrong config, contract mismatch) |
    | `2` | Configuration error (env vars missing or malformed; no test possible) |
    | `3` | Upstream unavailable (service is down — not our problem, but block deploys anyway) |

6. **Dual output:** JSON to stdout (machine-readable for CI), pretty text to stderr (human-readable). One report shape across all probes so an aggregating runner can consume any of them uniformly.

7. **Secrets are redacted** in all output. API keys are never printed; on failure the relevant key name is identified but never its value.

8. **OpenAI-API-compatible LLM probe.** The LLM smoke test is written against the **OpenAI chat-completions API shape**, not Anthropic's native SDK. Every major provider (Anthropic via `/v1/openai/chat/completions`, OpenAI itself, OpenAI-compat servers like vLLM/Ollama/Together/Groq/Gemini-compat) accepts this shape. Changing providers is a config flip in the smoke-test env — same model-agnosticism story as the production LLM client abstraction.

### 12.2 The `Probe` Base Class

Every smoke script is a thin runner over a `Probe` base. The base handles config loading, timing, output formatting, exit codes, and secrets redaction. The per-integration subclass declares the checks.

```python
# smoke/_base.py
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import IntEnum
import json, sys, time, os

class ExitCode(IntEnum):
    PASS = 0
    FAIL = 1
    CONFIG = 2
    UPSTREAM = 3

@dataclass
class CheckResult:
    name: str
    passed: bool
    latency_ms: float
    detail: str = ""
    fix_hint: str = ""

@dataclass
class ProbeReport:
    probe: str                       # "agentphone", "supermemory", "llm", ...
    mode: str                        # "check" | "smoke" | "repair"
    overall: str                     # "pass" | "fail" | "config_error" | "upstream_down"
    checks: list[CheckResult] = field(default_factory=list)
    started_at: str = ""
    duration_ms: float = 0

class Probe(ABC):
    name: str                        # "agentphone", "supermemory", ...
    required_env: list[str]          # env vars that MUST be set

    def __init__(self, mode: str = "check"):
        self.mode = mode
        self.report = ProbeReport(probe=self.name, mode=mode)

    def run(self) -> ExitCode:
        # 1. Verify required env vars present
        missing = [v for v in self.required_env if not os.environ.get(v)]
        if missing:
            self._emit_config_error(missing)
            return ExitCode.CONFIG

        # 2. Run probe-specific checks
        t0 = time.time()
        try:
            self.checks_for_mode()
        except UpstreamUnavailable as e:
            self._emit_upstream(e)
            return ExitCode.UPSTREAM
        finally:
            self.report.duration_ms = (time.time() - t0) * 1000

        # 3. Emit report (JSON to stdout, pretty to stderr)
        self._emit_report()
        return ExitCode.PASS if all(c.passed for c in self.report.checks) else ExitCode.FAIL

    @abstractmethod
    def checks_for_mode(self) -> None:
        """Run the right set of checks for self.mode."""
        ...

    def check(self, name: str, fn, fix_hint: str = "") -> bool:
        """Helper to run one named check, time it, capture failures."""
        t0 = time.time()
        try:
            detail = fn() or ""
            self.report.checks.append(CheckResult(name, True, (time.time()-t0)*1000, detail))
            return True
        except Exception as e:
            self.report.checks.append(CheckResult(
                name, False, (time.time()-t0)*1000, str(e), fix_hint
            ))
            if self.mode != "repair":
                raise   # fail-fast unless in repair mode
            return False

    # ... _emit_* helpers, redaction, etc.

class UpstreamUnavailable(Exception):
    """Raised when the third-party service is itself down (HTTP 5xx, timeout)."""
```

### 12.3 Smoke-Test Directory Layout

```
smoke/
  __init__.py
  _base.py                   # Probe, CheckResult, ProbeReport
  _runner.py                 # `python -m smoke run --all` aggregator
  agentphone.py              # AgentPhoneProbe(Probe)
  supermemory.py             # SupermemoryProbe(Probe)
  llm.py                     # LLMProbe(Probe)  (OpenAI-compat)
  postgres_app.py            # AppPostgresProbe(Probe)
  postgres_brain.py          # BrainPostgresProbe(Probe)  (includes pgvector check)
  redis.py                   # RedisProbe(Probe)
  object_storage.py          # ObjectStorageProbe(Probe)
  fixtures/
    sample_audio.wav         # tiny fixture for AP outbound test
    sample_doc.pdf           # tiny fixture for Supermemory upload
  manifests/
    probes.yaml              # canonical list, used by the runner
```

Each probe file is executable two ways:
- **Solo:** `python -m smoke.agentphone --smoke` → exits with code 0/1/2/3, JSON to stdout
- **Aggregated:** `python -m smoke run --all --mode smoke` → fan out, collect, emit summary

### 12.4 Worked Example — AgentPhone Probe

```python
# smoke/agentphone.py
import os, hmac, hashlib, time, httpx
from ._base import Probe, UpstreamUnavailable

class AgentPhoneProbe(Probe):
    name = "agentphone"
    required_env = ["AGENTPHONE_API_KEY", "AGENTPHONE_WEBHOOK_SECRET",
                    "SMOKE_AGENTPHONE_TEST_AGENT_ID", "SMOKE_AGENTPHONE_TEST_NUMBER_ID"]

    BASE = "https://api.agentphone.ai/v1"

    def checks_for_mode(self):
        if self.mode in ("check", "smoke", "repair"):
            self.check("auth_valid", self._auth_valid,
                       fix_hint="Verify AGENTPHONE_API_KEY in secret manager; rotate if needed.")
            self.check("webhook_configured", self._webhook_configured,
                       fix_hint="Run POST /v1/webhooks with your deployment's webhook URL.")

        if self.mode in ("smoke", "repair"):
            self.check("hmac_verification", self._hmac_verification_roundtrip,
                       fix_hint="AGENTPHONE_WEBHOOK_SECRET may be stale; regenerate by POSTing /v1/webhooks again.")
            self.check("test_webhook_delivery", self._test_webhook_endpoint,
                       fix_hint="Confirm your webhook endpoint is reachable from public internet (ngrok in dev).")
            self.check("conversation_state_roundtrip", self._conversation_state_roundtrip,
                       fix_hint="Check that PATCH /v1/conversations/{id} accepts the metadata shape.")
            self.check("ndjson_response_accepted", self._ndjson_response_shape,
                       fix_hint="Confirm voice webhook returns Content-Type: application/x-ndjson.")
            self.check("outbound_sms_capability", self._can_send_sms,
                       fix_hint="Ensure test number has SMS capability and account has balance.")

    # --- individual check methods ---

    def _auth_valid(self) -> str:
        with httpx.Client(timeout=5) as c:
            r = c.get(f"{self.BASE}/agents",
                      headers={"Authorization": f"Bearer {os.environ['AGENTPHONE_API_KEY']}"})
            if r.status_code == 401:
                raise RuntimeError("API key rejected (401)")
            if r.status_code >= 500:
                raise UpstreamUnavailable(f"AgentPhone returned {r.status_code}")
            r.raise_for_status()
        return "200 OK"

    def _webhook_configured(self) -> str:
        with httpx.Client(timeout=5) as c:
            r = c.get(f"{self.BASE}/webhooks",
                      headers={"Authorization": f"Bearer {os.environ['AGENTPHONE_API_KEY']}"})
            r.raise_for_status()
            data = r.json()
            if not data or not data.get("url"):
                raise RuntimeError("No master webhook configured")
        return f"url={data['url']}"

    def _hmac_verification_roundtrip(self) -> str:
        # Synthesize a payload + signature with our local secret; verify the same algorithm
        # accepts it. Catches drift between our verifier and what AP sends.
        secret = os.environ["AGENTPHONE_WEBHOOK_SECRET"]
        body = b'{"event":"agent.message","channel":"sms","data":{}}'
        ts = str(int(time.time()))
        signed = f"{ts}.".encode() + body
        expected = hmac.new(secret.encode(), signed, hashlib.sha256).hexdigest()
        # round-trip through our production verifier (imported from our adapter)
        from app.telephony.agentphone import verify_webhook
        if not verify_webhook(body, f"sha256={expected}", ts, secret):
            raise RuntimeError("Local HMAC verifier disagrees with synthesized signature")
        return "HMAC algorithm OK"

    def _test_webhook_endpoint(self) -> str:
        with httpx.Client(timeout=10) as c:
            r = c.post(f"{self.BASE}/webhooks/test",
                       headers={"Authorization": f"Bearer {os.environ['AGENTPHONE_API_KEY']}"})
            r.raise_for_status()
            data = r.json()
            if not data.get("success"):
                raise RuntimeError(f"Test delivery failed: {data.get('errorMessage')}")
        return f"httpStatus={data.get('httpStatus')}"

    def _conversation_state_roundtrip(self) -> str:
        # Set metadata on a pre-provisioned test conversation, read it back.
        # Requires SMOKE_AGENTPHONE_TEST_CONVERSATION_ID
        ...

    def _ndjson_response_shape(self) -> str:
        # Spin up a temp HTTP server, register it as a webhook, POST a synthetic
        # agent.message:voice to it via /v1/webhooks/test, verify NDJSON is accepted.
        # (In repair mode, prints the exact response AP got back.)
        ...

    def _can_send_sms(self) -> str:
        # Send to a fixture test number (must be configured: SMOKE_AGENTPHONE_TEST_TO).
        # Asserts only that AP accepts the request; doesn't verify delivery.
        ...


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--mode", choices=["check", "smoke", "repair"], default="check")
    args = p.parse_args()
    raise SystemExit(AgentPhoneProbe(mode=args.mode).run())
```

### 12.5 Worked Example — LLM Probe (OpenAI-API Compatible)

The LLM probe is intentionally written against the **OpenAI chat-completions API shape**, not against Anthropic's native SDK. Every major provider exposes this shape (Anthropic at `/v1/openai/chat/completions`, OpenAI natively, vLLM/Ollama/Together/Groq via their compat endpoints). Swapping providers is a config flip in the smoke env. The production code uses the native Anthropic SDK for richer features; the smoke test is the contract-level common denominator.

```python
# smoke/llm.py
import os, time, httpx, json
from ._base import Probe, UpstreamUnavailable

class LLMProbe(Probe):
    """Verifies the configured LLM endpoint speaks OpenAI chat-completions."""
    name = "llm"
    required_env = ["LLM_API_KEY", "LLM_BASE_URL", "LLM_MODEL"]
    # Defaults for Anthropic via OpenAI-compat:
    #   LLM_BASE_URL=https://api.anthropic.com/v1/openai
    #   LLM_MODEL=claude-sonnet-...  (or whatever is pinned in skills/orchestrator/SKILL.md)
    #   LLM_API_KEY=<your Anthropic key>

    def checks_for_mode(self):
        if self.mode in ("check", "smoke", "repair"):
            self.check("auth_valid", self._auth_valid,
                       fix_hint="Verify LLM_API_KEY and LLM_BASE_URL match the provider.")
            self.check("basic_completion", self._basic_completion,
                       fix_hint="Provider rejected basic chat completion — check model name in LLM_MODEL.")

        if self.mode in ("smoke", "repair"):
            self.check("streaming_completion", self._streaming_completion,
                       fix_hint="Provider does not stream — VotF's hot path requires SSE streaming.")
            self.check("json_mode", self._json_mode,
                       fix_hint="Provider does not honor response_format=json_object — classifier skill will fail.")
            self.check("tool_calls", self._tool_calls,
                       fix_hint="Provider does not support tool/function calls — Orchestrator tools will fail.")
            self.check("long_context_50k", self._long_context,
                       fix_hint="Model context window is below 50k tokens — onboarding intake may not fit.")
            self.check("skill_models_reachable", self._skill_models,
                       fix_hint="One or more models pinned in skills/*/SKILL.md are not available on this provider.")

    def _client(self):
        return httpx.Client(
            base_url=os.environ["LLM_BASE_URL"],
            headers={"Authorization": f"Bearer {os.environ['LLM_API_KEY']}",
                     "Content-Type": "application/json"},
            timeout=30,
        )

    def _basic_completion(self) -> str:
        with self._client() as c:
            r = c.post("/chat/completions", json={
                "model": os.environ["LLM_MODEL"],
                "messages": [{"role": "user", "content": "Reply with one word: pong"}],
                "max_tokens": 16,
            })
            if r.status_code == 401: raise RuntimeError("API key rejected")
            if r.status_code >= 500: raise UpstreamUnavailable(f"{r.status_code}")
            r.raise_for_status()
            content = r.json()["choices"][0]["message"]["content"]
            if "pong" not in content.lower():
                raise RuntimeError(f"Unexpected response: {content!r}")
        return f"response={content!r}"

    def _streaming_completion(self) -> str:
        # SSE streaming — what the Orchestrator's hot path depends on
        first_token_ms = None
        t0 = time.time()
        with self._client() as c:
            with c.stream("POST", "/chat/completions", json={
                "model": os.environ["LLM_MODEL"],
                "messages": [{"role": "user", "content": "Count from 1 to 5."}],
                "stream": True,
                "max_tokens": 50,
            }) as r:
                for line in r.iter_lines():
                    if line.startswith("data: ") and line != "data: [DONE]":
                        if first_token_ms is None:
                            first_token_ms = (time.time() - t0) * 1000
        if first_token_ms is None:
            raise RuntimeError("No streamed tokens received")
        return f"first_token={first_token_ms:.0f}ms"

    def _json_mode(self) -> str:
        with self._client() as c:
            r = c.post("/chat/completions", json={
                "model": os.environ["LLM_MODEL"],
                "messages": [{"role": "user",
                              "content": 'Return JSON: {"status":"ok"}. Reply with only JSON.'}],
                "response_format": {"type": "json_object"},
                "max_tokens": 50,
            })
            r.raise_for_status()
            content = r.json()["choices"][0]["message"]["content"]
            parsed = json.loads(content)   # raises if not valid JSON
            if parsed.get("status") != "ok":
                raise RuntimeError(f"Unexpected JSON: {parsed!r}")
        return "JSON shape honored"

    def _tool_calls(self) -> str:
        with self._client() as c:
            r = c.post("/chat/completions", json={
                "model": os.environ["LLM_MODEL"],
                "messages": [{"role": "user", "content": "What's the weather in SF?"}],
                "tools": [{
                    "type": "function",
                    "function": {
                        "name": "get_weather",
                        "description": "Get current weather",
                        "parameters": {
                            "type": "object",
                            "properties": {"location": {"type": "string"}},
                            "required": ["location"],
                        },
                    },
                }],
                "tool_choice": "auto",
                "max_tokens": 100,
            })
            r.raise_for_status()
            msg = r.json()["choices"][0]["message"]
            if not msg.get("tool_calls"):
                raise RuntimeError(f"Model did not return a tool call: {msg}")
        return f"tool_call={msg['tool_calls'][0]['function']['name']}"

    def _long_context(self) -> str:
        # Send ~50k tokens worth of filler + a question at the end
        ...

    def _skill_models(self) -> str:
        # Walk skills/*/SKILL.md, extract pinned model strings, probe each
        ...


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--mode", choices=["check", "smoke", "repair"], default="check")
    args = p.parse_args()
    raise SystemExit(LLMProbe(mode=args.mode).run())
```

### 12.6 Worked Example — Supermemory Probe

```python
# smoke/supermemory.py
import os, uuid
from supermemory import Supermemory
from ._base import Probe, UpstreamUnavailable

class SupermemoryProbe(Probe):
    name = "supermemory"
    required_env = ["SUPERMEMORY_API_KEY"]

    def checks_for_mode(self):
        if self.mode in ("check", "smoke", "repair"):
            self.check("auth_valid", self._auth_valid)

        if self.mode in ("smoke", "repair"):
            test_user_id = f"smoketest:probe:{uuid.uuid4()}"
            memory_id = None

            try:
                memory_id = self.check_with_return(
                    "memory_write", lambda: self._write_memory(test_user_id))
                self.check("memory_search_finds_write",
                           lambda: self._search_finds(test_user_id, memory_id))
                self.check("memory_delete",
                           lambda: self._delete_memory(memory_id))
                self.check("file_upload_small",
                           lambda: self._upload_file(test_user_id))
                self.check("profile_fetch",
                           lambda: self._profile_fetch(test_user_id))
            finally:
                # Cleanup: delete any memories left behind under this test user
                self._cleanup(test_user_id)

    def _client(self):
        return Supermemory(api_key=os.environ["SUPERMEMORY_API_KEY"])

    def _auth_valid(self) -> str:
        with self._client() as c:
            r = c.search.execute(q="ping", limit=1)   # benign search
        return "auth OK"

    def _write_memory(self, user_id: str) -> str:
        with self._client() as c:
            r = c.add(content="smoketest content " + uuid.uuid4().hex,
                      user_id=user_id, metadata={"smoketest": True})
        return r.id

    def _search_finds(self, user_id: str, memory_id: str) -> str:
        # search is eventually consistent — may need a small wait
        import time
        for _ in range(5):
            with self._client() as c:
                r = c.search.execute(q="smoketest", user_id=user_id, limit=5)
            if any(m.id == memory_id for m in r.results):
                return f"found in {_+1} attempts"
            time.sleep(1)
        raise RuntimeError("Memory not searchable after 5s")

    # ... _delete_memory, _upload_file, _profile_fetch, _cleanup
```

### 12.7 Infrastructure Probes

The same `Probe` pattern covers infra:

```python
# smoke/postgres_brain.py
class BrainPostgresProbe(Probe):
    name = "postgres_brain"
    required_env = ["BRAIN_DATABASE_URL"]

    def checks_for_mode(self):
        self.check("connect", self._connect)
        self.check("pgvector_present", self._pgvector_present,
                   fix_hint="Run: CREATE EXTENSION IF NOT EXISTS vector;")
        if self.mode in ("smoke", "repair"):
            self.check("schema_per_workspace_create",
                       self._create_test_workspace_schema)
            self.check("embedding_roundtrip",
                       self._embedding_insert_and_search)
            self.check("schema_per_workspace_drop",
                       self._drop_test_workspace_schema)


# smoke/redis.py
class RedisProbe(Probe):
    name = "redis"
    required_env = ["REDIS_URL"]

    def checks_for_mode(self):
        self.check("connect", self._connect)
        self.check("set_get", self._set_get_roundtrip)
        if self.mode in ("smoke", "repair"):
            self.check("pubsub_roundtrip", self._pubsub_roundtrip)
            self.check("arq_enqueue", self._arq_enqueue_dequeue)


# smoke/object_storage.py
class ObjectStorageProbe(Probe):
    name = "object_storage"
    required_env = ["S3_BUCKET", "S3_ACCESS_KEY", "S3_SECRET_KEY"]
    # S3_ENDPOINT_URL is optional (empty = real AWS S3, set = R2 or MinIO)

    def checks_for_mode(self):
        self.check("bucket_reachable", self._bucket_reachable)
        if self.mode in ("smoke", "repair"):
            self.check("put_object", self._put)
            self.check("get_object", self._get)
            self.check("signed_url_generation", self._signed_url)
            self.check("delete_object", self._delete)
            self.check("workspace_prefix_isolation",
                       self._prefix_isolation,
                       fix_hint="Bucket-level ACLs may be too permissive.")
```

### 12.8 The Aggregating Runner

```bash
# Run every probe in check mode (CI pre-flight)
python -m smoke run --all

# Run every probe in smoke mode (release gate)
python -m smoke run --all --mode smoke

# Run just the third-party probes (skip infra)
python -m smoke run --filter third_party --mode smoke

# Repair a specific failing integration
python -m smoke run --only agentphone --mode repair
```

The runner reads `smoke/manifests/probes.yaml`:

```yaml
probes:
  third_party:
    - { module: smoke.agentphone, critical: true }
    - { module: smoke.supermemory, critical: true }
    - { module: smoke.llm, critical: true }
  infrastructure:
    - { module: smoke.postgres_app, critical: true }
    - { module: smoke.postgres_brain, critical: true }
    - { module: smoke.redis, critical: true }
    - { module: smoke.object_storage, critical: true }

modes:
  default: check
  pre_release: smoke

exit_policy:
  on_config_error: fail_fast        # don't run others if env is broken
  on_upstream_down: collect_and_report   # don't block deploy on third-party outage we can't fix
```

The aggregator runs probes **in parallel** (each is independent), times them, aggregates JSON reports into one summary, and exits with the worst code across all probes (per `exit_policy`).

### 12.9 CI Integration

Smoke tests run at three stages:

| Stage | Mode | What fails the build |
|---|---|---|
| Pre-merge (PR CI) | `check` against staging credentials | Any check fail |
| Pre-deploy (release pipeline) | `smoke` against staging | Any smoke fail in `critical` probes |
| Post-deploy verification | `smoke` against the new prod deployment | Any smoke fail; rollback automated |

A separate **hourly cron** runs `smoke run --all --mode check` against production and pages on `--fail` for any non-upstream-down probe. This catches credential expiration, API drift, and config rot between deploys.

### 12.10 Adding a New Integration

Adding a new third-party (say, a CRM connector) is mechanical:

1. Create `smoke/<name>.py` extending `Probe`.
2. Declare `name`, `required_env`, implement `checks_for_mode()`.
3. Add an entry to `smoke/manifests/probes.yaml` under the right category.
4. Document the operator-setup steps in §11 of this HLD.
5. Wire the probe into the CI stages above.

The shape constraint (`Probe` base, three modes, four exit codes, JSON output) makes every smoke test interchangeable from the runner's perspective. No bespoke harnesses.

### 12.11 What These Tests Don't Cover

To be honest about scope:

- **Production load testing** — smoke tests verify *correctness*, not *capacity*. Latency budgets and concurrent-call scaling are separate load tests.
- **End-to-end VotF flows** — a Manager-signs-up-then-Rep-calls full-stack test belongs in `tests/e2e/`, not in `smoke/`. Smoke tests are integration-by-integration.
- **Failure-mode coverage** — these tests verify the happy path against each integration. Adversarial cases (what if Anthropic rate-limits us mid-call?) belong in resilience tests.
- **Cost** — smoke tests cost real money each run (LLM tokens, Supermemory writes, AgentPhone test endpoints). The `check` mode is cheap (<$0.01 per full run); `smoke` mode costs $0.05–0.20 per run. Hourly cron in `check` mode is fine; `smoke` mode is for release gates only.

---

## 13. Phase-by-Phase Implementation Map

| # | Priority | Phase | Component Work |
|---|---|---|---|
| 1 | Manager signup | 0 | `auth` + `me` routers; `Organization` + `ManagerWorkspace` + `User` (role=manager) models; signup flow |
| 2 | Workspace provisioning + data sources | 0 | AgentPhone number provisioning; `data_sources` router; `ConnectorRegistry`; `IntakeBuffer`; Supermemory adapter; initial `BrainProvider` (basic pgvector + tsvector, no graph yet) |
| 3 | Intake classification + ingestion | 0 | `skills/classifier/`; `IntakeProcessor`; typed handlers (`OrgBrainHandler`, `CallerBrainHandler`, `CrossRefHandler`, `RawSourceHandler`); `brain_seeder` mini-agent; Stage 5 verification surface |
| 4 | Inbound call (hot path, streamed) | 0 | Telephony adapter (HMAC verify, dedupe, `conversationState` echo); Workspace resolution; profiling sub-flow; Orchestrator turn loop with **streaming LLM → NDJSON to AP** (§5.5.1); bridge-chunk pattern for slow work; pre-warmed retrieval |
| 5 | Multi-call live view (WS) | 0 | `/api/v1/workspaces/{wid}/ws/live` multiplexes all active calls; FE renders parallel call panes; lifecycle frames (`call.started`, `transcript.fragment`, `decision.opened`, `decision.resolved`, `call.ended`) |
| 6 | Decision Loop (three classes) | 0 | `DecisionRequest` model with `decision_class`; `decisions` router; WS frame on the multi-call channel; SMS fallback channel; class-appropriate bridging in Orchestrator system prompt |
| 7 | Decision timeout + brief-flagging | 0 | Timeout worker; "Manager unavailable, moving on" Orchestrator phrasing; timed-out decisions surface as **"Decisions you missed"** section in the Manager's next daily brief (handled by `dashboard_rollup`) |
| 8 | Correction & Provenance scaffolding | 0 | `Provenance` on all writes (per-page in Phase 0); `BrainPageVersion` table; `CorrectionIntake` + `CorrectionHandler`; `correction_cascade` worker (minimal); `manager_authoritative` flag |
| 9 | Skills directory + eval CI | 0 | `skills/<name>/` layout for `classifier`, `orchestrator`, `caller_profiler`; `SkillRegistry`; eval CI step blocks regressions below `quality_bar` |
| 10 | Hierarchy guard test | 0 | Integration test: stub `org_admin` and `rep` users can be created + authenticated but are rejected from `/workspaces/...` endpoints; reserved namespace routers exist but return 404/501 |
| 11 | Deployment profiles (local + cloud) | 0 | `docker-compose.local.yml` brings up Postgres × 2 + Redis + MinIO; env-var-driven config (§10.2) so prod swaps to managed services with no code change; ngrok/cloudflared tunnel for AP webhook in dev |
| 12 | Smoke-test framework | 0 | `smoke/` directory with `Probe` base + one probe per integration (AgentPhone, Supermemory, LLM via OpenAI-compat, Postgres × 2, Redis, S3); three modes (`check`/`smoke`/`repair`); aggregating runner; CI wired at pre-merge / pre-deploy / post-deploy; hourly cron in `check` mode against prod. See §12. |
| 13 | Transcripts + call history in FE | 1 | Transcript persistence; `calls` router; FE live + historical view |
| 14 | Post-call summarization + action items | 1 | `summarizer` mini-agent (skill, takes AP's `provider_summary` as a hint); `action_item_extractor` (skill); `post_call` worker fan-out; `action_items` router |
| 15 | Brain self-update (full) | 1 | `brain_updater` mini-agent runs typed-graph extractor; `brain_maintenance` nightly cron; entity escalation logic |
| 16 | Manager intervention — whisper mode | 1 | `ManagerIntervention` table; `POST /workspaces/{wid}/calls/{call_id}/whisper`; Orchestrator turn-prompt extension to include `manager_whispers`; `takeover.granted` / `takeover.released` WS frames; post-call audit of whispers |
| 17 | Daily brief (with missed decisions) | 1 | `dashboard_rollup` mini-agent generates the daily brief; "Decisions you missed" section pulls `DecisionRequest.status=timed_out` since last brief; one-click resolve CTA |
| 18 | Scheduling / emailing with approval | 2 | `scheduler` mini-agent; approval flow; outbound integrations (Gmail / Calendar) |
| 19 | Multi-conversation dashboards | 2 | Expanded `dashboard_rollup` output; trend dashboards; `dashboards` router |
| 20 | Manager takeover mode (audio) | 2+ | WebRTC bridge from Manager's mic into the AP call leg; AP outbound voice channel handoff; substantial telecom work, gated to Phase 2+ |

Phase 0 is the MVP loop **plus** the architectural commitments that make later phases cheap: provenance, hierarchy guard test, skills versioning, streaming-by-default, deployment profiles. Phase 1 makes the system durable (everything captured, reviewable, intervenable). Phase 2 makes it productive (acting on what was captured, including real-time audio takeover).

---

## 14. Open Questions, Resolutions, Future Work

### 14.1 Resolved Decisions (carried into the design above)

- **Tenancy unit.** Manager Workspace is the unit of isolation. Each Manager who signs up gets their own Organization (auto-created, single-Manager) and one Workspace beneath it. See §2, §5.2, §6.
- **Numbering model.** Per-Workspace dedicated AgentPhone numbers in Phase 0. Shared-pool routing not built. See §5.1.
- **Privacy posture.** Phase 0 is Manager-private only. No peer, team, or org-level visibility tiers yet. See §2.
- **Decision timeouts.** Three classes (`inline` 45s, `bridged` 2 min, `async` no live wait), Workspace-configurable. See §5.5.3.
- **Manager-away behavior (Phase 0).** No delegation. On timeout, Orchestrator tells the Rep plainly that the Manager is unavailable and **moves on**; timed-out `DecisionRequest` surfaces in the Manager's **next daily brief** under a "Decisions you missed" section. See §5.5.3, §7.3.
- **End-to-end streaming.** Rep ↔ LLM ↔ TTS uses token-streaming via Anthropic's `messages.stream()` and NDJSON interim chunks to AgentPhone. Bridge-chunk pattern keeps the line live during slow operations. Caller-perceived latency P50 ~560ms. See §5.5.1, §15.
- **Multi-call live view.** One WebSocket per Manager session (`workspace:{wid}/ws/live`) multiplexes all active calls; FE renders parallel call panes. See §5.5.2.
- **Manager intervention.** Phase 1 ships `whisper` mode (Manager types guidance → Orchestrator incorporates in next turn, Rep is unaware). `takeover` mode (real-time audio replacement) is designed but deferred to Phase 2+ due to telecom complexity. See §5.5.4.
- **Local + cloud deployment profiles.** Postgres, Redis, and object storage all support both local (containerized) and cloud (managed) modes via env-var configuration; AgentPhone, Supermemory, and Anthropic are cloud-only by their nature. See §10.2.
- **Smoke-test framework.** Every third-party and infrastructure integration has an independent smoke script following the same `Probe` shape. Three modes (`check`/`smoke`/`repair`), four exit codes, JSON+pretty output, parallel runner, CI-integrated at pre-merge / pre-deploy / post-deploy plus hourly prod cron. The LLM probe uses OpenAI chat-completions API shape so provider swaps are config flips. See §12.
- **Correction & provenance.** Manager corrections always win, append-only-versioned, cascade through dependent edges, never destroy historical evidence. See §9.
- **Skills are first-class artifacts.** Every prompt is a directory with SKILL.md, schema, evals, CHANGELOG. See §8.7.
- **Third-party integration contracts.** Backend uses REST/SDK; MCP is for external consumers only. See §11.

### 14.2 Still-Open Questions

- **PII / compliance.** Recording and transcript retention defaults, deletion mechanics, SOC 2 / HIPAA roadmap. Data model already supports per-Workspace retention (`workspace.config.retention_*`) and a deletion worker that respects the provenance graph; defaults need product input. Likely Phase 0 ships strong-defaults-only; configurable in Phase 1; HIPAA tier Phase 2.
- **Multi-language.** AgentPhone is US/Canada at launch. Some Field teams are multilingual on the same call. Plan?
- **Per-claim vs per-page provenance.** §9 describes both; Phase 0 likely ships per-page only and upgrades later.
- **`manager_authoritative` granularity.** Once a Manager corrects a value, does it lock the whole page or just the specific claim/field? Leaning field-level but unresolved.
- **Voice intake duration.** 20-minute guided onboarding call may be too long. Needs product calibration with early users.

### 14.3 Explicitly Deferred Future Work

These are **designed for** but not implemented. The architecture commits to them — schema, API path structure, and extension points already accommodate — but the features are gated to later phases.

- **Multi-Manager Organizations.** Many Workspaces under one Org, org-level admins (`role=org_admin`), cross-Workspace dashboards, Org-level brain rollups. Schema is ready: `organization_id` on every workspace-owned row; `User.workspace_id` is nullable for org-level admins; `/api/v1/organizations/{org_id}/...` namespace is reserved.
- **Field Rep Front-End.** Reps gain `User` accounts with `role=rep`, linked to `FieldEmployee` via `FieldEmployee.user_id`. Rep-side dashboards (their calls, their action items, the brain pages their Manager permits them to see). The `/api/v1/rep/...` namespace is reserved.
- **Delegation chains.** When org-level surfaces ship, `DecisionRequest.target_user_id` becomes rotatable; a delegation worker re-targets an open request to an `org_admin` after a sub-timeout. The data model, tool schema, and FE channel structure already accommodate this.
- **Privacy tiers.** Once peer/org visibility exists, content gains tier tags (`workspace_private` / `team` / `org`) at extraction time. The `summarizer` skill is already structured so a tier-tagging step can be added without disrupting the rest of the pipeline.
- **Shared-pool numbering.** Phase 1+ opt-in if a Workspace wants to share a number with caller-ID routing instead of a dedicated line.

### 14.4 Risks

- **Hot-path latency.** End-to-end <2s per turn is tight. Pre-warming retrieval, picking a fast LLM tier, and keeping tool calls async help. Needs a latency budget enforced in load tests before launch.
- **Supermemory as critical dependency.** If Supermemory is down, the system degrades. Mitigation: graceful fallback to brain-only context; cache last-known Field Rep profile in Postgres.
- **GBrain-inspired brain is non-trivial to build.** The full hybrid search + typed graph + compiled-truth + versioning model is real engineering. Phase 0 ships a simpler brain (pgvector + tsvector + basic search), Phase 1 adds typed graph + RRF + versioning. Don't block MVP on full feature parity.
- **Workspace isolation bugs are catastrophic.** Cross-Workspace data leak is the worst failure mode. Mitigation: schema-per-Workspace for the brain (not row-level), automated tests that assert isolation across both app DB and brain DB, and a Workspace-aware DB driver wrapper that errors on any unscoped query.
- **Cost.** Voice minutes + STT + LLM per turn + Supermemory + storage stacks up. Need per-Workspace cost telemetry from day one.
- **Trust and tone of the agent.** The product's value depends on Field Reps finding the agent easy and natural to talk to. The interview playbook is as much product as engineering. Iterate continuously with real call data.
- **"Designed for future, built for now" drift.** The biggest architectural risk is that the org-level and rep-level extension points decay because no one tests them. Mitigation: the §13 priority 10 guard test asserts that stub `org_admin` and `rep` users can be created, authenticated, and rejected from endpoints they shouldn't access. This test runs from Phase 0 and keeps the design commitment honest.

---

## 15. Appendix — Sample Sequence (Streaming Hot-Path Call Turn)

This is the per-millisecond budget for a single conversational turn with end-to-end streaming enabled (§5.5.1). Times are P50 targets; P95 is roughly 1.6× each segment.

```
T+0       Rep finishes their utterance; AgentPhone STT closes the turn
T+50ms    AP delivers agent.message:voice webhook to our adapter
            { data: { transcript: "...", confidence: 0.95, ... },
              conversationState: { workspace_id, call_id, field_employee_id } }
T+60ms    Adapter HMAC-verifies, dedupes by X-Webhook-ID, publishes
            transcript fragment to Redis bus
T+60ms    WS hub forwards fragment to Manager's live multi-call view
            (frame type: transcript.fragment, tagged with call_id)
T+70ms    Orchestrator session loaded from Redis by call_id

            ┌─── PARALLEL ───────────────────────────────────────┐
T+70ms    │  CallerMemory.search(user_id, utterance, k=5)        │
T+70ms    │  Brain.hybrid_search(workspace_id, utterance, k=8)   │
            └─────────────────────────────────────────────────────┘

T+250ms   If retrieval will run >300ms total, Orchestrator emits a bridge chunk:
            stream → AP: {"text": "Let me check on that...", "interim": true}
            (AP starts speaking the bridge while retrieval continues)
T+300ms   Retrieval completes (Caller + Brain results merged + ranked)
T+310ms   Orchestrator opens streaming LLM call:
            client.messages.stream() with:
              - system prompt (rendered from skills/orchestrator/system_prompt.j2)
              - retrieved context (brain pages + caller memories)
              - conversation history (last N turns from Redis)
              - tool schemas (orchestrator tools)
              - manager_whispers if any (Phase 1)

T+550ms   First token-group arrives from LLM
T+555ms   Orchestrator forwards to AP as NDJSON interim chunk:
            {"text": "<first token-group>", "interim": true}
T+560ms   AP begins TTS playback (Rep hears the agent start speaking)

          [token-streaming continues as the LLM emits more tokens]

T+1.2s    LLM completes generation
T+1.21s   Orchestrator emits final NDJSON chunk (no interim flag) — closes the turn
T+1.5s    AP finishes speaking the full reply

          [Rep responds → next turn starts]

Branch A: If the LLM emitted a tool call instead of text:
T+550ms   Tool call arrives (e.g., request_manager_decision)
T+555ms   Orchestrator emits bridge chunk to AP for the tool latency:
            stream → AP: {"text": "Let me run that by leadership...", "interim": true}
T+560ms   Open DecisionRequest, push decision.opened frame to Manager's WS,
            fire SMS to Manager's mobile, continue Orchestrator with bridging logic
T+~30s    Manager taps option (or SMS reply) → decision.resolved frame →
            Orchestrator next LLM turn incorporates the answer
```

**Caller-perceived latency** (Rep finishes → agent starts speaking): **~560ms P50**, down from ~1.5–2s without token streaming. The bridge-chunk pattern means even tool calls and decision loops never produce silence longer than ~300ms.

**Latency budget enforcement.** A load test from Phase 0 onward asserts P95 caller-perceived latency stays under 1s. If retrieval or LLM time budgets drift up, the system regresses gracefully (the bridge chunk is always emitted) rather than producing dead air.
