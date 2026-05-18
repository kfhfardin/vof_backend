# Phase 0 — Low-Level Design

**Scope:** Project scaffolding + the MVP loop + smoke-test framework.
**Source HLD:** `voice_of_the_field_hld.md` v0.6 — Phase 0 priorities #1–#12.
**Audience:** Engineers implementing this phase. Read once end-to-end before coding; refer back per component.

> This LLD is split into three parts:
> - **Part A — Scaffolding** (the "real" Phase 0 below the HLD's Phase 0): folder layout, app factory, config, DB, auth, testing, CI, deployment profiles.
> - **Part B — Smoke Probe Framework** (HLD §12, priority #12): independent verification of every third-party + infra integration, with explicit hot-path verification scripts.
> - **Part C — MVP Loop** (HLD priorities #1–#10): signup → intake → call → decision loop, with provenance/correction/skills/guard-test baked in from day one.
>
> Parts A and B are prerequisites for Part C. They should land in main before any feature work in Part C starts.

---

## Table of Contents

- [Part A — Scaffolding](#part-a--scaffolding)
  - [A1. Repository Layout](#a1-repository-layout)
  - [A2. Configuration & Settings](#a2-configuration--settings)
  - [A3. FastAPI Application Factory](#a3-fastapi-application-factory)
  - [A4. Database Stack (App DB + Brain DB)](#a4-database-stack-app-db--brain-db)
  - [A5. Redis + arq Worker Layer](#a5-redis--arq-worker-layer)
  - [A6. Object Storage Abstraction](#a6-object-storage-abstraction)
  - [A7. Auth — JWT, OAuth2 Password + Refresh](#a7-auth--jwt-oauth2-password--refresh)
  - [A8. Error Handling & Standard Responses](#a8-error-handling--standard-responses)
  - [A9. Logging, Tracing, Metrics](#a9-logging-tracing-metrics)
  - [A10. Skills Loader & Registry](#a10-skills-loader--registry)
  - [A11. Extension-Point Registries (Tools, MiniAgents, Connectors, Telephony, Memory, Brain)](#a11-extension-point-registries)
  - [A12. Testing Strategy](#a12-testing-strategy)
  - [A13. Lint / Format / Type-check / Pre-commit / CI](#a13-lint--format--type-check--pre-commit--ci)
  - [A14. docker-compose.local.yml + Local Dev](#a14-docker-composelocalyml--local-dev)
  - [A15. Deployment Profile Switch (local vs cloud)](#a15-deployment-profile-switch-local-vs-cloud)
- [Part B — Smoke Probe Framework](#part-b--smoke-probe-framework)
  - [B1. `Probe` Base Class](#b1-probe-base-class)
  - [B2. AgentPhoneProbe](#b2-agentphoneprobe)
  - [B3. SupermemoryProbe](#b3-supermemoryprobe)
  - [B4. LLMProbe (OpenAI-compat)](#b4-llmprobe-openai-compat)
  - [B5. AppPostgresProbe](#b5-apppostgresprobe)
  - [B6. BrainPostgresProbe](#b6-brainpostgresprobe)
  - [B7. RedisProbe](#b7-redisprobe)
  - [B8. ObjectStorageProbe](#b8-objectstorageprobe)
  - [B9. Aggregating Runner + Manifest](#b9-aggregating-runner--manifest)
  - [B10. CI Wiring](#b10-ci-wiring)
  - [B11. Hot-Path Verification Scripts](#b11-hot-path-verification-scripts)
  - [B12. Operator Setup & First-Run Verification Checklist](#b12-operator-setup--first-run-verification-checklist)
- [Part C — MVP Loop](#part-c--mvp-loop)
  - [C1. Manager Signup + Workspace Provisioning (priorities 1–2)](#c1-manager-signup--workspace-provisioning)
  - [C2. Onboarding Intake Pipeline (priority 3)](#c2-onboarding-intake-pipeline)
  - [C3. Telephony Adapter — AgentPhone (priority 4a)](#c3-telephony-adapter--agentphone)
  - [C4. Orchestrator + Hot-Path Streaming (priority 4b)](#c4-orchestrator--hot-path-streaming)
  - [C5. Multi-Call Live WebSocket (priority 5)](#c5-multi-call-live-websocket)
  - [C6. Decision Loop (priority 6)](#c6-decision-loop)
  - [C7. Decision Timeout & Brief-Flagging Skeleton (priority 7)](#c7-decision-timeout--brief-flagging-skeleton)
  - [C8. Correction & Provenance Scaffolding (priority 8)](#c8-correction--provenance-scaffolding)
  - [C9. Skills Directory + Eval CI (priority 9)](#c9-skills-directory--eval-ci)
  - [C10. Hierarchy Guard Test (priority 10)](#c10-hierarchy-guard-test)
  - [C11. Minimum Post-Call Writeback (closes the compounding loop)](#c11-minimum-post-call-writeback)

---

# Part A — Scaffolding

## A1. Repository Layout

The repo is **monorepo Python** with three top-level packages and shared infra. Mirrors HLD §5.6 module structure, expanded with the cross-cutting pieces.

```
vof_backend/
├── pyproject.toml                # uv/pip; single source for deps + tool config
├── uv.lock                       # locked deps
├── README.md
├── voice_of_the_field_hld.md
├── lld/
│   ├── phase_0_scaffolding_and_mvp.md   # this file
│   ├── phase_1_durability.md
│   └── phase_2_productivity.md
├── docker-compose.local.yml      # Postgres × 2 + Redis + MinIO (§A14)
├── .env.example                  # template; never .env in git
├── .env.local                    # gitignored
├── .pre-commit-config.yaml
├── .github/workflows/
│   └── ci.yml                    # MVP: lint + unit + thin integration on PR (§A13)
├── Makefile                      # `make smoke`, `make verify-hot-path`, `make e2e` — human-run (§B10)
│
├── app/                          # the FastAPI service + Orchestrator + workers (the product)
│   ├── __init__.py
│   ├── main.py                   # `uvicorn app.main:app`
│   ├── factory.py                # build_app() — used by main, tests, scripts
│   ├── settings.py               # pydantic-settings — §A2
│   ├── deps.py                   # FastAPI deps: db, redis, current_user, workspace scope
│   ├── errors.py                 # exception types + handlers — §A8
│   ├── logging.py                # structlog/OTel bootstrap — §A9
│   ├── lifespan.py               # startup/shutdown: registries warm-up, pool init
│   │
│   ├── api/                      # FastAPI routers — HLD §5.6
│   │   ├── __init__.py           # auto-discovery walker
│   │   ├── auth.py
│   │   ├── me.py
│   │   ├── webhooks/
│   │   │   ├── __init__.py
│   │   │   └── agentphone.py     # the AP webhook endpoint
│   │   ├── workspaces/           # Phase 0 implementation
│   │   │   ├── __init__.py
│   │   │   ├── config.py
│   │   │   ├── data_sources.py
│   │   │   ├── field_employees.py
│   │   │   ├── calls.py
│   │   │   ├── decisions.py
│   │   │   ├── action_items.py
│   │   │   ├── brain.py
│   │   │   ├── intake.py
│   │   │   ├── dashboards.py
│   │   │   └── ws.py             # /workspaces/{wid}/ws/live multiplex
│   │   ├── organizations/        # reserved namespace, empty router
│   │   │   └── __init__.py
│   │   └── rep/                  # reserved namespace, empty router
│   │       └── __init__.py
│   │
│   ├── schemas/                  # Pydantic v2 DTOs — request/response models
│   │   ├── auth.py
│   │   ├── workspace.py
│   │   ├── call.py
│   │   ├── decision.py
│   │   ├── intake.py
│   │   ├── brain.py
│   │   └── ws_frames.py          # WebSocket frame schemas — §C5
│   │
│   ├── services/                 # business logic, called by routers — no FastAPI in here
│   │   ├── auth_service.py
│   │   ├── workspace_provisioning.py
│   │   ├── intake_processor.py
│   │   ├── intake_extractors/    # one module per SupportedUpload — §C2
│   │   │   ├── __init__.py       # SupportedUpload enum + registry + resolve(mime, ext)
│   │   │   ├── base.py           # IntakeExtractor Protocol, ExtractedContent
│   │   │   ├── pdf_extractor.py
│   │   │   ├── docx_extractor.py
│   │   │   ├── text_extractor.py
│   │   │   ├── csv_extractor.py
│   │   │   ├── xlsx_extractor.py
│   │   │   └── json_extractor.py
│   │   ├── decisions.py
│   │   ├── corrections.py
│   │   └── retrieval.py          # hybrid retrieval used by Orchestrator
│   │
│   ├── db/                       # data layer — §A4
│   │   ├── base.py               # declarative Base, naming convention
│   │   ├── app_session.py        # AsyncSession factory for the App DB
│   │   ├── brain_session.py      # AsyncSession factory for the Brain DB, schema-aware
│   │   ├── workspace_router.py   # schema-per-Workspace switch
│   │   ├── models/               # SQLAlchemy 2.x mapped classes
│   │   │   ├── __init__.py
│   │   │   ├── organization.py
│   │   │   ├── workspace.py
│   │   │   ├── user.py
│   │   │   ├── field_employee.py
│   │   │   ├── call.py
│   │   │   ├── transcript.py
│   │   │   ├── decision.py
│   │   │   ├── action_item.py
│   │   │   ├── intake_buffer.py
│   │   │   ├── provenance.py
│   │   │   └── brain_page.py     # lives in brain schema; tagged with `__table_args__={"schema": ...}`
│   │   ├── repositories/         # one class per aggregate; the only place SQL lives
│   │   │   ├── workspace_repo.py
│   │   │   ├── call_repo.py
│   │   │   ├── decision_repo.py
│   │   │   └── brain_repo.py
│   │   └── unit_of_work.py       # async context manager wrapping repos + transaction
│   │
│   ├── migrations/               # Alembic — §A4
│   │   ├── env.py                # multi-DB aware (App + Brain)
│   │   ├── script.py.mako
│   │   ├── versions_app/
│   │   └── versions_brain/
│   │
│   ├── workers/                  # arq workers — §A5
│   │   ├── __init__.py
│   │   ├── settings.py           # WorkerSettings classes per queue
│   │   ├── post_call.py
│   │   ├── brain_maintenance.py
│   │   ├── data_source_sync.py
│   │   ├── correction_cascade.py
│   │   ├── action_item_followup.py
│   │   └── decision_timeout.py   # §C7
│   │
│   ├── orchestrator/             # the live-call engine — §C4
│   │   ├── session.py            # CallSession state object (Redis-backed)
│   │   ├── turn_loop.py
│   │   ├── streaming.py          # NDJSON streamer to AP, bridge-chunk emitter
│   │   ├── retrieval.py          # parallel CallerMemory + Brain fetch
│   │   ├── prompts.py            # render orchestrator/turn_prompt.j2
│   │   └── tools/                # OrchestratorTool implementations
│   │       ├── __init__.py
│   │       ├── request_manager_decision.py
│   │       ├── web_research.py   # stub in Phase 0
│   │       ├── request_correction.py
│   │       ├── mark_followup.py
│   │       ├── fetch_account.py
│   │       └── end_call.py
│   │
│   ├── telephony/                # TelephonyProvider impls — §C3
│   │   ├── base.py               # TelephonyProvider ABC + event dataclasses
│   │   ├── agentphone.py         # AgentPhoneAdapter + verify_webhook helper
│   │   └── events.py             # InboundVoiceTurn / InboundSMS / CallEnded
│   │
│   ├── memory/                   # CallerMemoryProvider impls — HLD §8.6
│   │   ├── base.py
│   │   └── supermemory.py
│   │
│   ├── brain/                    # BrainProvider impls — HLD §8.6
│   │   ├── base.py
│   │   ├── postgres_brain.py     # pgvector + tsvector + RRF
│   │   └── entity_extractor.py   # regex; zero-LLM extraction
│   │
│   ├── miniagents/               # MiniAgent impls — HLD §8.2
│   │   ├── base.py
│   │   ├── classifier.py         # wraps the classifier skill
│   │   ├── brain_seeder.py
│   │   ├── caller_profiler.py
│   │   └── researcher.py         # stubbed in Phase 0
│   │
│   ├── connectors/               # DataSourceConnector impls — HLD §8.3
│   │   ├── base.py
│   │   ├── manual_upload.py      # Phase 0: only-source-shipped
│   │   └── registry.py
│   │
│   ├── skills/                   # the loader; the skill content lives in /skills (sibling)
│   │   ├── base.py               # Skill, LLMSkill, SkillRegistry — §A10
│   │   ├── loader.py
│   │   └── llm_client.py         # Anthropic SDK + provider abstraction
│   │
│   ├── realtime/                 # WS hub + transcript bus — §C5
│   │   ├── bus.py                # Redis pub/sub wrapper
│   │   └── ws_hub.py             # per-Workspace fan-out
│   │
│   ├── security/
│   │   ├── jwt.py                # encode/decode, claims
│   │   ├── hashing.py            # passlib bcrypt
│   │   └── hmac.py               # AP webhook verify
│   │
│   └── observability/
│       ├── otel.py
│       └── metrics.py
│
├── skills/                       # prompts as first-class artifacts — HLD §8.7
│   ├── classifier/
│   │   ├── SKILL.md
│   │   ├── prompt.j2
│   │   ├── schema.py
│   │   ├── fixtures/
│   │   ├── evals/
│   │   │   ├── golden_set.jsonl
│   │   │   └── run.py
│   │   └── CHANGELOG.md
│   ├── orchestrator/
│   │   ├── SKILL.md
│   │   ├── system_prompt.j2
│   │   ├── turn_prompt.j2
│   │   ├── schema.py
│   │   ├── fixtures/
│   │   ├── evals/
│   │   └── CHANGELOG.md
│   └── caller_profiler/
│       └── ... (same layout)
│
├── smoke/                        # independent probes — HLD §12 / §B
│   ├── __init__.py
│   ├── _base.py                  # Probe, CheckResult, ProbeReport, ExitCode
│   ├── _runner.py                # `python -m smoke run --all`
│   ├── agentphone.py
│   ├── supermemory.py
│   ├── llm.py
│   ├── postgres_app.py
│   ├── postgres_brain.py
│   ├── redis.py
│   ├── object_storage.py
│   ├── fixtures/
│   │   ├── sample_audio.wav
│   │   └── sample_doc.pdf
│   └── manifests/
│       └── probes.yaml
│
├── scripts/                      # one-shot operator + dev scripts
│   ├── verify_hot_path.py        # §B11 — full call-turn simulation
│   ├── simulate_inbound_voice.py # §B11 — POST a synthetic AP voice webhook to local app
│   ├── seed_dev_workspace.py     # creates a test Workspace with sample roster
│   ├── new_skill.py              # scaffold a new skills/<name>/ directory
│   └── alembic_wrapper.py        # multi-DB Alembic dispatcher
│
└── tests/
    ├── conftest.py               # async-pytest, db fixtures, app fixture
    ├── unit/
    │   ├── orchestrator/
    │   ├── intake/
    │   ├── brain/
    │   └── skills/
    ├── integration/              # touches real Postgres+Redis from compose; mocks 3rd-party SaaS
    │   ├── api/
    │   ├── workers/
    │   └── telephony/
    ├── e2e/                      # full stack against compose + fake-AP server
    │   ├── test_signup_to_first_call.py
    │   └── test_decision_loop_end_to_end.py
    └── load/                     # hot-path latency budget — see HLD §15
        └── test_turn_latency.py
```

**Rationale highlights:**
- `app/` is the single deployable. `uvicorn app.main:app` serves it; `arq app.workers.settings.PostCallWorker` runs each queue. No "monolith vs microservices" debate at Phase 0 — one process boundary.
- `skills/` is a **sibling** of `app/`, not under it. Skill files are loaded from disk by path; treating them as a data directory makes the "skills are code" principle visible (separate from Python package code) while still being version-controlled together.
- `smoke/` is a **sibling** of `app/`. It must run standalone — its only `app/` dependency is the HMAC verifier import (B2). No accidental coupling.
- `scripts/` holds operator-facing one-shots that are not part of the running service but live in the repo for reproducibility (HLD §12 calls these out).

## A2. Configuration & Settings

**Single settings class** in `app/settings.py`, built on `pydantic-settings`. Reads `.env` files merged with process env. Validates at startup; failure to validate exits with code 2 (matches the smoke-probe CONFIG semantics in §B).

```python
# app/settings.py
class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=(".env", ".env.local"), extra="ignore")

    # Profile
    deployment_profile: Literal["local", "cloud"]
    environment: Literal["dev", "staging", "prod"]

    # Databases
    database_url: PostgresDsn
    brain_database_url: PostgresDsn
    redis_url: RedisDsn

    # Object storage
    s3_bucket: str
    s3_access_key: SecretStr
    s3_secret_key: SecretStr
    s3_region: str = "us-east-1"
    s3_endpoint_url: HttpUrl | None = None      # set for R2/MinIO; empty = real AWS

    # Auth
    jwt_secret: SecretStr
    jwt_access_ttl_seconds: int = 3600
    jwt_refresh_ttl_seconds: int = 60 * 60 * 24 * 30
    jwt_algorithm: str = "HS256"

    # Third-party
    agentphone_api_key: SecretStr
    agentphone_webhook_secret: SecretStr
    supermemory_api_key: SecretStr
    anthropic_api_key: SecretStr

    # LLM (mirrors smoke probe vars so the same env powers both)
    llm_base_url: HttpUrl = "https://api.anthropic.com/v1/openai"
    llm_default_model: str = "claude-sonnet-4-6"   # production code uses native SDK, this is a fallback

    # CORS / public URLs
    public_base_url: HttpUrl
    cors_allow_origins: list[HttpUrl] = []

    # Observability
    otel_exporter_endpoint: HttpUrl | None = None
    log_level: Literal["DEBUG", "INFO", "WARN", "ERROR"] = "INFO"
```

**Access pattern:** `get_settings()` returns a cached singleton (`@lru_cache`). Never instantiate `Settings()` directly elsewhere.

**Edge cases:**
- Missing required env → `ValidationError` at import time; surfaced as exit code 2.
- `deployment_profile=local` but `s3_endpoint_url` empty → validation rule rejects: local profile must use MinIO/R2 endpoint.
- `jwt_secret` shorter than 32 bytes → reject.

**Tests:** `tests/unit/test_settings.py` — load happy path; assert each validation rule; assert `SecretStr` fields don't leak via `repr()`.

## A3. FastAPI Application Factory

```python
# app/factory.py
def build_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    app = FastAPI(
        title="Voice of the Field",
        version=read_version(),
        lifespan=lifespan,
        docs_url="/docs" if settings.environment != "prod" else None,
        openapi_url="/openapi.json" if settings.environment != "prod" else None,
    )
    register_middleware(app, settings)
    register_exception_handlers(app)
    register_routers(app)              # auto-discovery walker (§A1)
    instrument_otel(app, settings)
    return app

app = build_app()
```

**Middleware order (outermost first):**
1. `OTelASGIMiddleware` — trace span per request, with `workspace_id` baggage.
2. `CORSMiddleware` — origins from settings.
3. `RequestIdMiddleware` — generate `X-Request-Id` if absent; bind to logger context.
4. `BodySizeLimitMiddleware` — 25 MB default; tighter for non-upload routes.

**Router auto-discovery** (`app/api/__init__.py`):

```python
def register_routers(app: FastAPI) -> None:
    for module_name in _walk_routers("app.api"):
        module = importlib.import_module(module_name)
        router = getattr(module, "router", None)
        if router is None:
            continue
        app.include_router(router, prefix="/api/v1")
    # Reserve org/rep namespaces explicitly so the §C10 guard test can hit them
    app.include_router(organizations_router, prefix="/api/v1/organizations", tags=["reserved"])
    app.include_router(rep_router, prefix="/api/v1/rep", tags=["reserved"])
```

Each router file declares `router = APIRouter(prefix=..., tags=..., dependencies=[Depends(require_workspace_access)])`.

**Lifespan** (`app/lifespan.py`): on startup, eagerly instantiate the singleton registries (Tool, MiniAgent, Connector, Telephony, Memory, Brain — see §A11), open the DB pool warm-ups, ping Redis. Fail fast on any failure. On shutdown, close pools and flush log buffers.

## A4. Database Stack (App DB + Brain DB)

Two logical databases per HLD §5.8. Both Postgres 16; in dev they're two databases in one cluster, in prod they're typically two managed instances. Always referenced via the two URLs `DATABASE_URL` / `BRAIN_DATABASE_URL`.

**ORM:** SQLAlchemy 2.x with `Mapped[]` syntax. Async only (`asyncpg` driver).

**Sessions:**

```python
# app/db/app_session.py
_engine = create_async_engine(settings.database_url.unicode_string(), pool_size=10, max_overflow=20)
_session_factory = async_sessionmaker(_engine, expire_on_commit=False)

@asynccontextmanager
async def app_session() -> AsyncIterator[AsyncSession]:
    async with _session_factory() as s:
        yield s

# app/db/brain_session.py
_brain_engine = create_async_engine(settings.brain_database_url.unicode_string(), pool_size=10, max_overflow=20)
_brain_factory = async_sessionmaker(_brain_engine, expire_on_commit=False)

@asynccontextmanager
async def brain_session(workspace_id: UUID) -> AsyncIterator[AsyncSession]:
    async with _brain_factory() as s:
        # Pin the search_path for this session to the Workspace's brain schema
        await s.execute(text(f'SET LOCAL search_path TO "brain_w_{workspace_id}", public'))
        yield s
```

**Workspace router** (`app/db/workspace_router.py`):
- Idempotent `ensure_brain_schema(workspace_id)` — creates `brain_w_{wid}` if absent and applies all brain-schema migrations into it (Alembic `versions_brain/` reused with schema parameter).
- `with_workspace(workspace_id)` async ctx manager — wraps `brain_session(workspace_id)` + acquires an advisory lock on `hashtext('brain_w_' || workspace_id)` for migration-safe operations.

**Migrations (Alembic):**
- Two version directories: `versions_app/` and `versions_brain/`.
- `scripts/alembic_wrapper.py app|brain upgrade head` dispatches to the right one.
- For brain migrations: a custom command `python -m scripts.alembic_wrapper brain upgrade --all-workspaces` iterates `ManagerWorkspace` rows and runs `versions_brain/` against each `brain_w_{wid}` schema. Used in deploy.
- `tests/conftest.py` truncates between tests with `TRUNCATE ... RESTART IDENTITY CASCADE`; per-test transaction rollback is **not** used because async fixtures + advisory-locked schema operations don't compose with it cleanly.

**Naming convention** (`app/db/base.py`): set `MetaData(naming_convention=...)` so generated constraint names are predictable across migrations (`ix_`, `fk_`, `ck_`).

**Unit of Work** (`app/db/unit_of_work.py`): a small wrapper bundling `app_session()` + per-aggregate repositories. Routers use it; services accept a UoW or specific repos for testability.

**Workspace-aware DB wrapper (HLD §14.4 risk).** The brain-schema search-path pin is enforced by `brain_session(workspace_id)`. Cross-Workspace queries are impossible unless someone bypasses the wrapper. A repo-level lint check (`tools/lint_unscoped_queries.py`) greps for `await session.execute(text(...))` outside `app/db/` and fails CI — the only place raw SQL is allowed is the repositories layer.

**Tests:**
- `tests/integration/db/test_workspace_isolation.py` — create two Workspaces; insert into one's brain; assert the other can't read it via either schema-search-path bug or row-leak.
- `tests/integration/db/test_migrations_brain_multi.py` — run brain migrations against three Workspaces, assert each schema has identical structure.

## A5. Redis + arq Worker Layer

**One Redis cluster, namespaced keys.** Namespace prefixes:
| Prefix | Use |
|---|---|
| `session:call:{call_id}` | Orchestrator call state (HLD §5.4) |
| `call:{call_id}:transcript` | Pub/sub channel for transcript bus |
| `call:{wid}:active` | Set of active call IDs per Workspace |
| `seen_webhooks` | Idempotency set, TTL ≥7 days |
| `decision:{decision_id}` | DecisionRequest in-flight cache |
| `arq:*` | arq's own queue keys |

**Connection:** `app/realtime/bus.py` exposes `redis()` returning a `redis.asyncio.Redis` from a shared pool. arq uses its own pool (its `RedisSettings`).

**Workers:** one `WorkerSettings` per queue in `app/workers/settings.py`. Deploy runs one process per worker class, scaled by demand. Each handler:
- Accepts `(ctx, ...payload)` per arq convention.
- Idempotent by passing a stable `_job_id` at enqueue time (e.g., `post_call:{call_id}`).
- Wraps body in an OTel span named after the queue.

**Worker registry (Phase 0):**
| Queue | Handler module | Enqueue trigger | Retry policy |
|---|---|---|---|
| `post_call` | `workers/post_call.py` | `agent.call_ended` webhook | 3 retries, exponential backoff 5s/30s/3m |
| `brain_maintenance` | `workers/brain_maintenance.py` | Cron, nightly per Workspace | 1 retry |
| `data_source_sync` | `workers/data_source_sync.py` | Onboarding intake; cron incremental | 3 retries |
| `correction_cascade` | `workers/correction_cascade.py` | After each `CorrectionIntake` commit | 5 retries |
| `decision_timeout` | `workers/decision_timeout.py` | Scheduled per DecisionRequest | no retry (idempotent close) |

**Edge cases:**
- arq enqueue when Redis is down → API returns 503 with a `degraded` reason; webhook handlers respond 500 (AP retries per HLD §11.2.3, 6 attempts over 21h).
- Duplicate webhook → `seen_webhooks` set dedup; second arrival short-circuits to 200.

**Tests:**
- `tests/integration/workers/test_idempotency.py` — enqueue same `_job_id` twice; assert handler runs once.
- `tests/integration/workers/test_post_call_chain.py` — Phase 1 stub-handlers in Phase 0; assert fan-out call graph.

## A6. Object Storage Abstraction

```python
# app/storage/base.py  (lives under app/, omitted from A1 tree above; place under app/storage/)
class ObjectStore(Protocol):
    async def put(self, key: str, data: BinaryIO | bytes, content_type: str) -> str: ...
    async def get(self, key: str) -> AsyncIterator[bytes]: ...
    async def delete(self, key: str) -> None: ...
    async def signed_url(self, key: str, ttl_seconds: int = 900, method: Literal["GET", "PUT"] = "GET") -> str: ...

# app/storage/s3.py
class S3ObjectStore: ...           # uses aiobotocore; configured by Settings
```

**Key layout** (HLD §11.5): `workspaces/{workspace_id}/calls/{call_id}/{kind}/...` where `kind ∈ {recording, transcript, source_uploads}`.

A helper `workspace_key(wid, *parts)` is the only allowed way to build keys outside the storage module (enforced by a lint rule alongside the SQL one).

**Tests:**
- `tests/integration/storage/test_workspace_prefix.py` — put a blob under WS1; try to list under WS2 prefix; assert empty.
- The matching smoke check is `ObjectStorageProbe.workspace_prefix_isolation` (§B8).

## A7. Auth — JWT, OAuth2 Password + Refresh

OAuth2 password grant (HLD §5.2). Endpoints:
| Method | Path | Body |
|---|---|---|
| POST | `/api/v1/auth/signup` | `{email, password, workspace_name}` → 201 with access + refresh tokens |
| POST | `/api/v1/auth/login` | `{username, password}` (OAuth2 standard form) → access + refresh |
| POST | `/api/v1/auth/refresh` | `{refresh_token}` → new access token |
| POST | `/api/v1/auth/logout` | revoke refresh token |
| GET | `/api/v1/me` | current user profile |

**JWT claims:**
```json
{
  "sub": "<user_id>",
  "org": "<organization_id>",
  "ws":  "<workspace_id>",      // null for org_admin
  "role": "manager",
  "iat": ..., "exp": ..., "jti": "..."
}
```

`jti` is opaque per access token; refresh tokens are stored hashed in `auth_refresh_tokens` table (rotation: each refresh issues a new refresh token, the prior is marked revoked).

**FastAPI dependencies** (`app/deps.py`):

```python
async def current_user(token: str = Depends(oauth2_scheme),
                       uow: UnitOfWork = Depends(get_uow)) -> User: ...

def require_workspace_access(workspace_id: UUID = Path(...),
                             user: User = Depends(current_user)) -> User:
    if str(user.workspace_id) != str(workspace_id):
        raise HTTPException(403, "wrong_workspace_scope")
    if user.role not in {"manager"}:                      # Phase 0
        raise HTTPException(403, "insufficient_role")
    return user

def require_org_access(...): ...                          # Phase 0 stub — always 403 for non-org_admin
def require_rep_access(...): ...                          # Phase 0 stub
```

The two stub dependencies are present from Phase 0 because the §C10 guard test needs them.

**Edge cases:**
- Expired access token → 401 with `WWW-Authenticate: Bearer error="invalid_token"`.
- Token signature mismatch (e.g., post-key-rotation) → 401, log alert.
- Refresh-token reuse after rotation → revoke entire chain (CVE-class detection); log + page on-call.

**Tests:**
- `tests/integration/auth/test_login_refresh_revoke.py`
- `tests/integration/auth/test_workspace_scope_enforcement.py` — create two Workspaces; user from WS1 tries to read WS2's `/calls`; assert 403.

## A8. Error Handling & Standard Responses

**Exception hierarchy** (`app/errors.py`):

```python
class VotFError(Exception):
    http_status: int = 500
    code: str = "internal_error"

class NotFound(VotFError): http_status = 404; code = "not_found"
class Forbidden(VotFError): http_status = 403; code = "forbidden"
class Validation(VotFError): http_status = 400; code = "validation"
class Conflict(VotFError): http_status = 409; code = "conflict"
class DependencyDown(VotFError): http_status = 503; code = "dependency_down"
class UpstreamError(VotFError): http_status = 502; code = "upstream_error"  # 3rd-party 5xx
```

**Standard error body:**
```json
{
  "error": {
    "code": "not_found",
    "message": "Call not found",
    "request_id": "...",
    "details": { /* optional */ }
  }
}
```

Handlers in `app/errors.py` translate `VotFError` and FastAPI's `HTTPException` into this shape. Pydantic `ValidationError` is wrapped with `code=validation` and `details` carrying the loc/msg list.

**Webhook handlers are an exception**: AP must get a plain `200` or `4xx`/`5xx` per its retry rules; webhook routes bypass the JSON envelope formatter and return per HLD §11.2.3.

## A9. Logging, Tracing, Metrics

**Logging:** structlog, JSON output, context binds for `request_id`, `workspace_id`, `call_id`, `user_id`. One logger config in `app/logging.py` set up before app instantiation so import-time errors are also JSON.

**Tracing:** OpenTelemetry; `app/observability/otel.py` wires:
- ASGI middleware for HTTP spans.
- SQLAlchemy instrumentation for DB spans.
- httpx instrumentation for outbound (AP, Supermemory, Anthropic).
- Manual spans in: orchestrator turn loop, post-call worker handlers, intake classifier.

Exporter target: `OTEL_EXPORTER_OTLP_ENDPOINT`. Default exporter is `console` in dev (logged to stderr).

**Metrics (Prometheus-shaped, via OTel meter):**
| Metric | Type | Labels | Source |
|---|---|---|---|
| `votf_call_turn_latency_ms` | histogram | `workspace_id` | Orchestrator turn loop |
| `votf_call_first_token_ms` | histogram | `workspace_id` | Orchestrator streaming |
| `votf_webhook_dedupe_hits_total` | counter | `provider` | Telephony adapter |
| `votf_decision_outcome_total` | counter | `class`, `outcome` | Decision service |
| `votf_intake_classification_confidence` | histogram | `kind` | Classifier mini-agent |
| `votf_smoke_probe_result` | gauge | `probe`, `mode` | Hourly cron writes |

**Logging-test:** `tests/unit/test_logging_redaction.py` asserts `SecretStr` and `Authorization` headers are scrubbed.

## A10. Skills Loader & Registry

Implements HLD §8.7. The base class is the contract; the loader is the wiring; the registry is the lookup.

```python
# app/skills/base.py
class Skill(ABC):
    name: str
    version: str                  # parsed from SKILL.md frontmatter
    input_schema: type[BaseModel]
    output_schema: type[BaseModel]
    model: str                    # pinned in SKILL.md
    quality_bar: str | None

    @abstractmethod
    async def run(self, inputs: BaseModel, ctx: SkillContext) -> BaseModel: ...

class LLMSkill(Skill):
    """Default: render prompt.j2 → call LLM in JSON mode → validate against output_schema → retry once on schema fail."""

class SkillRegistry:
    _skills: dict[str, Skill]
    @classmethod
    def register(cls, skill: Skill) -> None: ...
    @classmethod
    def get(cls, name: str, *, workspace_id: UUID | None = None) -> Skill: ...
```

**Loader behavior** (`app/skills/loader.py`):
1. On startup, walk `skills/<name>/` directories.
2. Parse `SKILL.md` YAML frontmatter (name, version, model, trigger, quality_bar).
3. Compile the `prompt.j2` template.
4. Import `<name>/schema.py` and resolve `Input`/`Output` Pydantic classes by convention.
5. Instantiate `LLMSkill(name=..., prompt_path=..., schema=..., model=...)` and `SkillRegistry.register`.
6. **Workspace overrides:** at `get(workspace_id=...)`, check `workspace_skill_overrides` table for a row keyed `(workspace_id, skill_name)`; if present, build an override-LLMSkill using the stored prompt text instead of the on-disk template. Cached for 60s.

**LLM client** (`app/skills/llm_client.py`): an abstraction that maps the `model` string to a provider (Anthropic native SDK for `claude-*`; OpenAI-compat SDK for everything else). Production path uses Anthropic native for hot-path streaming; classifier/extractor paths can use either.

**Eval harness** (`skills/<name>/evals/run.py`): loads `golden_set.jsonl` (one `{input, expected_output}` per line), invokes the skill, computes the metric defined by the skill (precision/recall/exact-match). Returns exit 0 if metric ≥ `quality_bar`, exit 1 otherwise. CI step calls this for every changed skill on every PR.

**Tests:** `tests/unit/skills/test_loader.py` — temporary `tmp_skills/` directory with a sample SKILL.md + prompt + schema; assert the loader registers it correctly; assert workspace override beats base; assert version mismatch in import is reported clearly.

## A11. Extension-Point Registries

All six (HLD §8) follow the same shape and live under their respective module directories. Common pattern:

```python
class Registry(Generic[T]):
    _items: dict[str, T] = {}
    @classmethod
    def register(cls, item: T) -> None:
        if item.name in cls._items:
            raise ValueError(f"{cls.__name__}: duplicate {item.name}")
        cls._items[item.name] = item
    @classmethod
    def get(cls, name: str) -> T:
        try: return cls._items[name]
        except KeyError: raise NotFound(f"{cls.__name__}: {name} not registered")
    @classmethod
    def list(cls) -> list[str]: return sorted(cls._items)
```

Registries used in Phase 0:
| Registry | Items (Phase 0) |
|---|---|
| `ToolRegistry` | request_manager_decision, request_correction, mark_followup, fetch_account, end_call (web_research stub) |
| `MiniAgentRegistry` | classifier, brain_seeder, caller_profiler |
| `ConnectorRegistry` | manual_upload (more in Phase 1) |
| `TelephonyRegistry` | agentphone |
| `MemoryProviderRegistry` | supermemory |
| `BrainProviderRegistry` | postgres_brain |
| `SkillRegistry` | classifier, orchestrator, caller_profiler |

Registries are populated **at import** of the providing module; `app/lifespan.py` triggers the imports explicitly so the order is deterministic.

## A12. Testing Strategy

Four tiers; each runs in a separate CI job for parallelism and fail-fast clarity.

### Tier 1 — Unit
- Pure in-process; no Postgres, no Redis, no network.
- Targets: services, repository SQL formation (against a SQLite in-memory or a fake), Pydantic schemas, Orchestrator turn-state transitions, prompt rendering.
- Tool: `pytest`, `pytest-asyncio` (`asyncio_mode=auto`), `freezegun` for time-sensitive assertions.
- Goal: <30s total.

### Tier 2 — Integration
- Uses the compose stack (`docker-compose.local.yml`). Real Postgres × 2, real Redis, real MinIO.
- Mocks third-party SaaS (AP, Supermemory, Anthropic). For AP we use a `fake_agentphone` httpx-mock server that speaks the webhook protocol back to us.
- Each test gets a fresh Workspace; teardown truncates the App DB and drops `brain_w_{wid}` schemas.
- Goal: <3 min total in CI.

### Tier 3 — End-to-End
- Same compose stack + a `fake_agentphone` process. **No** real third-party calls.
- Scenarios:
  - `test_signup_to_first_call.py`: signup → upload sample CRM → wait for intake → simulate inbound call → assert WS frames + Call row + transcript.
  - `test_decision_loop_end_to_end.py`: hot-path turn → tool emits `request_manager_decision` → push WS frame → Manager (test client) responds → assert Orchestrator next turn sees the answer.
- Tool: `pytest`, `httpx.AsyncClient` for HTTP, the FastAPI test client for WS.

### Tier 4 — Smoke (Part B of this LLD)
- Independent of the test framework. `python -m smoke run --all` against real third-parties.
- Hot-path scripts in `scripts/` (§B11).

### Common rules
- All tests are async-by-default. Sync wrappers banned.
- `tests/conftest.py` exposes one fixture surface — `app_client`, `workspace`, `manager_user`, `field_employee`. New tests reuse these; ad-hoc fixtures get rejected in review.
- **Coverage** target Phase 0: 75% statement on `app/services/`, `app/orchestrator/`, `app/skills/`. Hard gate at 70% in CI on changed files only (using `coverage --include`).

## A13. Lint / Format / Type-check / Pre-commit / CI

| Tool | Purpose |
|---|---|
| `ruff` | lint + format (single tool; pyproject `[tool.ruff]`) |
| `mypy --strict` | type-check; gated on `app/`, advisory on `skills/` and `scripts/` |
| `bandit` | security lint (Phase 0: advisory, Phase 1: gated) |
| `vulture` | dead-code detection on PRs that delete files |
| Custom: `tools/lint_unscoped_queries.py` | rejects raw SQL outside `app/db/` |
| Custom: `tools/lint_unscoped_storage_keys.py` | rejects object-storage keys not built via `workspace_key()` |

**Pre-commit** runs ruff + custom linters on staged files; tests run in CI.

**CI (MVP scope) — one workflow:**

`.github/workflows/ci.yml` runs on PR + push to main with three jobs:
- `lint`: ruff + mypy + custom linters.
- `unit`: tier-1 tests.
- `integration`: spin Postgres + Redis as GitHub Actions `services:`, run a **thin** integration suite (~10 critical-path tests covering signup, webhook HMAC, decision-loop happy path, brain isolation). Full tier-2 runs locally via `make integration`.

That's the entire CI gate for MVP. Everything else lives as `make` targets a human invokes:

| `make` target | Wraps | When to run |
|---|---|---|
| `make smoke` | `python -m smoke run --all --mode check` | Before pushing a deploy; after a deploy if you want assurance |
| `make smoke-full` | `python -m smoke run --all --mode smoke` | Before any release that touches a third-party integration |
| `make verify-hot-path` | `python -m scripts.verify_hot_path` | Before any release that touches `app/telephony/` or `app/orchestrator/` |
| `make e2e` | tier-3 tests against local compose | When iterating on flows that cross multiple components |
| `make skills-eval` | runs every `skills/<name>/evals/run.py` | When iterating on a prompt — surfaces precision regressions before merge |

**What this trades off vs. a fuller CI** (and when to revisit):
- No automated post-deploy rollback. A human reverts if prod breaks — fine until customer count or SLA demands faster MTTR.
- No hourly canary against prod. Third-party drift (an AgentPhone header rename) is caught the next time someone runs `make smoke` or when a customer hits the bug — re-add the hourly cron when you can't tolerate that lag.
- Skill-eval is human-triggered, not a merge gate — re-add the gate when prompt regressions start hurting in production.
- Smoke against staging is not gated — add a `workflow_dispatch` `smoke_staging.yml` the day you have a staging environment worth gating on.

The point: the smoke framework (§B) still earns its keep on day one as a debugging tool a human runs. It just doesn't need four pipelines wrapped around it for an MVP.

## A14. docker-compose.local.yml + Local Dev

```yaml
# docker-compose.local.yml
services:
  postgres:
    image: postgres:16
    environment:
      POSTGRES_USER: votf
      POSTGRES_PASSWORD: votf
      POSTGRES_MULTIPLE_DATABASES: "votf_app,votf_brain"
    volumes:
      - ./scripts/postgres_init/:/docker-entrypoint-initdb.d/    # creates pgvector ext on votf_brain
      - pg_data:/var/lib/postgresql/data
    ports: ["5432:5432"]

  redis:
    image: redis:7-alpine
    ports: ["6379:6379"]

  minio:
    image: minio/minio
    command: server /data --console-address ":9001"
    environment:
      MINIO_ROOT_USER: minioadmin
      MINIO_ROOT_PASSWORD: minioadmin
    ports: ["9000:9000", "9001:9001"]
    volumes: [ minio_data:/data ]

  minio-init:
    image: minio/mc
    depends_on: [minio]
    entrypoint: >
      sh -c "until mc alias set local http://minio:9000 minioadmin minioadmin; do sleep 1; done;
             mc mb -p local/votf-local || true"

volumes:
  pg_data:
  minio_data:
```

**Postgres init script** (`scripts/postgres_init/01_dbs.sh`) — creates both DBs from the `POSTGRES_MULTIPLE_DATABASES` env, then runs `CREATE EXTENSION IF NOT EXISTS vector;` on `votf_brain`.

**The ngrok caveat** (HLD §10.2): a `scripts/dev_tunnel.sh` helper starts an ngrok tunnel pointing at `localhost:8000`, prints the HTTPS URL, and gives instructions for registering it as the AP webhook URL for the dev tenant. This is documented in `README.md`; not automated.

**Dev workflow:**
```bash
docker compose -f docker-compose.local.yml up -d
uv sync
python -m scripts.alembic_wrapper app upgrade head
python -m scripts.alembic_wrapper brain upgrade head
python -m scripts.seed_dev_workspace
uvicorn app.main:app --reload
arq app.workers.settings.PostCallWorker &
```

## A15. Deployment Profile Switch (local vs cloud)

The same code reads two env files: `.env` (committed-defaults, no secrets) + `.env.local` (gitignored) for dev, or `.env.production` for prod. `DEPLOYMENT_PROFILE=local` vs `cloud` flips:
- `S3_ENDPOINT_URL` non-empty → boto3 hits MinIO/R2; empty → boto3 hits real AWS.
- `LLM_BASE_URL` defaults to Anthropic OpenAI-compat; can be re-pointed at OpenAI/vLLM/etc. for the smoke probes only.
- (No code branches on `deployment_profile`; the variable exists to validate combinations and to tag metrics/logs.)

**Per HLD §10.2**, AgentPhone / Supermemory / Anthropic are cloud-only regardless of profile.

---

# Part B — Smoke Probe Framework

Implements HLD §12 (priority #12). Independent verification per integration. Three modes, four exit codes, JSON+pretty dual output.

## B1. `Probe` Base Class

`smoke/_base.py` is the contract. Already specified at signature level in HLD §12.2; the LLD additions:

**Module structure:**
```python
class ExitCode(IntEnum):
    PASS = 0; FAIL = 1; CONFIG = 2; UPSTREAM = 3

@dataclass
class CheckResult:
    name: str; passed: bool; latency_ms: float
    detail: str = ""; fix_hint: str = ""

@dataclass
class ProbeReport:
    probe: str; mode: str; overall: str
    checks: list[CheckResult] = field(default_factory=list)
    started_at: str = ""; duration_ms: float = 0

class Probe(ABC):
    name: str
    required_env: list[str]
    def __init__(self, mode: str = "check"): ...
    def run(self) -> ExitCode: ...
    @abstractmethod
    def checks_for_mode(self) -> None: ...
    def check(self, name: str, fn, fix_hint: str = "") -> bool: ...
    def check_with_return(self, name: str, fn, fix_hint: str = "") -> Any: ...   # captures fn's return for chained checks
```

**Output rules:**
- **stdout** = machine: one JSON object per run (the `ProbeReport`).
- **stderr** = human: colorized lines `[PASS] auth_valid       12ms`, `[FAIL] webhook_configured  240ms — Verify ...`.
- Secrets redaction: a `redact()` helper masks any substring matching `os.environ[k]` for `k` in `required_env` if `k.endswith(("_KEY", "_SECRET", "_PASSWORD", "_TOKEN"))`. Run over every detail string before emit.
- A run takes <2s in `check` mode, <30s in `smoke` mode (HLD §12.1). Probes must enforce per-check timeouts.

**Mode dispatch in `checks_for_mode`** uses `if self.mode in (...)` guards rather than a dispatch dict — read more naturally in subclasses.

## B2. AgentPhoneProbe

`smoke/agentphone.py` — full spec already in HLD §12.4. LLD additions and edge cases:

**Required env:** `AGENTPHONE_API_KEY`, `AGENTPHONE_WEBHOOK_SECRET`, `SMOKE_AGENTPHONE_TEST_AGENT_ID`, `SMOKE_AGENTPHONE_TEST_NUMBER_ID`, and for `smoke` mode: `SMOKE_AGENTPHONE_TEST_TO_NUMBER`, `SMOKE_AGENTPHONE_TEST_CONVERSATION_ID`.

**Checks per mode:**
| Check | check | smoke | repair |
|---|---|---|---|
| `auth_valid` | ✓ | ✓ | ✓ |
| `webhook_configured` | ✓ | ✓ | ✓ |
| `hmac_verification` | | ✓ | ✓ |
| `test_webhook_delivery` | | ✓ | ✓ |
| `conversation_state_roundtrip` | | ✓ | ✓ |
| `ndjson_response_accepted` | | ✓ | ✓ |
| `outbound_sms_capability` | | ✓ | ✓ |

**`hmac_verification` test design** (HLD §12.4 has the sketch): the probe imports `app.telephony.agentphone.verify_webhook` — the **production** verifier — and round-trips a synthetic payload through it with a freshly-generated signature. Catches the class of bug where our verifier disagrees with AP's spec.

**`ndjson_response_accepted` test design:** the probe stands up a temporary FastAPI subapp on a random port, registers it temporarily as an AP webhook target (in repair mode only; in smoke mode it uses an `--ngrok` flag and reuses the dev tunnel), POSTs a synthetic voice event via AP's `/v1/webhooks/test`, asserts the response was logged with status 200 and `Content-Type: application/x-ndjson`.

**Cleanup:** any temporary webhook registration is reverted on exit (`atexit`).

## B3. SupermemoryProbe

`smoke/supermemory.py` — spec in HLD §12.6. LLD additions:

**Cleanup pattern (every probe that writes ephemeral data must follow):**
```python
test_user_id = f"smoketest:probe:{uuid.uuid4()}"
try:
    memory_id = ...
finally:
    # delete every memory written under test_user_id, even if checks raised
```

**Eventual-consistency tolerance:** `memory_search_finds_write` polls for up to 5s with 1s waits. If still not found, FAIL with `fix_hint="Eventual consistency window exceeded — check Supermemory status page."`.

**File upload check** (`file_upload_small`): uploads `smoke/fixtures/sample_doc.pdf` (a 1-page PDF, <100KB) under the test user; asserts the returned document ID is searchable; deletes it.

**Profile fetch:** asserts `client.profile.get(user_id=...)` returns a `Profile` object even for a user with one memory.

## B4. LLMProbe (OpenAI-compat)

`smoke/llm.py` — spec in HLD §12.5. LLD additions:

**Required env:** `LLM_API_KEY`, `LLM_BASE_URL`, `LLM_MODEL`.

**Defaults documented in code:** for Anthropic via OpenAI-compat, `LLM_BASE_URL=https://api.anthropic.com/v1/openai`. For OpenAI native, `LLM_BASE_URL=https://api.openai.com/v1`. For local vLLM/Ollama, the appropriate local URL.

**`skill_models_reachable` check (the important one):** walks `skills/*/SKILL.md` frontmatter, extracts the `model:` field, and probes each model with a 1-token completion. Catches the case where a skill is pinned to a model that the provider has retired or that's not enabled on the current API key. Reports a single line per model: `[PASS] claude-haiku-4-5 12ms`, etc.

**`long_context_50k` design:** sends a prompt of `~50000 tokens` of filler ("A. " repeated ~25k times) followed by `"Question: what was the first letter? Answer with just the letter."` Asserts the response is `A`. Timeout 60s. Cost is non-trivial — only runs in `smoke` mode.

**Tool-call check:** sets `tool_choice: "auto"` with a `get_weather` tool. Some providers respond with `tool_choice` but no actual call when the model "decides" it doesn't need the tool — the prompt `"What's the weather in SF?"` reliably triggers the call in current models. If providers later regress, the prompt is updated alongside the skill.

## B5. AppPostgresProbe

`smoke/postgres_app.py`:
| Check | Mode |
|---|---|
| `connect` | check |
| `migrations_at_head` | check — runs `alembic_wrapper app current` and compares to `heads`; fails if behind |
| `crud_roundtrip` | smoke — inserts a `_smoke_test` row in a `_smoke_test` table (created in advance via migration), reads it back, deletes |
| `transaction_isolation` | smoke — opens two sessions, asserts read-committed behavior |

Edge case: the probe must NOT need migration permission — it only reads `alembic_version` and does CRUD in a designated `_smoke_test` table.

## B6. BrainPostgresProbe

`smoke/postgres_brain.py` — sketch in HLD §12.7. LLD additions:

| Check | Mode |
|---|---|
| `connect` | check |
| `pgvector_present` | check — `SELECT extname FROM pg_extension WHERE extname='vector';` |
| `tsvector_present` | check — `SELECT to_tsvector('english', 'test');` |
| `schema_per_workspace_create` | smoke — `CREATE SCHEMA brain_w_smoketest_{uuid}` |
| `embedding_roundtrip` | smoke — inserts a 1536-dim random vector + a tsvector; runs a hybrid query; asserts the row scores >0 |
| `rrf_query_correctness` | smoke — inserts two rows; asserts RRF ranks the expected one first |
| `schema_per_workspace_drop` | smoke — `DROP SCHEMA brain_w_smoketest_{uuid} CASCADE` |

The smoke checks always operate inside a transaction wrapped in a savepoint; in `repair` mode the savepoint is rolled back but query plans are dumped via `EXPLAIN ANALYZE`.

## B7. RedisProbe

`smoke/redis.py`:
| Check | Mode |
|---|---|
| `connect` | check |
| `set_get` | check |
| `pubsub_roundtrip` | smoke — publishes to `_smoke_test_channel`; subscriber receives within 500ms |
| `arq_enqueue` | smoke — uses arq's `create_pool` to enqueue a no-op `_smoke_test_job`; asserts queue length grew then dequeue |
| `dedupe_set_ttl` | smoke — asserts the `seen_webhooks` SADD+EXPIRE pattern works |

## B8. ObjectStorageProbe

`smoke/object_storage.py` — sketch in HLD §12.7. Full check matrix:
| Check | Mode |
|---|---|
| `bucket_reachable` | check |
| `put_object` | smoke |
| `get_object` | smoke |
| `signed_url_generation` | smoke — verifies generated URL is reachable + expires |
| `delete_object` | smoke |
| `workspace_prefix_isolation` | smoke — writes a blob under `_smoke_test/ws_a/`, lists `_smoke_test/ws_b/`, asserts empty |

`fix_hint` for `workspace_prefix_isolation`: `"Bucket-level ACLs may be too permissive; we rely on prefix-based scoping in app code and signed URLs at the bucket level."`

## B9. Aggregating Runner + Manifest

`smoke/_runner.py`:
- Reads `smoke/manifests/probes.yaml` (HLD §12.8 has the YAML).
- Supports `--filter`, `--only`, `--mode`, `--fail-fast`.
- Runs probes **in parallel** using `asyncio.create_subprocess_exec` (each probe is a separate Python invocation — preserves isolation).
- Collects JSON reports from each subprocess's stdout; assembles a `SuiteReport`.
- Exit code = worst of all probe exits (per `exit_policy`).
- Pretty output is a table to stderr; JSON suite report to stdout.

**Failure summary line format** (so it's grep-friendly):
```
SMOKE_SUMMARY mode=smoke probes=7 pass=6 fail=1 config_error=0 upstream_down=0 duration_ms=18432
```

## B10. CI Wiring (MVP scope: human-run, not automated)

For MVP, smoke probes are **not** wired into CI. They live as a CLI a human invokes via Makefile targets:

| `make` target | Mode | When | Fail action |
|---|---|---|---|
| `make smoke` | check | before push to prod; after deploy if desired | human reads output, decides |
| `make smoke-full` | smoke | before any third-party-touching release | human reads output, decides |
| `make smoke-repair PROBE=agentphone` | repair | when debugging a specific failing integration | dumps diagnostic detail |

**Why not automate it yet** (per §A13): for a pre-customer / single-engineer system, four CI pipelines + automated rollback is more ops burden than it saves. Re-introduce in this order as the system scales:
1. First scale step → add `smoke_staging.yml` with a `workflow_dispatch` trigger (manual button in GitHub UI to run smoke against staging on demand).
2. After first prod incident → add `smoke_hourly_prod.yml` as a cron-driven canary.
3. When MTTR matters → add `smoke_post_deploy.yml` with automated rollback hook.
4. When team grows past 2–3 engineers → gate PRs with `smoke_check` against staging.

**Secrets posture for the human-run path:** the operator's local `.env.staging` and `.env.production` files hold the credentials. They are never committed and never copied into CI. When CI gating is reintroduced, store the same values as repo Secrets — distinct credentials per environment, with the production Supermemory key scoped read-only (no `delete`) since the probe doesn't need to write to prod data.

## B11. Hot-Path Verification Scripts

Beyond the integration-level probes in B2–B8, the user explicitly asked for scripts that verify the **third-party hot path**. The hot path is HLD §5.5.1: Rep utterance → AP webhook → Orchestrator → streaming LLM → NDJSON back to AP → TTS. Two scripts:

### `scripts/simulate_inbound_voice.py`

Sends a synthetic `agent.message:voice` webhook to the locally-running app and asserts the response is well-formed NDJSON streamed within the latency budget.

```
USAGE: python -m scripts.simulate_inbound_voice \
         --base-url http://localhost:8000 \
         --workspace <wid> \
         --field-employee <feid> \
         --utterance "I just met with the buyer at Acme" \
         [--repeat 10]

OUTPUT (per turn):
  TURN  1   first_chunk=420ms  full_response=1210ms  chunks=8  status=ok
  TURN  2   first_chunk=388ms  full_response=1102ms  chunks=7  status=ok
  ...
  ─────────────────────────
  p50 first_chunk=405ms   p95 first_chunk=560ms
  p50 full_response=1.18s p95 full_response=1.49s
EXIT 0 if all turns meet first_chunk < 700ms AND full_response < 2500ms (HLD §15).
EXIT 1 otherwise.
```

Construction:
- Signs the synthetic payload using `AGENTPHONE_WEBHOOK_SECRET` so the production HMAC verifier accepts it (no test bypass).
- Uses `conversationState={workspace_id, call_id, field_employee_id}` (no DB lookup).
- Consumes the NDJSON response with `httpx.stream` to measure first-chunk and last-chunk timings.
- Treats the first turn as warm-up (excluded from percentiles).

### `scripts/verify_hot_path.py`

End-to-end against real AgentPhone + real LLM, **once**, against staging:

1. Probes prerequisites (`smoke run --filter third_party --mode check`).
2. Provisions a dummy Workspace with a pre-allocated AP number.
3. Triggers AP's test-call utility (or, if unavailable, prompts the operator to call the number).
4. Captures the full call lifecycle from webhook receipt to `agent.call_ended`.
5. Asserts: HMAC verified, transcript delivered, ≥1 NDJSON chunk emitted within 700ms of first webhook, `agent.call_ended` received, `Call.status=ended`.
6. Cleans up: deletes the test Workspace + brain schema + Supermemory entries.

Outputs a single PASS/FAIL line + a `verify_hot_path_report_<ts>.json` artifact. Runs manually pre-launch and after any change to `app/telephony/`, `app/orchestrator/streaming.py`, or `skills/orchestrator/`.

## B12. Operator Setup & First-Run Verification Checklist

**Audience:** the person bringing up a fresh VotF deployment (local, staging, or prod) for the first time. The smoke probes in §B2–§B8 already exist; this section tells the operator **what to obtain, where, and how to verify each integration is truly functional end-to-end**.

The workflow per integration is always the same:
1. **Sign up & generate credentials** (where + how)
2. **Pre-provision test resources** (what to create in the third-party dashboard so smoke probes can run cheaply)
3. **Set env vars** (which names, where to store)
4. **Run the smoke probe** (exact command)
5. **Interpret output** (what PASS / FAIL / CONFIG / UPSTREAM looks like)
6. **Common failures + fixes**

### B12.1 — Single-page verification matrix

Read top-to-bottom; tick each row before declaring the deployment ready.

| # | Integration | Sign-up URL | Required env vars | Pre-provisioned test inputs | Verify command | Expected exit |
|---|---|---|---|---|---|---|
| 1 | App Postgres | (local: compose; cloud: RDS/Supabase/Neon) | `DATABASE_URL` | none (the probe creates a `_smoke_test` row) | `python -m smoke.postgres_app --mode smoke` | 0 |
| 2 | Brain Postgres + pgvector | same provider as #1 | `BRAIN_DATABASE_URL` | `pgvector` extension installed | `python -m smoke.postgres_brain --mode smoke` | 0 |
| 3 | Redis | (local: compose; cloud: Upstash/ElastiCache) | `REDIS_URL` | none | `python -m smoke.redis --mode smoke` | 0 |
| 4 | Object storage | (local: MinIO; cloud: AWS S3 / R2) | `S3_BUCKET`, `S3_ACCESS_KEY`, `S3_SECRET_KEY`, `S3_REGION`, `S3_ENDPOINT_URL`* | bucket exists, IAM allows `Put/Get/Delete` | `python -m smoke.object_storage --mode smoke` | 0 |
| 5 | Anthropic LLM | https://console.anthropic.com | `LLM_API_KEY`, `LLM_BASE_URL`, `LLM_MODEL`, `ANTHROPIC_API_KEY` | none | `python -m smoke.llm --mode smoke` | 0 |
| 6 | Supermemory | https://supermemory.ai | `SUPERMEMORY_API_KEY` | none (probe creates ephemeral user) | `python -m smoke.supermemory --mode smoke` | 0 |
| 7 | AgentPhone | https://agentphone.ai | `AGENTPHONE_API_KEY`, `AGENTPHONE_WEBHOOK_SECRET`, `SMOKE_AGENTPHONE_TEST_AGENT_ID`, `SMOKE_AGENTPHONE_TEST_NUMBER_ID`, `SMOKE_AGENTPHONE_TEST_CONVERSATION_ID`, `SMOKE_AGENTPHONE_TEST_TO_NUMBER` | 1 test AP Agent, 1 test number, 1 test conversation, 1 SMS-capable target phone you own | `python -m smoke.agentphone --mode smoke` | 0 |
| 8 | All third-party at once | (above) | (above) | (above) | `python -m smoke run --filter third_party --mode smoke` | 0 |
| 9 | All infra at once | (above) | (above) | (above) | `python -m smoke run --filter infrastructure --mode smoke` | 0 |
| 10 | Hot-path round-trip | (Phase 0 §B11) | (above) | a real phone you can call from | `python -m scripts.verify_hot_path` | 0 |

\* `S3_ENDPOINT_URL` is empty for real AWS S3; set to MinIO/R2 endpoint URL otherwise.

If every row exits 0, the deployment's third-party + infrastructure surface is verified and the MVP loop can be exercised end-to-end (sign up a test Manager, upload a sample doc, place a call).

### B12.2 — Per-integration walkthrough

#### B12.2.1 — App Postgres (#1)

**Sign-up & setup:**
- *Local:* `docker compose -f docker-compose.local.yml up -d postgres` brings up the `votf_app` database via the init script in `scripts/postgres_init/`.
- *Cloud:* pick a managed provider (AWS RDS, Supabase, Neon, Render). Create a database named `votf_app`. Note the connection string.

**Env var:**
```bash
DATABASE_URL=postgresql+asyncpg://user:pass@host:5432/votf_app
```

**Pre-flight before running probe:**
```bash
python -m scripts.alembic_wrapper app upgrade head
```

**Run:**
```bash
python -m smoke.postgres_app --mode smoke
```

**Expected PASS output (stderr, human-readable):**
```
[PASS] connect                 12ms
[PASS] migrations_at_head      30ms  alembic_version=abc123
[PASS] crud_roundtrip          88ms
[PASS] transaction_isolation  120ms
```

**Common failures:**
| Symptom | Likely cause | Fix |
|---|---|---|
| `connect` fails with `password authentication failed` | bad creds in `DATABASE_URL` | Fix URL; check the password isn't URL-encoded twice |
| `migrations_at_head` fails | new migration on main not yet applied | `python -m scripts.alembic_wrapper app upgrade head` |
| Probe exits with code 2 (CONFIG) | `DATABASE_URL` not set | Source your `.env.local` / `.env.staging` |
| `crud_roundtrip` fails with `relation "_smoke_test" does not exist` | smoke-test table migration missing | Run the bootstrap migration `0001_smoke_test_table.py` |

---

#### B12.2.2 — Brain Postgres + pgvector (#2)

**Sign-up & setup:**
- *Local:* same Postgres container as #1; the init script creates `votf_brain` and runs `CREATE EXTENSION IF NOT EXISTS vector;`.
- *Cloud:* the same managed Postgres can host both databases (`votf_app` and `votf_brain`); ensure pgvector is enabled. Supabase / Neon enable it via a one-click toggle; RDS requires `CREATE EXTENSION vector` on the database (Postgres 16+).

**Env var:**
```bash
BRAIN_DATABASE_URL=postgresql+asyncpg://user:pass@host:5432/votf_brain
```

**Pre-flight:**
```bash
python -m scripts.alembic_wrapper brain upgrade head
```

**Run:**
```bash
python -m smoke.postgres_brain --mode smoke
```

**Expected PASS:**
```
[PASS] connect                              12ms
[PASS] pgvector_present                     22ms  extname=vector
[PASS] tsvector_present                     14ms
[PASS] schema_per_workspace_create          61ms  schema=brain_w_smoketest_<uuid>
[PASS] embedding_roundtrip                 138ms  hit_count=1
[PASS] rrf_query_correctness               142ms
[PASS] schema_per_workspace_drop            48ms
```

**Common failures:**
| Symptom | Likely cause | Fix |
|---|---|---|
| `pgvector_present` fails | extension not enabled | `CREATE EXTENSION IF NOT EXISTS vector;` as a superuser on the brain DB |
| `schema_per_workspace_create` fails with `permission denied` | DB user lacks `CREATE` privilege | Grant `CREATE` on database to the app user |
| `embedding_roundtrip` fails with `type "vector" does not exist` | pgvector installed in a different schema | Set search_path; or `CREATE EXTENSION vector WITH SCHEMA public` |

---

#### B12.2.3 — Redis (#3)

**Sign-up & setup:**
- *Local:* `docker compose up -d redis` (in `docker-compose.local.yml`).
- *Cloud:* Upstash (TLS-encrypted, generous free tier) or AWS ElastiCache. Note the URL — Upstash uses `rediss://` (TLS).

**Env var:**
```bash
REDIS_URL=redis://localhost:6379/0           # local
REDIS_URL=rediss://default:PASS@host:6379    # Upstash
```

**Run:**
```bash
python -m smoke.redis --mode smoke
```

**Expected PASS:**
```
[PASS] connect            8ms
[PASS] set_get           14ms
[PASS] pubsub_roundtrip 102ms
[PASS] arq_enqueue       96ms  queue_len_grew_by=1
[PASS] dedupe_set_ttl    21ms
```

**Common failures:**
| Symptom | Likely cause | Fix |
|---|---|---|
| `connect` fails with `Connection refused` | wrong URL or container not up | `docker compose ps`; check URL |
| `connect` fails with TLS errors against Upstash | using `redis://` instead of `rediss://` | Switch scheme |
| `arq_enqueue` succeeds but `pubsub_roundtrip` times out | provider doesn't allow pubsub (some managed Redis variants restrict it) | Move to a provider that supports pubsub (Upstash does) |

---

#### B12.2.4 — Object storage (#4)

**Sign-up & setup:**
- *Local:* MinIO via compose. The `minio-init` service in `docker-compose.local.yml` creates the `votf-local` bucket on startup.
- *Cloud AWS S3:* create a bucket in your chosen region; create an IAM user with a policy scoped to `s3:PutObject`, `s3:GetObject`, `s3:DeleteObject`, `s3:ListBucket` on that bucket. Generate access keys.
- *Cloud R2:* Cloudflare dashboard → R2 → create bucket → generate API token with object read+write. Note the S3-compatible endpoint URL (e.g., `https://<account>.r2.cloudflarestorage.com`).

**Env vars:**
```bash
# Local
S3_BUCKET=votf-local
S3_ACCESS_KEY=minioadmin
S3_SECRET_KEY=minioadmin
S3_REGION=us-east-1
S3_ENDPOINT_URL=http://localhost:9000

# AWS S3
S3_BUCKET=votf-prod
S3_ACCESS_KEY=AKIA...
S3_SECRET_KEY=...
S3_REGION=us-east-1
S3_ENDPOINT_URL=                     # empty

# Cloudflare R2
S3_BUCKET=votf-prod
S3_ACCESS_KEY=...
S3_SECRET_KEY=...
S3_REGION=auto
S3_ENDPOINT_URL=https://<account>.r2.cloudflarestorage.com
```

**Run:**
```bash
python -m smoke.object_storage --mode smoke
```

**Expected PASS:**
```
[PASS] bucket_reachable             45ms
[PASS] put_object                  102ms  key=_smoke_test/<uuid>.bin
[PASS] get_object                   68ms  sha256_match=true
[PASS] signed_url_generation        12ms  expires_in=900s
[PASS] delete_object                51ms
[PASS] workspace_prefix_isolation  140ms  cross_prefix_list_empty=true
```

**Common failures:**
| Symptom | Likely cause | Fix |
|---|---|---|
| `bucket_reachable` fails with 403 | IAM policy too restrictive | Add the four bucket-scoped actions above |
| `signed_url_generation` URL returns 403 when curled | URL signature doesn't match endpoint | Confirm `S3_REGION` matches bucket region; for R2 use `auto` |
| `workspace_prefix_isolation` fails | bucket-level ACL too permissive | Tighten ACL; we rely on prefix scoping in app code, but a permissive bucket can leak via list operations |

---

#### B12.2.5 — Anthropic LLM (#5)

**Sign-up & setup:**
1. Create an account at https://console.anthropic.com.
2. **Add a payment method** (no usable API access without one; the free trial credits are limited).
3. Generate an API key (Settings → API Keys → "Create Key"). Copy the value once — it's shown only at creation time.
4. Set per-tier rate limits and a monthly spend cap (Settings → Limits) as a safety guardrail. Recommended: $50/month cap for staging, scaled for prod.

**Env vars:**
```bash
ANTHROPIC_API_KEY=sk-ant-...                              # production-code (Anthropic native SDK)
LLM_API_KEY=sk-ant-...                                    # smoke probe (OpenAI-compat)
LLM_BASE_URL=https://api.anthropic.com/v1/openai          # OpenAI-compat endpoint
LLM_MODEL=claude-sonnet-4-6                               # whatever's pinned in skills/orchestrator/SKILL.md
```

`ANTHROPIC_API_KEY` and `LLM_API_KEY` are typically the same value — production code uses Anthropic's native SDK (richer features); the smoke probe uses the OpenAI-compat endpoint (cross-provider portability per HLD §12.5).

**Run:**
```bash
python -m smoke.llm --mode smoke
```

**Expected PASS:**
```
[PASS] auth_valid                    340ms
[PASS] basic_completion              810ms  response="pong"
[PASS] streaming_completion          640ms  first_token=420ms
[PASS] json_mode                     950ms  JSON shape honored
[PASS] tool_calls                   1220ms  tool_call=get_weather
[PASS] long_context_50k             4100ms  response="A"
[PASS] skill_models_reachable       2200ms  checked=3 ok=3
```

**Common failures:**
| Symptom | Likely cause | Fix |
|---|---|---|
| `auth_valid` fails with 401 | key revoked or wrong | Rotate in console; update env |
| `auth_valid` fails with 402/payment-required | no payment method | Add card in console |
| `basic_completion` fails with `model not found` | `LLM_MODEL` retired or unavailable on plan | Update to a current model ID; verify the same model is in `skills/orchestrator/SKILL.md` |
| `streaming_completion` succeeds but first_token > 2s | network latency or provider throttle | Test against a closer region; verify you're not hitting a rate-limit tier |
| `skill_models_reachable` fails for one skill | a SKILL.md pins a model the API key can't access | Either update the SKILL.md to a reachable model or upgrade the API plan |

---

#### B12.2.6 — Supermemory (#6)

**Sign-up & setup:**
1. Create an account at https://supermemory.ai.
2. **Choose a pricing tier** appropriate to expected volume (HLD §11.3.6 estimate: 500–5,000 writes + 1,000–3,000 queries per Workspace/month).
3. Generate an API key (developer platform → API Keys). Copy once.

**Env var:**
```bash
SUPERMEMORY_API_KEY=sm_...
```
(The Python SDK reads this env var automatically.)

**Run:**
```bash
python -m smoke.supermemory --mode smoke
```

**Expected PASS:**
```
[PASS] auth_valid                     180ms
[PASS] memory_write                   420ms  id=mem_abc
[PASS] memory_search_finds_write     2100ms  found in 2 attempts
[PASS] memory_delete                  330ms
[PASS] file_upload_small              860ms  doc_id=doc_xyz
[PASS] profile_fetch                  240ms
```

The `memory_search_finds_write` step polls up to 5s (eventual consistency); 2 attempts is normal.

**Common failures:**
| Symptom | Likely cause | Fix |
|---|---|---|
| `auth_valid` fails with 401 | key bad | Regenerate in dashboard |
| `memory_search_finds_write` times out after 5s | indexing lag exceeded test window | Check Supermemory status page; retry; raise issue if persistent |
| `file_upload_small` fails 413 | file size limit on your tier | Use a smaller fixture; or upgrade tier |
| `profile_fetch` returns null when memory exists | profile extraction is async on SM's side; allow a few minutes between first memory and profile read | Re-run; if persistent, contact SM support |

---

#### B12.2.7 — AgentPhone (#7, the most involved)

**Sign-up & setup:**
1. Create an account at https://agentphone.ai.
2. **Fund the account.** Pay-as-you-go: ~$1–2/month per number + voice minutes + SMS. Add a payment method; pre-load $20 for staging exploration.
3. Generate an API key (dashboard → API Keys). Copy once.
4. **Provision a test AP Agent** (the persona that owns a phone number). Dashboard → Agents → Create. Name it `votf-smoke-test`. Note the agent ID (`agt_...`).
5. **Provision a test phone number** attached to the test agent. Dashboard → Numbers → Buy. Note the number ID (`num_...`) and the actual phone number (`+1...`).
6. **Configure the master webhook** so AP delivers events to your deployment:
   ```bash
   curl -X POST https://api.agentphone.ai/v1/webhooks \
     -H "Authorization: Bearer $AGENTPHONE_API_KEY" \
     -H "Content-Type: application/json" \
     -d '{
       "url": "https://<your-deployment>/api/v1/webhooks/agentphone",
       "contextLimit": 10,
       "timeout": 30
     }'
   ```
   The response includes `"secret": "whsec_..."` — **save this** as `AGENTPHONE_WEBHOOK_SECRET`. It's shown only once.

   *Local dev:* `<your-deployment>` is the public HTTPS URL of your `ngrok` (or `cloudflared`) tunnel pointing at `localhost:8000`. See HLD §10.2 + LLD §A14.
7. **Initiate one test inbound conversation** so the probe has a `SMOKE_AGENTPHONE_TEST_CONVERSATION_ID` to PATCH. Easiest path: call the number once from your mobile, let it end after a few seconds. Find the conversation ID in the AP dashboard under Conversations.
8. **Have a target phone number** you own (your mobile) that AP can SMS during the `outbound_sms_capability` check. Set `SMOKE_AGENTPHONE_TEST_TO_NUMBER` to it.

**Env vars:**
```bash
AGENTPHONE_API_KEY=...                                # from step 3
AGENTPHONE_WEBHOOK_SECRET=whsec_...                   # from step 6
SMOKE_AGENTPHONE_TEST_AGENT_ID=agt_...                # from step 4
SMOKE_AGENTPHONE_TEST_NUMBER_ID=num_...               # from step 5
SMOKE_AGENTPHONE_TEST_CONVERSATION_ID=conv_...        # from step 7
SMOKE_AGENTPHONE_TEST_TO_NUMBER=+15551234567          # from step 8 (E.164 format)
```

**Run:**
```bash
python -m smoke.agentphone --mode smoke
```

**Expected PASS:**
```
[PASS] auth_valid                       210ms
[PASS] webhook_configured                88ms  url=https://...
[PASS] hmac_verification                 12ms  HMAC algorithm OK
[PASS] test_webhook_delivery           1850ms  httpStatus=200
[PASS] conversation_state_roundtrip     480ms
[PASS] ndjson_response_accepted        2210ms
[PASS] outbound_sms_capability          720ms  accepted
```

The `outbound_sms_capability` step **actually sends an SMS** to `SMOKE_AGENTPHONE_TEST_TO_NUMBER`. Cost is a few cents per run. The probe asserts only that AP accepted the request — manual confirmation that the SMS *arrived* is the final piece of human verification.

**Common failures:**
| Symptom | Likely cause | Fix |
|---|---|---|
| `webhook_configured` returns `No master webhook configured` | step 6 skipped, or webhook deleted | Re-run the `POST /v1/webhooks` curl |
| `hmac_verification` fails | `AGENTPHONE_WEBHOOK_SECRET` doesn't match what AP issued | Re-create the webhook (step 6); save the new secret |
| `test_webhook_delivery` returns `httpStatus=4xx/5xx` | your deployment's webhook endpoint is unreachable or erroring | If local: confirm ngrok tunnel is up and the URL matches AP's webhook config; if cloud: check the deployment is up and `/api/v1/webhooks/agentphone` responds 200 to AP's test payload |
| `test_webhook_delivery` returns `httpStatus=200` but `success=false` | endpoint responded but didn't ack | Inspect app logs around the timestamp; likely a 200 with wrong body |
| `ndjson_response_accepted` fails | voice handler doesn't return `Content-Type: application/x-ndjson` | Check `app/orchestrator/streaming.py`; ensure `StreamingResponse(media_type="application/x-ndjson")` |
| `outbound_sms_capability` returns 402 | account balance depleted | Top up |
| SMS doesn't arrive though probe passed | carrier filtering or wrong country | Try a different target number; check AP delivery log |

---

#### B12.2.8 — Running everything at once (#8–#9)

Once each probe passes individually, run the aggregated suite:

```bash
python -m smoke run --filter third_party --mode smoke
python -m smoke run --filter infrastructure --mode smoke
python -m smoke run --all --mode smoke
```

The aggregator emits per-probe results plus a single summary line at the end:

```
SMOKE_SUMMARY mode=smoke probes=7 pass=7 fail=0 config_error=0 upstream_down=0 duration_ms=18432
```

Exit code is the worst result across all probes. PASS for all = exit 0.

---

#### B12.2.9 — Hot-path round-trip (#10)

The final verification step exercises the full Rep-utterance → AP webhook → Orchestrator → LLM → NDJSON streaming → AP TTS loop. See §B11 for the script details.

```bash
# Pre-requisite: app server + arq workers running; ngrok tunnel up if local
python -m scripts.verify_hot_path
```

Outputs a PASS/FAIL line and a JSON artifact (`verify_hot_path_report_<ts>.json`) with per-turn latency breakdowns. PASS = `first_chunk_p95 < 700ms` and `full_response_p95 < 2500ms` across 10 simulated turns.

If #10 passes, the deployment is **truly functional end-to-end**: third-party + infrastructure verified individually, and the live hot path proven against real services.

### B12.3 — Where to store credentials

| Environment | Storage |
|---|---|
| Local dev | `.env.local` (gitignored). Never commit. |
| Staging | A secret manager (AWS Secrets Manager / GCP Secret Manager / 1Password CLI / Doppler) — pulled into env at process start. |
| Production | Same secret manager as staging, separate namespace. **Production credentials must be distinct from staging.** Production Supermemory key should be scoped read-only on customer data (no `delete`) if your tier supports scoped keys. |

A `.env.example` ships in the repo as a template (filenames-only, no values).

### B12.4 — Rotation cadence

| Credential | Rotate every | How |
|---|---|---|
| `AGENTPHONE_API_KEY` | 90 days | Dashboard → regenerate; update secret manager; restart app |
| `AGENTPHONE_WEBHOOK_SECRET` | 90 days | `POST /v1/webhooks` with same URL produces a new secret; old becomes invalid immediately |
| `SUPERMEMORY_API_KEY` | 90 days | Dashboard → regenerate |
| `ANTHROPIC_API_KEY` | 90 days | Console → revoke + new key |
| Database passwords | 180 days | Cloud provider rotation feature |
| S3 access keys | 90 days | IAM rotation feature |
| `JWT_SECRET` | only on suspected leak | Forced re-login for all users; communicate to customers |

After every rotation, **re-run `python -m smoke run --all --mode check`** before announcing complete.

### B12.5 — What to do when a probe fails in production

1. Check the exit code: `1`=our config/contract broken, `2`=env vars missing, `3`=third-party down (often not actionable).
2. For exit `1`: read the `fix_hint` in the failed check; this is the most likely fix.
3. For exit `3` on a third-party probe: check the third-party's status page; if confirmed outage, page status to customers but don't roll back.
4. Re-run the same probe in `repair` mode for verbose diagnostics:
   ```bash
   python -m smoke.<name> --mode repair
   ```
   Repair mode dumps the full request/response from each failed check (with secrets redacted) plus query plans for the Postgres probes.

---

# Part C — MVP Loop

The 10 product priorities (#1–#10 in HLD §13). Sections below give module boundaries, signatures, sequence, data-model deltas, edge cases, tests.

## C1. Manager Signup + Workspace Provisioning

Covers HLD priorities #1 and #2.

**Endpoints (in `app/api/auth.py` and `app/api/workspaces/config.py`):**
| Method | Path | Purpose |
|---|---|---|
| POST | `/api/v1/auth/signup` | Create user + org + workspace + AP number + Supermemory namespace + brain schema |
| GET | `/api/v1/me` | Current user + workspace summary |
| GET | `/api/v1/workspaces/{wid}/config` | Return Workspace settings |
| PATCH | `/api/v1/workspaces/{wid}/config` | Update `workspace.config` JSON (timeouts, retention, defaults) |

**Service: `WorkspaceProvisioningService` (`app/services/workspace_provisioning.py`).**

```python
class WorkspaceProvisioningService:
    def __init__(self, uow: UnitOfWork, telephony: TelephonyProvider,
                 memory: CallerMemoryProvider, brain: BrainProvider): ...

    async def signup(self, email: str, password: str, workspace_name: str) -> SignupResult:
        async with self.uow.begin():
            org = await self.uow.org.create(name=f"{workspace_name} (auto)")
            user = await self.uow.user.create(email=email, password_hash=hash(password),
                                              role="manager", organization_id=org.id)
            ws = await self.uow.workspace.create(organization_id=org.id, manager_user_id=user.id,
                                                  name=workspace_name, primary_number="")
            user.workspace_id = ws.id
            await self.uow.flush()
        # Outside the transaction: external side effects
        ws.primary_number = await self.telephony.provision_workspace(ws)
        await self.brain.ensure_schema(ws.id)             # creates brain_w_{wid} + runs migrations
        await self.memory.ensure_namespace(ws.id)         # noop for Supermemory; placeholder for futures
        async with self.uow.begin():
            await self.uow.workspace.update_number(ws.id, ws.primary_number)
        return SignupResult(user=user, workspace=ws, tokens=issue_tokens(user))
```

**Failure handling — the critical sequence:** external calls (AP number provisioning, brain-schema creation) happen *after* the DB commit. If AP fails, the Workspace row exists with empty `primary_number` and is marked `provisioning_state="number_pending"`; a background `workspace_provisioning_retry` job retries every 30s for up to 1h, then notifies the Manager that signup is stuck. The signup endpoint returns 201 with `{"workspace": {...}, "provisioning_state": "number_pending"}` if AP is slow — the FE shows a banner until the number is live.

This pattern (commit-then-side-effect with explicit pending state) avoids the worst case: a transaction-rolled-back AP number that we paid for and now leak.

**Data model deltas vs HLD §6:**
```python
class ManagerWorkspace(Base):
    ...                                  # all HLD fields
    provisioning_state: Literal["pending", "number_pending", "ready", "failed"] = "pending"
    agentphone_agent_id: str | None      # AP persona ID
    agentphone_number_id: str | None     # AP number ID (for later deprovisioning)
```

**Edge cases:**
- Email already exists → 409 `email_taken`.
- AP provisioning rate-limited → mark `number_pending`, retry async, don't block 201.
- Brain schema creation fails (Postgres permissions) → 500 `provisioning_failed` after retry exhausted; row marked `failed`; ops alert.

**Tests:**
- `tests/integration/api/test_signup_happy_path.py` — fake AP returns a number; signup returns 201; assert org/workspace/user/brain_schema all exist.
- `tests/integration/api/test_signup_ap_slow.py` — fake AP delays 10s; assert signup returns 201 with `number_pending`; assert background retry eventually fills the number.
- `tests/integration/api/test_signup_email_taken.py`.

## C2. Intake Pipeline (Onboarding + Continuous Updates)

Covers HLD priority #3, drawing on HLD §7.1.

**Important framing:** the intake API is **not onboarding-only**. The Manager continues to use it whenever they have new information to feed the system: a fresh CRM export quarterly, an updated playbook, a per-Rep coaching note, a corrected account fact. The same classifier + handlers + provenance pipeline runs whether the input arrives on day 1 or day 200. Onboarding is just the first heavy use of the same surface.

The pipeline distinguishes "onboarding" from "ongoing" only at the intake-record level (a `purpose` field on `IntakeBufferItem`) so analytics can split them; behavior is identical.

**Endpoints (in `app/api/workspaces/intake.py`):**

*Submission (used both during onboarding and ongoing):*
| Method | Path | Purpose |
|---|---|---|
| POST | `/workspaces/{wid}/intake/text` | Add a free-form intake item (form field, voice intake transcript chunk, ad-hoc note) |
| POST | `/workspaces/{wid}/intake/upload` | Upload a document (multipart); returns `intake_item_id` |
| POST | `/workspaces/{wid}/intake/process` | Trigger or check the IntakeProcessor (idempotent; usually triggered automatically on submit) |

*Inspection + history (continuous use):*
| Method | Path | Purpose |
|---|---|---|
| GET | `/workspaces/{wid}/intake/items?purpose=&kind=&from=&to=` | List all past intake items, paginated, filterable. The "everything I've ever fed the system" view. |
| GET | `/workspaces/{wid}/intake/items/{item_id}` | Detail: classification, handler result, links to created/updated Brain pages |
| GET | `/workspaces/{wid}/intake/items/{item_id}/download` | 302 to signed URL for the original uploaded blob (if `kind=upload`) |
| POST | `/workspaces/{wid}/intake/items/{item_id}/supersede` | Mark a prior item superseded by a newly-uploaded one (e.g., "this is the Q3 playbook, replacing the Q2 one"). Triggers re-extraction; old item's provenance is retained for audit. |
| DELETE | `/workspaces/{wid}/intake/items/{item_id}` | Soft-delete: removes the blob from S3, retains the row + an audit note; downstream Brain pages keep their derived content but lose the citation, surfacing as `[broken-citation]` (cleanup is a Phase 1 dream-cycle task). |

*Review (Stage 5 verification + ongoing low-confidence review):*
| Method | Path | Purpose |
|---|---|---|
| GET | `/workspaces/{wid}/intake/review` | Items needing Manager review (low-confidence classifications + the Stage-5 "What we learned" snapshot during onboarding) |
| POST | `/workspaces/{wid}/intake/review/{item_id}` | Manager confirms or corrects a classification |

**Data models:**
```python
class IntakeBufferItem(Base):                # in app DB
    id: UUID
    workspace_id: UUID
    organization_id: UUID
    source: Literal["form", "upload", "voice_intake", "correction"]
    purpose: Literal["onboarding", "ongoing_update", "correction"]  # analytics + Stage-5 filtering
    content_text: str | None
    content_blob_key: str | None             # s3 key for uploads, via workspace_key(...)
    content_mime: str | None
    content_filename: str | None             # original filename, retained for audit
    content_sha256: str | None               # dedupes accidental re-uploads (same file twice → 200 with original item_id)
    extractor_used: str | None               # which extractor module handled extraction (see SupportedUpload below)
    submitted_by_user_id: UUID
    submitted_at: datetime
    status: Literal["queued", "extracting", "classified", "ingested", "needs_review", "failed", "superseded", "deleted"]
    classification: dict | None              # ClassificationOutput JSON, post-classifier
    handler_result: dict | None              # what got written: page slugs created/updated, etc.
    superseded_by_item_id: UUID | None       # set when a newer upload replaces this
    error: str | None
```

**Supported upload formats & extractor modules:**

```python
# app/services/intake_extractors/base.py
class IntakeExtractor(Protocol):
    name: str
    accepts_mime: list[str]
    accepts_ext: list[str]
    async def extract(self, blob: BinaryIO, filename: str) -> ExtractedContent: ...

class ExtractedContent(BaseModel):
    text: str | None                         # for prose docs
    rows: list[dict] | None                  # for tabular (CSV/XLSX) — header-keyed dicts
    tables: list[list[list[str]]] | None     # for PDFs with embedded tables
    metadata: dict                           # extractor-specific (sheet names, page count, etc.)
    warnings: list[str] = []                 # e.g., "scanned PDF: no text extracted"
```

```python
# app/services/intake_extractors/__init__.py
class SupportedUpload(StrEnum):
    PDF = "pdf"
    DOCX = "docx"
    TXT = "txt"
    MD = "md"
    CSV = "csv"
    XLSX = "xlsx"
    JSON = "json"
```

| Extractor module | Format | Library | Output shape |
|---|---|---|---|
| `pdf_extractor.py` | `.pdf` | `pdfplumber` (text) + `pypdf` fallback | `text` + `tables` (if any) |
| `docx_extractor.py` | `.docx` | `python-docx` | `text` |
| `text_extractor.py` | `.txt`, `.md` | stdlib | `text` |
| `csv_extractor.py` | `.csv` | stdlib `csv` | `rows` |
| `xlsx_extractor.py` | `.xlsx` | `openpyxl` | `rows` per sheet, `metadata.sheets` |
| `json_extractor.py` | `.json` | stdlib | `rows` if top-level array, else `text` |

**Extractor registry** follows the same pattern as the other §A11 registries. Adding `.eml` support is one new file + one registry entry. The `IntakeProcessor` resolves the right extractor by MIME first, file extension as fallback; unknown formats land as `failed` with `error="unsupported_format"`.

**Submit flow:**

```
POST /intake/upload (multipart file)
  ↓ validate size <25MB → 413 if not
  ↓ compute SHA-256; if (workspace_id, sha256) already exists with status≠deleted:
      return 200 with original item_id (dedupe)
  ↓ stream blob to S3 at workspace_key(wid, "intake", item_id, filename)
  ↓ persist IntakeBufferItem(status=queued, purpose=ongoing_update|onboarding inferred from FE flag)
  ↓ enqueue arq job process_intake_item(item_id)

POST /intake/text  (JSON body)
  ↓ persist IntakeBufferItem(content_text=..., status=queued, purpose=...)
  ↓ enqueue arq job process_intake_item(item_id)
```

**Worker flow:**
```
worker process_intake_item:
  ↓ load item
  ↓ if kind=upload: resolve extractor; status=extracting; run extractor; persist extracted summary in handler_result
  ↓ classify via classifier skill (text → ClassificationOutput)
  ↓ if confidence < 0.7: status=needs_review, exit
  ↓ resolve handler by (scope, kind):
      ORG_WIDE → OrgBrainHandler
      CALLER_SPECIFIC → CallerBrainHandler
      BOTH → CrossRefHandler
      RAW_SOURCE → RawSourceHandler
  ↓ handler.ingest(...)  (writes to Brain and/or Supermemory, with Provenance)
  ↓ status=ingested
```

**Handlers** (in `app/services/intake_processor.py`):

```python
class IntakeHandler(Protocol):
    async def ingest(self, *, workspace_id: UUID, content: IntakeContent,
                     classification: ClassificationOutput, item_id: UUID) -> HandlerResult: ...

class OrgBrainHandler:
    """Fuzzy-match slug; create-or-update BrainPage; run regex entity extractor; embed."""
class CallerBrainHandler:
    """Update field_employees / caller_profiles structured fields; push free-form to Supermemory."""
class CrossRefHandler:
    """Compose OrgBrainHandler + CallerBrainHandler + create bidirectional edges."""
class RawSourceHandler:
    """Fan-out: whole doc → Supermemory; per-row entities → Brain; ownership rollups → caller profiles.
       Spawns brain_seeder mini-agent for the heavy walk."""
```

**Provenance** (HLD §9.1): every write carries a `Provenance` record. Construction helper `Provenance.from_intake(item)` populates `source_type`, `source_id=item.id`, `extracted_by=f"classifier@{skill_version}"`, `extracted_at=now`, `confidence`.

**Stage 5 verification surface** (HLD §7.1.6): `GET /intake/review` returns a structured "What we learned" snapshot:
```json
{
  "summary": {
    "accounts_created": 47, "people_created": 132, "themes_created": 8,
    "ownership_assignments": 200, "needs_review_count": 12
  },
  "needs_review": [{ "item_id": ..., "classification": ..., "content_preview": ... }, ...],
  "top_accounts": [...],
  "callers_built": [...]
}
```

The FE renders this and lets the Manager confirm or click into corrections (which go through §C8).

**On re-uploads & supersession (continuous-use behavior):**

When the Manager uploads an updated version of something already ingested (e.g., a refreshed playbook), three behaviors stack:

1. **SHA-256 dedupe.** Identical file bytes → 200 with the original `item_id`; no work done. Catches accidental double-clicks.
2. **Slug fuzzy-match in OrgBrainHandler.** A different file with the same logical target slug (`playbooks/discovery`) updates the existing `BrainPage` via the §C8 versioning machinery: new `BrainPageVersion`, old version retained, timeline gets an entry "Updated from upload {item_id}".
3. **Explicit `POST /supersede`.** When the Manager wants to be explicit ("this Q3 playbook replaces the Q2 one"), the new item links via `superseded_by_item_id`; the old item's status flips to `superseded`; the OrgBrainHandler is invoked with `mode=replace` instead of `mode=update`, which clears the prior compiled_truth rather than merging.

**Manager-authoritative interaction:** if any field on the target page is `manager_authoritative=true` (set by a prior Manager correction per §C8), the ongoing upload **cannot silently overwrite it** — the conflict surfaces as a `needs_review` item with a side-by-side diff. The Manager either confirms the new value (which keeps `manager_authoritative=true`) or rejects it (the upload still creates a Brain timeline entry citing it as context, but the compiled_truth stays as-is). This is the §9.6 "the LLM doesn't get to correct itself" rule extended to Manager-driven re-ingestion.

**Edge cases:**
- Upload >25 MB → 413 with `fix_hint`. Manager splits.
- Unsupported extension → `failed` with `error="unsupported_format"`; FE shows supported list.
- Scanned-image PDF (no text-extractable layer) → extractor returns `warnings=["no_text_extracted"]`; item lands `needs_review` so the Manager knows to re-export as searchable PDF.
- Classifier returns invalid JSON twice → mark `failed`, surface to ops dashboard.
- Brain page slug collision after fuzzy match (two distinct entities with same suggested slug) → fall back to `kind:{N}` suffix; surface to NeedsReview.
- `DELETE /items/{id}` on an item whose extractions are heavily linked (10+ derived pages) → 409 with `linkage_count`; Manager confirms with `?force=true`. Even with `force=true`, derived pages are kept (audit), but lose the citation.
- `POST /supersede` targeting an item that's itself already superseded → 409, point at the current head of the chain.

**Tests:**
- `tests/integration/intake/test_classifier_routes_correctly.py` — golden fixtures from `skills/classifier/fixtures/`.
- `tests/integration/intake/test_raw_source_fanout.py` — upload a tiny CRM CSV; assert 5 accounts + 8 people + 5 owned_by edges + 5 caller-profile updates.
- `tests/integration/intake/test_needs_review_surfacing.py` — feed a low-confidence item; assert it shows in `/intake/review`.
- `tests/integration/intake/test_extractor_registry.py` — one test per extractor: upload a fixture file, assert ExtractedContent shape matches expected.
- `tests/integration/intake/test_sha_dedupe.py` — upload same file twice; assert second call returns original item_id, no second worker run.
- `tests/integration/intake/test_supersede_replaces_compiled_truth.py` — upload playbook v1, then supersede with v2; assert OrgBrainHandler runs in replace mode and `BrainPageVersion` chain has 2 entries.
- `tests/integration/intake/test_ongoing_upload_respects_manager_authoritative.py` — Manager corrects a page (sets `manager_authoritative=true`); subsequent upload with conflicting content lands `needs_review` instead of silently overwriting.
- `tests/integration/intake/test_intake_history_list_filters.py` — submit items across two purposes + two kinds; assert filter params slice correctly.

## C3. Telephony Adapter — AgentPhone

Covers HLD priority #4 (telephony slice). Backed by `app/telephony/agentphone.py`.

**Webhook endpoint:** `POST /api/v1/webhooks/agentphone` in `app/api/webhooks/agentphone.py`. Critical: **NOT under `/workspaces/{wid}`** — AP doesn't know our scope; the adapter resolves it.

```python
@router.post("/agentphone", response_class=StreamingResponse | Response)
async def agentphone_webhook(request: Request, adapter: AgentPhoneAdapter = Depends(...)):
    raw = await request.body()
    headers = request.headers
    try:
        event = adapter.parse_webhook(raw, headers)     # raises 401/400 on bad HMAC/replay
    except (BadSignature, ReplayWindowExceeded) as e:
        return Response(status_code=e.http_status)

    if await is_duplicate(headers["X-Webhook-ID"]):
        return Response(status_code=200)

    match event:
        case InboundVoiceTurn():
            return await orchestrator_voice_turn(event)        # NDJSON StreamingResponse
        case InboundSMS():
            await dispatch_sms(event)
            return Response(status_code=200)
        case CallEnded():
            await on_call_ended(event)                          # enqueues post_call
            return Response(status_code=200)
```

**`AgentPhoneAdapter.parse_webhook` responsibilities** (HLD §5.1, §11.2):
1. HMAC-SHA256 verify over `{timestamp}.{raw_body}` with `AGENTPHONE_WEBHOOK_SECRET`.
2. Reject if `|now - timestamp| > 300s`.
3. Resolve scope: prefer `conversationState.workspace_id` echo; fall back to `Workspace.where(primary_number=data.to)`.
4. Dedupe via Redis `seen_webhooks` set (TTL 7d).
5. Map AP event/channel into one of `InboundVoiceTurn | InboundSMS | CallEnded | ReactionReceived`.

**`reply_voice` streaming** (HLD §5.5.1, §11.2.3): returns a `StreamingResponse(content_type="application/x-ndjson")` that yields `{"text": "...", "interim": True|False}` objects until the Orchestrator emits its final chunk. The streamer lives in `app/orchestrator/streaming.py` (§C4) — the adapter is thin.

**Per-conversation metadata:** on the first voice webhook for a new `callId`, the adapter calls `client.conversations.update(metadata={workspace_id, call_id, field_employee_id})`. Subsequent webhooks have `conversationState` populated and skip the DB lookup.

**Edge cases:**
- HMAC fail → 401, log + counter `votf_webhook_hmac_fail_total`.
- Number not associated with any Workspace → 404 with body `{"error":"unknown_number"}`; AP retries 6 times then gives up (expected: misconfigured number).
- AP retries while our handler is still processing the first attempt → second attempt sees `seen_webhooks` and returns 200 instantly (idempotent).
- Voice turn while no orchestrator session in Redis → spawn one (call must have been started; if not, log + 200 to drain AP retries while ops investigates).

**Tests:**
- `tests/integration/telephony/test_hmac.py` — valid sig accepted; bad sig 401; replay window 400.
- `tests/integration/telephony/test_dedupe.py` — same `X-Webhook-ID` twice → handler runs once.
- `tests/integration/telephony/test_conversation_state_echo.py` — first webhook PATCHes metadata; second webhook skips the PATCH.
- `tests/e2e/test_inbound_call_end_to_end.py` — uses fake-AP to deliver call.started → voice × N → call.ended; asserts full state.

## C4. Orchestrator + Hot-Path Streaming

Covers HLD priority #4 (orchestrator slice). The single hottest module in the system.

**Module layout** (`app/orchestrator/`):
- `session.py` — `CallSession`, Redis-backed state.
- `retrieval.py` — parallel CallerMemory + Brain hybrid search.
- `prompts.py` — wraps `skills/orchestrator/turn_prompt.j2`.
- `streaming.py` — NDJSON streamer + bridge-chunk emitter.
- `turn_loop.py` — the per-turn driver.
- `tools/` — `OrchestratorTool` implementations.

**CallSession**:

```python
@dataclass
class CallSession:
    call_id: UUID
    workspace_id: UUID
    field_employee_id: UUID | None
    conversation_history: list[Turn]          # capped at last 40 turns
    retrieved_cache: dict                     # starter-pack + per-turn caches
    pending_decisions: list[DecisionRef]
    manager_whispers: list[str]               # populated in Phase 1
    state_version: int                        # optimistic concurrency

class SessionStore:
    async def load(self, call_id: UUID) -> CallSession: ...
    async def save(self, session: CallSession) -> None: ...     # CAS on state_version
```

Backed by Redis key `session:call:{call_id}`, JSON-encoded. TTL = max-call-duration (4h) + buffer.

**Turn loop:**

```python
async def handle_voice_turn(event: InboundVoiceTurn) -> AsyncIterator[NDJSONChunk]:
    session = await session_store.load(event.call_id)
    transcript = TranscriptFragment(speaker="caller", text=event.transcript, ts=now())
    await transcript_bus.publish(session.workspace_id, session.call_id, transcript)
    await call_repo.append_transcript(transcript)

    # Parallel retrieval
    retrieval_task = asyncio.create_task(retrieve_context(session, event.transcript))

    # If retrieval is slow, emit a bridge chunk
    bridge_task = asyncio.create_task(maybe_bridge_chunk(retrieval_task))
    async for chunk in bridge_task:                       # yields 0 or 1 chunk
        yield chunk

    retrieved = await retrieval_task
    session.append_retrieved(retrieved)

    # Streaming LLM call
    async for chunk in stream_llm_turn(session, retrieved, event.transcript):
        yield chunk

    await session_store.save(session)
```

**Retrieval** (`retrieval.py`):

```python
async def retrieve_context(session: CallSession, utterance: str) -> RetrievedContext:
    starter = session.retrieved_cache.get("starter")
    if starter is None:                       # first turn — pre-warm
        starter = await prewarm(session)
        session.retrieved_cache["starter"] = starter
    caller_task = caller_memory.search(session.field_employee_id_key, utterance, k=5)
    brain_task = brain.hybrid_search(session.workspace_id, utterance, k=8)
    caller, brain_hits = await asyncio.gather(caller_task, brain_task)
    return RetrievedContext(starter=starter, caller=caller, brain=brain_hits)
```

**Streaming LLM** (`streaming.py`):
- Uses Anthropic native `client.messages.stream()` for the live path.
- Token groups (small batches) are forwarded as NDJSON `{"text": group, "interim": true}` chunks.
- Tool calls trigger: emit bridge chunk → execute tool → re-call LLM with tool result → continue streaming.
- Final chunk has `interim` absent (HLD §11.2.3).

**Bridge chunk policy** (HLD §5.5.1): if retrieval task hasn't resolved within 300ms, emit `{"text":"<short bridging phrase>","interim":true}` chosen from a small rotation in `skills/orchestrator/bridges.json` (e.g., "Let me check on that...", "Give me a sec..."). The rotation prevents the same phrase every call.

**Tools** (HLD §5.5.3, §7.3):
- `request_manager_decision(prompt, options, decision_class)` — §C6.
- `request_correction(target, kind, payload, rationale?)` — §C8.
- `mark_followup(description, due_at?)` — creates an `ActionItem(status=pending_approval)`.
- `fetch_account(slug)` — convenience wrapper around `brain.get_page`.
- `end_call(reason)` — emits `{"hangup": true}` chunk.

`web_research` is a Phase 1+ tool; in Phase 0 it's registered but always returns "not available in this phase" so the LLM stops trying.

**Edge cases & failure modes:**
- LLM timeout (>10s for first token) → emit `{"text":"Sorry, I'm having trouble. Let me try again shortly.", "interim": false}`, close turn, log error. Next caller utterance gets a fresh attempt.
- Tool raises → emit bridge "Hmm, let me try that another way" and pass an error-shaped tool result back to LLM so it can recover.
- Redis session lost (e.g., key evicted) → reconstruct from `Call` row + last N `TranscriptFragment` rows; log warning. Conversation continues with minimal context loss.
- AP webhook timeout looming (we have 30s) → if we're at 25s and still streaming, emit the current accumulated text as a final chunk and continue the rest in the *next* turn (rare; logged).

**Tests:**
- `tests/unit/orchestrator/test_session_cas.py` — concurrent save raises; retry.
- `tests/unit/orchestrator/test_bridge_chunk_emission.py` — fake slow retrieval; assert bridge chunk emitted.
- `tests/integration/orchestrator/test_streaming_ndjson_shape.py` — fake LLM that emits 5 token-groups; assert client receives 5 interim + 1 final NDJSON line.
- `tests/load/test_turn_latency.py` — uses `scripts/simulate_inbound_voice.py` against a fake-LLM that emits a token every 50ms; asserts P95 first-chunk <700ms.

## C5. Multi-Call Live WebSocket

Covers HLD priority #5 (HLD §5.5.2).

**Endpoint:** `GET /api/v1/workspaces/{wid}/ws/live` (WebSocket upgrade). Auth via `?token=<short-lived JWT>` query string (per HLD §5.6). Token TTL 30s, single-use, issued by `POST /workspaces/{wid}/ws/token` after a normal authenticated request.

**Frame types** (`app/schemas/ws_frames.py`, mirroring HLD §5.5.2):
| Frame | Schema |
|---|---|
| `call.started` | `{call_id, field_employee_id, started_at}` |
| `transcript.fragment` | `{call_id, speaker, text, ts}` |
| `decision.opened` | `{call_id, decision_id, prompt, options, decision_class, timeout_at}` |
| `decision.resolved` | `{call_id, decision_id, response, responded_via}` |
| `call.ended` | `{call_id, ended_at}` |

(`takeover.*` frames ship Phase 1.)

**Hub** (`app/realtime/ws_hub.py`):
- On connect, server subscribes to `call:*:transcript` for this Workspace's active calls (set: `call:{wid}:active`).
- When a new call starts (lifecycle event), hub subscribes to that call's channel on the fly.
- Inbound frames are tagged with `call_id` and forwarded to the WS.
- Server also publishes a `decisions:{wid}` channel that carries `decision.opened` / `decision.resolved` frames.
- Heartbeat: server sends a ping frame every 20s; client must pong within 10s or the connection is closed.

**Initial snapshot:** on connect, server sends a `snapshot` frame with the current list of in-progress calls (calls `GET /workspaces/{wid}/calls?status=in_progress` internally). Replaces the FE doing a separate REST call.

**Edge cases:**
- WS disconnect mid-call → client reconnects with a new short-lived token; receives a fresh snapshot frame; no replay of transcript fragments (the REST `GET /calls/{id}/transcript` is the durable source).
- 50+ concurrent calls in a Workspace → server fanout uses one Redis subscriber per WS connection (not per-call). Scales to 100s of calls per WS.
- Backpressure on slow client → server buffers up to 100 frames; drops further frames with a `dropped` counter; logs.

**Tests:**
- `tests/integration/realtime/test_ws_multi_call.py` — open WS, start two calls, publish transcript fragments on each; assert both reach the WS tagged correctly.
- `tests/integration/realtime/test_ws_auth.py` — bad token rejected; expired token rejected; valid token accepted.
- `tests/integration/realtime/test_ws_reconnect.py` — drop WS mid-call; reconnect; assert snapshot has the in-progress call.

## C6. Decision Loop

Covers HLD priority #6 (HLD §5.5.3, §7.3).

**Endpoints (in `app/api/workspaces/decisions.py`):**
| Method | Path | Purpose |
|---|---|---|
| GET | `/workspaces/{wid}/decisions?status=...` | List |
| GET | `/workspaces/{wid}/decisions/{id}` | Detail |
| POST | `/workspaces/{wid}/decisions/{id}/respond` | Manager picks an option |

Plus the SMS response path: AP delivers an inbound SMS from the Manager → adapter dispatches to `DecisionService.match_sms_response`.

**Data model:** as HLD §6. No changes.

**`DecisionService` (`app/services/decisions.py`):**

```python
class DecisionService:
    async def open(self, *, call_id: UUID, workspace_id: UUID,
                   prompt: str, options: list[str],
                   decision_class: Literal["inline","bridged","async"]) -> DecisionRequest:
        timeout = {"inline": 45, "bridged": 120, "async": None}[decision_class]
        d = await self.repo.create(...)
        await self.bus.publish_decision_opened(workspace_id, call_id, d)
        await self.sms.fire_decision_sms(workspace_id, d)
        if timeout:
            await arq.enqueue(decision_timeout_job, d.id, _defer_by=timeout, _job_id=f"dt:{d.id}")
        return d

    async def respond(self, decision_id: UUID, user_id: UUID,
                      response: str, via: Literal["websocket","sms"]) -> DecisionRequest:
        d = await self.repo.lock_for_update(decision_id)        # SELECT ... FOR UPDATE
        if d.status != "open":
            raise Conflict("decision_already_resolved")
        await self.repo.mark_answered(d, response, user_id, via)
        await self.session_bus.publish(d.call_id, DecisionResolved(d.id, response, via))
        await self.bus.publish_decision_resolved(d.workspace_id, d.call_id, d)
        return d
```

**Fan-out on `open`:**
1. Persist row.
2. WS frame `decision.opened` to the Workspace's live channel.
3. SMS to the Manager's mobile (parallel; first-responder wins).
4. Schedule the `decision_timeout` arq job at `now + class_timeout`.

**Bridging behavior in Orchestrator:**
- `inline`: streaming continues with a bridging utterance like "Let me check on that — while I do, what did the buyer say about timeline?"
- `bridged`: Orchestrator continues the conversation on a different thread; the LLM is prompted that an answer may arrive later and will be inserted in the next turn.
- `async`: no bridging; no live wait; surfaces post-call.

The prompt strings for bridging live in `skills/orchestrator/turn_prompt.j2` so they're versioned + evallable.

**SMS response matching:** when the Manager texts back, we need to know which open DecisionRequest they meant. Phase 0 strategy: the SMS sent in step 3 begins with `[DR-<short_id>]`. The Manager's reply is parsed for this prefix; if missing and exactly one open DR for this Manager, assume that one; if missing and multiple open DRs, reply with a clarification SMS listing them.

**Edge cases:**
- Manager taps option on WS and replies SMS within the same second → repo `SELECT FOR UPDATE` + `status=open` check means the second loses with 409; loser is shown a "decision already resolved" toast.
- SMS reply but parsing fails (unrelated text) → not a decision response; routed to brain-write per HLD §5.5.5 (Phase 0 partial implementation: log + drop with a "didn't understand that" SMS back).
- Orchestrator already ended the call by the time the response arrives → record on the DecisionRequest but skip session push; surfaces in post-call review.

**Tests:**
- `tests/integration/decisions/test_open_pushes_ws_and_sms.py`.
- `tests/integration/decisions/test_first_responder_wins.py`.
- `tests/integration/decisions/test_sms_prefix_matching.py`.
- `tests/e2e/test_decision_loop_end_to_end.py`.

## C7. Decision Timeout & Brief-Flagging Skeleton

Covers HLD priority #7. Full daily-brief implementation is Phase 1 (priority #17); Phase 0 ships the skeleton.

**Worker:** `app/workers/decision_timeout.py`:

```python
async def decision_timeout_job(ctx, decision_id: UUID):
    d = await decisions_repo.lock_for_update(decision_id)
    if d.status != "open":
        return                                 # already answered
    await decisions_repo.mark_timed_out(d)
    await session_bus.publish(d.call_id,
        SessionEvent("decision_timed_out", {"decision_id": str(d.id)}))
    await ws_bus.publish_decision_resolved(d.workspace_id, d.call_id, d)   # carries response=null, via="timeout"
    # Brief-flagging: nothing more here in Phase 0; dashboard_rollup
    # in Phase 1 will pull DecisionRequest.status=timed_out since last brief.
```

**Orchestrator behavior on receiving `decision_timed_out` session event:** the next LLM turn's prompt receives a system note: "The Manager did not respond to your decision request. Tell the Rep plainly that the Manager is unavailable, capture anything else worth knowing, and move on." See HLD §5.5.3.

**`missed_decisions` view** (skeleton for Phase 1 to consume): `app/services/decisions.py::list_missed_for_brief(workspace_id, since: datetime)` returns timed-out decisions whose `surfaced_in_brief_at` is null. Phase 1's `dashboard_rollup` calls it and marks them surfaced.

**Tests:**
- `tests/integration/decisions/test_timeout_marks_status.py` — open + advance clock + assert `timed_out`.
- `tests/integration/decisions/test_timeout_after_answer_noop.py`.
- `tests/integration/orchestrator/test_timeout_alters_next_turn_prompt.py` — assert the next-turn prompt includes the timeout note.

## C8. Correction & Provenance Scaffolding

Covers HLD priority #8 (HLD §9). Phase 0 scope:
- Per-page provenance only (per-claim is §14.2 open).
- `BrainPageVersion` table with monotonic version + `superseded_by`.
- `CorrectionIntake` flow shared from intake pipeline (§C2).
- `correction_cascade` worker — minimal: updates denormalized lists (caller owned_accounts), adds timeline entries, invalidates retrieval cache. Heavier propagation (embedding recompute) deferred to Phase 1.
- `manager_authoritative=true` flag set on fields touched by a Manager correction; auto-extractor cannot overwrite.

**Data model** (`app/db/models/provenance.py`):

```python
class Provenance(Base):
    id: UUID
    source_type: Literal["manager_form","manager_upload","manager_voice_intake",
                          "manager_correction","field_call","automated_extraction",
                          "external_research","system_seed"]
    source_id: UUID
    extracted_by: str | None         # e.g., "classifier@0.3.0"
    extracted_at: datetime
    confidence: float | None
    cites: list[Citation]            # JSON column
```

`BrainPage` gains `provenance_id` FK and `manager_authoritative: bool`. Every write through the brain provider takes a `provenance: Provenance` argument; the provider persists it before writing the page.

**BrainPageVersion** (lives in `brain_w_{wid}` schema):
```python
class BrainPageVersion(Base):
    __table_args__ = {"schema": <runtime workspace schema>}
    id: UUID
    page_slug: str
    version: int                     # monotonic per slug
    compiled_truth: str
    provenance_id: UUID
    superseded_by: UUID | None
    created_at: datetime
```

The "current" view: `SELECT DISTINCT ON (page_slug) * FROM brain_page_versions WHERE superseded_by IS NULL ORDER BY page_slug, version DESC`.

**CorrectionIntake handler** (`app/services/corrections.py`):

```python
class CorrectionHandler:
    async def apply(self, intake: CorrectionIntake) -> CorrectionResult:
        # 1. Resolve target entity
        # 2. Apply the correction_kind:
        #    - replace_compiled_truth: new BrainPageVersion, append timeline "[CORRECTED by manager]..."
        #    - delete_edge / add_edge: as named
        #    - merge_entities / split_entity: tombstone + new pages, retain provenance
        #    - set_profile_field: update caller_profiles row, set manager_authoritative=true
        #    - soft_delete_page: mark deleted_at, retain rows
        # 3. Persist with source_type=manager_correction, confidence=1.0
        # 4. Enqueue correction_cascade(target, kind, payload)
```

**`correction_cascade` worker** (`app/workers/correction_cascade.py`): the Phase 0 minimum is the example walk in HLD §9.4 — update denormalized caller `owned_accounts`, append timeline tags on related calls, invalidate `RetrievalCache` for affected slugs. Embedding recompute is enqueued but executed lazily on next read in Phase 0; Phase 1 adds an immediate pass.

**Endpoints (in `app/api/workspaces/brain.py`):**
| Method | Path | Purpose |
|---|---|---|
| GET | `/workspaces/{wid}/brain/pages/{slug}` | Current truth + timeline + provenance |
| GET | `/workspaces/{wid}/brain/pages/{slug}/versions` | Version history |
| POST | `/workspaces/{wid}/brain/corrections` | Submit a CorrectionIntake (same shape as Stage 5 corrections) |

**Edge cases:**
- Correction targeting nonexistent slug → 404 `target_not_found`.
- Correction targeting a slug being modified by another correction → optimistic concurrency on `BrainPageVersion.version`; retry.
- Cascade error after main correction committed → cascade marked `partially_applied`; ops-visible; user sees the correction in place but with a "syncing" indicator.

**Tests:**
- `tests/integration/corrections/test_replace_compiled_truth_versioning.py`.
- `tests/integration/corrections/test_manager_authoritative_blocks_auto.py` — apply correction; run auto extractor; assert auto-extracted change does NOT land.
- `tests/integration/corrections/test_cascade_ownership.py` — Sarah→Bob example end-to-end.

## C9. Skills Directory + Eval CI

Covers HLD priority #9 (HLD §8.7). Most plumbing landed in §A10. Phase 0 ships three skills:

| Skill | Used by | Model | Quality bar |
|---|---|---|---|
| `classifier` | IntakeProcessor (§C2) | claude-haiku | precision ≥0.85 on golden set |
| `orchestrator` | Orchestrator (§C4) | claude-sonnet | manual eval — produces a `eval_score` of ≥0.8 against transcript-graded fixtures |
| `caller_profiler` | Profiling sub-flow (§C3 / C4) | claude-haiku | extraction completeness ≥0.9 |

**Eval harness shape** (`skills/<name>/evals/run.py`):

```python
def main() -> int:
    inputs = load_jsonl("golden_set.jsonl")
    results = []
    for case in inputs:
        out = run_sync_skill(name, case["input"])
        score = metric(out, case["expected"])
        results.append(score)
    metric_value = aggregate(results)
    quality_bar = parse_quality_bar_from_skill_md(name)
    print(json.dumps({"skill": name, "metric": metric_value, "bar": quality_bar}))
    return 0 if metric_value >= quality_bar else 1
```

**CI gate:** `ci.yml::skills_eval` runs every changed `skills/<name>/evals/run.py`. A skill change that drops below bar blocks the merge.

**Workspace overrides surface** (`POST /workspaces/{wid}/skill_overrides`): stores a per-Workspace override prompt for a named skill. Loader picks it up. Phase 0 endpoint is admin-only and lightly documented; it exists so the architecture is provable, not because Phase 0 needs heavy use of it.

**Tests:**
- `tests/integration/skills/test_eval_harness_runs.py` — uses the classifier's golden set; asserts metric > bar.
- `tests/integration/skills/test_workspace_override_loads.py`.

## C10. Hierarchy Guard Test

Covers HLD priority #10. The single most important architectural-commitment test.

**Test file:** `tests/integration/api/test_hierarchy_guard.py`.

**What it asserts:**
1. A `User(role="org_admin", workspace_id=None, organization_id=<org>)` can be created and authenticated.
2. A `User(role="rep", workspace_id=<ws>, field_employee_id=<feid>)` can be created and authenticated.
3. `org_admin` is rejected (403) from `/workspaces/{wid}/...` endpoints (the `require_workspace_access` dep requires `role=manager` in Phase 0).
4. `rep` is rejected (403) from `/workspaces/{wid}/...` endpoints.
5. `org_admin` GET to `/organizations/{org_id}/...` returns 404 (the namespace is reserved but empty in Phase 0).
6. `rep` GET to `/rep/...` returns 404.
7. The `Workspace.organization_id` foreign key is enforced; orphaned Workspaces cannot exist.
8. Cross-Workspace data access is impossible: User from WS_A trying to read WS_B's `Call` returns 403, not 404 — we don't even leak existence.

**Why this matters:** the test enforces that the Phase 0 design *actually* admits Phase 1+ shapes (it isn't only-implemented enough to look right). If a future refactor breaks the multi-tenant scaffolding, this test fails before deploy.

**Adjacent CI check:** a lint that searches for `User(role="manager"` and ensures every non-test usage allows the role list to grow — i.e., `role in {"manager", *FUTURE_ROLES}` patterns rather than hardcoded `role == "manager"` outside the auth layer.

## C11. Minimum Post-Call Writeback

**Why this is in Phase 0** (not Phase 1 as the HLD's priority table suggests): without per-call writes to Brain and Supermemory, the system doesn't compound. Tuesday's call wouldn't benefit from Monday's call; the Brain would only grow from Manager intake (§C2). The whole product premise is "every conversation enriches the next one," so a Phase 0 without writeback fails the demo. The full Phase 1 §D2/§D3 mechanics (action items, typed graph, RRF, escalation, dream cycle) are still deferred — this section ships only the minimum that closes the compounding loop.

### Scope split — Phase 0 §C11 vs Phase 1 §D2 / §D3

| Concern | Phase 0 §C11 (this section) | Phase 1 §D2 / §D3 (extends this) |
|---|---|---|
| `post_call` worker exists | ✓ — fan-out skeleton | extended with `action_item_extractor` |
| `summarizer` mini-agent | ✓ — basic: discussion, blockers, extracted entities | extended: verbatim quotes, topics, multi-entity disambiguation; quality bar raised |
| `brain_updater` mini-agent | ✓ — entity extraction (regex), page upsert, timeline append, stub-page creation | typed graph edges, backlink-boost, escalation logic |
| Caller Memory write | ✓ — push call digest to Supermemory | profile inference helpers; rollups (§D6 if added) |
| Provenance on writes | ✓ — per-page provenance (already from §C8) | per-claim provenance optional |
| Action items | — | ✓ |
| RRF hybrid search | — (Phase 0 brain uses simpler vector+text combine) | ✓ |
| Nightly `brain_maintenance` | — | ✓ |
| Daily brief integration | — | ✓ §D5 |

### Module deltas

`app/miniagents/summarizer.py` (Phase 0 minimum):
```python
class SummarizerMiniAgent(MiniAgent):
    name = "summarizer"
    trigger = "queue"
    async def run(self, ctx, inputs: SummarizerInput) -> SummarizerOutput: ...
```
Backed by `skills/summarizer/` (skill directory created in Phase 0 per §C9; quality bar set low — Phase 1 raises it).

**Skill `skills/summarizer/` minimum:**
- `model: claude-sonnet-4-6` (slow path; budget allows).
- **Input:** Call metadata, full transcript, AP `provider_summary` (hint), top 5 Brain hits for entities mentioned in transcript (best-effort, optional).
- **Output:** `SummarizerOutput { discussion: str, blockers: list[str], extracted_entities: list[EntityRef] }`. Notably **no** `verbatim_quotes`, `topics`, or `confidence` per-entity in Phase 0 — those are Phase 1 additions.
- **Quality bar (Phase 0):** `entity_recall ≥ 0.6` on a 10-call golden set. Low so it doesn't gate MVP; Phase 1 raises to 0.85 with a larger golden set.

`app/miniagents/brain_updater.py` (Phase 0 minimum):
```python
class BrainUpdaterMiniAgent(MiniAgent):
    name = "brain_updater"
    trigger = "queue"
    async def run(self, ctx, inputs: BrainUpdaterInput) -> BrainUpdaterOutput:
        # 1. Run regex entity extractor (app/brain/entity_extractor.py)
        # 2. For each extracted entity:
        #    - resolve_slug() — fuzzy-match against existing pages
        #    - if exists: append TimelineEntry citing call_id; do NOT touch compiled_truth
        #      (compiled_truth changes are reserved for Manager corrections + Phase 1)
        #    - if not exists: create stub BrainPage with compiled_truth=auto-generated one-liner,
        #      provenance(source_type="automated_extraction", confidence=0.6),
        #      manager_authoritative=False
        # 3. Embed any new/changed pages, persist to brain_w_{wid}
        # 4. Return list of (slug, action) pairs for observability
```

What Phase 0 §C11 brain_updater **does not do** (Phase 1 §D3 adds):
- Typed graph edges (`works_at`, `discussed`, `mentioned_in`)
- Backlink in-degree maintenance
- Stub→enriched escalation (the mention_count ≥3 promotion)
- Cross-call entity deduplication (it relies purely on slug fuzzy-match in Phase 0)
- The `researcher` mini-agent invocation for newly-escalated pages

`app/services/caller_memory_write.py`:
```python
async def write_call_to_caller_memory(
    *, workspace_id: UUID, field_employee_id: UUID,
    call: Call, transcript: list[TranscriptFragment], summary: SummarizerOutput,
) -> None:
    user_id = f"workspace:{workspace_id}:caller:{field_employee_id}"
    digest = render_caller_memory_digest(call, transcript, summary)
    await memory_provider.add(
        user_id=user_id,
        content=digest,
        metadata={
            "call_id": str(call.id),
            "tags": ["call_digest"],
            "started_at": call.started_at.isoformat(),
            "extracted_by": f"summarizer@{summary_skill_version}",
        },
    )
```

`render_caller_memory_digest()` builds a compact block — not the full transcript verbatim — so Supermemory's per-user search returns gist-level results, not raw call transcripts (those live in object storage per §D1's `CallArtifact`).

### `post_call` worker (Phase 0 implementation)

`app/workers/post_call.py`:
```python
async def post_call_job(ctx, call_id: UUID):
    call = await call_repo.get(call_id)
    if call.status != "ended":
        log.warn("post_call invoked for non-ended call; skipping", call_id=call_id)
        return

    transcript = await call_repo.assemble_transcript(call_id)

    # Run summarizer first (brain_updater can use its extracted entities as a hint)
    summary = await summarizer.run(SummarizerInput(call=call, transcript=transcript,
                                                   provider_summary=call.provider_summary))
    await call_repo.save_summary_artifact(call.id, summary)

    # Run the two writeback paths in parallel — independent failure domains
    brain_task = asyncio.create_task(
        brain_updater.run(BrainUpdaterInput(call=call, summary=summary, transcript=transcript)))
    memory_task = asyncio.create_task(
        write_call_to_caller_memory(workspace_id=call.workspace_id,
                                    field_employee_id=call.field_employee_id,
                                    call=call, transcript=transcript, summary=summary))
    brain_result, memory_result = await asyncio.gather(brain_task, memory_task,
                                                        return_exceptions=True)

    if isinstance(brain_result, Exception):
        log.error("brain_updater failed", call_id=call_id, exc_info=brain_result)
    if isinstance(memory_result, Exception):
        log.error("caller_memory_write failed", call_id=call_id, exc_info=memory_result)

    # Non-blocking notification
    await notify_summary_ready(call)
```

**Independent failure domains:** if Supermemory is down but the Brain is up, the Brain still gets updated (and vice versa). The job records partial success; both sides are retried independently via a `post_call_retry` worker that re-runs only the failed leg.

### Sequence

```
agent.call_ended webhook (adapter — §C3)
   ↓ persist Call.ended_at, Call.provider_summary
   ↓ enqueue arq job post_call(call_id) with _job_id=f"post_call:{call_id}"
post_call worker:
   ↓ load call + assemble transcript
   ↓ summarizer.run() → SummarizerOutput (basic)
   ↓ save_summary_artifact (CallArtifact in S3 — minimum from this section; full FE surface is §D1)
   ┌─────── PARALLEL ───────┐
   │ brain_updater.run()    │  → upsert pages, append timeline, embed
   │ caller_memory_write()  │  → Supermemory.add()
   └────────────────────────┘
   ↓ notify summary_ready (WS frame on the live multi-call channel)
```

### Endpoints (Phase 0 minimum surface)

| Method | Path | Purpose |
|---|---|---|
| GET | `/workspaces/{wid}/calls/{id}/summary` | Returns the SummarizerOutput. (Full call-detail UI is §D1 in Phase 1.) |

That's it for new endpoints. The Brain-side writes are observable via the existing `/workspaces/{wid}/brain/pages/{slug}` endpoint (§C8); the Supermemory-side writes are observable via per-call testing (§B11) and via the next call's retrieval picking them up.

### Why this is enough for compounding to work on day 1

- **Tomorrow's call retrieves yesterday's facts.** When Sarah calls about Acme on Tuesday, the Orchestrator's parallel retrieval (§C4) hits the `accounts/acme-corp` BrainPage; its `timeline` now has Monday's entry `"2026-05-15: Sarah discussed Acme — buyer mentioned board check-in. See call:{id}"`. The system already compounds, just without the bells.
- **Caller Memory works the same way.** Sarah's Caller Memory in Supermemory has yesterday's digest tagged `call_digest`. When the Orchestrator pulls her caller context at next call start, the digest is in the results.
- **Decisions made yesterday are queryable independently.** `DecisionRequest` rows from §C6 are first-class App-DB records; the Orchestrator can query `decision_requests where workspace_id=... and decided_at > yesterday` via a `fetch_recent_decisions` tool (added to §C4's tool list) when relevant.

### Edge cases

- Summarizer LLM rate-limited → arq retries with exponential backoff (§A5). The `Call` row is marked `summary_pending` so the FE knows.
- `brain_updater` extracts an entity that conflicts with a `manager_authoritative=true` field (e.g., infers different ownership) → does NOT overwrite. Creates a `needs_review` flag on the page; surfaces in §C8 corrections UI. This is the §9.6 rule honored end-to-end on day 1.
- Call ended with `Call.status=failed` (Orchestrator crashed mid-call) → still runs summarizer on the partial transcript with `summary.warnings=["partial_call"]`; brain_updater runs on the partial extraction.
- Supermemory write fails → logged; the call's brain side is fine; `post_call_retry` re-runs only the Supermemory leg. The Rep's profile is slightly stale for the next call; not catastrophic.
- Brain write fails after summary saved → same pattern; brain side retried.
- Duplicate `post_call` invocations (arq retry) → idempotent because: (a) `save_summary_artifact` overwrites with same key, (b) `brain_updater` checks for existing timeline entries with same `call_id` citation before appending, (c) `caller_memory_write` uses Supermemory's content-dedupe (no second memory row).

### Tests

- `tests/integration/workers/test_post_call_writeback_phase0.py` — end-to-end: send a fake `agent.call_ended` → assert summary saved → assert Brain page updated with timeline entry citing the call → assert Supermemory has a digest under the Rep's user_id.
- `tests/integration/workers/test_post_call_partial_failure.py` — Supermemory mock raises; assert Brain still updated, retry job enqueued for Supermemory leg.
- `tests/integration/workers/test_post_call_idempotent.py` — invoke twice with same call_id; assert no duplicate timeline entries, no duplicate Supermemory memories.
- `tests/integration/orchestrator/test_next_call_retrieves_prior_call.py` — the demo test: complete call A; complete call B with same Rep ~30s later; assert call B's retrieval includes call A's timeline entry + caller digest. **This is the test that proves the compounding loop works.**
- `tests/integration/workers/test_brain_updater_respects_manager_authoritative.py` — Manager corrects a page; subsequent call's brain_updater extracts conflicting info; assert page is NOT overwritten and a `needs_review` flag exists.

### Phase 0 §C11 exit signal

The single test that proves this section delivered: `test_next_call_retrieves_prior_call.py` passes. If that test passes, the Manager's demo on day 1 is "call A happens, hang up, call B happens, watch the agent reference what was said in call A" — which is the whole product.

---

# Phase 0 Exit Criteria

A Manager can sign up, upload data, see a brain seeded, receive a call, have the agent interview the Rep with streaming TTS, request a decision mid-call, answer it on FE or SMS, and review the timed-out ones in a list (full daily brief is Phase 1). **Crucially: a second call with the same Rep references what was said in the first** (§C11 closes the compounding loop).

In addition, *all of these* must be green for the phase to be considered done:
- `ci.yml` passes on main with all four test tiers + skills_eval + smoke_check.
- `python -m smoke run --all --mode smoke` against staging returns exit 0.
- `python -m scripts.verify_hot_path` against staging returns exit 0.
- The hierarchy guard test (§C10) is part of the gated integration suite.
- `tests/integration/orchestrator/test_next_call_retrieves_prior_call.py` passes (§C11 — proves the compounding loop is wired end-to-end).
- `lld/phase_1_durability.md` exists and is reviewed (planning continuity).
