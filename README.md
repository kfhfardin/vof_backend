# Lien

> AI-supervised intake for personal-injury law firms.
> Submission for **AgentPhone — Call My Agent Hackathon** (YC, May 17 2026).

A managing partner can't be on every intake call. Lien puts an AI agent on the phone, supervises every call in real time, lets the partner approve or whisper from anywhere, and writes everything into a brain the next call benefits from.

---

## Demo · 30-second version

1. `cd ~/Downloads/vof-frontend && npm run dev` → open <http://localhost:3000>
2. **Call** `+1 (478) 330-4859` — *Sue*, our AI intake agent, picks up
3. Play the caller (Fardin Hoque, rear-ended on the 101) — see **DEMO_SCRIPT.md** for lines
4. Open `/inbox/ix_001` on screen — transcript streams as you talk
5. At the prior-injury moment (~02:22), type a whisper in the right rail → real iMessage / email lands on a phone you hold up
6. Open `/approve/ix_001` on a second window/phone → **tap Accept** → Supermemory + AgentMail + Browser Use fire in parallel
7. Open `/cases/ca_2401` → the Supermemory write shows up live in the Brain panel

---

## How the stack maps to sponsors

| Sponsor | Where it fires | What it does in the demo |
|---|---|---|
| **AgentPhone** | AP-hosted agent `cmpa4o1e005ecjz00n7khhuzm` | Answers the phone as *Sue*. Voice-mode `hosted`, model tier `max`, the entire Sue script + prior-injury probe are baked into the agent's `systemPrompt`. AP runs the LLM itself — no webhook server required. |
| **Anthropic / Bedrock** | Powers AP hosted-mode under the hood (`claude-haiku-4-5`) | Drives Sue's conversation in real time on the call. |
| **Supermemory** | `POST /v3/memories` (write) + `POST /v3/search` (read) | Write: on Accept, the case summary + transcript is written to the firm's brain with tags `reyes-associates`, `intake:<id>`, `demo`. Read: `/cases/[id]` queries Supermemory live and shows matched memories. Decline also writes (tagged `declined`). |
| **AgentMail** | `POST /v0/inboxes/{inbox}/messages/send` | Engagement letter on Accept · partner-guidance email when AP SMS is 10DLC-blocked · client follow-up on Need-more-info · approval iMessage fallback on Send-to-Margarita. |
| **Moss** | `@moss-dev/moss` SDK — sub-10ms semantic search runtime | Indexes the firm's precedent set (`reyes-brain`) and serves sub-10ms semantic retrieval over it. Surfaces precedents matching the live call's fact pattern. |
| **Browser Use** | `POST /api/v2/tasks` | On Accept, fires a real cloud browser session to "create a matter in the CRM" — returns a task ID and runs in their dashboard. |
| **Stripe / Sponge** | (not wired) | Out of scope for this build — would handle disbursement / contingency advances. |

---

## What's wired vs what's mocked

### Wired (real network calls to real upstreams)

- **AP hosted-agent script** — Sue is configured by `scripts/configure_agent.py`. Phone calls land at AP's hosted LLM and stream voice back. No webhook server in this stack.
- **`POST /api/integrations/accept-case`** — Supermemory + AgentMail + Browser Use, in parallel via `Promise.allSettled`.
- **`POST /api/integrations/decline-case`** — Supermemory write tagged `declined`.
- **`POST /api/integrations/need-more-info`** — AgentMail follow-up requesting ER papers, photos, witnesses.
- **`POST /api/integrations/whisper`** — Tries AP `/v1/messages` first (10DLC-blocked on this account), falls back to AgentMail so the whisper always delivers.
- **`POST /api/integrations/escalate`** — Same AP-then-AgentMail fallback to push case + approval link to the partner's phone/email.
- **`POST /api/integrations/brain-search`** — Supermemory `v3/search` over the firm's tag space.
- **`POST /api/integrations/moss`** — Moss SDK semantic search; auto-seeds on first query. Body `{ op: "query", q, topK }` or `{ op: "seed" }`.

### Mocked / simulated

- **Streaming transcript** — The center pane on `/inbox/ix_001` reveals lines from a hardcoded script on a 4× timer, simulating real-time AP transcription. AP's transcripts go to the agent and not yet back to our UI (would need an AP webhook receiver — see "What's next").
- **Whisper trigger inside the call** — Sue's system prompt is pre-baked with the prior-injury probe as a CRITICAL instruction, so the audio asks the right question whether or not you press the whisper button. The whisper button proves the *channel* works (real email/SMS).

---

## Setup

### One-time

```bash
cd ~/Downloads/vof-frontend
npm install
cp .env.local.example .env.local  # then paste your keys (already populated for this demo)
```

### Configure the AgentPhone agent

```bash
python3 scripts/configure_agent.py
```

This PATCHes the existing agent into `hosted` mode and installs the Sue system prompt. It prints the phone numbers attached to the agent at the end.

### Run

```bash
npm run dev
# open http://localhost:3000
```

---

## Architecture (one line each)

- **Framework:** Next.js 16 App Router, TypeScript, Tailwind v4 with glassmorphism.
- **No backend server:** all integrations live in Next.js API routes under `/app/api/integrations/*`. The friend's Python backend (<https://github.com/kfhfardin/vof_backend>) is the long-term home — for the hackathon, we kept everything in the FE project.
- **Hosted AP agent:** AP runs the LLM itself (Bedrock-hosted Claude Haiku 4.5) using the script's `systemPrompt`. Latency is AP's problem, not ours.
- **Moss runtime:** indexes load in-process inside Node 18+ API routes; sub-10ms retrieval after warm-up.

---

## File map

```
app/
  api/integrations/
    accept-case/         POST → Supermemory + AgentMail + Browser Use
    decline-case/        POST → Supermemory (declined)
    need-more-info/      POST → AgentMail follow-up
    whisper/             POST → AP SMS → AgentMail fallback (partner guidance)
    escalate/            POST → AP SMS → AgentMail fallback (case to partner)
    brain-search/        POST → Supermemory v3/search
    moss/                POST → Moss SDK seed + query
  _components/
    accept-actions.tsx       3-button approval card with live status rows
    streaming-transcript.tsx 4× transcript playback for live demo
    whisper.tsx              Auto-suggest + free-text whisper composer
    brain-search.tsx         Supermemory-backed brain panel
    send-to-margarita.tsx    Escalation button
    live-timer.tsx           Ticking call duration
    ui.tsx                   Glass primitives (Card, Pill, Button, SectionLabel)
  _data/mock.ts          Intakes, transcript, precedents, whisper suggestions
  inbox/[id]/page.tsx    Live intake with 3-pane copilot layout
  approve/[id]/page.tsx  Mobile partner-approval card
  cases/[id]/page.tsx    Case detail with live Brain panel
scripts/
  configure_agent.py     One-shot setup for the AP hosted agent
DEMO_SCRIPT.md           Full caller script with timing + whisper cue card
```

---

## Demo phone number

**Call `+1 (478) 330-4859`** — Sue picks up.

The greeting:
> *"Thanks for calling Reyes & Associates, this is Sue. I'm so sorry to hear you've been in an accident — let's get you taken care of. Can you walk me through what happened?"*

---

## What's next (post-hackathon, two days of work each)

- **AP `agent.call_ended` webhook receiver** under `/api/webhooks/agentphone` — auto-fires Supermemory write + AgentMail engagement letter on hangup instead of needing the Accept button. Needs ngrok or a deploy.
- **Real-time AP voice transcription stream** to the FE via SSE — replaces the 4× simulated stream on `/inbox/[id]`.
- **Moss index hydration from Supermemory** — keep the two stores in sync so Moss has every fact Supermemory has.
- **10DLC registration** so AP outbound SMS works — removes the AgentMail-fallback shim on whisper + escalate.
- **Per-firm onboarding wizard** — Lien is currently single-tenant (Reyes & Associates); next is the per-firm setup flow that provisions a number and seeds the brain from existing case management exports.

---

---

## ⚠ Required environment variables

Nothing works without these. Drop them into **`.env.local`** at the project root before `npm run dev`. The repo ships with a template populated for the hackathon demo — for any new deployment you need to swap in your own keys.

| Variable | What it powers | Where to get it |
|---|---|---|
| `AGENTPHONE_API_KEY` | Sue picks up calls + outbound SMS attempts | <https://app.agentphone.ai> |
| `AGENTPHONE_WEBHOOK_SECRET` | HMAC verify on inbound AP webhooks | AP dashboard → Webhooks |
| `AGENTPHONE_AGENT_ID` | Which AP agent runs Sue (defaults to the demo agent) | AP dashboard → Agents |
| `SUPERMEMORY_API_KEY` | Brain write on Accept, brain search on case page | <https://supermemory.ai> |
| `AGENTMAIL_API_KEY` | Engagement letter, whisper fallback, escalate fallback, follow-up email | <https://agentmail.to> |
| `AGENTMAIL_INBOX` | The from-address the firm sends from | AgentMail dashboard |
| `BROWSER_USE_API_KEY` | "Create matter" cloud-browser task on Accept | <https://browser-use.com> |
| `MOSS_PROJECT_ID` + `MOSS_PROJECT_KEY` | Sub-10ms semantic search over the brain | <https://portal.moss.dev> |
| `MOSS_INDEX` | Name of the Moss index (defaults to `reyes-brain`) | choose your own |
| `DEMO_CLIENT_EMAIL` | The inbox the engagement letter / follow-up lands in | your own email |
| `DEMO_PARTNER_EMAIL` *(optional)* | Where escalation lands when AP SMS is blocked | partner's email |
| `ANTHROPIC_API_KEY` *(optional)* | Only needed if you stop using AP's hosted LLM and run your own | Anthropic / Bedrock |

