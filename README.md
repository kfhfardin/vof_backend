# Voice of the Field — Backend

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
> 10DLC registration is complete** in the AP dashboard. The full
> architecture ships and works; you just won't see a reply until that
> paperwork clears.

Design docs: [`hld/`](./hld/) for the high-level design,
[`lld/`](./lld/) for low-level design per phase
(`phase_0_scaffolding_and_mvp.md`, `phase_1_durability_and_productivity.md`).

---

## Table of contents

1. [Code architecture](#code-architecture)
2. [What Phase 0 vs Phase 1 ships](#what-phase-0-vs-phase-1-ships)
3. [Quickstart (dev inner-loop)](#quickstart-dev-inner-loop)
4. [LLM provider — Anthropic direct OR AWS Bedrock](#llm-provider--anthropic-direct-or-aws-bedrock)
5. [Connection-pooling + lifespan](#connection-pooling--lifespan)
6. [Optional third-party integrations](#optional-third-party-integrations)
7. [Running the production container locally](#running-the-production-container-locally)
8. [Smoke tests — per-integration verification](#smoke-tests--per-integration-verification)
9. [Unit + integration tests](#unit--integration-tests)
10. [Seeding a Workspace into the DB](#seeding-a-workspace-into-the-db)
11. [Live end-to-end testing (real phone call)](#live-end-to-end-testing-real-phone-call)
12. [Common make targets](#common-make-targets)
13. [Troubleshooting](#troubleshooting)

---

## Code architecture

VotF is one Python package (`app/`) plus a sibling `skills/` directory
of LLM prompt assets, two Postgres databases, one Redis instance, one
S3 bucket, and a handful of external personas (AgentPhone, AgentMail,
Supermemory). Each external boundary is behind a Protocol so individual
pieces can be unit-tested, smoke-tested, and replaced without rewriting
the rest.

```
.
├── app/                          # FastAPI application package
│   ├── main.py                   # ASGI entrypoint: `uvicorn app.main:app`
│   ├── factory.py                # build_app() — routers, middleware, lifespan
│   ├── lifespan.py               # startup warmup + shutdown drain (see § Connection-pooling)
│   ├── deps.py                   # FastAPI deps + provider singletons (LLM/Telephony/Memory/Store)
│   ├── settings.py               # pydantic-settings; reads .env / env vars
│   ├── errors.py                 # exception hierarchy + handlers
│   │
│   ├── api/                      # HTTP + WebSocket surface
│   │   ├── auth.py               # signup, login, refresh, logout (rotation + revocation)
│   │   ├── me.py                 # /me
│   │   ├── webhooks/
│   │   │   ├── agentphone.py     # AP webhook: HMAC → dedupe → parse → dispatch
│   │   │   └── agentmail.py      # AgentMail inbound replies (Phase 1)
│   │   └── workspaces/
│   │       ├── intake.py         # form/upload/voice-intake + classification (Phase 0)
│   │       ├── decisions.py      # list / get / respond (first-responder-wins)
│   │       ├── calls.py          # list calls + transcripts + artifacts (Phase 1 F1)
│   │       ├── brain.py          # workspace brain pages + corrections
│   │       ├── ws.py             # multi-call WebSocket (live frames)
│   │       ├── action_items.py   # list / approve / execute (Phase 1 F3)
│   │       ├── dashboards.py     # briefs + trends (Phase 1 F8)
│   │       ├── email.py          # list inbox (Phase 1 F6)
│   │       ├── verifications.py  # claim verification results (Phase 1 F5)
│   │       └── integrations.py   # OAuth surface (Phase 1 F9; Google dormant)
│   │
│   ├── orchestrator/             # per-turn LLM loop (§C4 / HLD §15)
│   │   ├── turn_loop.py          # voice turn driver: retrieval → LLM → reply
│   │   ├── sms_orchestrator.py   # turn-based SMS path (no streaming)
│   │   ├── prompts.py            # message builder
│   │   ├── retrieval.py          # Caller-memory + Brain hybrid search (parallel)
│   │   ├── streaming.py          # NDJSON wrapper + bridge phrases
│   │   ├── session.py            # Redis-backed CallSession (CAS via WATCH)
│   │   ├── prewarm.py            # one-time cache warmup helpers
│   │   ├── tool_dispatch.py      # mid-stream <<TOOL …>> marker scanner
│   │   └── tools/
│   │       ├── request_manager_decision.py
│   │       ├── request_correction.py
│   │       └── end_call.py
│   │
│   ├── miniagents/               # background workflows
│   │   ├── summarizer_agent.py     # post-call summary
│   │   ├── brain_updater.py        # upsert pages / append timeline
│   │   ├── caller_memory_writer.py # Supermemory writes (per-rep tag)
│   │   ├── email_drafter.py        # F3: drafts + Gmail send (Google optional)
│   │   ├── email_delivery.py       # F6: AgentMail outbound
│   │   ├── email_reply_handler.py  # F6: inbound webhook → handler dispatch
│   │   ├── scheduler.py            # F3: calendar event creation (Google optional)
│   │   ├── web_verifier.py         # F5: claim verification mini-agent
│   │   └── dashboard_rollup.py     # F8: daily brief rollup
│   │
│   ├── workers/                  # arq jobs: post_call (fan-out), decision_timeout,
│   │                             #   correction_cascade
│   │
│   ├── services/                 # app-layer services
│   │   ├── auth_service.py       # signup, login, refresh (with rotation), logout
│   │   ├── workspace_provisioning.py
│   │   ├── intake_processor.py + intake_processing.py
│   │   ├── intake_extractors/    # PDF, DOCX, XLSX, CSV, JSON, Markdown/text
│   │   ├── intake_handlers/      # scope-specific Brain ingesters
│   │   ├── action_items/         # F3: heuristic extractor + save + templates
│   │   ├── dashboards/           # F8: aggregator
│   │   ├── web_verifier/         # F5: browser client (browser-use optional)
│   │   ├── corrections.py        # replace_compiled_truth / soft_delete / append_timeline
│   │   └── correction_intake.py
│   │
│   ├── skills/                   # Python-side LLMSkill registry + loader
│   │   ├── base.py               # LLMSkill ABC + ClassVar.model
│   │   ├── loader.py             # walks ../skills/<name>/, parses SKILL.md
│   │   └── llm_client.py         # OpenAICompatClient + BedrockMessagesClient (cached)
│   │
│   ├── brain/                    # BrainProvider protocol + PostgresBrainProvider
│   │   ├── postgres_brain.py     # per-Workspace pgvector schemas
│   │   ├── entity_extractor.py   # F4: brain self-update entity extraction
│   │   └── tags.py
│   │
│   ├── memory/                   # CallerMemoryProvider protocol +
│   │                             #   Supermemory adapter (cached) + Stub
│   ├── telephony/                # TelephonyProvider protocol + AgentPhoneAdapter
│   │                             #   (cached) + Fake + WebhookDispatcher
│   ├── email/                    # AgentMail + composer + OAuth-personal + templates
│   ├── connectors/               # OAuth connectors (google_workspace.py — dormant)
│   ├── storage/                  # S3-compat ObjectStore (aiobotocore, cached)
│   ├── realtime/                 # Redis pub/sub bus + WS frame schemas
│   ├── db/                       # SQLAlchemy models + repositories + sessions
│   ├── migrations/               # Alembic env + per-target versions/
│   ├── security/                 # JWT, password hashing, HMAC
│   ├── observability/            # OTel + structlog wiring
│   └── schemas/                  # Pydantic request/response + WS frames
│
├── skills/                       # LLM skill assets (loaded at boot)
│   ├── classifier/               # intake classifier
│   ├── orchestrator/             # live voice + SMS turn loop
│   ├── summarizer/               # post-call summary
│   ├── web_verifier/             # F5: verification reasoning prompt
│   └── dashboard_rollup_writer/  # F8: daily brief narrative composer
│
├── smoke/                        # per-integration verification probes
│   ├── _base.py                  # Probe ABC, ExitCode, CheckResult
│   ├── _runner.py                # aggregator (multi-probe runner)
│   ├── postgres_app.py           # app DB
│   ├── postgres_brain.py         # brain DB (pgvector + schema lifecycle)
│   ├── redis.py                  # connect, pub/sub, dedupe-set TTL
│   ├── object_storage.py         # PUT/GET/signed URL/prefix isolation
│   ├── llm.py                    # OpenAI-compat + Bedrock — branches on LLM_PROVIDER
│   ├── supermemory.py            # write/search/profile + caller isolation
│   ├── agentphone.py             # auth/webhook/HMAC/SMS/conv-state
│   └── manifests/probes.yaml     # registry the aggregator reads
│
├── tests/
│   ├── unit/                     # fast, no external services (173 tests)
│   ├── integration/              # require docker compose Postgres/Redis (5 files)
│   ├── e2e/                      # full stack + fake AP (scaffolded)
│   └── load/                     # latency budget checks (scaffolded)
│
├── scripts/
│   ├── alembic_wrapper.py        # multi-DB dispatcher (app | brain)
│   ├── seed_test_workspace.py    # seed Org + Manager + Workspace (+ optional FE)
│   └── postgres_init/01_dbs.sh   # creates brain DB + pgvector at first boot
│
├── hld/                          # high-level design
├── lld/                          # low-level design per phase
│
├── Dockerfile                    # multi-stage prod image (uv → slim runtime)
├── docker-compose.yml            # full stack: built image + infra + worker
├── docker-compose.local.yml      # infra only — for the dev inner-loop
├── alembic.ini                   # app DB target
├── alembic-brain.ini             # brain DB target
└── pyproject.toml                # uv-managed deps + ruff + mypy + pytest
```

### Hot path — one voice turn

```
AgentPhone webhook (HMAC) → app.api.webhooks.agentphone
  → WebhookDispatcher → app.orchestrator.turn_loop.TurnLoop.run
    ├── append caller fragment to transcripts (Postgres)
    ├── retrieve in parallel (~150ms budget):
    │     • Caller-memory single-tag search  (Supermemory, cached httpx)
    │     • Brain hybrid search              (pgvector + tsvector)
    ├── render prompt (app.orchestrator.prompts)
    ├── stream LLM (Anthropic direct OR Bedrock invoke_model_with_response_stream)
    │     └── mid-stream <<TOOL …>> markers dispatched via ToolRegistry
    ├── wrap tokens as NDJSON chunks → StreamingResponse → AgentPhone
    ├── append agent reply + publish multi-call WS frames
    └── save CallSession to Redis (CAS via WATCH/MULTI/EXEC)
```

### SMS hot path (Phase 1)

```
AgentPhone webhook (HMAC, sms/imessage) → app.api.webhooks.agentphone
  → app.orchestrator.sms_orchestrator.handle_inbound_sms
    ├── same retrieval (caller memory + brain)
    ├── same prompt rendering
    ├── LLM non-streaming completion
    └── AgentPhoneAdapter.send_sms(agent_id, to_number, body)
       (10DLC gate: outbound returns 404 until your AP account is registered)
```

### Post-call fan-out (Phase 1 F2)

```
agent.call_ended webhook → post_call_job (arq)
  ├── summarizer skill → {discussion, blockers, extracted_entities}
  ├── save call artifact (full transcript) → object store
  ├── PARALLEL:
  │     • brain_updater       (F4: upsert pages / append timeline)
  │     • caller_memory_writer (Supermemory add, [caller, workspace] tags)
  │     • action_items heuristic extractor (F3: extract candidate items)
  │     • web_verifier        (F5: queue claim verifications)
  │     • email_drafter       (F3: render outbound email drafts)
  │     • dashboard_rollup    (F8: roll into daily snapshot)
  └── publish call.summary_ready WS frame
```

### Provider contracts

Every external dependency is behind a Protocol so tests + dev paths can
swap a fake in via FastAPI `dependency_overrides`:

| Protocol                        | Real impl                          | Test fake / stub                    |
|---------------------------------|------------------------------------|-------------------------------------|
| `TelephonyProvider`             | `AgentPhoneAdapter`                | `FakeTelephonyProvider`             |
| `CallerMemoryProvider`          | `SupermemoryCallerMemoryProvider`  | `StubCallerMemoryProvider`          |
| `BrainProvider`                 | `PostgresBrainProvider`            | (uses real brain DB in tests)       |
| `ObjectStore`                   | `S3ObjectStore` (aiobotocore)      | (uses MinIO in tests)               |
| `LLMClient`                     | `OpenAICompatClient` OR `BedrockMessagesClient` | `FakeLLMClient` |
| `EmailProvider` (Phase 1)       | `AgentMailProvider`                | no-op when key empty                |

Each real implementation **caches its underlying transport for the
process lifetime** — see [§ Connection-pooling + lifespan](#connection-pooling--lifespan).

---

## What Phase 0 vs Phase 1 ships

**Phase 0 (the live voice loop):**

- Auth: signup, login, **refresh-token rotation + reuse detection**, logout
- Telephony: AgentPhone webhook + HMAC verify + dispatch
- Orchestrator hot path: voice turn streaming through Claude
- Per-rep Caller Memory (Supermemory containerTags)
- Per-Workspace Brain (pgvector + tsvector hybrid search)
- Decision flow: SMS pings + first-responder-wins + timeouts
- Tools: `request_manager_decision`, `request_correction`, `end_call`
- Intake: text + upload (PDF/DOCX/XLSX/CSV/JSON/text) → classifier → handler → Brain
- Manager corrections: replace / soft-delete / append timeline (with `manager_authoritative` guard)
- Post-call writeback: summarize → Brain + Caller Memory

**Phase 1 (F1–F9, durability + productivity):**

| ID | Feature | Status |
|---|---|---|
| F1 | Transcripts + Call History | ✅ shipped |
| F2 | Post-call pipeline fan-out worker | ✅ shipped |
| F3 | Action Items (extract → approve → execute) | ✅ shipped |
| F4 | Brain Self-Update (entity extractor) | ✅ shipped |
| F5 | Web Verifier (claim verification) | ✅ shipped (`BROWSER_USE_API_KEY` optional — falls back to httpx + regex stripper) |
| F6 | Email Surface (in + out + drafter) | ✅ shipped (`AGENTMAIL_API_KEY` optional — no-ops when empty) |
| F7 | Manager Intervention (whisper) | ✅ shipped |
| F8 | Dashboards (daily brief + trends) | ✅ shipped |
| F9 | Google Workspace OAuth + handlers | 🟡 **dormant** — connector code is in place but env vars are intentionally not surfaced. Endpoints return 503; email/scheduler handlers return drafts with `error: "google_oauth_not_configured"`. To re-enable, add `GOOGLE_OAUTH_CLIENT_ID` + `_SECRET` back to settings + env. |

Phase 1 added 8 new tables (`correction_intakes`, `action_items`,
`manager_interventions`, `claim_verifications`, `email_messages`,
`workspace_oauth_credentials`, `dashboard_snapshots`,
`saved_dashboard_queries`) plus columns on `manager_workspaces`
(`email_inbox_id`, `email_inbox_addr`, `email_domain`). All in
`app/migrations/versions_app/0010_phase_1_unified.py`.

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

# 6. Run migrations (creates both app + brain schemas, applies Phase 0 + Phase 1)
make migrate

# 7. Start the API and (in another shell) the arq worker
make run            # uvicorn app.main:app --reload  → http://localhost:8000
make worker         # arq app.workers.settings.WorkerSettings
```

The dev inner-loop uses **`docker-compose.local.yml`** which only ships
the infra services (Postgres, Redis, MinIO). FastAPI + arq run on the
host so `--reload` and breakpoints work. For production-image-in-the-loop
testing, see [Running the production container locally](#running-the-production-container-locally).

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
back to `FakeLLMClient` with a stderr warning — dev environments
without a real key won't silently produce garbage skill output.

### Anthropic direct (default)

```bash
# .env.local
LLM_PROVIDER=openai_compat
LLM_API_KEY=sk-ant-...
LLM_BASE_URL=https://api.anthropic.com/v1/openai
LLM_DEFAULT_MODEL=claude-sonnet-4-6                   # orchestrator hot path
LLM_MODEL=claude-haiku-4-5                            # smoke probe
```

### AWS Bedrock

Bedrock requires the **native Anthropic Messages API** path
(`invoke_model` + `invoke_model_with_response_stream`). AWS does
publish an OpenAI-compat endpoint at `/openai/v1/chat/completions` but
it 404s on many accounts — the native path is the universally-available
surface. `BedrockMessagesClient` handles this via `aiobotocore` with a
single cached client reused across calls (cold-start is ~12s, warm
calls are ~1s — lifespan warms the client at startup so the first real
voice turn doesn't pay the cold cost).

```bash
# .env.local
LLM_PROVIDER=bedrock
ANTHROPIC_API_KEY=<Bedrock long-term API key>         # NOT an sk-ant key
AWS_REGION=us-east-1
LLM_DEFAULT_MODEL=us.anthropic.claude-sonnet-4-6      # cross-region inference profile
LLM_MODEL=us.anthropic.claude-sonnet-4-6              # smoke probe uses the same
```

**Model IDs must be cross-region inference profile IDs** (prefixed with
the region group, e.g. `us.`). Plain Anthropic IDs like
`anthropic.claude-sonnet-4-6` raise `ValidationException` because
on-demand throughput isn't supported.

### Skill model IDs

Each skill pins its model in `skills/<name>/SKILL.md` frontmatter. When
flipping providers, also flip the frontmatter — e.g.
`model: us.anthropic.claude-sonnet-4-6` for Bedrock or
`model: claude-sonnet-4-6` for Anthropic direct.

---

## Connection-pooling + lifespan

Every long-lived adapter (LLM, telephony, memory, object store, Redis)
caches its underlying transport for the process lifetime — TLS
handshakes and pool setup happen once at startup, not on every request.

### Cached clients (verified by unit tests)

| Adapter                              | Cached object         | Built on first call to | Closed by `_close_singletons()` |
|--------------------------------------|-----------------------|------------------------|---------------------------------|
| `OpenAICompatClient`                 | `httpx.AsyncClient`   | `_get_client()`        | yes                             |
| `BedrockMessagesClient`              | `aiobotocore` client  | `_get_client()`        | yes                             |
| `AgentPhoneAdapter`                  | `httpx.AsyncClient`   | `_get_client()`        | yes                             |
| `SupermemoryCallerMemoryProvider`    | `AsyncSupermemory`    | `_get_client()`        | yes                             |
| `S3ObjectStore`                      | `aiobotocore` S3      | `_get_client()`        | yes                             |
| Redis singleton (`get_redis()`)      | `redis.asyncio` pool  | first access           | yes                             |
| App + brain DB engines               | `AsyncEngine` (`@lru_cache`'d) | first session  | (closed on process exit)        |

Each adapter uses double-checked locking around an `asyncio.Lock` so two
concurrent requests during cold start don't race to build two clients.
The cache-contract tests in
[`tests/unit/test_llm_streaming.py`](tests/unit/test_llm_streaming.py)
assert that two consecutive `_get_client()` calls return the **same**
object (`is` identity); regression to per-call construction fails them
loudly.

### Startup warmup (`app/lifespan.py`)

On FastAPI startup, after the registries are loaded, lifespan warms the
expensive cold paths so the first real voice turn doesn't pay them:

```
lifespan_startup_begin
  ├── load skills + register orchestrator voice handler
  ├── warm Bedrock client + first invoke_model TLS handshake
  ├── warm Postgres pool (SELECT 1)
  ├── warm Supermemory httpx pool (no-op search)
  └── warm pgvector index (hybrid_search against UUID(int=0))
lifespan_startup_complete
```

Each warmup step is best-effort with `try/except` + `log.warning` — a
failure during warmup is logged but doesn't block startup (the first
real call just pays the cold cost instead).

### Shutdown drain (`_close_singletons()`)

On uvicorn shutdown, lifespan walks every cached singleton and calls
`.close()` so connection pools drain gracefully:

```
lifespan_shutdown_begin
  ├── llm_client_closed
  ├── telephony_client_closed
  ├── memory_client_closed
  ├── object_store_closed
  └── redis_client_closed
lifespan_shutdown_complete
```

Each close is independently `try/except`'d — a failure to drain one
pool never blocks the others.

---

## Optional third-party integrations

Three third-party integrations are **optional** in Phase 1 — code paths
detect missing config and degrade cleanly:

### AgentMail (F6)

`AGENTMAIL_API_KEY` empty:
- Outbound email no-ops; `email_delivery` mini-agent logs + skips
- Inbound webhook (`POST /api/v1/webhooks/agentmail/webhook`) still 200s but doesn't process

With `AGENTMAIL_API_KEY` set:
- `app/email/agentmail.py` hits `https://api.agentmail.to/v0`
- Optional `EMAIL_DOMAIN` gives each workspace `<slug>@<your-domain>` (default is `*.agentmail.to`)
- Phase 1 speed variant **skips webhook signature verification** (worth tightening for prod)

### Browser Use (F5)

`BROWSER_USE_API_KEY` empty:
- `app/services/web_verifier/browser_client.py` uses an httpx + regex HTML-stripper fallback
- Good enough for the "did the page say this?" verifier prompt on static HTML pages
- JS-rendered pages won't verify until the real SDK is wired

With `BROWSER_USE_API_KEY` set:
- The real Browser Use Cloud SDK can drop in — `BrowserSession.fetch_page` interface is shaped for it

### Google Workspace (F9 — dormant)

By default the connector is **disabled** at config layer (env vars are
not surfaced; `is_google_workspace_configured()` returns `False`).
Effects:

- `/api/v1/workspaces/{ws}/integrations/google/auth_url` and `/callback` return **HTTP 503** with `{"error":"google_oauth_not_configured"}`
- `email_drafter` mini-agent returns the draft with `error: "google_oauth_not_configured"` (no Gmail send)
- `scheduler` mini-agent returns a rendered event draft with the same error (no Calendar event)
- `OAuthPersonalEmailProvider.send_message` raises `NotImplementedError` → `email_delivery` maps to `oauth_connector_unavailable` and falls back to AgentMail

To re-enable later:

1. Add to `app/settings.py`:
   ```python
   google_oauth_client_id: SecretStr = SecretStr("")
   google_oauth_client_secret: SecretStr = SecretStr("")
   ```
2. Add to `.env.local`:
   ```bash
   GOOGLE_OAUTH_CLIENT_ID=
   GOOGLE_OAUTH_CLIENT_SECRET=
   ```
3. Set real values. `is_google_workspace_configured()` flips to `True`,
   endpoints stop returning 503, mini-agents resume calling Gmail / Calendar.
   No code changes needed — connector + handlers + endpoints + repo +
   migration all stayed in place.

---

## Running the production container locally

`Dockerfile` is a two-stage build (uv → `python:3.12-slim`) that
produces a single image used for both the web API and the arq worker
(worker overrides `CMD`). `docker-compose.yml` wires it up against the
same Postgres/Redis/MinIO compose stack used for dev, plus a one-shot
`migrate` service that web + worker `depends_on`.

```bash
# Reuse .env.local for defaults. JWT_SECRET is required.
docker compose --env-file .env.local up --build
```

| Service       | Image                       | Purpose                                                  |
|---------------|-----------------------------|----------------------------------------------------------|
| `postgres`    | `pgvector/pgvector:pg16`    | hosts both `votf_app` and `votf_brain` (pgvector ready)  |
| `redis`       | `redis:7-alpine`            | session store, pub/sub bus, arq queue                    |
| `minio`       | `minio/minio`               | S3-compat object store                                   |
| `minio-init`  | `minio/mc`                  | one-shot: creates the bucket on first boot               |
| `migrate`     | `vof-backend:local`         | one-shot: `alembic upgrade head` for both DBs            |
| `web`         | `vof-backend:local`         | uvicorn on `:8000`, health at `/health`                  |
| `worker`      | `vof-backend:local`         | `arq app.workers.settings.WorkerSettings`                |

```bash
docker compose logs -f web                   # tail one service
docker compose run --rm migrate              # re-run migrations
docker compose exec web sh                   # shell in container
docker compose down                          # stop (keeps volumes)
docker compose down -v                       # stop + wipe DB/object data
```

### What's in the image

- the resolved venv at `/app/.venv` (built from `uv.lock`, no dev deps)
- the `app/` Python package
- the `skills/` directory (loaded at startup by `app.skills.loader`)
- the `scripts/` directory (Alembic wrapper, seed scripts)
- `alembic.ini` + `alembic-brain.ini`

**Not** in the image: `tests/`, `smoke/`, `hld/`, `lld/`. See
`.dockerignore`. The image runs as non-root `votf` (UID 1000) with a
`HEALTHCHECK` against `/health`.

### Environment contract (production)

Required for the runtime container:

| Var                              | Notes                                                              |
|----------------------------------|--------------------------------------------------------------------|
| `DATABASE_URL`                   | `postgresql+asyncpg://…/votf_app`                                  |
| `BRAIN_DATABASE_URL`             | `postgresql+asyncpg://…/votf_brain` (pgvector required)            |
| `REDIS_URL`                      | shared by session store, pub/sub, arq                              |
| `S3_BUCKET` + `S3_ACCESS_KEY` + `S3_SECRET_KEY` + `S3_REGION` | omit `S3_ENDPOINT_URL` for AWS S3; set it for R2 / MinIO |
| `JWT_SECRET`                     | ≥32 bytes, rotate per environment                                  |
| `AGENTPHONE_API_KEY` + `AGENTPHONE_WEBHOOK_SECRET` | empty → `FakeTelephonyProvider` (fake numbers at signup) |
| `SUPERMEMORY_API_KEY`            | empty → `StubCallerMemoryProvider` (writes return synthetic ids)   |
| `LLM_PROVIDER`                   | `openai_compat` or `bedrock`                                       |
| `LLM_API_KEY` / `ANTHROPIC_API_KEY` | required per provider (see § LLM provider table)                |
| `LLM_DEFAULT_MODEL` / `LLM_MODEL` | model IDs match the provider's format                             |
| `AWS_REGION`                     | required when `LLM_PROVIDER=bedrock`                               |
| `DEPLOYMENT_PROFILE`             | `cloud` for prod, `local` for dev (with `S3_ENDPOINT_URL`)         |
| `AGENTMAIL_API_KEY`              | **optional** — empty disables email surface (see § Optional integrations) |
| `EMAIL_DOMAIN`                   | optional custom email domain                                       |
| `BROWSER_USE_API_KEY`            | **optional** — falls back to httpx + regex stripper                |

Empty third-party keys log a warning at startup and bind a fake/stub
provider. Safe for local prod-image validation, **not for production
voice** — `make smoke` against the deployed environment is the gate.

### Webhook reachability

AgentPhone and AgentMail can't reach `localhost`. For local validation
of the production container against real services, expose port 8000 via
a tunnel and register a **per-agent webhook** for AgentPhone (see
[Live end-to-end testing](#live-end-to-end-testing-real-phone-call)).
In production, deploy behind a TLS terminator (Cloud Run, Fly.io,
nginx + cert-manager) and use that URL.

---

## Smoke tests — per-integration verification

The `smoke/` framework proves that the deployment can reach every
service it depends on AND that every contract behaves as expected.
Each probe is **fully independent** — no probe imports another, no
probe shares in-memory state with another, and every probe namespaces
its scratch resources with random UUIDs so concurrent runs don't
collide.

### What the smoke framework covers

| # | Probe                  | Verifies                                                                       |
|---|------------------------|--------------------------------------------------------------------------------|
| 1 | `smoke.postgres_app`   | connect, transaction isolation, CRUD round-trip                                |
| 2 | `smoke.postgres_brain` | connect, pgvector + tsvector present, schema-per-Workspace lifecycle, vector + tsvector round-trip |
| 3 | `smoke.redis`          | connect, set/get, pub/sub round-trip, dedupe-set + TTL                         |
| 4 | `smoke.object_storage` | bucket reachable, PUT/GET/DELETE, signed-URL generation, prefix isolation      |
| 5 | `smoke.llm`            | auth, basic completion, **streaming**, **JSON mode**, **tool calls** — branches between OpenAI-compat (HTTP) and Bedrock (`boto3.invoke_model`) based on `LLM_PROVIDER` |
| 6 | `smoke.supermemory`    | auth, write/search/profile, **per-caller isolation** via single-tag search, OR-semantic tripwire, indexing-lag-aware (30s polling window) |
| 7 | `smoke.agentphone`     | auth, master webhook configured, **HMAC round-trip through the production verifier**, test webhook delivery, outbound SMS, `PATCH /conversations/{id}` metadata round-trip |

> Phase 1 third-parties (AgentMail, Browser Use) don't have smoke probes
> yet — they're optional and the production code degrades cleanly when
> empty, so a missing probe doesn't block deployment. Worth adding if/when
> you depend on those surfaces for critical flows.

### Three operating modes + four exit codes

| Mode       | Flag (default `check`)  | What runs                                  | Cost           | When                          |
|------------|-------------------------|--------------------------------------------|----------------|-------------------------------|
| **Check**  | `--mode check`          | auth + connectivity only                   | free / cents   | every push, CI pre-flight     |
| **Smoke**  | `--mode smoke`          | every feature VotF actually uses           | $0.05–0.20 + 1 SMS | pre-release, post-incident |
| **Repair** | `--mode repair`         | smoke + verbose diagnostics on failure     | same as smoke  | when debugging                |

| Code | Meaning                                  | What to do                                   |
|------|------------------------------------------|----------------------------------------------|
| `0`  | **PASS**                                 | proceed                                      |
| `1`  | **FAIL** — config/contract broken        | read the `fix:` hint on the failed check     |
| `2`  | **CONFIG** — required env vars missing   | source `.env.local`; missing vars are listed |
| `3`  | **UPSTREAM** — the third-party is down   | check the provider's status page             |

### Run everything

```bash
set -a && source .env.local && set +a

# Cheap: connectivity-only across all 7 probes (~2s)
make smoke

# Thorough: exercises every feature (~30s, $0.05-0.20, 1 SMS)
make smoke-full
```

Aggregator output ends with a single grep-friendly summary line:

```
SMOKE_SUMMARY mode=smoke probes=7 pass=7 fail=0 config_error=0 upstream_down=0 duration_ms=18432
```

Exit code is the worst result across all probes.

### Run a single probe

```bash
uv run python -m smoke.postgres_app   --mode check
uv run python -m smoke.postgres_brain --mode smoke
uv run python -m smoke.redis          --mode smoke
uv run python -m smoke.object_storage --mode smoke
uv run python -m smoke.llm            --mode smoke   # branches on LLM_PROVIDER
uv run python -m smoke.supermemory    --mode smoke
uv run python -m smoke.agentphone     --mode smoke
```

### Per-probe independence — enforced, not just claimed

- **No cross-probe imports.** The only `app.*` import in `smoke/` is
  `app.security.hmac` from `smoke.agentphone` — load-bearing because the
  HMAC round-trip must use the production verifier.
- **No shared in-memory state.** Each probe is its own subprocess.
- **No external-state collisions.** Every probe namespaces by random
  UUID: `_smoke_probe` table (postgres_app), `brain_w_smoketest_<uuid>`
  schema (postgres_brain), `_smoke:*` keys (redis), `_smoke_probe/<uuid>`
  keys (object storage), synthetic UUIDs in container_tags
  (supermemory). The AgentPhone probe uses operator-pinned test
  resources (intentionally shared).

### Output format

- **stdout** — one JSON line (the `ProbeReport`) — machine-readable, pipeable.
- **stderr** — colorized human-readable lines with
  `[PASS]`/`[FAIL]`/`[CONFIG]`/`[UPSTREAM]` tags and `fix:` hints.

Secrets are redacted in all output (any env var ending in `_KEY`,
`_SECRET`, `_PASSWORD`, or `_TOKEN`).

### Adding a new probe

Drop a file in `smoke/<name>.py` extending `Probe`, declare `name` +
`required_env: ClassVar[list[str]]`, implement `checks_for_mode()`. Add
an entry to `smoke/manifests/probes.yaml`. The runner discovers it
automatically. See `smoke/postgres_app.py` for the shortest reference
implementation (~80 lines).

---

## Unit + integration tests

### Unit tests — `tests/unit/` (173 tests)

Fast, no external services. Settings are bound to safe defaults in
`tests/conftest.py` so importing the app never touches your real
config. Tests that need an HTTP surface use the `app_client` fixture
(httpx `ASGITransport`, bypasses sockets entirely). Tests that need a
provider override use `app.dependency_overrides` or `set_llm_client()`.

```bash
make test        # uv run pytest tests/unit -q
```

Coverage snapshot:

| Area | What it tests |
|---|---|
| JWT / hashing / HMAC | token round-trip, bcrypt with SHA-256 prehash, AP HMAC verifier |
| LLM clients | OpenAI-compat SSE parsing + FakeLLMClient + **BedrockMessagesClient** (system-message hoisting, body shape, `anthropic_version` pinning, factory branching) |
| **Client-caching contracts** | every adapter (OpenAI-compat, Bedrock, AgentPhone, Supermemory, S3) — verifies consecutive `_get_client()` calls return the **same** instance |
| Streaming / tool dispatch | NDJSON wrapper, `<<TOOL …>>` marker scanner, mid-stream dispatch |
| Skill loader | SKILL.md frontmatter parsing, model registration |
| Memory + container tags | tag scheme, writer wiring, **single-tag retrieval (post-OR-fix)** |
| Post-call writeback | brain_updater stub-vs-append, caller_memory_writer, frame shapes |
| Webhook endpoint | HMAC + replay + dedupe + parse + dispatch |
| Decisions | SMS prefix matching, first-responder-wins, timeout job |
| Corrections | replace_compiled_truth, soft_delete_page, append_timeline_entry |
| WS endpoint + frames | one-time auth tokens, frame shapes |
| Intake | classifier/extractor handlers (PDF/DOCX/XLSX/CSV/JSON/text/MD) |
| AgentPhone adapter | webhook parsing for every event type |
| Settings + models | safe defaults, model metadata |

### Integration tests — `tests/integration/` (5 files)

Tier-2 tests against a real Postgres + Redis. They run against the same
`docker-compose.local.yml` stack used for dev.

```bash
make compose-up
set -a && source .env.local && set +a
make migrate
make integration
```

Per-test isolation: `tests/integration/conftest.py` has an autouse
`_truncate_app_db_between_tests` fixture that truncates every
non-Alembic table with `RESTART IDENTITY CASCADE` before each test AND
clears the cached SQLAlchemy engine factories (so each test gets an
engine bound to its own pytest-asyncio event loop). If Postgres isn't
reachable the whole suite is skipped, not failed.

| File                              | Covers                                                   |
|-----------------------------------|----------------------------------------------------------|
| `test_migrations.py`              | runs real Alembic migrations against compose Postgres (down → up → down → up to leave schema intact for subsequent tests) |
| `test_signup_and_auth.py`         | signup → login → /me → refresh (rotation) → logout (revocation) |
| `test_hierarchy_guard.py`         | Workspace / FieldEmployee / Manager scope enforcement    |
| `test_ws_live.py`                 | multi-call WS bus: connect, auth, publish, drop          |
| `test_onboarding_and_intake.py`   | end-to-end onboarding via real services: signup → workspace re-stamp → rep added → sales/car intake ingested |

### Session finalizer — `_reseed_for_live_calls`

`tests/integration/conftest.py` has a **session-scope autouse
finalizer** that re-runs the production onboarding flow after every
per-test truncate completes. Net effect: after `make integration`
finishes, the DB is left with:

- One Organization (`VotF`) + Manager (`manager@votf-prod.com`)
- One Workspace at `primary_number = +14783304859` (the AP test number)
- One FieldEmployee at `+17653506634`
- The sales/car onboarding intake item, `status = ingested`

So you can dial `+14783304859` immediately after a test run without
re-seeding. The finalizer disposes the SQLAlchemy engine cache before
its `asyncio.run()` so pytest-asyncio's stale connections don't pollute
the seed.

### When to use which tier

| Question                                       | Layer            |
|------------------------------------------------|------------------|
| Does this pure function do the right thing?    | unit             |
| Does this provider's protocol behave correctly? | unit (with fake) |
| Does the DB schema work + API contract round-trip? | integration   |
| Is the orchestrator hot path within latency budget? | load / verify-hot-path |
| Can the deployed environment reach every dep?  | smoke (not pytest) |

---

## Seeding a Workspace into the DB

`scripts/seed_test_workspace.py` writes the minimum rows needed for an
inbound call to route through the orchestrator. Two modes:

### Workspace-only (production-style — many different callers)

Omit `--caller-number`. The dispatcher
(`app/telephony/dispatcher.py`) auto-creates an unprofiled
`FieldEmployee` for each new caller phone on first inbound voice turn,
so callers don't need to be pre-registered.

```bash
set -a && source .env.local && set +a
uv run python -m scripts.seed_test_workspace \
  --ap-number +14783304859 \
  --org-name "Acme Corp" \
  --workspace-name "Acme Manager Workspace" \
  --manager-email "manager@acme.example.com"
```

### Workspace + one known caller (test-style — same caller dials repeatedly)

Pass `--caller-number` to also pre-seed one `FieldEmployee` bound to
that phone.

```bash
uv run python -m scripts.seed_test_workspace \
  --ap-number +17578314612 \
  --caller-number +17653506634 \
  --ap-agent-id cmpa4o1e005ecjz00n7khhuzm
```

### Outbound SMS

For `DecisionService` to send SMS pings to the Manager, the workspace
needs `agentphone_agent_id` set. Pass `--ap-agent-id` on the seed run
(idempotent — re-running updates the existing row).

### One AP agent owning multiple numbers

One AP agent can own multiple phone numbers — the normal pattern when
you want one persona to answer on multiple lines. If multiple workspaces
share one AP agent, the per-agent webhook URL is the same for all; the
dispatcher routes by `data.to` (the dialed number) to the right
workspace. Each workspace keeps its own Brain + Caller Memory.

---

## Live end-to-end testing (real phone call)

Verifying the actual hot path — Rep dials AP → webhook → orchestrator
streams Claude → AP voices it back — requires:

1. Real AgentPhone account with a **voice-capable** dedicated number
   (not a `shared-imessage` pool number — those route to AP's default
   handler and never fire your webhook)
2. **Per-agent webhook** registered:
   ```bash
   export AGENTPHONE_API_KEY=ap_...
   AP_AGENT_ID=cmp...   # from AP dashboard
   curl -X POST "https://api.agentphone.ai/v1/agents/$AP_AGENT_ID/webhook" \
     -H "Authorization: Bearer $AGENTPHONE_API_KEY" \
     -H "Content-Type: application/json" \
     -d '{
       "url": "https://YOUR-NGROK.ngrok-free.dev/api/v1/webhooks/agentphone",
       "contextLimit": 14,
       "timeout": 30
     }'
   # Save the returned "secret" → AGENTPHONE_WEBHOOK_SECRET
   ```
3. ngrok or Cloudflare Tunnel exposing `localhost:8000`
4. A seeded workspace whose `primary_number` matches the AP number
5. Production LLM provider configured

Once seeded, dial the AP number from any mobile — terminal A
(`make run`) will show the webhook arrive, orchestrator turn-loop
logs, and the LLM stream.

### Why "unknown number" returns 404 (correct)

When AP's synthetic test deliveries or any unknown `data.to` hits the
webhook with a phone number not registered to any workspace,
`materialize_scope_and_call` raises `NotFound("unknown_number")` and
the handler returns 404. This is intentional defensive behavior — we
don't want to silently accept webhooks for numbers we don't manage. A
404 with `webhook_unknown_scope` in the logs means the handler worked
correctly; just no scope to dispatch into.

---

## Common make targets

| Target | Action |
|---|---|
| `make install` | `uv sync` |
| `make lint` | `ruff check` + `mypy app/` |
| `make format` | `ruff format` + `ruff check --fix` |
| `make type` | `mypy app/` |
| `make test` / `make unit` | unit tests (no external services) |
| `make integration` | integration tests (needs compose) |
| `make e2e` | e2e tests (full stack + fake AP) |
| `make smoke` | connectivity check across all probes (~2s) |
| `make smoke-full` | exercise every feature (~30s, costs cents) |
| `make smoke-repair PROBE=<name>` | verbose diagnostics for one failing probe |
| `make verify-hot-path` | end-to-end Rep utterance → LLM → TTS latency check |
| `make skills-eval` | run every `skills/<name>/evals/run.py` |
| `make run` | `uvicorn app.main:app --reload` |
| `make worker` | `arq app.workers.settings.WorkerSettings` |
| `make compose-up` / `compose-down` | start/stop local Postgres + Redis + MinIO |
| `make migrate` | `alembic upgrade head` on both app + brain DBs |

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `CONFIG` exit on a probe | env vars not loaded | `set -a && source .env.local && set +a` |
| `UPSTREAM` on an infra probe | compose stack not running | `make compose-up && docker compose ps` |
| `make migrate` errors `ModuleNotFoundError: psycopg2` | Alembic used wrong dialect | `app/migrations/env.py` uses `+psycopg` (v3) — pull latest + re-run |
| `make migrate` errors `extension "vector" is not available` | postgres image lacks pgvector | compose uses `pgvector/pgvector:pg16` — `make compose-down -v && make compose-up` |
| `Identifier exceeds maximum length of 63 characters` during migration | auto-generated FK name too long | already fixed in `0003_intake_buffer_items.py` |
| Slow first voice turn (~12s before any audio) | Bedrock cold start; lifespan warmup failed | check terminal A for `bedrock_warmup_failed` — likely auth or model id |
| LLM `auth_valid` FAIL (openai_compat) with 402 | no Anthropic payment method | add card in console.anthropic.com |
| LLM `basic_completion` FAIL (bedrock) with `inference profile` error | model id isn't a cross-region profile | use `us.anthropic.claude-sonnet-4-6` not `anthropic.claude-sonnet-4-6` |
| LLM `streaming_completion` FAIL | provider doesn't speak SSE / EventStream | swap providers or fix the proxy |
| LLM call returns body `{"Output":{"__type":"...UnknownOperationException"}}` | hit the wrong Bedrock URL path | production uses `invoke_model` not `/v1/chat/completions`; this only appears if you curl manually |
| `caller_a_does_not_see_caller_b_memory` FAIL | Supermemory ignoring tag filter | privacy-critical — **stop, don't deploy**; investigate SDK version + dashboard config |
| `container_tags_or_semantics_documented` FAIL with "AND-matching" | Supermemory changed semantics | good news — revisit `Retriever.for_turn`; the workaround can be reverted |
| AgentPhone `test_webhook_delivery` FAIL 401 | uvicorn started with empty `AGENTPHONE_WEBHOOK_SECRET` | restart `make run` after `set -a && source .env.local && set +a` |
| AgentPhone `test_webhook_delivery` FAIL 500 | downstream dep down (Redis/Postgres) | check terminal A traceback + `make compose-up` |
| AgentPhone call says "experiencing technical difficulties" + ngrok `ttl` doesn't bump | number is `shared-imessage` or per-agent webhook missing | provision a dedicated voice number; register per-agent webhook |
| AgentPhone `outbound_sms_capability` FAIL with `/messages` 404 | `SMOKE_AGENTPHONE_TEST_AGENT_ID` is stale or agent has no number | `curl GET /v1/agents/{id}` to verify; attach a number |
| `conversation_state_roundtrip` FAIL 404 | `SMOKE_AGENTPHONE_TEST_CONVERSATION_ID` stale | dial AP number once to create a fresh conversation, save id |
| Outbound SMS replies fail with 404 from AP | account-level 10DLC registration incomplete | complete A2P 10DLC in AP dashboard — pure paperwork, no code change |
| `/api/v1/workspaces/{ws}/integrations/google/auth_url` returns 503 | Google Workspace is intentionally dormant | normal — see [§ Optional integrations](#optional-third-party-integrations) for re-enable steps |
| Email action item completes with `error: "google_oauth_not_configured"` | same — handler is degrading cleanly | normal; surface the draft to the Manager for manual send |
| `auth/refresh` returns 200 on a re-used token (reuse detection not firing) | AuthService.refresh used to not commit | fixed — `refresh()` and `logout()` now call `session.commit()` |
| Tests fail with `value is not a valid email address: …reserved name…` | test used `.test` / `.local` TLD | use `*.example.com` or other non-RFC-reserved TLDs |
| `Task ... got Future ... attached to a different loop` after `test_migrations` | engine cache pinned to a stale event loop | integration `conftest.py` clears `_engine.cache_clear()` per test |
| Slow `object_storage` probe (~9s) | first MinIO call cold-start under parallel probe load | harmless; subsequent calls are <50ms |
| `docker compose up` web exits with `FATAL: password authentication failed` | stale `pg_data/` volume from a prior init | `docker compose down -v && docker compose up --build` |
| Lifespan log shows `*_close_failed` warnings on shutdown | one of the cached singletons errored on close | non-fatal; other clients still drained. Check the traceback for which adapter |

For full troubleshooting + production triage, see
`lld/phase_0_scaffolding_and_mvp.md` §B12 and
`lld/phase_1_durability_and_productivity.md`.
