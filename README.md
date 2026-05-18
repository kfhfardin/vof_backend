# Voice of the Field — Backend

Phone-first intelligence layer that turns Field Rep conversations into
structured, actionable knowledge for Managers. Two telephony surfaces are
in the box: **live voice** (sub-2s warm-turn streaming) and
**conversational SMS** (turn-based, no streaming). FastAPI + Postgres × 2 +
Redis + S3-compatible object store, fronted by AgentPhone for telephony
and backed by Claude (via either Anthropic's API or AWS Bedrock) for
the orchestrator LLM.

> **One critical caveat for SMS:** outbound SMS via AgentPhone is gated on
> US-carrier 10DLC registration at the account level. **Inbound SMS works
> immediately; outbound replies will fail with HTTP 404 from AP until 10DLC
> registration is complete in the AP dashboard.** The full architecture
> ships and works; you just won't see a reply on your phone until that
> paperwork clears. See [§ SMS messaging](#sms-messaging-inbound-conversational--outbound-gated-on-10dlc).

Design docs: [`hld/`](./hld/) for the high-level design,
[`lld/`](./lld/) for low-level design per phase.

---

## Table of contents

1. [Code architecture](#code-architecture)
2. [Quickstart (dev inner-loop)](#quickstart-dev-inner-loop)
3. [LLM provider — Anthropic direct OR AWS Bedrock](#llm-provider--anthropic-direct-or-aws-bedrock)
4. [Connection-pooling + lifespan](#connection-pooling--lifespan)
5. [Running the production container locally](#running-the-production-container-locally)
6. [Smoke tests — per-integration verification](#smoke-tests--per-integration-verification)
7. [Unit + integration tests](#unit--integration-tests)
8. [Seeding a Workspace into the DB](#seeding-a-workspace-into-the-db)
9. [Live end-to-end testing (real phone call)](#live-end-to-end-testing-real-phone-call)
10. [**SMS messaging (inbound conversational; outbound gated on 10DLC)**](#sms-messaging-inbound-conversational--outbound-gated-on-10dlc)
11. [Common make targets](#common-make-targets)
12. [Troubleshooting](#troubleshooting)

---

## Code architecture

VotF is one Python package (`app/`) plus a sibling `skills/` directory
of LLM prompt assets, two Postgres databases, one Redis instance, one
S3 bucket, and one external persona (AgentPhone). Each boundary is
explicit so individual pieces can be unit-tested, smoke-tested, and
replaced without rewriting the rest.

```
.
├── app/                          # FastAPI application package
│   ├── main.py                   # ASGI entrypoint: `uvicorn app.main:app`
│   ├── factory.py                # build_app() — routers, middleware, lifespan
│   ├── lifespan.py               # startup warmup + shutdown drain (see § Connection-pooling + lifespan)
│   ├── deps.py                   # FastAPI deps + provider singletons (LLM/Telephony/Memory/Store)
│   ├── settings.py               # pydantic-settings; reads .env / env vars
│   ├── errors.py                 # exception hierarchy + handlers
│   │
│   ├── api/                      # HTTP + WebSocket surface
│   │   ├── auth.py               # signup, login, refresh, logout
│   │   ├── me.py                 # /me
│   │   ├── webhooks/agentphone.py  # AP webhook: HMAC → dedupe → parse → dispatch
│   │   └── workspaces/
│   │       ├── intake.py         # form/upload/voice-intake + classification
│   │       ├── decisions.py      # list, get, respond (first-responder-wins)
│   │       ├── calls.py          # list calls + transcripts + artifacts
│   │       ├── brain.py          # workspace brain pages + corrections
│   │       └── ws.py             # multi-call WebSocket (live frames)
│   │
│   ├── orchestrator/             # per-turn LLM loop (§C4 / HLD §15)
│   │   ├── turn_loop.py          # VOICE: caller utterance → retrieval → LLM stream → NDJSON
│   │   ├── voice_handler.py      # plugs the voice loop into the dispatcher
│   │   ├── sms_orchestrator.py   # SMS: inbound message → retrieval → LLM → send_sms (no streaming)
│   │   ├── prompts.py            # voice message builder
│   │   ├── retrieval.py          # Caller-memory + Brain hybrid search (parallel)
│   │   ├── prewarm.py            # per-call context prewarm (Redis-cached)
│   │   ├── streaming.py          # NDJSON wrapper + bridge phrases (voice-only)
│   │   ├── session.py            # Redis-backed CallSession (CAS via WATCH; shared by voice + SMS)
│   │   ├── tool_dispatch.py      # mid-stream <<TOOL …>> marker scanner (shared)
│   │   └── tools/
│   │       ├── request_manager_decision.py   # voice + SMS
│   │       ├── request_correction.py
│   │       └── end_call.py                    # voice-only — excluded from SMS tool subset
│   │
│   ├── miniagents/               # post-call: summarizer, brain_updater,
│   │                             #   caller_memory_writer
│   ├── workers/                  # arq jobs: post_call, decision_timeout,
│   │                             #   correction_cascade
│   │
│   ├── services/                 # AuthService, DecisionService, IntakeProcessor,
│   │   │                         #   WorkspaceProvisioningService, corrections
│   │   └── intake_extractors/    # PDF, DOCX, XLSX, CSV, JSON, Markdown/text
│   │
│   ├── skills/                   # Python-side LLMSkill registry + loader
│   │   ├── base.py               # LLMSkill ABC + ClassVar.model
│   │   ├── loader.py             # walks ../skills/<name>/, parses SKILL.md
│   │   └── llm_client.py         # OpenAICompatClient + BedrockMessagesClient (cached)
│   │
│   ├── brain/                    # BrainProvider protocol + PostgresBrainProvider
│   │                             #   (per-Workspace pgvector schemas)
│   ├── memory/                   # CallerMemoryProvider protocol +
│   │                             #   Supermemory adapter (cached) + Stub
│   ├── telephony/                # TelephonyProvider protocol + AgentPhoneAdapter
│   │                             #   (cached) + Fake + WebhookDispatcher
│   ├── storage/                  # S3-compat ObjectStore (aiobotocore, cached)
│   ├── realtime/                 # Redis pub/sub bus + WS frame schemas
│   ├── db/                       # SQLAlchemy models + repositories + sessions
│   ├── migrations/               # Alembic env + per-target versions/
│   ├── security/                 # JWT, password hashing, HMAC
│   ├── observability/            # OTel + structlog wiring
│   ├── schemas/                  # Pydantic request/response + WS frames
│   └── connectors/               # third-party SDK clients
│
├── skills/                       # LLM skill assets (loaded at boot)
│   ├── classifier/               # SKILL.md frontmatter + prompt + schema + evals
│   ├── orchestrator/
│   └── summarizer/
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
│   ├── unit/                     # fast, no external services (172 tests)
│   ├── integration/              # require docker compose Postgres/Redis
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
    ├── retrieve in parallel (~150ms speculative race):
    │     • Caller-memory single-tag search  (Supermemory, cached httpx)
    │     • Brain hybrid search              (pgvector + tsvector)
    │     fall back to prewarm cache on race loss; bridge chunk on >300ms
    ├── render prompt (app.orchestrator.prompts)
    ├── stream LLM (Anthropic direct OR Bedrock invoke_model_with_response_stream)
    │     └── mid-stream <<TOOL …>> markers dispatched via ToolRegistry
    ├── wrap tokens as NDJSON chunks → StreamingResponse → AgentPhone
    ├── append agent reply + publish multi-call WS frames
    └── save CallSession to Redis (CAS via WATCH/MULTI/EXEC)
```

### Hot path — one inbound SMS

```
AgentPhone webhook (HMAC) → app.api.webhooks.agentphone
  → WebhookDispatcher → app.orchestrator.sms_orchestrator.SMSOrchestratorHandler.handle
    ├── if body starts with "[DR-XXXXXX]":
    │     route to DecisionService.match_sms_response  (preserves Phase 0 decision-pings path)
    │     return — no SMS reply, no LLM call
    ├── else (conversational path):
    │     ├── resolve/create FieldEmployee by from_number
    │     ├── find/create Call row keyed sms_<ap_conversation_id>
    │     ├── persist inbound TranscriptFragment(speaker=caller)
    │     ├── load/create Redis CallSession (same store as voice)
    │     ├── retrieve in parallel (no streaming pressure — awaited in full)
    │     ├── render SMS-tuned prompt (no end_call tool; "reply in 1-2 sentences")
    │     ├── collect full LLM reply (no NDJSON wrapper)
    │     ├── dispatch any request_manager_decision tool call inline
    │     ├── persist agent TranscriptFragment + save session
    │     └── telephony.send_sms(...)  ◄── BLOCKED BY 10DLC — see § SMS messaging
    └── return 200 to AP regardless of send outcome  (AP must not retry)
```

### Post-call writeback (§C11)

```
agent.call_ended webhook → post_call_job (arq)
  → load transcript → summarize → save artifact (object store)
    ├── brain_updater  (upsert pages / append timeline / honor manager_authoritative)
    └── caller_memory_writer  (Supermemory add with [caller, workspace] tags)
  → publish call.summary_ready WS frame
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
| `LLMClient`                     | `OpenAICompatClient` OR `BedrockMessagesClient` | `FakeLLMClient` (set via `set_llm_client()`) |

Each real implementation **caches its underlying transport for the
process lifetime** — see [§ Connection-pooling + lifespan](#connection-pooling--lifespan).

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
make test           # unit tests (172 pass)

# 6. Run migrations (creates both app + brain schemas)
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

The Bedrock long-term API key is the AWS bearer credential — no IAM
access-key/secret pair needed. We surface it to boto3 via
`AWS_BEARER_TOKEN_BEDROCK` at client construction; boto3 ≥ 1.34.103 reads
that automatically.

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
| App + brain DB engines               | `AsyncEngine` (`@lru_cache`'d factory) | first session  | (closed implicitly on process exit) |

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

## Running the production container locally

`Dockerfile` is a two-stage build (uv → `python:3.12-slim`) that
produces a single image used for both the web API and the arq worker
(worker overrides `CMD`). `docker-compose.yml` wires it up against the
same Postgres/Redis/MinIO compose stack used for dev, plus a one-shot
`migrate` service that web + worker `depends_on`.

### Build + run the whole stack

```bash
# Reuse .env.local for defaults. JWT_SECRET is required.
docker compose --env-file .env.local up --build
```

| Service       | Image                       | Purpose                                                  |
|---------------|-----------------------------|----------------------------------------------------------|
| `postgres`    | `pgvector/pgvector:pg16`    | hosts both `votf_app` and `votf_brain` (pgvector ready)  |
| `redis`       | `redis:7-alpine`            | session store, pub/sub bus, arq queue                    |
| `minio`       | `minio/minio`               | S3-compat object store (transcripts, intake docs)        |
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
| `LLM_PROVIDER`                   | `openai_compat` or `bedrock` (see § LLM provider)                  |
| `LLM_API_KEY` / `ANTHROPIC_API_KEY` | required per provider (see § LLM provider table)                |
| `LLM_DEFAULT_MODEL` / `LLM_MODEL` | model IDs match the provider's format                             |
| `AWS_REGION`                     | required when `LLM_PROVIDER=bedrock`                               |
| `DEPLOYMENT_PROFILE`             | `cloud` for prod, `local` for dev (with `S3_ENDPOINT_URL`)         |

Empty third-party keys log a warning at startup and bind a fake/stub
provider. Safe for local prod-image validation, **not for production** —
`make smoke` against the deployed environment is the gate.

### Webhook reachability

AgentPhone can't reach `localhost`. For local validation of the
production container against the real AP service, expose port 8000 via
a tunnel and register a **per-agent webhook** (see
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

### Step 1 — set up env vars

```bash
cp .env.example .env.local
$EDITOR .env.local        # fill in what you have
```

Empty third-party values are fine. The corresponding probes will simply
report `CONFIG` and exit. Verification is per-integration — Postgres
can be `PASS` while AgentPhone is still `CONFIG`.

### Step 2 — bring up local infra (zero accounts needed)

```bash
make compose-up
```

Postgres (both `votf_app` and `votf_brain` databases, pgvector enabled
via `scripts/postgres_init/01_dbs.sh`), Redis, and MinIO. No external
account required.

### Step 3 — verify infrastructure first (cheapest, fastest)

```bash
set -a && source .env.local && set +a

# Just the four infra probes
uv run python -m smoke run --filter infrastructure --mode smoke
```

Expected output:

```
=== SMOKE SUITE SUMMARY ===
  [PASS    ] postgres_app           120ms
  [PASS    ] postgres_brain         310ms
  [PASS    ] redis                  180ms
  [PASS    ] object_storage         410ms

SMOKE_SUMMARY mode=smoke probes=4 pass=4 fail=0 config_error=0 upstream_down=0 duration_ms=1020
```

If anything fails, re-run that probe alone in repair mode:

```bash
make smoke-repair PROBE=postgres_brain
# or
uv run python -m smoke.postgres_brain --mode repair
```

### Step 4 — verify third-party integrations one at a time

#### 4a. LLM (Anthropic direct OR Bedrock — both verified by the same probe)

The probe branches on `LLM_PROVIDER`. Five checks: `auth_valid`,
`basic_completion`, `streaming_completion`, `json_mode`, `tool_calls`.

**Anthropic direct:**
```bash
# .env.local
LLM_PROVIDER=openai_compat
LLM_API_KEY=sk-ant-...
LLM_BASE_URL=https://api.anthropic.com/v1/openai
LLM_MODEL=claude-haiku-4-5
```

```bash
set -a && source .env.local && set +a
uv run python -m smoke.llm --mode smoke
```

**Bedrock:**
```bash
# .env.local
LLM_PROVIDER=bedrock
ANTHROPIC_API_KEY=<Bedrock long-term API key>
AWS_REGION=us-east-1
LLM_MODEL=us.anthropic.claude-sonnet-4-6
```

```bash
set -a && source .env.local && set +a
uv run python -m smoke.llm --mode smoke
```

Bedrock-specific gotchas the probe catches:
- `auth_valid` fails fast if `AWS_BEARER_TOKEN_BEDROCK` doesn't authenticate
- `basic_completion` fails with a clear hint if `LLM_MODEL` is a plain
  Anthropic ID instead of a cross-region inference profile
- `streaming_completion` exercises `invoke_model_with_response_stream`
  with the same EventStream parsing the production hot path uses
- `tool_calls` uses Anthropic's `input_schema` format (not OpenAI's
  `parameters`) — verifies the skill tool registry works on Bedrock

#### 4b. Supermemory

1. Sign up at https://supermemory.ai → generate API key.
2. Set in `.env.local`:
   ```bash
   SUPERMEMORY_API_KEY=sm_...
   ```
3. Run:
   ```bash
   set -a && source .env.local && set +a
   uv run python -m smoke.supermemory --mode smoke
   ```

Expected 9 PASS lines:

```
[PASS] auth_valid
[PASS] memory_write_caller_a
[PASS] memory_write_caller_b
[PASS] caller_a_finds_own_memory                  # via [caller_X] search only
[PASS] caller_b_finds_own_memory
[PASS] caller_a_does_not_see_caller_b_memory      # the load-bearing isolation check
[PASS] container_tags_or_semantics_documented     # tripwire — fails if Supermemory switches to AND-matching
[PASS] workspace_tag_finds_both                   # cross-rep workspace search
[PASS] profile_endpoint_reachable
```

**Why the probe matters**: Supermemory's `container_tags` is OR-matching,
not AND-matching (verified against the live API). The production
retriever (`Retriever.for_turn`) consequently searches with `[caller_tag]`
only — passing `[caller_tag, workspace_tag]` would return every memory
that has *either* tag and leak cross-rep memories. The probe is the
guardrail that catches this if Supermemory ever changes semantics.

The probe writes under synthetic `caller_<uuid>` + `workspace_<uuid>`
tags and cleans up via `client.memories.forget()` in a `finally` block —
your real Supermemory data is never touched.

#### 4c. AgentPhone

This needs a webhook URL reachable from the public internet. For local
dev, that's ngrok or Cloudflare Tunnel.

1. Sign up at https://docs.agentphone.ai, fund the account, generate
   an API key.
2. Provision an Agent + a phone number in the AP dashboard. Confirm
   the agent has `voiceMode: webhook` and the number is voice-capable
   (not `shared-imessage`).
3. Start ngrok:
   ```bash
   ngrok http 8000
   # copy the https URL
   ```
4. Register a **per-agent webhook** (the project-default webhook is
   not sufficient on all AP accounts — voice events may only fire via
   the per-agent webhook):
   ```bash
   export AGENTPHONE_API_KEY=ap_...
   AP_AGENT_ID=cmp...                         # from AP dashboard

   curl -X POST "https://api.agentphone.ai/v1/agents/$AP_AGENT_ID/webhook" \
     -H "Authorization: Bearer $AGENTPHONE_API_KEY" \
     -H "Content-Type: application/json" \
     -d '{
       "url": "https://YOUR-NGROK.ngrok-free.dev/api/v1/webhooks/agentphone",
       "contextLimit": 14,
       "timeout": 30
     }'
   # response includes "secret": "whsec_..." — SAVE IT
   ```
5. Make one test call to your AP number to create a conversation; grab
   the conversation id from the AP dashboard for the
   `conversation_state_roundtrip` check.
6. Set in `.env.local`:
   ```bash
   AGENTPHONE_API_KEY=ap_...
   AGENTPHONE_WEBHOOK_SECRET=whsec_...
   SMOKE_AGENTPHONE_TEST_AGENT_ID=cmp...
   SMOKE_AGENTPHONE_TEST_NUMBER_ID=cmp...
   SMOKE_AGENTPHONE_TEST_CONVERSATION_ID=conv_...
   SMOKE_AGENTPHONE_TEST_TO_NUMBER=+1...      # your mobile, E.164
   ```
7. Run:
   ```bash
   set -a && source .env.local && set +a
   uv run python -m smoke.agentphone --mode smoke
   ```

Expected 4 PASS + 2 expected-FAIL lines on a fresh AP account:

```
[PASS] auth_valid
[PASS] webhook_configured
[PASS] hmac_verification
[PASS] test_webhook_delivery
[FAIL] outbound_sms_capability        — agentphone rejected POST /messages: 404
       (or "Outbound SMS is not enabled for this account. Complete 10DLC registration first.")
[FAIL] conversation_state_roundtrip   — if SMOKE_AGENTPHONE_TEST_CONVERSATION_ID unset
```

**The `outbound_sms_capability` failure is expected and not a regression
until you complete 10DLC registration in the AP dashboard**, since AP
gates `POST /v1/messages` on US-carrier registration. See
[§ SMS messaging](#sms-messaging-inbound-conversational--outbound-gated-on-10dlc)
for the full explanation and the path to enable it. The `auth`,
`webhook`, `HMAC`, and `test_webhook_delivery` checks together prove
that **inbound** SMS (and voice) will route into the system correctly —
which is the load-bearing part of the contract for Phase 0.

### Step 5 — run everything together

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

Exit code is the worst result across all probes. **`exit 0` means the
deployment can reach every integration it needs and every contract
behaves as expected.**

### Per-probe independence — enforced, not just claimed

- **No cross-probe imports.** The only `app.*` import in `smoke/` is
  `app.security.hmac` from `smoke.agentphone` — load-bearing because the
  HMAC round-trip must use the production verifier.
- **No shared in-memory state.** Each probe is its own subprocess via
  `smoke._base.main_for`.
- **No external-state collisions.** Every probe namespaces by random
  UUID: `_smoke_probe` table (postgres_app), `brain_w_smoketest_<uuid>`
  schema (postgres_brain), `_smoke:*` keys (redis), `_smoke_probe/<uuid>`
  keys (object storage), synthetic UUIDs in container_tags
  (supermemory). The AgentPhone probe uses operator-pinned test
  resources (intentionally shared).
- **Within-probe sequential checks** exist where a read depends on a
  prior write (`postgres_brain` schema_create → embedding_roundtrip;
  `object_storage` put → get / signed_url; `supermemory` write →
  search). All use `try/finally` to run cleanup regardless of failures.

### Output format

- **stdout** — one JSON line (the `ProbeReport`) — machine-readable, pipeable.
- **stderr** — colorized human-readable lines with
  `[PASS]`/`[FAIL]`/`[CONFIG]`/`[UPSTREAM]` tags and `fix:` hints.

Secrets are redacted in all output (any env var ending in `_KEY`,
`_SECRET`, `_PASSWORD`, or `_TOKEN`).

### Run a single probe directly

```bash
uv run python -m smoke.postgres_app   --mode check
uv run python -m smoke.postgres_brain --mode smoke
uv run python -m smoke.redis          --mode smoke
uv run python -m smoke.object_storage --mode smoke
uv run python -m smoke.llm            --mode smoke   # branches on LLM_PROVIDER
uv run python -m smoke.supermemory    --mode smoke
uv run python -m smoke.agentphone     --mode smoke
```

### Adding a new probe

Drop a file in `smoke/<name>.py` extending `Probe`, declare `name` +
`required_env: ClassVar[list[str]]`, implement `checks_for_mode()`. Add
an entry to `smoke/manifests/probes.yaml`. The runner discovers it
automatically. See `smoke/postgres_app.py` for the shortest reference
implementation (~80 lines).

For deeper per-integration troubleshooting + rotation cadences + prod
failure triage, see **`lld/phase_0_scaffolding_and_mvp.md` §B12**.

---

## Unit + integration tests

### Unit tests — `tests/unit/` (172 tests)

Fast, no external services. Settings are bound to safe defaults in
`tests/conftest.py` so importing the app never touches your real
config. Tests that need an HTTP surface use the `app_client` fixture
(httpx `ASGITransport`, bypasses sockets entirely). Tests that need a
provider override use `app.dependency_overrides` or `set_llm_client()`.

```bash
make test        # uv run pytest tests/unit -q
```

Coverage snapshot (25 files):

| Area | What it tests |
|---|---|
| JWT / hashing / HMAC | token round-trip, bcrypt with SHA-256 prehash, AP HMAC verifier |
| LLM clients | OpenAI-compat SSE parsing + FakeLLMClient + **BedrockMessagesClient** (system-message hoisting, body shape, `anthropic_version` pinning, factory branching) |
| **Client-caching contracts** | every adapter (OpenAI-compat, Bedrock, AgentPhone, Supermemory, S3) verifies that consecutive `_get_client()` calls return the **same** instance; regression to per-call construction fails loudly |
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

### Integration tests — `tests/integration/` (4 files)

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
non-Alembic table with `RESTART IDENTITY CASCADE` before each test.
If Postgres isn't reachable the whole suite is skipped, not failed.

| File                              | Covers                                                   |
|-----------------------------------|----------------------------------------------------------|
| `test_migrations.py`              | runs real Alembic migrations against compose Postgres    |
| `test_signup_and_auth.py`         | signup → login → /me → refresh → logout                  |
| `test_hierarchy_guard.py`         | Workspace / FieldEmployee / Manager scope enforcement    |
| `test_ws_live.py`                 | multi-call WS bus: connect, auth, publish, drop          |

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
(`app/telephony/dispatcher.py:281`) auto-creates an unprofiled
`FieldEmployee` for each new caller phone on first inbound voice turn,
so callers don't need to be pre-registered.

```bash
set -a && source .env.local && set +a
uv run python -m scripts.seed_test_workspace \
  --ap-number +14783304859 \
  --org-name "Acme Corp" \
  --workspace-name "Acme Manager Workspace" \
  --manager-email "manager@acme.com"
```

Writes: one `Organization`, one `User` (manager, role `manager`), one
`ManagerWorkspace` with `primary_number = <--ap-number>` and
`provisioning_state = "ready"`. Each new caller's phone becomes an
unprofiled FE; Caller Memory accumulates over time (post-call writeback
under `caller_<fe.id>` tag).

### Workspace + one known caller (test-style — same caller dials repeatedly)

Pass `--caller-number` to also pre-seed one `FieldEmployee` bound to
that phone.

```bash
uv run python -m scripts.seed_test_workspace \
  --ap-number +17578314612 \
  --caller-number +17653506634 \
  --ap-agent-id cmpa4o1e005ecjz00n7khhuzm
```

### Outbound SMS (decision pings to Manager)

For `DecisionService` to send SMS pings to the Manager, the workspace
needs `agentphone_agent_id` set. Pass `--ap-agent-id` on the seed run
(idempotent — re-running updates the existing row). The agent id is
shown in `GET /v1/agents` on the AP API or in the AP dashboard.

### One AP agent owning multiple numbers

One AP agent can own multiple phone numbers — that's the normal pattern
when you want one persona to answer on multiple lines. If you have
multiple workspaces sharing one AP agent (verified by `agentId` being
the same on multiple entries in `GET /v1/numbers`), the per-agent
webhook URL is the same for all of them; the dispatcher routes by
`data.to` (the dialed number) to the right workspace.

Each workspace has its own brain + caller memory namespace — they're
isolated at the DB layer even when sharing an AP agent.

### Cleanup / re-seed

The seed script is idempotent — re-running with the same `--ap-number`
**updates** the existing row rather than creating a duplicate. To drop a
workspace entirely:

```bash
docker compose -f docker-compose.local.yml exec -T postgres psql -U votf -d votf_app <<'SQL'
DELETE FROM field_employees WHERE workspace_id IN (
  SELECT id FROM manager_workspaces WHERE primary_number = '+14783304859'
);
DELETE FROM manager_workspaces WHERE primary_number = '+14783304859';
SQL
```

---

## Live end-to-end testing (real phone call)

This section covers **voice**. For the SMS equivalent (which uses the
same webhook + workspace seeding but has the 10DLC outbound caveat), see
[§ SMS messaging](#sms-messaging-inbound-conversational--outbound-gated-on-10dlc).

Verifying the actual voice hot path — Rep dials AP → webhook → orchestrator
streams Claude → AP voices it back — requires:

1. Real AgentPhone account with a **voice-capable** dedicated number
   (not a `shared-imessage` pool number; those route to AP's default
   handler and never fire your webhook)
2. **Per-agent webhook** registered (see § Smoke step 4c)
3. ngrok or Cloudflare Tunnel exposing `localhost:8000`
4. A seeded workspace whose `primary_number` matches the AP number
   (see § Seeding above)
5. Production LLM provider configured (Bedrock or Anthropic direct)

Once seeded, dial the AP number from any mobile — terminal A
(`make run`) will show the webhook arrive, orchestrator turn-loop
logs, and the LLM stream.

**Voice doesn't need 10DLC.** Carrier voice and A2P SMS are separate
regulatory tracks. Voice calls work today on any provisioned
voice-capable AP number, regardless of SMS registration status.

### Why "unknown number" returns 404 (this is correct)

When AP's synthetic test deliveries or any unknown `data.to` hits the
webhook with a phone number not registered to any workspace,
`materialize_scope_and_call` raises `NotFound("unknown_number")` and
the handler returns 404. This is intentional defensive behavior — we
don't want to silently accept webhooks for numbers we don't manage. A
404 with `webhook_unknown_scope` in the logs means the handler worked
correctly; just no scope to dispatch into.

---

## SMS messaging (inbound conversational; outbound gated on 10DLC)

The system handles SMS through the same webhook endpoint as voice. The
**SMS orchestrator** (`app/orchestrator/sms_orchestrator.py`) mirrors
the voice orchestrator's architecture — same retrieval pipeline, same
Redis session store, same tool registry — but adapted for the turn-based,
non-streaming nature of SMS.

> **TL;DR**: Inbound SMS works end-to-end today. Outbound SMS replies
> from the agent **will fail with HTTP 404 from AgentPhone** until you
> complete US-carrier 10DLC registration in the AP dashboard. The handler
> composes the right reply, persists it to the DB, and only fails at the
> very last step (the `POST /v1/messages` call to AP). Once 10DLC clears,
> outbound starts working without a code change.

### Architecture — `SMSOrchestratorHandler`

Registered alongside the voice handler at startup (`app/lifespan.py` calls
`register_sms_with_dispatcher()` after `register_with_dispatcher()`). It
implements the `SMSHandler` protocol and replaces the Phase 0 default
that only logged + dropped non-decision SMS.

Two paths handled per inbound message:

1. **`[DR-XXXXXX] <text>` decision-response** — preserved verbatim from
   Phase 0. Routes to `DecisionService.match_sms_response()` to match
   open decision pings sent by the orchestrator mid-call. No SMS reply
   is sent (the decision result is consumed internally).

2. **Conversational orchestration** — everything else. Runs the full
   loop described in [Hot path — one inbound SMS](#hot-path--one-inbound-sms).

### What's different from voice (intentionally)

| Concern | Voice | SMS |
|---|---|---|
| Trigger | `agent.message:voice` per turn | `agent.message:sms` (channel `sms`/`mms`/`imessage`) |
| Latency budget | <30s AP webhook timeout, target <2s | none — fire-and-forget reply via `send_sms` |
| Streaming | NDJSON chunks back over the webhook HTTP response | one-shot accumulated reply, single outbound API call |
| Bridge chunks | yes (~300ms deadline) | no — no caller listening to silence |
| Speculative retrieval | yes (races against 150ms) | no — retrieval is awaited in full |
| Tool subset | `request_manager_decision`, `end_call`, `request_correction` | **`request_manager_decision` only** (no `end_call` — SMS has no "call" to end) |
| Session lifecycle | `agent.call_ended` closes the session | no end event — SMS conversations stay `in_progress` indefinitely |
| Call row key | `agentphone_call_id = <AP callId>` (with `ap_<numberId>_<ts>` synthetic fallback for null-callId voice turns) | `agentphone_call_id = sms_<ap_conversation_id>` (AP supplies a stable `conversationId` for SMS, unlike voice) |
| Prompt | `skills/orchestrator/` (warm + curious interviewer) | inline SMS-tuned prompt: "text not voice, 1-2 sentences, no greetings/sign-offs after first message" |

### What 10DLC is and why it blocks outbound

**10DLC = "10-Digit Long Code"** — the US carrier compliance regime for
sending application-to-person (A2P) SMS from regular 10-digit phone
numbers like `+14783304859`. Since 2021, AT&T / Verizon / T-Mobile
require every A2P sender to register their brand + use case via The
Campaign Registry (TCR) before the carriers will deliver outbound
messages. AgentPhone enforces this upstream by refusing the
`POST /v1/messages` call when an account hasn't completed registration.

What's affected:

| Path | Blocked by 10DLC? |
|---|---|
| Inbound voice | No (voice is a separate carrier track) |
| Inbound SMS / MMS / iMessage | **No** — receiving doesn't require registration |
| Outbound voice (not in scope yet) | No |
| **Outbound SMS from the SMS orchestrator** | **Yes** |
| **Outbound SMS for decision pings** (`DecisionService._send_sms_ping`) | **Yes** — managers won't receive SMS prompts mid-call until 10DLC clears |

So in plain terms: callers can text the AP number and the system will
**reason about** the message correctly (you'll see the agent's intended
reply in the DB and the uvicorn log), but the SMS-reply step won't reach
the caller's phone.

The exact failure visible in the log on a non-10DLC account:

```
{"event":"sms_reply_send_failed", "workspace_id":"...", "to_number":"+1...",
 "exception":"...UpstreamError: agentphone rejected POST /messages: 404"}
```

### How to enable outbound (one-time, account-level)

1. Log into the AgentPhone dashboard.
2. Find **"Brand & Campaign Registration"** / **"SMS Compliance"** / **"10DLC"**.
3. Submit a **Brand**: EIN/SSN, legal entity name, address, contact, website.
   Costs ~$4/mo + a one-time TCR vetting fee (~$15-40 depending on tier).
4. Submit a **Campaign** describing the use case (for VotF: "Conversational
   customer / field-employee communication"). Costs ~$10/mo per campaign.
   Include sample messages + opt-in flow description.
5. AP submits brand + campaign to TCR → TCR submits to carriers → carriers
   approve (24h-2 weeks; conversational/customer-care campaigns approve
   fastest, marketing/promo slowest).
6. Once approved, AP flips the account's `outbound_sms_enabled` flag
   server-side. **No code change needed** — the existing
   `telephony.send_sms()` call starts returning 200 instead of 404.

### Workarounds while 10DLC clears

| Option | Tradeoff |
|---|---|
| **Toll-free number** (`+1-800-…`) | Different verification track (TFN form, not 10DLC). Often approved in 1-3 days. AP supports buying toll-free numbers if your account permits. Outbound rates higher than 10DLC. |
| **iMessage line** | iMessage isn't subject to 10DLC. But it's iMessage-only — won't reach Android users — and AP-managed shared iMessage pool numbers can't be reconfigured to add voice. |
| **Stay inbound-only** | Capture SMS, reason about them, surface in FE/email/dashboard — but don't reply via SMS. Reasonable Phase 0 demo posture. |
| **Voice-only demo** | What we know works end-to-end today. No 10DLC; calls fire on the existing dedicated voice number. |

### Testing the inbound path WITHOUT 10DLC

You can fully exercise the SMS orchestrator without sending a real text —
the included synthetic-webhook approach signs a payload exactly like AP's
real one. Useful when iterating on the prompt, tool subset, or persistence
logic.

```bash
set -a && source .env.local && set +a

cat > /tmp/sim_sms.py <<'PYEOF'
import asyncio, json, os, time, uuid, httpx
from app.security.hmac import compute_signature

BASE="http://localhost:8000"; WEBHOOK="/api/v1/webhooks/agentphone"
SECRET=os.environ["AGENTPHONE_WEBHOOK_SECRET"]
CONV_ID=f"sms_test_{int(time.time())}"

async def send(body):
    payload = {
      "event":"agent.message","channel":"sms",
      "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S.000000Z", time.gmtime()),
      "agentId":"<YOUR_AP_AGENT_ID>",
      "data":{"conversationId":CONV_ID,"numberId":"<YOUR_AP_NUMBER_ID>",
              "from":"+17653506634","to":"+14783304859","body":body},
      "conversationState":None,
    }
    raw=json.dumps(payload).encode(); ts=str(int(time.time()))
    headers={"Content-Type":"application/json; charset=utf-8",
             "X-Webhook-Signature":compute_signature(raw,ts,SECRET),
             "X-Webhook-Timestamp":ts,"X-Webhook-Id":str(uuid.uuid4()),
             "X-Webhook-Event":"agent.message"}
    async with httpx.AsyncClient(timeout=60.0) as c:
        r = await c.post(BASE+WEBHOOK, content=raw, headers=headers)
    print(f">>> {body!r}  →  HTTP {r.status_code}")

asyncio.run(send("Hey - just hung up with Acme. They want 15% off the renewal."))
PYEOF

# Run from the repo root so app.* imports resolve
cp /tmp/sim_sms.py ./sim_sms.py
uv run python sim_sms.py
rm sim_sms.py
```

Expected outcome on a non-10DLC account:

- HTTP 200 from the webhook (we always return 200 so AP doesn't retry).
- Uvicorn log shows `sms_conversation_started` + a Supermemory search + a
  Bedrock invoke + `sms_reply_send_failed` with the AP 404 traceback.
- DB has both the inbound fragment AND the LLM-composed agent reply
  persisted under the synthetic Call row.

Inspect the DB:

```bash
docker exec vof_backend-postgres-1 psql -U votf -d votf_app -c "
SELECT c.agentphone_call_id, tf.seq, tf.speaker, LEFT(tf.text, 200)
FROM calls c JOIN transcript_fragments tf ON tf.call_id = c.id
WHERE c.agentphone_call_id LIKE 'sms_%'
ORDER BY c.started_at, tf.seq;"
```

You'll see exchanges like:

```
sms_sms_test_…  | 1 | caller | Hey - just hung up with Acme. They want 15% off the renewal.
sms_sms_test_…  | 2 | agent  | What's the current contract value and renewal date for Acme?
```

This proves the orchestrator path is sound; the only remaining gap is
the carrier-side delivery.

### Testing with a real phone (10DLC-aware)

Once uvicorn + ngrok + a seeded workspace are running (see
[§ Live end-to-end testing](#live-end-to-end-testing-real-phone-call)):

1. Text the AP voice/SMS-capable number (e.g. `+14783304859`) from your phone.
2. Watch terminal A for `sms_conversation_started`, then either
   `sms_reply_sent` (10DLC live) or `sms_reply_send_failed` (10DLC pending).
3. Confirm both turns landed in `transcript_fragments`.
4. If 10DLC is live: you should receive the SMS reply within ~3-5s.
5. If not: the orchestrator did its job; AP is the gate.

### Multi-channel support

The same handler serves `channel ∈ {sms, mms, imessage}` because AP
delivers all of them as `agent.message` with the `channel` discriminator.
For Phase 0 we don't branch on channel — same retrieval, same prompt,
same reply path. Phase 1 can add per-channel formatting (e.g. iMessage
tapbacks, MMS attachments) without rearchitecting.

### What's NOT shipped yet

- **iMessage-specific affordances** (tapbacks, attachments) — webhook
  events arrive (`agent.reaction`) but no-op in Phase 0.
- **Per-Workspace SMS opt-in/out config** — every workspace that has SMS
  capability uses the orchestrator. Phase 1 spec (§D7 email composer is
  the precedent) calls for per-Workspace `config.sms.enabled` flags.
- **SMS conversation idle timeout** — SMS Call rows stay `in_progress`
  forever today (no `agent.call_ended` for SMS). A nightly job to close
  rows untouched for >24h is a Phase 1 polish item.
- **Outbound SMS for new-thread initiation** — the orchestrator only
  replies to inbound. Proactive SMS (e.g. nudging a Rep about a missed
  decision) would route through `DecisionService._send_sms_ping`, also
  10DLC-gated.

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
| LLM call returns body `{"Output":{"__type":"...UnknownOperationException"}}` | hit the wrong Bedrock URL path | the production code uses `invoke_model` not `/v1/chat/completions`; this only appears if you curl manually |
| `caller_a_does_not_see_caller_b_memory` FAIL | Supermemory ignoring tag filter | privacy-critical — **stop, don't deploy**; investigate SDK version + dashboard config |
| `container_tags_or_semantics_documented` FAIL with "AND-matching" | Supermemory changed semantics | good news — revisit `Retriever.for_turn`; the workaround can be reverted |
| AgentPhone `test_webhook_delivery` FAIL 401 | uvicorn started with empty `AGENTPHONE_WEBHOOK_SECRET` | restart `make run` after `set -a && source .env.local && set +a` |
| AgentPhone `test_webhook_delivery` FAIL 500 | downstream dep down (Redis/Postgres) | check terminal A traceback + `make compose-up` |
| AgentPhone call says "experiencing technical difficulties" + ngrok `ttl` doesn't bump | number is `shared-imessage` or per-agent webhook missing | provision a dedicated voice number; register per-agent webhook |
| AgentPhone `outbound_sms_capability` FAIL with `Outbound SMS is not enabled` | account hasn't completed 10DLC registration | **expected on a fresh account** — see [§ SMS messaging → How to enable outbound](#how-to-enable-outbound-one-time-account-level). Voice + inbound SMS still work; this only blocks outbound SMS |
| AgentPhone `outbound_sms_capability` FAIL with `/messages` 404 after 10DLC done | 10DLC campaign still pending carrier approval, or `SMOKE_AGENTPHONE_TEST_AGENT_ID` is stale | check campaign approval status in AP dashboard; verify agent id with `curl GET /v1/agents/{id}` |
| `conversation_state_roundtrip` FAIL 404 | `SMOKE_AGENTPHONE_TEST_CONVERSATION_ID` stale | dial AP number once to create a fresh conversation, save id |
| Texted AP number → uvicorn logs `sms_conversation_started` but no SMS reply on phone | 10DLC outbound is blocked at AP | **expected** — handler did its job; reply is in `transcript_fragments` but never reached the carrier. Complete 10DLC to enable outbound. See [§ SMS messaging](#sms-messaging-inbound-conversational--outbound-gated-on-10dlc) |
| Texted AP number → no `sms_conversation_started` log entry at all | scope resolution failed (no workspace matches the AP number) or ngrok tunnel down | check `webhook_unknown_scope` warning + the seed (`primary_number` and `agentphone_number_id` columns); verify `ngrok` tunnel reachable |
| `sms_reply_send_failed` with `agentphone rejected POST /messages: 404` | 10DLC not enabled (same root cause as above) | this is the exact 10DLC error AP returns — see [§ SMS messaging](#sms-messaging-inbound-conversational--outbound-gated-on-10dlc) |
| `[DR-XXXXXX]` SMS reply from Manager — no decision matched | decision id stale or never opened, or sender phone doesn't match Workspace.manager_user_id | check `inbound_sms_dr_no_match` log; verify `DecisionRequest` row exists with matching id |
| iMessage from a phone via shared-imessage AP number | works as inbound but the AP-managed shared pool can't have voice added and won't reach Android | use a dedicated voice+SMS number, not the shared-imessage pool number |
| Slow `object_storage` probe (~9s) | first MinIO call cold-start under parallel probe load | harmless; subsequent calls are <50ms |
| `docker compose up` web exits with `FATAL: password authentication failed` | stale `pg_data/` volume from a prior init | `docker compose down -v && docker compose up --build` |
| Lifespan log shows `*_close_failed` warnings on shutdown | one of the cached singletons errored on close | non-fatal; other clients still drained. Check the traceback for which adapter |

For full troubleshooting + production triage, see
`lld/phase_0_scaffolding_and_mvp.md` §B12.