If any of the load-bearing keys above are missing, the corresponding integration route returns `{ ok: false, error: "<KEY> not set" }` instead of crashing — but the demo won't be a demo. Set them all.

---

## Pitch

> 50,000 personal injury law firms in the US run on one phone call. Someone gets hurt, sees a billboard, dials a number — and a paralegal making $18/hr decides whether a case worth $500K in fees walks out the door. The lawyer is in court. The lawyer is *always* in court. We made it so the moment they're not in the room — the moment that decides whether the firm grows or shrinks — happens correctly anyway.

— Lien · The intake supervisor that doesn't sleep.


---

# Voice of the Field — Python Backend

*The long-term home for the orchestrator, mini-agents, and Phase-1 durability layer. Not required for the hackathon demo (which runs entirely from the Next.js frontend above), but documented here for completeness.*

---


Phone-first intelligence layer that turns Field Rep conversations into
structured, actionable knowledge for Managers. Three surfaces ship in
the box:

- **Live voice** — sub-2s warm-turn streaming through AgentPhone, with
  Claude (via Anthropic API or AWS Bedrock) on the hot path
- **Conversational SMS** — turn-based, no streaming, same orchestrator
- **Email** — outbound + inbound replies via AgentMail, plus drafted
  emails as action-item outcomes

Backed by FastAPI + Postgres × 2 + Redis + S3-compat object store +
Supermemory for per-rep caller memory.

> **SMS caveat:** outbound SMS via AgentPhone is gated on US-carrier
> 10DLC registration at the account level. **Inbound SMS works
> immediately; outbound SMS replies fail with HTTP 404 from AP until
> 10DLC registration is complete** in the AP dashboard.

Design docs: [`hld/`](./hld/), [`lld/`](./lld/)
(`phase_0_scaffolding_and_mvp.md`, `phase_1_durability_and_productivity.md`).

---

## Table of contents

1. [Code architecture](#code-architecture)
2. [What Phase 0 vs Phase 1 ships](#what-phase-0-vs-phase-1-ships)
3. [Quickstart (dev inner-loop)](#quickstart-dev-inner-loop)
4. [LLM provider — Anthropic direct OR AWS Bedrock](#llm-provider--anthropic-direct-or-aws-bedrock)
5. [Connection-pooling + lifespan](#connection-pooling--lifespan)
6. [Optional third-party integrations](#optional-third-party-integrations)
7. [HTTP + WebSocket API reference](#http--websocket-api-reference)
8. [LLM-facing surface — Skills + Orchestrator tools](#llm-facing-surface--skills--orchestrator-tools)
9. [Background workers + mini-agents](#background-workers--mini-agents)
10. [Services layer](#services-layer)
11. [Database models + migrations](#database-models--migrations)
12. [Running the production container locally](#running-the-production-container-locally)
13. [Smoke tests — per-integration verification](#smoke-tests--per-integration-verification)
14. [Unit + integration tests](#unit--integration-tests)
15. [Seeding a Workspace into the DB](#seeding-a-workspace-into-the-db)
16. [Live end-to-end testing (real phone call)](#live-end-to-end-testing-real-phone-call)
17. [Common make targets](#common-make-targets)
18. [Troubleshooting](#troubleshooting)

---

## Code architecture

VotF is one Python package (`app/`) plus a sibling `skills/` directory
of LLM prompt assets, two Postgres databases, one Redis instance, one
S3 bucket, and a handful of external personas (AgentPhone, AgentMail,
Supermemory). Each external boundary is behind a Protocol so individual
pieces can be unit-tested, smoke-tested, and replaced without rewriting
the rest.

```
app/
├── main.py / factory.py / lifespan.py / deps.py / settings.py / errors.py
├── api/             — HTTP + WebSocket surface (auth, me, webhooks, workspaces/*)
├── orchestrator/    — voice + SMS turn loops + retrieval + tools
├── miniagents/      — post-call workflows (summarize, brain, memory, email, scheduler, verifier, dashboard)
├── workers/         — arq job runners (post_call, decision_timeout, etc.)
├── services/        — app-layer services (auth, intake, decisions, corrections, dashboards, action_items, web_verifier)
├── skills/          — Skill loader + cached LLMClient (OpenAI-compat + Bedrock)
├── brain/           — PostgresBrainProvider (per-Workspace pgvector schemas)
├── memory/          — Supermemory adapter (cached, single-tag retrieval)
├── telephony/       — AgentPhoneAdapter (cached) + dispatcher
├── email/           — AgentMail provider + composer + templates
├── connectors/      — OAuth connectors (google_workspace.py — dormant)
├── storage/         — S3-compat ObjectStore (aiobotocore, cached)
├── realtime/        — Redis pub/sub bus + WS frame schemas
├── db/              — SQLAlchemy models + repos + sessions
├── migrations/      — Alembic env + per-target versions/
├── security/        — JWT + bcrypt + HMAC
├── observability/   — OTel + structlog
├── schemas/         — Pydantic request/response + WS frames
└── connectors/      — third-party SDK clients

skills/
├── classifier/                — intake scope/kind classification (Haiku)
├── orchestrator/              — live voice + SMS turn loop (Haiku/Sonnet)
├── summarizer/                — post-call summary + entity extraction (Sonnet)
├── web_verifier/              — claim corroboration (Sonnet, F5)
└── dashboard_rollup_writer/   — daily brief composer (Sonnet, F8)

smoke/      — per-integration probes (postgres × 2, redis, S3, llm, supermemory, agentphone)
tests/      — unit (173 tests), integration (5 files), e2e (scaffolded), load (scaffolded)
scripts/    — alembic_wrapper, seed_test_workspace, postgres_init
hld/ lld/   — design docs
```

### Hot path — one voice turn

```
AgentPhone webhook (HMAC) → app.api.webhooks.agentphone
  → WebhookDispatcher → app.orchestrator.turn_loop.TurnLoop.run
    ├── persist caller fragment (Postgres)
    ├── speculative retrieval race (~150ms budget):
    │     • prewarmed snapshot from Redis (~1ms read)
    │     • fresh: Caller-memory single-tag search ∥ Brain hybrid search
    │     • whichever wins first feeds the prompt
    ├── render prompt (system + turn templates)
    ├── stream LLM (Anthropic direct OR Bedrock invoke_model_with_response_stream)
    │     └── mid-stream <<TOOL …>> markers dispatched via ToolRegistry
    ├── NDJSON chunks → StreamingResponse → AgentPhone TTS
    ├── persist agent reply + publish WS frames
    └── save CallSession to Redis (CAS via WATCH/MULTI/EXEC)
```

### Post-call fan-out (Phase 1 F2)

```
agent.call_ended webhook → post_call_job (arq)
  ├── summarizer skill → {discussion, blockers, extracted_entities, topics, quotes}
  ├── save call artifact (canonical_summary.json) → object store
  ├── PARALLEL:
  │     • brain_updater       (F4: upsert pages / append timeline / web-verifier trust tags)
  │     • caller_memory_writer (Supermemory add, [caller, workspace] tags)
  │     • web_verifier_fanout (F5: queue claim verifications)
  │     • action_items extract (F3: heuristic candidates → pending_approval)
  │     • dashboard_rollup    (F8 — actually fires nightly, not per-call)
  └── publish call.summary_ready WS frame
  └── enqueue email_delivery_job for opted-in recipients
```

---

## What Phase 0 vs Phase 1 ships

**Phase 0 (the live voice loop):**

- Auth: signup, login, **refresh-token rotation + reuse detection**, logout
- Telephony: AgentPhone webhook + HMAC verify + dispatch
- Orchestrator hot path: voice turn streaming through Claude
- Per-rep Caller Memory (Supermemory containerTags, single-tag retrieval)
- Per-Workspace Brain (pgvector + tsvector hybrid search)
- Decision flow: SMS pings + first-responder-wins + timeouts
- Tools: `request_manager_decision`, `request_correction`, `end_call`
- Intake: text + upload (PDF/DOCX/XLSX/CSV/JSON/text) → classifier → handler → Brain
- Manager corrections: replace / soft-delete / append timeline (with `manager_authoritative` guard)
- Post-call writeback: summarize → Brain + Caller Memory

**Phase 1 (F1–F9, durability + productivity):**

| ID | Feature | Status |
|---|---|---|
| F1 | Transcripts + Call History (calls list, transcript, summary, recording, interventions, WS replay) | ✅ shipped |
| F2 | Post-call pipeline fan-out worker | ✅ shipped |
| F3 | Action Items (heuristic extract → approve → handler execute) | ✅ shipped |
| F4 | Brain Self-Update (entity extractor + web-verifier trust tags) | ✅ shipped |
| F5 | Web Verifier (claim verification) | ✅ shipped — `BROWSER_USE_API_KEY` optional (falls back to httpx + regex stripper) |
| F6 | Email Surface (AgentMail outbound + inbound + drafter) | ✅ shipped — `AGENTMAIL_API_KEY` optional (no-ops when empty) |
| F7 | Manager Intervention (whisper) | ✅ shipped |
| F8 | Dashboards (daily brief + trends + saved queries) | ✅ shipped |
| F9 | Google Workspace OAuth + handlers | 🟡 **dormant** — connector code is in place but env vars are intentionally not surfaced. Endpoints return 503; email/scheduler handlers return drafts with `error: "google_oauth_not_configured"`. To re-enable, add `GOOGLE_OAUTH_CLIENT_ID` + `_SECRET` back to settings + env. |

Migration `0010_phase_1_unified.py` adds 8 new tables
(`correction_intakes`, `action_items`, `manager_interventions`,
`claim_verifications`, `email_messages`, `workspace_oauth_credentials`,
`dashboard_snapshots`, `saved_dashboard_queries`) plus columns on
`manager_workspaces` (`email_inbox_id`, `email_inbox_addr`,
`email_domain`).

---

## Quickstart (dev inner-loop)

Prereqs: Docker + [`uv`](https://docs.astral.sh/uv/) + Python 3.12.

```bash
# 1. Install deps
uv sync

# 2. Copy env template; fill in third-party keys as you get them.
cp .env.example .env.local

# 3. Bring up local infra (Postgres × 2, Redis, MinIO)
make compose-up

# 4. Source the env so the app + smoke probes see DATABASE_URL etc.
set -a && source .env.local && set +a

# 5. Verify the foundation works
make smoke          # connectivity check across all infra + third-party
make test           # unit tests (173 pass)

# 6. Run migrations (Phase 0 + Phase 1 both)
make migrate

# 7. Start the API and (in another shell) the arq worker
make run            # uvicorn app.main:app --reload  → http://localhost:8000
make worker         # arq app.workers.settings.WorkerSettings
```

---

## LLM provider — Anthropic direct OR AWS Bedrock

The orchestrator hot path and every skill call route through one
abstraction (`LLMClient` in `app/skills/llm_client.py`), with two
production implementations selected by **`LLM_PROVIDER`**:

| Provider | Class | Auth | Endpoint |
|---|---|---|---|
| `openai_compat` (default) | `OpenAICompatClient` | `LLM_API_KEY` as bearer | `LLM_BASE_URL` (any OpenAI-compatible endpoint) |
| `bedrock` | `BedrockMessagesClient` | `ANTHROPIC_API_KEY` as Bedrock long-term API key (surfaced to boto3 as `AWS_BEARER_TOKEN_BEDROCK`) | `bedrock-runtime.{AWS_REGION}.amazonaws.com` via `aiobotocore` |

Tests swap in `FakeLLMClient` via `set_llm_client()`. When the
production key is missing for the selected provider, the factory falls
back to `FakeLLMClient` with a stderr warning.

**Anthropic direct:**
```bash
LLM_PROVIDER=openai_compat
LLM_API_KEY=sk-ant-...
LLM_BASE_URL=https://api.anthropic.com/v1/openai
LLM_DEFAULT_MODEL=claude-sonnet-4-6
LLM_MODEL=claude-haiku-4-5
```

**AWS Bedrock:**
```bash
LLM_PROVIDER=bedrock
ANTHROPIC_API_KEY=<Bedrock long-term API key>
AWS_REGION=us-east-1
LLM_DEFAULT_MODEL=us.anthropic.claude-sonnet-4-6      # cross-region inference profile
LLM_MODEL=us.anthropic.claude-sonnet-4-6
```

Model IDs must be **cross-region inference profile IDs** (`us.` prefix);
plain Anthropic IDs raise `ValidationException` on Bedrock.

Each skill pins its model in `skills/<name>/SKILL.md` frontmatter —
flip both `.env` and the frontmatter together when switching providers.

---

## Connection-pooling + lifespan

Every long-lived adapter caches its underlying transport for the
process lifetime — TLS handshakes and pool setup happen once at
startup, not on every request.

| Adapter                              | Cached object         | Built on first call to | Closed by `_close_singletons()` |
|--------------------------------------|-----------------------|------------------------|---------------------------------|
| `OpenAICompatClient`                 | `httpx.AsyncClient`   | `_get_client()`        | yes                             |
| `BedrockMessagesClient`              | `aiobotocore` client  | `_get_client()`        | yes                             |
| `AgentPhoneAdapter`                  | `httpx.AsyncClient`   | `_get_client()`        | yes                             |
| `SupermemoryCallerMemoryProvider`    | `AsyncSupermemory`    | `_get_client()`        | yes                             |
| `S3ObjectStore`                      | `aiobotocore` S3      | `_get_client()`        | yes                             |
| Redis singleton (`get_redis()`)      | `redis.asyncio` pool  | first access           | yes                             |
| App + brain DB engines               | `AsyncEngine` (`@lru_cache`'d) | first session  | (closed on process exit)        |

Double-checked locking on an `asyncio.Lock` per adapter; concurrent
cold-start requests don't race. Cache-contract tests in
`tests/unit/test_llm_streaming.py` assert each `_get_client()` returns
the same instance.

### Startup warmup (`app/lifespan.py`)

```
lifespan_startup_begin
  ├── load skills + register orchestrator voice handler
  ├── warm Bedrock client + first invoke_model TLS handshake
  ├── warm Postgres pool (SELECT 1)
  ├── warm Supermemory httpx pool (no-op search)
  └── warm pgvector index (hybrid_search against UUID(int=0))
lifespan_startup_complete
```

Each step is best-effort with `try/except` + `log.warning`.

### Shutdown drain

```
lifespan_shutdown_begin
  ├── llm_client_closed
  ├── telephony_client_closed
  ├── memory_client_closed
  ├── object_store_closed
  └── redis_client_closed
lifespan_shutdown_complete
```

---

## Optional third-party integrations

### AgentMail (F6)
`AGENTMAIL_API_KEY` empty → outbound email no-ops, inbound webhook
returns 200 without processing. Set it to enable F6. `EMAIL_DOMAIN`
optional for custom `<slug>@<your-domain>` (defaults to `*.agentmail.to`).
Webhook signature verification is intentionally skipped (Phase 1 speed
variant — tighten for prod).

### Browser Use (F5)
`BROWSER_USE_API_KEY` empty → web verifier uses httpx + regex HTML
stripper (good enough for the verifier prompt on static pages).
JS-rendered pages need the real SDK.

### Google Workspace (F9 — dormant)
Connector code stays in place. With env vars not surfaced:
- `/api/v1/workspaces/{ws}/integrations/google/*` return **HTTP 503**
  with `{"error":"google_oauth_not_configured"}`
- `email_drafter` returns drafts with that error (no Gmail send)
- `scheduler` returns event drafts with that error (no Calendar event)
- `OAuthPersonalEmailProvider` raises `NotImplementedError` →
  `email_delivery` maps to `oauth_connector_unavailable` and may fall
  back to AgentMail

To re-enable: add `google_oauth_client_id` + `_secret` to
`app/settings.py` and `GOOGLE_OAUTH_CLIENT_ID` + `_SECRET` to
`.env.local`.

---

## HTTP + WebSocket API reference

All routes prefixed with `/api/v1`. Auth column meaning:
- **Public** — no auth required (signup, login, refresh, webhooks)
- **CurrentUser** — valid `Authorization: Bearer <access_token>`
- **require_workspace_access** — CurrentUser + workspace_id in path must match user's workspace

### `auth.py` — `/auth/*`

| Method | Path | Body | Response | Auth | Purpose |
|---|---|---|---|---|---|
| POST | `/auth/signup` | `{email, password, workspace_name}` | `SignupResponse(user, workspace, tokens)` | Public | Create org + workspace + manager user; provisions AP number + brain schema + memory namespace + AgentMail inbox |
| POST | `/auth/login` | `{email, password}` | `TokenPair` | Public | Authenticate; issue access + refresh tokens |
| POST | `/auth/refresh` | `{refresh_token}` | `TokenPair` | Public | Rotate refresh token (reuse detection — old token replay revokes the whole chain) |
| POST | `/auth/logout` | `{refresh_token}` | 204 | Public | Revoke refresh token (idempotent) |

### `me.py` — `/me`

| Method | Path | Body | Response | Auth | Purpose |
|---|---|---|---|---|---|
| GET | `/me` | — | `MeResponse(user, workspace)` | CurrentUser | Current user + workspace context |

### `webhooks/agentphone.py` — `/webhooks/agentphone`

| Method | Path | Body | Response | Auth | Purpose |
|---|---|---|---|---|---|
| POST | `/webhooks/agentphone` | raw (HMAC) | 200 OK OR `StreamingResponse` NDJSON (voice turns) | HMAC + replay window + dedupe | AP webhook dispatch: voice turns stream; SMS, call_ended, reactions sync-process |

Sequence: HMAC verify → replay-window check → Redis dedupe by
`X-Webhook-ID` → `adapter.parse_webhook` → `materialize_scope_and_call`
→ dispatcher (voice / sms / call_ended / reaction).

### `webhooks/agentmail.py` — `/integrations/agentmail/webhook`

| Method | Path | Body | Response | Auth | Purpose |
|---|---|---|---|---|---|
| POST | `/integrations/agentmail/webhook` | raw (no signature verification per LLD speed variant) | 200 | Public | Inbound email replies — route to `email_reply_handler` (CorrectionIntake for manager, IntakeBufferItem for rep) |

### `workspaces/intake.py` — `/workspaces/{ws}/intake/*`

| Method | Path | Body / Query | Response | Auth | Purpose |
|---|---|---|---|---|---|
| POST | `/intake/text` | `{text, purpose}` | `IntakeUploadResponse` | require_workspace_access | Submit text for classification + handler ingest |
| POST | `/intake/upload` | multipart `{file, purpose}` | `IntakeUploadResponse` | require_workspace_access | Upload PDF/DOCX/XLSX/CSV/JSON/text; SHA256 dedupe |
| GET | `/intake/items` | `?purpose=&limit=&offset=` | `IntakeListResponse` | require_workspace_access | List intake items, filtered by purpose |
| GET | `/intake/items/{id}` | — | `IntakeItemSummary` | require_workspace_access | Single item with classification + handler_result |
| GET | `/intake/items/{id}/download` | — | 302 redirect (signed URL) | require_workspace_access | Download original blob |
| POST | `/intake/items/{id}/supersede` | `{new_item_id}` | 204 | require_workspace_access | Mark older version superseded |
| DELETE | `/intake/items/{id}` | `?force=` | 204 | require_workspace_access | Soft delete |
| POST | `/intake/items/{id}/process` | — | `IntakeItemSummary` | require_workspace_access | Trigger / retry processing |
| GET | `/intake/review` | — | `IntakeReviewResponse` | require_workspace_access | Manager triage view (needs_review items) |

### `workspaces/decisions.py` — `/workspaces/{ws}/decisions/*`

| Method | Path | Body / Query | Response | Auth | Purpose |
|---|---|---|---|---|---|
| GET | `/decisions` | `?status=&limit=&offset=` | `DecisionListResponse` | require_workspace_access | List decisions for this workspace |
| GET | `/decisions/{id}` | — | `DecisionSummary` | require_workspace_access | Single decision detail |
| POST | `/decisions/{id}/respond` | `{response, via}` | `DecisionSummary` | require_workspace_access | First-responder-wins; SELECT FOR UPDATE |
| POST | `/decisions/{id}/resolve_now` | `{option}` | `{decision_id, status, response, responded_at, auto_approved_action_items}` | require_workspace_access | Force-resolve a timed-out decision; auto-approve gated action items |

### `workspaces/calls.py` — `/workspaces/{ws}/calls/*` (Phase 1 F1)

| Method | Path | Body / Query | Response | Auth | Purpose |
|---|---|---|---|---|---|
| GET | `/calls` | `?status=&limit=&offset=` | `CallListResponse` | require_workspace_access | List calls |
| GET | `/calls/{id}` | — | `CallSummary` | require_workspace_access | Call metadata + status |
| GET | `/calls/{id}/transcript` | — | `CallTranscriptResponse` (fragments) | require_workspace_access | Full transcript |
| GET | `/calls/{id}/summary` | — | canonical summary JSON | require_workspace_access | AI-generated summary from post-call worker |
| POST | `/calls/{id}/whisper` | `{guidance}` | `WhisperResponse(intervention_id)` | require_workspace_access | F7 manager intervention — guidance is appended to next turn's prompt as `manager_whispers` |
| GET | `/calls/{id}/recording` | — | 302 redirect (signed S3 URL) | require_workspace_access | Download call recording if ready |
| WS | `/calls/{id}/replay` | (upgrade) | streaming `transcript_fragment` + `replay_done` frames | Public (workspace_id in path) | Real-time playback of historical transcript |
| GET | `/calls/{id}/interventions` | — | `InterventionListResponse` | require_workspace_access | List all whispers for this call |

### `workspaces/brain.py` — `/workspaces/{ws}/brain/*`

| Method | Path | Body | Response | Auth | Purpose |
|---|---|---|---|---|---|
| GET | `/brain/pages/{slug}` | — | `BrainPageView` | require_workspace_access | Current page snapshot (compiled_truth + timeline + tags + manager_authoritative flag) |
| GET | `/brain/pages/{slug}/versions` | — | `BrainPageVersionsResponse` | require_workspace_access | Full version history |
| POST | `/brain/corrections` | `{target_slug, kind, payload, rationale}` | `BrainPageView | null` | require_workspace_access | Apply correction (`replace_compiled_truth` / `soft_delete_page` / `append_timeline_entry`); marks page `manager_authoritative` |

### `workspaces/action_items.py` — `/workspaces/{ws}/action_items/*` (Phase 1 F3)

| Method | Path | Body / Query | Response | Auth | Purpose |
|---|---|---|---|---|---|
| GET | `/action_items` | `?status=&limit=&offset=` | `ActionItemListResponse` | require_workspace_access | List action items (filter by status: pending_approval, approved, done, failed, etc.) |
| POST | `/action_items/{id}/approve` | — | `ActionItemDTO` | require_workspace_access | Approve → eligible for handler execution (scheduler / email_drafter) |
| POST | `/action_items/{id}/reject` | — | `ActionItemDTO` | require_workspace_access | Reject — handler never runs |
| PATCH | `/action_items/{id}` | `{title?, description?, due_at?, payload?, handler?}` | `ActionItemDTO` | require_workspace_access | Edit fields before approval (e.g. set recipient_email on email handler) |

### `workspaces/dashboards.py` — `/workspaces/{ws}/dashboards/*` (Phase 1 F8)

| Method | Path | Body / Query | Response | Auth | Purpose |
|---|---|---|---|---|---|
| GET | `/dashboards/daily_brief` | `?date=YYYY-MM-DD` | `DailyBriefResponse` (subject_line + 5 sections) | require_workspace_access | Daily brief for date (default: yesterday) |
| GET | `/dashboards/overview` | — | `OverviewResponse` (live KPIs from app DB) | require_workspace_access | Today's live stats |
| GET | `/dashboards/reps` | `?range=30d` | `SnapshotListResponse` | require_workspace_access | Rep dimension trend |
| GET | `/dashboards/accounts` | `?range=` | `SnapshotListResponse` | require_workspace_access | Account movement trend |
| GET | `/dashboards/themes` | `?range=` | `SnapshotListResponse` | require_workspace_access | Top themes trend |
| GET | `/dashboards/decisions` | `?range=` | `SnapshotListResponse` | require_workspace_access | Missed-decisions trend |
| GET | `/dashboards/queries` | — | `SavedQueryListResponse` | require_workspace_access | List saved queries (max 10 per user) |
| POST | `/dashboards/queries` | `{name, dimension, filters, pinned}` | `SavedQueryResponse` | require_workspace_access | Save a query |
| GET | `/dashboards/queries/{id}` | — | `SavedQueryResponse` | require_workspace_access | Single saved query |
| DELETE | `/dashboards/queries/{id}` | — | 204 | require_workspace_access | Delete saved query |

### `workspaces/email.py` — `/workspaces/{ws}/email/*` (Phase 1 F6)

| Method | Path | Body / Query | Response | Auth | Purpose |
|---|---|---|---|---|---|
| GET | `/email/messages` | `?limit=&offset=` | `EmailMessageListResponse` | require_workspace_access | Email audit trail (outbound + inbound replies) |

### `workspaces/verifications.py` — `/workspaces/{ws}/calls/{id}/verifications` etc. (Phase 1 F5)

| Method | Path | Body | Response | Auth | Purpose |
|---|---|---|---|---|---|
| GET | `/calls/{id}/verifications` | — | `ClaimVerificationListResponse` | require_workspace_access | Fact-checks for claims in this call |
| GET | `/brain/pages/{slug}/verifications` | — | `ClaimVerificationListResponse` | require_workspace_access | Fact-checks referencing this brain page |

### `workspaces/integrations.py` — `/workspaces/{ws}/integrations/*` (Phase 1 F9, dormant)

| Method | Path | Body / Query | Response | Auth | Purpose |
|---|---|---|---|---|---|
| GET | `/integrations/google/auth_url` | — | `{auth_url}` OR **503** | require_workspace_access | Build Google OAuth URL — returns 503 when Google is dormant |
| GET | `/integrations/google/callback` | `?code=&state=` | `{status, integration}` OR **503** | require_workspace_access | OAuth callback — same 503 behavior |
| GET | `/integrations` | — | `{integrations: [...]}` | require_workspace_access | List connected integrations (returns `[]` when none) |
| DELETE | `/integrations/{id}` | — | 204 | require_workspace_access | Disconnect / revoke |

### `workspaces/ws.py` — `/workspaces/{ws}/ws/*`

| Method | Path | Body / Query | Response | Auth | Purpose |
|---|---|---|---|---|---|
| POST | `/ws/token` | — | `WSTokenResponse(token, ttl_seconds=30)` | require_workspace_access | Mint one-time WS token (30s TTL, GET-then-DEL via Redis) |
| WS | `/ws/live` | `?token=` | live frame stream | Token (query) | Multi-call WebSocket bus — see frames table below |

### WS frame catalog (`app/schemas/ws_frames.py`)

Emitted on `/ws/live`. FE multiplexes by `type` field.

| Frame `type` | Emitted by | Payload |
|---|---|---|
| `snapshot` | Server on WS connect | `calls: [CallStartedFrame]` — in-progress calls at join time |
| `call.started` | call materialization (first voice/SMS event) | `call_id, field_employee_id, started_at` |
| `transcript.fragment` | each speaker turn (caller + agent) | `call_id, speaker (caller|agent), text, seq, ts` |
| `decision.opened` | `request_manager_decision` tool fires | `call_id, decision_id, prompt, options, decision_class, timeout_at` |
| `decision.resolved` | decision answered OR timed-out | `call_id, decision_id, response, responded_via (websocket|sms|timeout)` |
| `call.ended` | AP `agent.call_ended` webhook | `call_id, ended_at` |
| `call.summary_ready` | post_call_job completes | `call_id, has_summary, brain_pages_touched: [str]` — FE re-fetches summary |
| `ping` | server heartbeat | `ts` |

---

## LLM-facing surface — Skills + Orchestrator tools

### Skills

Each Skill is a directory under `skills/<name>/` with SKILL.md frontmatter
(name, version, model, prompt, trigger, quality_bar), a Jinja prompt
template, a Pydantic Input/Output schema in `schema.py`, fixtures, and an
eval harness. The loader walks the directory at boot and registers each
into `SkillRegistry`. **Skills are static** — they don't self-improve at
runtime; context evolution drives behavior.

| Skill | Trigger | Default model | Input (key fields) | Output (key fields) |
|---|---|---|---|---|
| `classifier` | `intake_buffer_item_added` | Haiku | `workspace_name, content, source, roster, known_accounts` | `scope (ORG_WIDE/CALLER_SPECIFIC/BOTH/RAW_SOURCE), kind, target_caller_id?, suggested_slug?, extracted_entities[], confidence, reasoning` |
| `orchestrator` | `voice_turn` | Haiku/Sonnet | `caller, rep_utterance, conversation_history, caller_hits, brain_hits, manager_whispers, decision_updates` | streamed text (with optional `<<TOOL …>>` markers at end) |
| `summarizer` (v0.2) | `call_ended` | Sonnet | `transcript, caller, started_at, brain_context, provider_summary?` | `discussion, blockers, extracted_entities[], verbatim_quotes[≤10], topics[≤15]` |
| `web_verifier` (F5) | `post_call_fanout` | Sonnet | `claim, evidence_url?, evidence_text?, fetch_ok` | `status (corroborated/unconfirmed/contradicted), confidence, evidence_snippet?, contradiction_detail?, reasoning` |
| `dashboard_rollup_writer` (F8) | `dashboard_rollup` | Sonnet | `call_count, top_topics, urgent_flags, missed_decisions[], account_movement[], reps_in_motion[], stub_escalations[]` | `subject_line, sections{yesterday_at_a_glance, decisions_you_missed, account_movement, reps_in_motion, stub_to_real_escalations}` |

### Orchestrator tools

Mid-stream tool calls — the LLM emits `<<TOOL name {json_args}>>` at the
end of its spoken text; `scan_for_tool_calls` parses + dispatches via
`ToolRegistry.dispatch()`.

| Tool | Marker args | Bridge text | end_turn | hangup | Side effects |
|---|---|---|---|---|---|
| `request_manager_decision` | `{prompt, options[], decision_class (inline/bridged/async), rationale?}` | inline: "Let me check with leadership real quick…" / bridged: "I'll run that by leadership…" / async: "Got it, I'll flag that…" | True for inline/bridged; False for async | False | Creates `DecisionRequest` row; publishes `decision.opened` frame; SMSes Manager via `[DR-XXXXXX]` prefix; schedules `decision_timeout_job` (45s inline / 120s bridged / none for async) |
| `request_correction` | `{slug, kind (replace_compiled_truth/append_timeline_entry), text, title?, rationale?}` | success: "Got it, I've updated that…" / NotFound: "I don't have a page called '{slug}' yet…" | False on success; True on error | False | `CorrectionService.apply()` — page becomes `manager_authoritative=True` for replace; cascade enqueued |
| `end_call` | `{reason}` | "Thanks - I've got what I need. Talk soon." | True | True (orchestrator emits hangup_chunk to AP) | AP drops the line |

### Voice turn flow (`app/orchestrator/turn_loop.py`)

```
1. Load call + workspace + FE; persist caller TranscriptFragment
2. Speculative retrieval race (150ms deadline):
   • prewarmed snapshot from Redis (~1ms read; 30min TTL)
   • fresh: Retriever.for_turn(caller, query) — caller memory single-tag + brain hybrid in parallel
   • fresh wins → use it; loses → emit BRIDGE_PHRASES chunk + use prewarmed fallback; cache fresh result for next turn
3. Drain decision_updates (answered / timed_out) from session.pending_decisions
4. Drain manager_whispers from Redis whispers:{call_id} list
5. render_messages(workspace, fe, session, context, rep_utterance, decision_updates) → [system, user]
6. llm.stream_chat() → scan_for_tool_calls():
   • text → spoken_parts + yield to NDJSON wrapper
   • tool_call → ToolRegistry.dispatch(ctx, name, args) → ToolResult
   • bridge_text → yield; end_turn → close; hangup → emit hangup_chunk
7. token_stream_to_ndjson (first flush 1 char, subsequent 12 chars) → bytes
8. Persist agent TranscriptFragment; append both turns to session.conversation_history (cap 40); save session via Redis CAS
```

### SMS turn flow (`app/orchestrator/sms_orchestrator.py`)

Two-path dispatch:
1. **Decision response** — body starts with `[DR-` → `_handle_decision_response()` (matches Manager SMS replies to open decisions)
2. **Conversational** — full retrieval (no race, no bridge), non-streaming LLM call, only `request_manager_decision` tool in scope, reply truncated to 1400 chars, persists fragments, sends via `AgentPhoneAdapter.send_sms(agent_id, to_number, body)`

### Prewarm (`app/orchestrator/prewarm.py`)

On first voice webhook for a call: `schedule_prewarm()` fires a background
task that warms the caller profile (Supermemory) + broad brain snapshot
(`hybrid_search(query="*", k=20)`) and stashes to Redis at
`prewarm:call:{call_id}` (30min TTL). Every turn reads this before
racing fresh retrieval against the 150ms deadline. Fresh result is
re-stashed after each turn (self-warming cache).

---

## Background workers + mini-agents

### arq worker registry (`app/workers/settings.py`)

Single process runs all queues. Start with `make worker` (=
`arq app.workers.settings.WorkerSettings`).

**On-demand jobs:**
- `post_call_job` — fanout after `agent.call_ended`
- `decision_timeout_job` — fires when an open decision expires
- `correction_cascade_job` — log + reserved hooks for cache invalidation
- `action_item_dispatcher_job` — per-workspace handler dispatch
- `dashboard_rollup_job` — per-workspace daily brief
- `email_delivery_job` — outbound email

**Cron jobs (Phase 1):**
- `dashboard_rollup_dispatcher_job` — daily 07:00 UTC, fans out per-workspace
- `action_item_dispatcher_cron` — every minute, fans out per-workspace

Each on-demand job has an **inline-mode toggle** env var
(`POST_CALL_INLINE`, `DECISION_TIMEOUT_INLINE`,
`CORRECTION_CASCADE_INLINE`, `DASHBOARD_ROLLUP_INLINE`) for tests that
bypass Redis.

### `post_call.py` — post-call fan-out

1. Load Call + transcript + FieldEmployee
2. Run summarizer skill → `SummarizerOutput`
3. Save artifact `calls/{call_id}/canonical_summary.json` to object store + `CallArtifact` row
4. **PARALLEL** (isolated failure domains):
   - `run_brain_updater` — upsert pages / append timeline / apply web-verifier trust tags
   - `write_call_to_caller_memory` — Supermemory digest under `[caller_X, workspace_W]`
   - `web_verifier_fanout` — verify claims (current claim list empty; F5 plumbing in place)
   - `extract_action_item_candidates` + `save_action_items` — inline, not async
5. Publish `call.summary_ready` frame with `brain_pages_touched`
6. Enqueue `email_delivery_job` for opted-in Manager + Rep recipients

### `decision_timeout.py`

When `DecisionService.open()` creates a row with `timeout_at`, schedules
`dt:{decision_id}` deferred job. On fire: SELECT FOR UPDATE → if still
`open`, mark `timed_out` + publish `decision.resolved` frame
(via=timeout). Orchestrator picks it up on next turn via
`session.pending_decisions` → renders "couldn't reach leadership" cue.

### `correction_cascade.py`

Phase 0 minimum — logs the correction event. Phase 1 hooks reserved for
caller-profile denormalization, retrieval-cache invalidation, embedding
recompute.

### `action_item_dispatcher.py` (Phase 1 F3)

Cron fan-out → per-workspace job → query
`ActionItem(status=approved, handler != none)` (limit 50) → call the
matching handler:

- `handler="scheduler"` → `SchedulerMiniAgent.execute()` → Google Calendar event (or draft if Google dormant)
- `handler="email_drafter"` → `EmailDrafterMiniAgent.execute()` → Gmail send (or draft if Google dormant)

Outcome JSON + error + attempt count persisted back to row. Status
transitions: `approved` → `done` / `failed` / `needs_reconnect` (OAuth
revoked) / retry (`approved` again until `MAX_HANDLER_ATTEMPTS=3`).

### `dashboard_rollup.py` (Phase 1 F8)

Cron @ 07:00 UTC → enumerate workspaces → enqueue one
`dashboard_rollup_job` per workspace for yesterday. Per-workspace job
calls `run_dashboard_rollup` mini-agent (see below).

### `email_delivery.py` (Phase 1 F6)

Thin shim calling `run(EmailDeliveryInput)` mini-agent.

### Mini-agents (`app/miniagents/`)

| Mini-agent | Input → Output | Side effects |
|---|---|---|
| `summarizer_agent.run_summarizer` | `SummarizerInput(transcript, caller, brain_context)` → `SummarizerOutput(discussion, blockers, entities, quotes, topics)` | None (caller persists the artifact) |
| `brain_updater.run_brain_updater` | `BrainUpdateInput(summary, verdicts?)` → `BrainUpdateResult(pages_upserted, timeline_appends, needs_review, tags_applied)` | Brain page upserts / timeline appends; provenance row; trust tag application; `ManagerAuthoritativeConflict` → needs_review |
| `caller_memory_writer.write_call_to_caller_memory` | call + FE + transcript + summary | Supermemory `add()` with `[caller_X, workspace_W]` tags |
| `email_drafter.EmailDrafterMiniAgent.execute` (F3) | `EmailDrafterContext` + `ActionItem` → `{message_id, thread_id, draft, sent_to, error?}` | Render `email_drafter_message.j2`; Gmail send via `GoogleWorkspaceConnector.gmail_send()` (skipped if Google dormant) |
| `email_delivery.run` (F6) | `EmailDeliveryInput(workspace_id, trigger_kind, trigger_ref_id, recipient, delivery_route, precomposed?)` → `EmailDeliveryResult(skipped?, reason?)` | Compose (or use precomposed) → send via AgentMail or OAuth personal Gmail → persist `EmailMessage` audit row with `correlation_idempotency_key` |
| `email_reply_handler.handle_event` (F6) | `AgentMailEvent` | Routes by sender: Manager → `CorrectionIntake` (origin=`manager_email_reply`); FE → `IntakeBufferItem` (source=`rep_email_followup`); else drop |
| `scheduler.SchedulerMiniAgent.execute` (F3) | `SchedulerContext` + `ActionItem` → `{provider_event_id, calendar_id, event_html_link, draft, error?}` | Render `scheduler_event.j2`; create Calendar event (skipped if Google dormant) |
| `web_verifier.web_verifier_fanout` (F5) | `(workspace_id, call_id, claims[])` → `[VerificationVerdict]` | Per-claim: freshness reuse → URL planning → fetch via `BrowserSession` → `web_verifier` skill adjudicates → `ClaimVerification` row + `CorrectionIntake` (if contradicted) |
| `dashboard_rollup.run_dashboard_rollup` (F8) | `DashboardRollupInput(workspace_id, brief_date)` → `DashboardRollupResult(brief_artifact_id, snapshots_written)` | `compute_aggregate` → render via `dashboard_rollup_writer` skill (fallback to skeleton) → write brief artifact JSON to object store → `write_snapshots` (per-dimension rows) → stamp overview metadata → `mark_decisions_surfaced` → enqueue `email_delivery_job` if opted in |

---

## Services layer

### `auth_service.py` — `AuthService`

| Method | Purpose |
|---|---|
| `login(email, password)` | Hash-verify password, issue access + refresh JWT pair |
| `refresh(refresh_token_str)` | Rotate token chain; revoke consumed; **commit** before returning (otherwise `app_session()` rolls back the revoke); reuse → revoke whole chain |
| `logout(refresh_token_str)` | Revoke token; commit (same reason) |
| `_issue_pair(user, parent_jti?)` | Generate access + refresh JWT; record refresh row with jti + expiry |

Module-level helper: `ensure_email_available(session, email)` raises
`Conflict` if email taken.

### `workspace_provisioning.py` — `WorkspaceProvisioningService`

| Method | Purpose |
|---|---|
| `signup(email, password, workspace_name)` | Create Org + Workspace + User in one transaction → then `_provision_externals(ws)` (best-effort, doesn't roll back DB) |
| `_provision_externals(ws)` | AP `provision_number()` → brain `ensure_schema()` → memory `ensure_namespace()` → AgentMail `provision_workspace_inbox()`; state transitions `pending` → `number_pending` → `ready` |

### Intake services

- **`intake_processor.py:IntakeProcessor`** — `submit_text`, `submit_upload`, `get`, `list`, `download_url`, `supersede`, `soft_delete`. Dedup by SHA256 on upload. Max upload 25 MB.
- **`intake_processing.py:process_intake_item(item_id, session, storage)`** — extract → classify (skill) → confidence gate (0.7) → resolve handler → ingest. Idempotent.
- **`intake_extractors/`** — 6 concrete extractors (`pdf`, `docx`, `xlsx`, `csv`, `json`, `text`) registered into `_ExtractorRegistry`; resolve by MIME → extension fallback; raises `UnsupportedFormat` otherwise. Each returns `ExtractedContent(text, rows, tables, metadata, warnings)`.
- **`intake_handlers.py`** — 4 scope-typed handlers:
  - `OrgBrainHandler` (`ORG_WIDE`) — upsert brain page (account/product/playbook/theme/org_positioning)
  - `CallerBrainHandler` (`CALLER_SPECIFIC`) — provenance only in Phase 0 (Supermemory write lands Phase 1)
  - `CrossRefHandler` (`BOTH`) — delegates to org handler; directed BrainEdge in Phase 1
  - `RawSourceHandler` (`RAW_SOURCE`) — one page per extracted entity (capped 25)

  `ManagerAuthoritativeConflict` → append timeline entry instead, flag `needs_review`.

### `decisions.py` — `DecisionService`

| Method | Purpose |
|---|---|
| `open(call_id, workspace_id, prompt, options, decision_class, context?, manager_phone?, agentphone_agent_id?)` | Create `DecisionRequest`; publish `decision.opened`; SMS Manager `[DR-XXXXXX] <prompt>`; schedule timeout (45s inline / 120s bridged / none async) |
| `respond(decision_id, responder_user_id, response, via)` | SELECT FOR UPDATE → mark answered → publish `decision.resolved`; raises `Conflict` if already resolved |
| `match_sms_response(body, manager_user_id)` | Parse `[DR-XXXXXX] <option>` from inbound SMS → call `respond()` |

### `corrections.py` — `CorrectionService`

| `kind` | Effect | Manager-authoritative guard |
|---|---|---|
| `REPLACE_COMPILED_TRUTH` | Upsert page; mark `manager_authoritative=True`; new version on chain | Sets the flag; future auto-extractors can't silently overwrite |
| `SOFT_DELETE_PAGE` | Append delete audit timeline → `brain.soft_delete_page()` | — |
| `APPEND_TIMELINE_ENTRY` | Timeline append only; no version bump | — |

Provenance row created BEFORE applying. `correction_cascade` job
enqueued for replace/delete.

### `correction_intake.py` — `open_correction_intake(...)`

Opens a `CorrectionIntake` row for Manager review before
`CorrectionService.apply()` runs. Origins: `system_web_verifier` (F5
contradiction), `manager_email_reply` (F6 inbound).

### `action_items/`

- **`heuristic_extractor.py:extract_action_item_candidates(blockers, transcript_turns)`** — regex heuristics on transcript turns + blocker text. Confidence 0.6 (blockers) / 0.7 (transcript). Inferred handler from `scheduler` / `email` hints.
- **`save.py:save_action_items(session, call, candidates)`** — persists each as `ActionItem(status="pending_approval")`.

### `dashboards/aggregator.py` (F8)

Per-day aggregation queries:
- **`compute_aggregate(session, workspace_id, brief_date)`** — read-only roll-up across `Call`, `DecisionRequest`, `FieldEmployee`, `ManagerWorkspace` → returns dict for skill input
- **`write_snapshots(session, agg, computed_at)`** — one `DashboardSnapshot` row per dimension (overview, rep, account, theme, decision)
- **`mark_decisions_surfaced(session, decision_ids, at)`** — sets `surfaced_in_brief_at` so each missed decision appears in only one brief

### `web_verifier/browser_client.py` (F5)

`browser_session(name, timeout_ms)` context manager →
`BrowserSession.fetch_page(url)` returns `PageFetchResult(ok, url, text,
error)`. httpx + regex HTML strip; text capped at 20k chars.
`BROWSER_USE_API_KEY` is detected but the real SDK isn't wired yet.

---

## Database models + migrations

### Models (`app/db/models/`) — Phase 0

| Model file | Table | Purpose |
|---|---|---|
| `organization.py` | `organizations` | Top-level container; auto-created at Manager signup |
| `user.py` | `users` | Auth principal; role ∈ (`manager`, `org_admin`, `rep`, `viewer`); `field_employee_id` reverse-links to roster |
| `workspace.py` | `manager_workspaces` | Isolation unit. Columns: `primary_number` (UNIQUE), `agentphone_agent_id/_number_id`, `provisioning_state`, plus Phase 1 `email_inbox_id/_addr`, `email_domain` |
| `refresh_token.py` | `refresh_tokens` | JWT rotation chain. `jti` (UNIQUE), `parent_jti` (indexed), `revoked_at`, `revoked_reason`. Powers reuse detection |
| `intake.py` | `intake_buffer_items` | Manager intake pipeline. `source ∈ (form, upload, voice_intake, correction, rep_email_followup)`; `status` lifecycle |
| `field_employee.py` | `field_employees` | Rep roster. `(workspace_id, phone)` UNIQUE; `profiled` bool; `profile` JSONB |
| `call.py` | `calls` | Phone-call lifecycle. `agentphone_call_id` UNIQUE; `status ∈ (ringing, in_progress, ended, failed)` |
| `transcript.py` | `transcript_fragments` | One row per speaker turn. `seq` monotonic per call; `UNIQUE(call_id, seq)` |
| `decision.py` | `decision_requests` | Mid-call decision asks. `decision_class ∈ (inline, bridged, async)`; `status ∈ (open, answered, answered_late, timed_out, cancelled)`; `surfaced_in_brief_at` for F8 dedupe |
| `provenance.py` | `provenance` | Audit row attached to every brain write. `source_type ∈ (manager_form, …, manager_correction, field_call, automated_extraction, external_research, system_seed)` |
| `call_artifact.py` | `call_artifacts` | Metadata for blobs in object store. `kind ∈ (canonical_summary, transcript, recording, provider_summary, action_items_export, action_item_handler_outcome, daily_brief)` |

### Models added in Phase 1 (migration 0010)

| Model file | Table | Purpose |
|---|---|---|
| `correction_intake.py` | `correction_intakes` | Pre-correction queue. `origin ∈ (manager, rep_callback, system_web_verifier, manager_email_reply)`; `status ∈ (open, applied, rejected, dismissed)` |
| `action_item.py` | `action_items` | F3 tasks. `status ∈ (pending_approval, needs_review, approved, done, failed, needs_reconnect, rejected)`; `handler ∈ (scheduler, email_drafter, none)` |
| `manager_intervention.py` | `manager_interventions` | F7 whisper records. `mode ∈ (whisper)`; `started_at, ended_at, payload` |
| `claim_verification.py` | `claim_verifications` | F5 fact-checks. `status ∈ (corroborated, unconfirmed, contradicted)`; FK to `correction_intakes` when contradicted |
| `email_message.py` | `email_messages` | F6 audit. `provider ∈ (agentmail, oauth_personal)`; `trigger_kind ∈ (post_call_summary, daily_brief, missed_decisions, action_item_handler)`; `correlation_idempotency_key` UNIQUE |
| `oauth_credentials.py` | `workspace_oauth_credentials` | F9 OAuth tokens. `provider ∈ (google_workspace)`; refresh + access tokens plaintext (per LLD speed variant) |
| `dashboard.py` | `dashboard_snapshots` | F8 metrics rollup. `dimension ∈ (overview, rep, account, theme, decision)`; opaque JSONB `metrics`; composite index `(workspace_id, snapshot_date, dimension)` |
| `dashboard.py` | `saved_dashboard_queries` | F8 pinned filters (max 10/user) |

### Repositories (`app/db/repositories/`)

| Repo | Notable methods |
|---|---|
| `users_repo.py` | `get_by_id`, `get_by_email`, `create` |
| `workspaces_repo.py` | `create`, `get_by_id`, `get_by_primary_number`, `get_by_agentphone_agent_id`, `get_by_agentphone_number_id`, `update_provisioning`, `get_manager_email`, `get_by_email_inbox_id`, `update_email_inbox` |
| `field_employees_repo.py` | `get`, `find_by_phone`, `get_by_email`, `create_unprofiled` |
| `refresh_tokens_repo.py` | `record`, `get_by_jti`, `revoke`, `revoke_user_chain` |
| `intake_repo.py` | `find_by_sha`, `create`, `get`, `list_for_workspace`, `update_status`, `mark_superseded`, `soft_delete` |
| `calls_repo.py` | `get`, `get_by_agentphone_id`, `list_in_progress`, `list_for_workspace`, `create`, `mark_ended` |
| `transcripts_repo.py` | `append`, `list_for_call` |
| `decisions_repo.py` | `get`, `lock_for_update`, `create`, `mark_answered`, `mark_timed_out`, `list_for_workspace`, `list_open_for_user`, `list_missed_for_brief`, `mark_surfaced_in_brief` |
| `provenance_repo.py` | `create`, `get` |
| `call_artifacts_repo.py` | `create`, `get_by_kind`, `list_for_call` |
| `action_items_repo.py` | `create`, `get`, `list_for_workspace`, `update_status`, `update_handler_outcome`, `list_approved_with_handler` |
| `manager_interventions_repo.py` | `create`, `get`, `list_for_call`, `mark_consumed` |
| `claim_verifications_repo.py` | `create`, `list_for_call`, `list_for_claim_subject`, `find_existing_corroborated` (freshness reuse) |
| `email_messages_repo.py` | `create`, `exists_by_idem`, `find_by_provider_message_ids`, `list_for_workspace` |
| `oauth_credentials_repo.py` | `create`, `get`, `get_for_workspace`, `get_active`, `list_all_for_workspace`, `update_tokens`, `mark_revoked`, `to_public` |
| `dashboards_repo.py` | `bulk_create`, `list_for_range`, `get_for_date` (snapshots); `create`, `list_for_workspace`, `delete`, `count_pinned` (saved queries) |

### Sessions

- **`app/db/app_session.py`** — `app_session()` async context manager around `_factory()()`; engine cached via `@lru_cache`; `pool_pre_ping=True`
- **`app/db/brain_session.py`** — `brain_session(workspace_id)` pins `search_path` to `brain_w_{workspace_id.hex}` via `SET LOCAL search_path` — workspace isolation enforced at session init

### Migration revisions

**App DB (`versions_app/`):**
1. `0001_initial` — orgs, manager_workspaces, users
2. `0002_refresh_tokens` — rotation chain + reuse detection
3. `0003_intake_buffer_items` — intake pipeline (FK name shortened to fit 63-char limit)
4. `0004_field_employees_and_calls` — Rep roster + Call rows
5. `0005_transcript_fragments` — per-turn rows
6. `0006_decision_requests` — decision lifecycle
7. `0007_provenance` — brain-write audit
8. `0008_call_artifacts` — blob metadata
9. `0009_drop_field_employee_supermemory_user_id` — Supermemory isolation moves to containerTags
10. `0010_phase_1_unified` — 8 new tables (correction_intakes, action_items, manager_interventions, claim_verifications, email_messages, workspace_oauth_credentials, dashboard_snapshots, saved_dashboard_queries) + columns on manager_workspaces (email_inbox_id, _addr, email_domain) + CHECK widening on existing enums

**Brain DB (`versions_brain/`):**
1. `0001_initial_brain` — `CREATE EXTENSION vector` (per-workspace schemas created at runtime by `BrainProvider.ensure_schema()`)

---

## Running the production container locally

`Dockerfile` is a two-stage build (uv → `python:3.12-slim`) producing
one image used for both web + worker (worker overrides CMD).
`docker-compose.yml` wires it up against the same infra stack plus a
one-shot `migrate` service.

```bash
docker compose --env-file .env.local up --build
```

| Service | Image | Purpose |
|---|---|---|
| `postgres` | `pgvector/pgvector:pg16` | hosts both `votf_app` and `votf_brain` |
| `redis` | `redis:7-alpine` | session, pub/sub, arq |
| `minio` + `minio-init` | `minio/minio` + `minio/mc` | S3-compat + auto-bucket |
| `migrate` | `vof-backend:local` | one-shot `alembic upgrade head` for both DBs |
| `web` | `vof-backend:local` | uvicorn :8000, `/health` |
| `worker` | `vof-backend:local` | `arq app.workers.settings.WorkerSettings` |

Image contains: `/app/.venv` (resolved from `uv.lock`, no dev deps),
`app/`, `skills/`, `scripts/`, both alembic configs. **Not in image:**
`tests/`, `smoke/`, `hld/`, `lld/`. Runs as non-root `votf` (UID 1000)
with `HEALTHCHECK` on `/health`.

### Environment contract (production)

Required:

| Var | Notes |
|---|---|
| `DATABASE_URL`, `BRAIN_DATABASE_URL` | `postgresql+asyncpg://…` |
| `REDIS_URL` | shared by session, pub/sub, arq |
| `S3_BUCKET`, `S3_ACCESS_KEY`, `S3_SECRET_KEY`, `S3_REGION` | omit `S3_ENDPOINT_URL` for AWS S3 |
| `JWT_SECRET` | ≥32 bytes, rotate per environment |
| `LLM_PROVIDER` + provider-specific keys | see § LLM provider |
| `AGENTPHONE_API_KEY`, `AGENTPHONE_WEBHOOK_SECRET` | empty → `FakeTelephonyProvider` |
| `SUPERMEMORY_API_KEY` | empty → `StubCallerMemoryProvider` |
| `AGENTMAIL_API_KEY` | **optional** — empty disables F6 |
| `BROWSER_USE_API_KEY` | **optional** — F5 falls back to httpx |
| `EMAIL_DOMAIN` | optional custom email domain |
| `DEPLOYMENT_PROFILE` | `cloud` for prod, `local` for dev with MinIO |

---

## Smoke tests — per-integration verification

7 probes (`smoke/`). Each is fully independent (no cross-probe imports,
no shared state, UUID-namespaced scratch resources).

| Probe | Verifies |
|---|---|
| `postgres_app` | connect, transaction isolation, CRUD round-trip |
| `postgres_brain` | connect, pgvector + tsvector, schema-per-Workspace lifecycle, vector + tsvector round-trip |
| `redis` | connect, set/get, pub/sub round-trip, dedupe-set + TTL |
| `object_storage` | bucket reachable, PUT/GET/DELETE, signed-URL, prefix isolation |
| `llm` | auth, basic completion, **streaming**, **JSON mode**, **tool calls** — branches between OpenAI-compat (HTTP) and Bedrock (`boto3.invoke_model`) on `LLM_PROVIDER` |
| `supermemory` | auth, write/search/profile, **per-caller isolation** via single-tag search, OR-semantic tripwire, indexing-lag-aware (30s polling window) |
| `agentphone` | auth, master webhook, **HMAC round-trip through prod verifier**, test webhook delivery, outbound SMS, `PATCH /conversations/{id}` metadata round-trip |

> Phase 1 third-parties (AgentMail, Browser Use) don't have smoke
> probes yet — they're optional and the production code degrades
> cleanly when empty.

### Modes + exit codes

| Mode | Flag | What | Cost |
|---|---|---|---|
| Check (default) | `--mode check` | auth + connectivity | free/cents |
| Smoke | `--mode smoke` | every feature | $0.05–0.20 + 1 SMS |
| Repair | `--mode repair` | smoke + verbose diagnostics | same |

| Exit | Meaning |
|---|---|
| 0 | PASS |
| 1 | FAIL (config/contract broken) |
| 2 | CONFIG (env vars missing) |
| 3 | UPSTREAM (third-party down) |

```bash
make smoke         # cheap connectivity, ~2s
make smoke-full    # exercise every feature, ~30s
make smoke-repair PROBE=postgres_brain   # verbose diagnostics for one

# Single probe directly
uv run python -m smoke.<name> --mode {check|smoke|repair}
```

stdout: one JSON line per probe (machine-readable). stderr: colorized
`[PASS]`/`[FAIL]`/`[CONFIG]`/`[UPSTREAM]` + `fix:` hints. Secrets
redacted (any var ending `_KEY/_SECRET/_PASSWORD/_TOKEN`).

---

## Unit + integration tests

### Unit (`tests/unit/`, 173 tests)

```bash
make test
```

Fast, no external services. Safe env defaults in `tests/conftest.py`;
`app_client` fixture uses httpx `ASGITransport`; provider overrides via
`app.dependency_overrides` or `set_llm_client()`.

Covers: JWT/hashing/HMAC, LLM clients (OpenAI-compat SSE + Bedrock
body shape + factory branching), **client-caching contracts** (every
adapter returns same `_get_client()` instance), streaming + tool
dispatch, skill loader, memory + container tags (**single-tag
retrieval**), post-call writeback, webhook endpoint, decisions,
corrections, WS frames, intake handlers (all 6 extractors), AgentPhone
adapter, settings + models.

### Integration (`tests/integration/`, 5 files)

```bash
make compose-up && make migrate
set -a && source .env.local && set +a
make integration
```

Autouse fixture per test: truncate every non-Alembic table + clear
SQLAlchemy engine cache (so each test gets an engine bound to its own
pytest-asyncio event loop). If Postgres unreachable → suite is skipped,
not failed.

| File | Covers |
|---|---|
| `test_migrations.py` | Alembic up/down/up cycle; leaves schema at head |
| `test_signup_and_auth.py` | signup → login → /me → refresh (rotation) → logout (revocation) |
| `test_hierarchy_guard.py` | Workspace / FieldEmployee / Manager scope enforcement |
| `test_ws_live.py` | multi-call WS bus: connect, auth, publish, drop |
| `test_onboarding_and_intake.py` | end-to-end onboarding via real services: signup → workspace re-stamp → rep added → sales/car intake ingested |

### Session finalizer — `_reseed_for_live_calls`

After every per-test truncate completes, `tests/integration/conftest.py`
re-runs the production onboarding flow. Net effect after `make
integration`:

- Organization (`VotF`) + Manager (`manager@votf-prod.com`)
- Workspace at `primary_number = +14783304859`
- FieldEmployee at `+17653506634`
- Sales/car onboarding intake item (`status = ingested`)

So you can dial `+14783304859` immediately after a test run. The
finalizer disposes the engine cache before its `asyncio.run()` so
pytest-asyncio's stale connections don't pollute the seed.

---

## Seeding a Workspace into the DB

`scripts/seed_test_workspace.py` writes the minimum rows for an inbound
call to route through the orchestrator.

**Workspace-only (production-style — many callers):**
```bash
uv run python -m scripts.seed_test_workspace \
  --ap-number +14783304859 \
  --org-name "Acme Corp" \
  --workspace-name "Acme Manager Workspace" \
  --manager-email "manager@acme.example.com"
```

Dispatcher auto-creates an unprofiled `FieldEmployee` for each new
caller phone on first inbound voice turn.

**Workspace + one known caller:**
```bash
uv run python -m scripts.seed_test_workspace \
  --ap-number +17578314612 \
  --caller-number +17653506634 \
  --ap-agent-id cmpa4o1e005ecjz00n7khhuzm
```

For outbound SMS (decision pings), pass `--ap-agent-id` (the workspace
needs `agentphone_agent_id` set). Idempotent — re-running updates the
existing row.

---

## Live end-to-end testing (real phone call)

1. Real AP account with a **voice-capable** dedicated number (not `shared-imessage`)
2. **Per-agent webhook** registered:
   ```bash
   curl -X POST "https://api.agentphone.ai/v1/agents/$AP_AGENT_ID/webhook" \
     -H "Authorization: Bearer $AGENTPHONE_API_KEY" \
     -H "Content-Type: application/json" \
     -d '{"url":"https://YOUR-NGROK/api/v1/webhooks/agentphone","contextLimit":14,"timeout":30}'
   ```
3. ngrok or Cloudflare Tunnel on :8000
4. Seeded workspace whose `primary_number` matches the AP number
5. LLM provider configured

Dial from any mobile — terminal A (`make run`) logs the webhook, then
orchestrator turn loop + LLM stream.

**Why "unknown number" returns 404 (correct):** when the test or any
caller hits a `data.to` not registered to any workspace,
`materialize_scope_and_call` raises `NotFound("unknown_number")` and
the handler returns 404. Intentional defensive behavior.

---

## Common make targets

| Target | Action |
|---|---|
| `make install` | `uv sync` |
| `make lint` / `make format` / `make type` | ruff + mypy |
| `make test` / `make unit` | unit tests |
| `make integration` | integration tests (needs compose) |
| `make e2e` | e2e tests (full stack + fake AP) |
| `make smoke` / `make smoke-full` | per-integration probes |
| `make smoke-repair PROBE=<name>` | verbose diagnostics for one probe |
| `make verify-hot-path` | end-to-end Rep utterance → LLM → TTS latency check |
| `make skills-eval` | run every `skills/<name>/evals/run.py` |
| `make run` | uvicorn |
| `make worker` | arq |
| `make compose-up` / `compose-down` | start/stop local infra |
| `make migrate` | `alembic upgrade head` on both DBs |

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `CONFIG` exit on a probe | env vars not loaded | `set -a && source .env.local && set +a` |
| `UPSTREAM` on an infra probe | compose stack not running | `make compose-up && docker compose ps` |
| `make migrate` errors `ModuleNotFoundError: psycopg2` | Alembic used wrong dialect | `app/migrations/env.py` uses `+psycopg` (v3) |
| `make migrate` errors `extension "vector" is not available` | postgres image lacks pgvector | compose uses `pgvector/pgvector:pg16`; `make compose-down -v && make compose-up` |
| `Identifier exceeds maximum length of 63 characters` | auto-gen FK name too long | fixed in `0003_intake_buffer_items.py` |
| Slow first voice turn (~12s) | Bedrock cold start; warmup failed | check terminal A for `bedrock_warmup_failed` |
| LLM `auth_valid` FAIL (openai_compat) with 402 | no Anthropic payment | add card |
| LLM `basic_completion` FAIL (bedrock) with `inference profile` error | model id not cross-region profile | use `us.anthropic.claude-sonnet-4-6` |
| LLM call returns `{"Output":{"__type":"...UnknownOperationException"}}` | wrong Bedrock URL | prod uses `invoke_model`; only appears on manual curl |
| `caller_a_does_not_see_caller_b_memory` FAIL | Supermemory ignoring tag filter | **privacy-critical** — stop, don't deploy |
| `container_tags_or_semantics_documented` FAIL with "AND-matching" | Supermemory changed semantics | good news — `Retriever.for_turn` can revert to two-tag |
| AP `test_webhook_delivery` FAIL 401 | uvicorn started with empty `AGENTPHONE_WEBHOOK_SECRET` | restart `make run` after sourcing env |
| AP `test_webhook_delivery` FAIL 500 | downstream dep down (Redis/Postgres) | check terminal A traceback + `make compose-up` |
| AP call says "technical difficulties" + ngrok `ttl` doesn't bump | number is `shared-imessage` or per-agent webhook missing | provision dedicated voice number; register per-agent webhook |
| AP `outbound_sms_capability` FAIL with `/messages` 404 | `SMOKE_AGENTPHONE_TEST_AGENT_ID` stale or no number attached | `curl GET /v1/agents/{id}`; attach number |
| `conversation_state_roundtrip` FAIL 404 | conversation id stale | dial AP number once, save new id |
| Outbound SMS replies fail with 404 | 10DLC registration incomplete | complete A2P 10DLC in AP dashboard |
| `/integrations/google/auth_url` returns 503 | Google Workspace is dormant | normal — see [§ Optional integrations](#optional-third-party-integrations) |
| Email action item completes with `error: "google_oauth_not_configured"` | handler degrading cleanly | normal; surface draft to Manager |
| `auth/refresh` returns 200 on re-used token | AuthService used to not commit | fixed — `refresh()` + `logout()` now commit |
| Tests fail with `value is not a valid email address: …reserved name…` | test used `.test`/`.local` TLD | use non-RFC-reserved (`.example.com` etc.) |
| `Task ... got Future ... attached to a different loop` after `test_migrations` | engine cache pinned to stale loop | conftest clears `_engine.cache_clear()` per test |
| Slow `object_storage` probe (~9s) | MinIO cold-start under parallel probe load | harmless; later calls <50ms |
| `docker compose up` web exits `FATAL: password authentication failed` | stale `pg_data/` volume | `docker compose down -v && docker compose up --build` |
| Lifespan log shows `*_close_failed` on shutdown | cached singleton errored on close | non-fatal; others still drained |

For full troubleshooting + production triage, see
`lld/phase_0_scaffolding_and_mvp.md` §B12 and
`lld/phase_1_durability_and_productivity.md`.
