# Phases 1 + 2 — Unified Low-Level Design (Durability + Productivity)

**Scope:** Take the system from "loop works on the wire" (Phase 0) to "everything captured, reviewable, intervenable" (Durability) *and* "acts on what was said, presents cross-call trends, lets the Manager intervene live" (Productivity).
**Source HLDs:** `voice_of_the_field_hld.md` v0.6 priorities #13–#20; `web_verifier_hld_mini_agent.md`; `email_delivery_hld.md`.
**Prerequisite:** Phase 0 (`lld/phase_0_scaffolding_and_mvp.md`) complete and live.

> **This is the speed-optimized variant.** All security is removed (no webhook signature verification, no encryption-at-rest, no KMS, no OAuth scope minimization, no privacy filters, no double-confirmation, no quarantine, no health-tracking, no daily caps). All LLM work uses **one model: `claude-sonnet-4-6`** — already in use as Phase 0's orchestrator default and the `llm_default_model` fallback in `app/settings.py`. Multi-skill subsystems collapse to single skills wherever possible. The takeover gateway (was P2 E3) is deferred — whisper is the only intervention mode. One connector vendor only: Google Workspace.

> **Critically, the post-call sections extend the §C11 workers and mini-agents — they don't replace them.** Each subsection's header explains what's new on top of §C11.

---

## Table of Contents

- [Speed Optimizations](#speed-optimizations) — what's been cut and why
- [F1. Transcripts + Call History in FE](#f1-transcripts--call-history-in-fe)
- [F2. Post-Call Pipeline — Fan-Out Worker](#f2-post-call-pipeline--fan-out-worker)
- [F3. Action Items — Extraction → Approval → Handler Execution](#f3-action-items--extraction--approval--handler-execution)
- [F4. Brain Self-Update](#f4-brain-self-update)
- [F5. Web Verifier](#f5-web-verifier)
- [F6. Email Surface — Outbound + Inbound + Handler Drafter](#f6-email-surface--outbound--inbound--handler-drafter)
- [F7. Manager Intervention — Whisper Only](#f7-manager-intervention--whisper-only) (takeover deferred)
- [F8. Dashboards — Daily Brief + Multi-Conversation Trends](#f8-dashboards--daily-brief--multi-conversation-trends)
- [F9. Google Workspace Connector + OAuth (Plaintext)](#f9-google-workspace-connector--oauth-plaintext)
- [Cross-Cutting Concerns](#cross-cutting-concerns)
- [Combined Exit Criteria](#combined-exit-criteria)

---

## Speed Optimizations

This variant strips anything not load-bearing for the happy-path demo. The drops:

| Category | Dropped | Kept |
|---|---|---|
| **Models** | per-skill model selection (haiku vs sonnet); model-pinning per `SKILL.md` | One model — `claude-sonnet-4-6` — for everything. Already in use, removes "is this skill cheap enough for haiku?" debate. |
| **Webhook security** | Svix HMAC verification on AgentMail webhook; dedup-by-svix-id ring | The webhook endpoint itself; idempotency by `provider_message_id` (functional dedupe) |
| **Encryption** | KMS envelope encryption of OAuth tokens; `smoke/kms.py` | Tokens stored as `TEXT` in DB. Add encryption when it's needed for compliance, not now. |
| **OAuth scope minimization** | per-handler scope minimums; "minimum permissions" review | Request broad scopes (`gmail.send`, `calendar.events`) at OAuth consent; one connect-button covers all handlers |
| **Composer privacy filter** | recipient-role privacy filter inside composer skills; adversarial fixtures; "security gate" CI step | All emails to a recipient include the same content. Manager can edit before send if they care. |
| **Double-confirmation** | approve → preview → confirm three-step UX | One-step: `POST /approve` *executes the handler immediately* if the action item carries a handler. Manager can `/reject` first if they want to edit. |
| **Sender classifier (email replies)** | `email_sender_classifier` skill; manager_aliases override | Direct string match: if `from_addr == workspace.manager_email` → manager; if matches any `field_employee.email` → rep; else log+drop. No skill, no model call. |
| **Quarantine + health tracking** | `email_quarantine` table; `email_health` JSONB; bounce/complaint auto-pause; daily cost cap | Send and forget. AgentMail returns errors; we log them. Cost cap can come later. |
| **Brain dream cycle** | nightly `brain_maintenance` worker (citation repair, dedup, merge proposals, backlink rebuild, stale flagging) | RRF + typed graph + escalation happen on every write. Nightly cleanup is deferred — the brain self-corrects via the next call's writes. |
| **Tier-A materialized views** | 5-min mview refresh worker; live KPI strip | Direct queries against the App DB for the overview endpoint. If it gets slow, add the mview later. |
| **Verifier multi-skill pipeline** | separate `web_verifier_planner` + `web_verifier_adjudicator` + `contradiction_reporter` skills; multi-page evidence gathering | One `web_verifier` skill: input = claim, output = `{verdict, confidence, evidence_url, contradiction_detail?}`. Single browser fetch per claim. |
| **Composer skills** | `post_call_email_composer` + `daily_brief_email_composer` + `email_drafter` as three separate skills | One `email_composer` skill that takes `{ kind, artifact, recipient }` params. |
| **LLM skills overall** | Many new skills: `action_item_extractor`, `email_composer`, `scheduler`, `email_drafter`, `web_verifier_planner`, `web_verifier_adjudicator`, `contradiction_reporter`, `email_sender_classifier`, `dashboard_rollup_writer` | **Only two NEW LLM skills: `web_verifier` and `dashboard_rollup_writer`.** Everything else is Jinja templates or regex. Phase 0 skills `summarizer` and `classifier` get version bumps but aren't "new." |
| **Connectors** | Google Workspace + Microsoft 365 + Slack | Google Workspace only. |
| **Takeover (was E3)** | TakeoverGateway service, WebRTC, STUN/TURN, sticky session routing, 25-takeover load test, second `TelephonyProvider` fallback | **Deferred.** Whisper is the only intervention mode. The `mode` column is `Literal["whisper"]` for now; widening is a 1-line change later. |
| **Smoke probes** | `smoke/kms.py`, `smoke/turn.py`, `smoke/microsoft_365.py`, `smoke/agentmail.py` security checks | Functional smoke: `smoke/google_workspace.py` (OAuth refresh + one send), `smoke/agentmail.py` (auth + one send) — no signature-verification or oversize-payload checks. |
| **CI security gates** | composer privacy-filter as security gate; adversarial near-miss fixtures for adjudicator; manager-classification precision gate | Standard skill eval only (golden set, accuracy ≥ bar). Manual review for new skills. |

**Net effect:** roughly 40% smaller surface area than the secured variant; one-model deployment; one OAuth provider; one composer skill; whisper-only intervention; no nightly maintenance jobs.

**Schema collapses still apply** (from the prior pass):
- One `ActionItem` migration covering all extraction + handler-outcome columns.
- One `ManagerIntervention` state machine (whisper-only for now, mode column ready for takeover).
- One nightly `dashboard_rollup` producing brief + snapshots in one transaction.
- One enum migration adds `system_web_verifier` + `manager_email_reply` together.
- All registries populated in one lifespan pass.

---

## F1. Transcripts + Call History in FE

Covers HLD priority #13.

### Goals

- Every transcript fragment from Phase 0's live bus is also durably persisted in the App DB and to object storage as a single transcript artifact at call end.
- The FE has a stable REST surface to list calls, fetch transcripts, and replay the live frames historically.

### Module deltas

`app/db/models/transcript.py` already has `TranscriptFragment` from Phase 0; add:

```python
class CallArtifact(Base):                # App DB
    id: UUID
    call_id: UUID
    workspace_id: UUID
    kind: Literal["transcript", "recording", "provider_summary",
                  "canonical_summary", "action_items_export",
                  "action_item_handler_outcome"]
    storage_key: str
    bytes: int
    content_type: str
    created_at: datetime
```

> No SHA, no integrity check on download (dropped — object storage is trusted).

Transcripts are stored two ways:
- **Fragment rows** in `transcript_fragments` (Phase 0) — random access for live view replay.
- **Single transcript artifact** in object storage — built at `call.ended` by the `post_call` worker as JSONL of fragments. Used for export, search via Supermemory, retention.

### Endpoints

In `app/api/workspaces/calls.py`:

| Method | Path | Purpose |
|---|---|---|
| GET | `/workspaces/{wid}/calls` | List, paginated, filterable by `field_employee_id`, `status`, `from`/`to` |
| GET | `/workspaces/{wid}/calls/{call_id}` | Detail: metadata + summary + action items + decision log |
| GET | `/workspaces/{wid}/calls/{call_id}/transcript` | Full transcript (JSON) or `?format=text` |
| GET | `/workspaces/{wid}/calls/{call_id}/recording` | 302 to signed URL (15-min TTL) |
| GET | `/workspaces/{wid}/calls/{call_id}/replay` | WebSocket; replays original transcript+decision frames at original cadence |

### Edge cases

- Very long calls (1h+): transcript artifact stored uncompressed; `?format=text` returns gzipped per `Accept-Encoding`.
- Partial transcripts on failed call: `CallArtifact.kind=transcript` produced from whatever persisted; `Call.status=failed`.
- Recording lands asynchronously via AP webhook; `GET /recording` returns 425 `recording_not_ready_yet` until present.

### Tests

- `tests/integration/api/test_call_list_pagination.py`
- `tests/integration/api/test_transcript_artifact_assembly.py`
- `tests/integration/api/test_recording_signed_url.py`
- `tests/integration/api/test_call_replay_ws.py`

---

## F2. Post-Call Pipeline — Fan-Out Worker

Covers HLD priority #14. Integration spine for F3, F4, F5, F6.

> **Builds on Phase 0 §C11.** The `post_call` worker, `summarizer`, `caller_memory_write`, `brain_updater` already exist. This extends the worker to fan out. Claim extraction is hoisted so F4 + F5 share the same claim stream.

### Pipeline

```
agent.call_ended (§C11; unchanged)
   ↓ post_call worker (§C11; extended)
   ↓ summarizer (raised quality bar, brain_context injected)
   ↓ save_summary_artifact (writes CallArtifact for F1)
   ↓ classifier.extract_claims (v0.4; output carries verifiable_against_web)
   ┌──────────────────── PARALLEL ────────────────────┐
   │ web_verifier_fanout (F5)   ← org-wide verifiable only            │
   │ action_item_extractor (F3)                                       │
   │ caller_memory_write   (§C11)                                     │
   └──────────────────────────────────────────────────┘
   ↓ join: verifier verdicts feed brain_updater so writes carry trust tags
   ↓ brain_updater (F4)
   ↓ save_action_items (F3)
   ↓ notify summary_ready + action_items_ready WS frames
   ┌── PARALLEL: email fan-out (F6; if email enabled) ──┐
   │ email_delivery(manager,  post_call_summary)         │
   │ email_delivery(rep,      post_call_summary)         │
   └─────────────────────────────────────────────────────┘
```

```python
# app/workers/post_call.py — extended from §C11
async def post_call_job(ctx, call_id: UUID):
    call = await call_repo.get(call_id)
    transcript = await call_repo.assemble_transcript(call_id)
    summary = await summarizer.run(SummarizerInput(
        call=call, transcript=transcript,
        provider_summary=call.provider_summary,
        brain_context=await fetch_brain_hints(call, transcript)))
    await call_repo.save_summary_artifact(call.id, summary)

    # One extraction, two consumers
    claims = await classifier.extract_claims(call=call, transcript=transcript, summary=summary)
    verifiable_org_claims = [c for c in claims if c.scope in ("org_wide", "both")
                                                 and c.verifiable_against_web]

    verifier_task = asyncio.create_task(
        web_verifier_fanout(workspace_id=call.workspace_id, call_id=call.id,
                            claims=verifiable_org_claims))
    memory_task   = asyncio.create_task(write_call_to_caller_memory(...))
    # Heuristic action-item extraction (no LLM skill in speed-variant — see F3)
    actions = extract_action_items_heuristic(summary=summary, transcript=transcript)

    verdicts, memory_result = await asyncio.gather(
        verifier_task, memory_task, return_exceptions=True)

    brain_result = await brain_updater.run(BrainUpdaterInput(
        call=call, summary=summary, transcript=transcript, claims=claims,
        verdicts=verdicts if not isinstance(verdicts, Exception) else None))

    await save_action_items(call, actions)
    await notify_artifacts_ready(call, has_actions=bool(actions))

    # F6 email fan-out (no consent check duplication — config flag is the only gate)
    ws = await workspace_repo.get(call.workspace_id)
    email_cfg = ws.config.get("email", {})
    if email_cfg.get("enabled"):
        if email_cfg.get("manager_post_call_summary"):
            await arq.enqueue("email_delivery", EmailDeliveryInput(
                workspace_id=call.workspace_id, trigger_kind="post_call_summary",
                trigger_ref_id=call.id, recipient_class="manager",
                recipient_addr=ws.manager_email))
        if email_cfg.get("rep_post_call_summary"):
            fe = await field_employee_repo.get(call.field_employee_id)
            await arq.enqueue("email_delivery", EmailDeliveryInput(
                workspace_id=call.workspace_id, trigger_kind="post_call_summary",
                trigger_ref_id=call.id, recipient_class="rep",
                recipient_addr=fe.email))
```

### Skill changes (existing Phase 0 skills, version-bumped)

- **`summarizer`** — extended from §C11. Output gains `verbatim_quotes: list[str]` and `topics: list[str]`. Input gains `brain_context`. Bar: `entity_recall ≥ 0.85`, `topic_coverage ≥ 0.8` on 30-call golden set.
- **`classifier` v0.4** — output gains `verifiable_against_web: bool` per claim. Existing bars; precision on the new field added to the golden eval.

### Heuristic action-item extraction (no LLM skill)

`app/services/action_items/heuristic_extractor.py`:

```python
import re
from app.skills.summarizer.schema import Output as SummaryOutput

ACTION_PATTERNS = [
    re.compile(r"\b(i'?ll|i will|we'?ll|we will)\s+(send|email|schedule|set up|book|follow up)\b", re.I),
    re.compile(r"\b(let'?s|let me)\s+(schedule|book|set up|send)\b", re.I),
    re.compile(r"\bfollow[- ]?up\b.*\b(by|before|on)\s+(monday|tuesday|wednesday|thursday|friday|next week)\b", re.I),
]

def extract_action_items_heuristic(summary: SummaryOutput,
                                    transcript) -> list[ActionItemCandidate]:
    items = []
    for blocker in summary.blockers:                  # blockers often imply follow-ups
        items.append(ActionItemCandidate(
            title=blocker[:120], description=blocker,
            suggested_handler="none", payload={}, confidence=0.6,
            source_utterance=blocker))
    for turn in transcript:
        for pat in ACTION_PATTERNS:
            if pat.search(turn.text):
                items.append(ActionItemCandidate(
                    title=turn.text[:120], description=turn.text,
                    suggested_handler=_handler_hint(turn.text),
                    payload={}, confidence=0.7, source_utterance=turn.text))
                break
    return _dedupe(items)
```

Lower-quality than an LLM extractor but ships in an afternoon. Manager can add missed items manually; precision matters more than recall.

### Tests

- `tests/integration/workers/test_post_call_full_fanout.py` — end-to-end with all branches
- `tests/integration/skills/test_summarizer_phase1_bar.py`
- `tests/integration/skills/test_classifier_v04_verifiable_field.py`
- `tests/unit/action_items/test_heuristic_extractor.py` — fixture-based regex coverage

---

## F3. Action Items — Extraction → Approval → Handler Execution

Covers HLD priorities #14 (extraction) and #18 (handler execution). **One state machine, one ActionItem migration, no preview step.**

### Speed-optimized state machine (no preview tier)

```
        ┌──────────────────┐
        │ pending_approval │  (heuristic extractor in F2)
        └─────┬────────────┘
              │ Manager can /reject or PATCH-edit
              │ Manager POSTs /approve
              ▼
        ┌──────────┐
        │ approved │  (dispatcher picks up immediately)
        └─────┬────┘
              │ scheduler.execute() or email_drafter.execute()
              ▼
        ┌──────────┐         ┌────────────────────┐
        │   done   │   or → │ failed │ needs_reconnect │
        └──────────┘         └────────────────────┘
```

> **Cut: no preview/confirm step.** Approve = execute. The handler draft + execute happen back-to-back in the dispatcher. If the Manager wants to tweak before sending, they `PATCH` then `/approve`. If they want the email to look different after the fact, they reply to the recipient directly. This drops three states, two endpoints, and the FE preview UI.

### Draft generation — Jinja templates, no LLM skills

> **Speed cut: no `action_item_extractor`, no `scheduler` skill, no `email_drafter` skill.** Extraction is the heuristic regex extractor in F2. Handler drafts come from Jinja templates parameterized by the `ActionItem.payload`. The Manager can `PATCH` the item before approval to fix anything the template missed.

`app/services/action_items/templates/` directory:

```
scheduler_event.j2          # title, body, default 30-min duration
email_drafter_message.j2    # subject, body with greeting + signature from workspace.config
```

Example `email_drafter_message.j2`:

```jinja
Subject: {{ payload.subject_hint or (workspace.name + " — follow up on our call") }}

Hi {{ payload.recipient_name or "there" }},

{{ payload.body_hint or item.description }}

{% if tone == "friendly" %}Looking forward to hearing back!{% else %}Best regards,{% endif %}
{{ workspace.name }}
```

Tone comes from `workspace.config.outbound_email_tone` ∈ {`professional`, `friendly`, `direct`}. The template lives in source — versioning is git, no skill eval rig needed.

### Data model — one migration

```python
class ActionItem(Base):
    # HLD §6 core fields …
    extracted_by: str                     # "action_item_extractor@0.1.0"
    confidence: float
    handler: Literal["scheduler", "email_drafter", "none"]
    handler_outcome: dict | None          # provider IDs, sent_at, draft body
    handler_outcome_artifact_id: UUID | None  # FK to CallArtifact(kind="action_item_handler_outcome")
    handler_executed_at: datetime | None
    handler_attempts: int = 0
    handler_error: str | None
```

> Cut: `provider_summary_ref` (not used downstream), `handler_preview` (no preview step), `handler_idempotency_key` (use action_item.id + handler_attempts).

### Handler dispatcher

`app/workers/action_item_dispatcher.py` — small `trigger="cron"` mini-agent (per-Workspace, every 60s) that picks up `status="approved"` rows where `handler != "none"`, renders the Jinja template for the handler, then immediately calls the provider. Single pass.

```python
# app/miniagents/scheduler.py
class SchedulerMiniAgent(MiniAgent):
    name = "scheduler"
    trigger = "queue"

    async def execute(self, ctx, action_item: ActionItem) -> SchedulerOutcome:
        ws = await ctx.workspaces.get(action_item.workspace_id)
        draft = render_template("scheduler_event.j2",
                                 item=action_item, payload=action_item.payload,
                                 workspace=ws)
        event = await ctx.connectors.google.calendar_create_event(draft)
        return SchedulerOutcome(provider_event_id=event.id,
                                 calendar_id=event.calendar_id,
                                 event_html_link=event.htmlLink,
                                 draft=draft)

# app/miniagents/email_drafter.py — same shape, render email_drafter_message.j2
# then call Gmail send via ctx.connectors.google.gmail_send(...).
```

Outcome (provider event ID, sent_at, full draft body) is written to `CallArtifact(kind="action_item_handler_outcome")` and the artifact ID stored on `ActionItem.handler_outcome_artifact_id` — single audit trail.

### Endpoints

| Method | Path | Purpose |
|---|---|---|
| GET | `/workspaces/{wid}/action_items?status=...` | List |
| POST | `/workspaces/{wid}/action_items/{id}/approve` | Approve; dispatcher executes handler |
| POST | `/workspaces/{wid}/action_items/{id}/reject` | Reject |
| PATCH | `/workspaces/{wid}/action_items/{id}` | Edit title/description/due_at/handler payload before approval |

### Edge cases

- `action_item_extractor` returns item with `due_at` in the past → flagged `needs_review` (not auto-rejected).
- Extractor fails but rest of post-call succeeds → call still durable; action items show "extraction failed" CTA.
- Google OAuth revoked at execute time → `status=needs_reconnect`; FE prompts re-OAuth via F9.
- Email send 4xx → `status=failed` with `handler_error`.
- Handler retried internally on transient failure (network blip): `handler_attempts` increments; max 3 internal retries before `failed`.

### Tests

- `tests/integration/workers/test_post_call_action_items.py`
- `tests/unit/action_items/test_template_rendering.py` — scheduler + email_drafter Jinja output snapshot
- `tests/integration/action_items/test_approve_transitions_and_executes.py`
- `tests/integration/action_items/test_handler_failure_marks_failed.py`
- `tests/e2e/test_action_item_full_loop.py` — extract → approve → done (mocked provider)

---

## F4. Brain Self-Update

Covers HLD priority #15.

> **Builds on Phase 0 §C11.** Phase 0 already ships `brain_updater` (regex entity extraction, page upsert, timeline append, stub creation, embedding on write, simple vector+text search). This phase adds typed graph + RRF + escalation.

### What's new vs §C11

| Concern | §C11 ships | This phase adds |
|---|---|---|
| Regex entity extractor | basic | extended (money, dates, URLs); roster cross-reference |
| Vector + text search | simple combine | RRF + backlink-boost |
| Typed graph edges (`BrainEdge`) | none | extracted on write: `mentioned_in`, `works_at`, `attended`, `discussed` |
| Graph traversal | none | `traverse(slug, depth, edge_types)` |
| Stub→enriched escalation | none | `mention_count ≥ 3` → enqueue `researcher` mini-agent |

> **Cut:** nightly `brain_maintenance` dream cycle (citation repair, dedup proposals, backlink rebuild, stale flagging). The system self-improves on each write; deferred maintenance is dead-code until you have enough scale for it to matter.

### Modules

- `app/brain/entity_extractor.py` — extended from §C11.
- `app/brain/graph.py` — new. Wraps `BrainEdge` reads/writes; provides `traverse(slug, depth=2, edge_types=[...])`.
- `app/brain/hybrid_search.py` — replaces §C11's combiner:

```python
async def hybrid_search(workspace_id, query, k):
    vec_task = vector_search(workspace_id, embed(query), k=k*2)
    text_task = ts_search(workspace_id, query, k=k*2)
    vec_hits, text_hits = await asyncio.gather(vec_task, text_task)

    rrf: dict[str, float] = {}
    for rank, hit in enumerate(vec_hits):
        rrf[hit.slug] = rrf.get(hit.slug, 0) + 1 / (60 + rank)
    for rank, hit in enumerate(text_hits):
        rrf[hit.slug] = rrf.get(hit.slug, 0) + 1 / (60 + rank)
    for slug in rrf:
        in_degree = await graph_repo.in_degree(workspace_id, slug)
        rrf[slug] *= (1 + 0.05 * min(in_degree, 20))
    return [SearchHit(slug=s, score=rrf[s]) for s in
            sorted(rrf, key=rrf.get, reverse=True)[:k]]
```

### `brain_updater` mini-agent (extended)

```python
class BrainUpdater(MiniAgent):
    name = "brain_updater"
    trigger = "queue"

    async def run(self, ctx, inputs: BrainUpdateInput) -> BrainUpdateResult:
        # 1. extract entities (extended)               (§C11)
        # 2. upsert pages + timeline + stub-on-first   (§C11)
        # 3. create typed BrainEdge rows               (NEW)
        # 4. for entities with mention_count >= 3:     (NEW)
        #    enqueue researcher mini-agent
        # 5. invalidate retrieval cache                (NEW)
        # 6. apply trust tag from verdicts kwarg       (NEW)
        #    web_corroborated / unverified_web / contradicts_web_source
```

### Edge cases

- Two simultaneous `brain_updater` runs for same Workspace → advisory lock on `("brain_update", workspace_id)`.
- Entity extractor false positives (e.g., "March" → person) → roster cross-reference; conservative regex.

### Tests

- `tests/integration/brain/test_brain_updater_creates_edges.py`
- `tests/integration/brain/test_rrf_ranking.py`

---

## F5. Web Verifier

Covers HLD `hld/web_verifier_hld_mini_agent.md`. **Collapsed: single skill, single web fetch per claim.**

### What's new

| Concern | Pre-state | This section ships |
|---|---|---|
| Claim extraction | inline in `brain_updater` | already hoisted in F2 to `classifier.extract_claims()` |
| Trust tags on brain pages | implicit | explicit: `web_corroborated` / `unverified_web` / `contradicts_web_source` reserved values on `BrainPage.tags` |
| Contradiction surface | none | `CorrectionIntake` with `origin=system_web_verifier` |
| Per-claim audit | none | `ClaimVerification` table |
| Caller-memory claims | direct | unchanged — never reach verifier (HLD §8) |

### Module deltas

```
app/miniagents/web_verifier.py            # NEW
app/services/web_verifier/
    browser_client.py                     # Browser Use Cloud wrapper
app/db/models/claim_verification.py       # NEW
skills/web_verifier/                      # NEW — ONE skill (was 3)
```

> Cut: separate `web_verifier_planner` + `web_verifier_adjudicator` + `contradiction_reporter` skills. One `web_verifier` skill does fetch-plan + adjudication in one call. The contradiction text is rendered by the skill directly into the `CorrectionIntake.payload` (no separate reporter).

### Data model

```python
class ClaimVerification(Base):
    __tablename__ = "claim_verifications"
    id: UUID = Column(default=uuid4, primary_key=True)
    workspace_id: UUID = Column(ForeignKey("manager_workspaces.id"), index=True)
    organization_id: UUID
    call_id: UUID = Column(ForeignKey("calls.id"), index=True)
    claim_subject: str
    claim_predicate: str
    claim_object: str
    claim_source_utterance: str
    status: Literal["corroborated", "unconfirmed", "contradicted"]
    confidence: float
    evidence_url: str | None
    evidence_snippet: str | None
    contradiction_detail: str | None
    correction_intake_id: UUID | None = Column(ForeignKey("correction_intakes.id"))
    created_at: datetime
```

> Cut: `web_sources: list[dict]` (replaced by single `evidence_url` + `evidence_snippet`); `domain_skill_used`; partial-index on contradicted. Add indexes when query patterns are clear.

**`CorrectionIntake.origin` enum** gains `system_web_verifier` + `manager_email_reply` in one Alembic step (see F6).

**`BrainPage.tags` constants** in `app/brain/tags.py`: `WEB_CORROBORATED`, `UNVERIFIED_WEB`, `CONTRADICTS_WEB_SOURCE`. `brain_updater` (F4) applies them.

### Mini-agent

```python
class WebVerifierAgent(MiniAgent):
    name = "web_verifier"
    trigger = "queue"

    async def run(self, ctx, inputs: ClaimVerifierInput) -> ClaimVerifierResult:
        # Skip if Manager already adjudicated the page
        page = await ctx.brain.try_get_page(inputs.claim.subject)
        if page and page.manager_authoritative:
            return self._unconfirmed(reason="manager_authoritative_lock")

        # ONE skill call — plans + fetches + adjudicates in one pass
        async with browser_session(timeout_ms=30_000) as s:
            verdict = await Skill.get("web_verifier").run(
                claim=inputs.claim, browser=s)

        ci_id = None
        if verdict.status == "contradicted":
            ci_id = await ctx.corrections.open(
                workspace_id=inputs.workspace_id, origin="system_web_verifier",
                source_ref_id=inputs.call_id,
                target_user_id=ctx.workspace.manager_user_id,
                claim=inputs.claim,
                payload={"contradiction": verdict.contradiction_detail,
                         "evidence_url": verdict.evidence_url,
                         "evidence_snippet": verdict.evidence_snippet,
                         "source_utterance": inputs.claim.source_utterance})

        await ctx.db.write(ClaimVerification(
            workspace_id=inputs.workspace_id,
            organization_id=ctx.workspace.organization_id,
            call_id=inputs.call_id,
            claim_subject=inputs.claim.subject,
            claim_predicate=inputs.claim.predicate,
            claim_object=inputs.claim.object,
            claim_source_utterance=inputs.claim.source_utterance,
            status=verdict.status, confidence=verdict.confidence,
            evidence_url=verdict.evidence_url,
            evidence_snippet=verdict.evidence_snippet,
            contradiction_detail=verdict.contradiction_detail,
            correction_intake_id=ci_id))
        return ClaimVerifierResult(verdict=verdict, correction_intake_id=ci_id)
```

```python
async def web_verifier_fanout(*, workspace_id, call_id, claims):
    cfg = (await workspace_repo.get(workspace_id)).config.get("verifier", {})
    if cfg.get("disabled", False):
        return [VerificationVerdict.unconfirmed("verifier_disabled") for _ in claims]
    max_claims = cfg.get("max_claims_per_call", 5)
    capped = sorted(claims, key=lambda c: -c.classifier_confidence)[:max_claims]
    floor = cfg.get("skip_below_classifier_confidence", 0.7)
    target = [c for c in capped if c.classifier_confidence >= floor]
    results = await asyncio.gather(
        *(web_verifier.run(ClaimVerifierInput(workspace_id=workspace_id,
                                                call_id=call_id, claim=c, scope=c.scope))
          for c in target),
        return_exceptions=True)
    return [r.verdict if not isinstance(r, Exception) else
            VerificationVerdict.unconfirmed("verifier_error", error_str=repr(r))
            for r in results]
```

### Configuration

```python
"verifier": {
    "disabled": False,
    "max_claims_per_call": 5,
    "skip_below_classifier_confidence": 0.7,
    "session_timeout_ms": 30_000,
}
```

### Browser client

`app/services/web_verifier/browser_client.py` wraps Browser Use Cloud. Mints per-call session name; `async with` tears down. Env var: `BROWSER_USE_API_KEY`.

### Endpoints

| Method | Path | Purpose |
|---|---|---|
| GET | `/workspaces/{wid}/calls/{call_id}/verifications` | List `ClaimVerification` rows for a call |
| GET | `/workspaces/{wid}/brain/pages/{slug}/verifications` | List rows whose `claim_subject` matches |

### Edge cases

- Browser harness down → fan-out returns `unconfirmed("verifier_error")`; brain page tagged `unverified_web`.
- Claim already corroborated by a prior call → `ClaimVerification` queried first; corroborated rows within 30 days reused.
- More than `max_claims_per_call` extracted → top-N by confidence; remainder tagged `unverified_web`.
- Caller-specific claim mis-tagged `verifiable_against_web` → fan-out filters on scope, never dispatches.

### Tests

- `tests/integration/workers/test_post_call_runs_verifier.py`
- `tests/integration/web_verifier/test_caller_specific_never_verified.py`
- `tests/integration/web_verifier/test_contradiction_opens_correction.py`
- `tests/integration/web_verifier/test_browser_down_degrades_gracefully.py`
- `tests/integration/web_verifier/test_e2e_corroborated_then_contradicted.py`

---

## F6. Email Surface — Outbound + Inbound + Handler Drafter

Covers HLD `hld/email_delivery_hld.md` + the email half of priority #18. **Radically simplified: no webhook verification, no privacy filter, no quarantine, no health tracking, no daily cap, no sender classifier skill, one composer skill.**

### What's new

| Concern | Pre-state | This section ships |
|---|---|---|
| Outbound email | none | per-Workspace AgentMail inbox; `email_delivery` mini-agent (queue) |
| Inbound replies | none | `email_reply_handler` (http) on AgentMail webhook |
| Sender routing | none | direct string-match against `workspace.manager_email` and `field_employee.email` |
| Personal-mailbox outbound (F3) | none | same `email_delivery` agent with `delivery_route="oauth_personal"` |

### Module deltas

```
app/email/
    __init__.py
    base.py                                       # EmailProvider Protocol
    agentmail.py                                  # AgentMailEmailProvider
    oauth_personal.py                             # OAuthPersonalEmailProvider (Gmail; F3+F9)
    schemas.py                                    # SentMessage, AgentMailEvent
app/api/webhooks/agentmail.py                     # NEW — POST /api/v1/integrations/agentmail/webhook
app/miniagents/email_delivery.py                  # NEW — trigger=queue
app/miniagents/email_reply_handler.py             # NEW — trigger=http
app/db/models/email_message.py                    # NEW
app/email/templates/                              # NEW — Jinja templates, no LLM skill
    post_call_summary.j2
    daily_brief.j2
    missed_decisions.j2
```

The Phase 0 `MiniAgent` base class gains `trigger: Literal["queue", "http", "cron"]` (all three implemented at once).

### Data model

**`ManagerWorkspace` column additions:**

```python
class ManagerWorkspace(Base):
    ...                                          # Phase 0 §C1 fields
    email_inbox_id: str | None                   # AgentMail inbox_id
    email_inbox_addr: str | None                 # actual email address
    email_domain: str | None
```

> Cut: `email_health` JSONB column (no health tracking).

**`EmailMessage` table:**

```python
class EmailMessage(Base):
    __tablename__ = "email_messages"
    id: UUID = Column(default=uuid4, primary_key=True)
    workspace_id: UUID = Column(ForeignKey("manager_workspaces.id"), index=True)
    organization_id: UUID
    provider: Literal["agentmail", "oauth_personal"]
    provider_message_id: str = Column(index=True)
    provider_thread_id: str = Column(index=True)
    trigger_kind: Literal["post_call_summary", "daily_brief",
                          "missed_decisions", "action_item_handler"]
    trigger_ref_id: UUID                          # call_id, brief_id, or action_item_id
    recipient_class: Literal["manager", "rep", "external_customer"]
    recipient_addr: str
    sent_at: datetime
    correlation_idempotency_key: str = Column(unique=True)
```

> Cut: `delivered_at` / `bounced_at` (not tracked); `recipient_user_id` (recipient_addr is enough); `org_admin` recipient class (not used in P1+P2 happy path).

**`IntakeBufferItem.source` enum** gains `rep_email_followup`.

> Cut: `EmailQuarantine` table entirely.

### Configuration

```python
# ManagerWorkspace.config["email"]
"email": {
    "enabled": False,
    "manager_post_call_summary": False,
    "manager_daily_brief": True,
    "manager_missed_decisions_alert": True,
    "rep_post_call_summary": False,
    "outbound_email_tone": "professional",        # professional|friendly|direct
}
```

> Cut: per-rep overrides (`rep_overrides` keyed by employee_id), `outbound_per_workspace_per_day_cap`, `manager_aliases`. If a single Rep needs different settings, set `rep_post_call_summary=true` for all and let them filter in their inbox. Daily cap can come later if a cost incident happens.

### EmailProvider abstraction

```python
class EmailProvider(Protocol):
    name: Literal["agentmail", "oauth_personal"]

    async def provision_workspace_inbox(self, *, workspace_id, slug, domain) -> WorkspaceInbox: ...
    async def send(self, *, inbox_id, oauth_user_id, to, subject,
                    text, html, reply_to, headers) -> SentMessage: ...
    async def get_full_message(self, *, inbox_id, oauth_user_id, message_id) -> ReceivedMessage: ...
    def parse_webhook(self, *, raw_body: bytes) -> AgentMailEvent | None: ...
```

> Cut: `verify_webhook` (no signature verification). The webhook just `parse_webhook` raw body.

### Workspace provisioning extension

Phase 0's `WorkspaceProvisioningService.signup()` runs an additional side effect:

```python
ws.email_inbox = await self.email_agentmail.provision_workspace_inbox(
    workspace_id=ws.id, slug=slugify(ws.name), domain=settings.email.domain or None)
async with self.uow.begin():
    await self.uow.workspace.update_email_inbox(ws.id,
        inbox_id=ws.email_inbox.inbox_id, inbox_addr=ws.email_inbox.address,
        domain=settings.email.domain)
```

If AgentMail is slow/failing → Workspace lands `provisioning_state="number_pending"` (re-using §C1 terminology); existing retry job extended.

### The `email_delivery` mini-agent (queue)

```python
class EmailDeliveryInput(BaseModel):
    workspace_id: UUID
    trigger_kind: Literal["post_call_summary", "daily_brief",
                          "missed_decisions", "action_item_handler"]
    trigger_ref_id: UUID
    recipient_class: Literal["manager", "rep", "external_customer"]
    recipient_addr: EmailStr
    delivery_route: Literal["agentmail", "oauth_personal"] = "agentmail"
    oauth_user_id: UUID | None = None             # only when delivery_route=oauth_personal
    idempotency_key: str | None = None
    precomposed: ComposedEmail | None = None       # F3 supplies this; else composed inline

class EmailDeliveryAgent(MiniAgent):
    name = "email_delivery"
    trigger = "queue"

    async def run(self, ctx, inputs: EmailDeliveryInput) -> EmailDeliveryResult:
        ws = await ctx.workspaces.get(inputs.workspace_id)
        provider = ctx.email_providers[inputs.delivery_route]

        if inputs.delivery_route == "agentmail" and not ws.email_inbox_id:
            return EmailDeliveryResult(skipped=True, reason="inbox_not_provisioned")
        if inputs.delivery_route == "oauth_personal":
            cred = await ctx.connectors.oauth_creds_for(ws.id, inputs.oauth_user_id)
            if not cred or cred.revoked:
                return EmailDeliveryResult(skipped=True, reason="oauth_disconnected")

        idem = inputs.idempotency_key or _build_idem_key(inputs)
        if await ctx.db.email_message_exists(idem):
            return EmailDeliveryResult(skipped=True, reason="already_sent_idempotent")

        # F3 pre-composes (it already ran email_drafter for the personal-mailbox flow).
        # F6 composes inline using the unified composer skill.
        composed = inputs.precomposed or await self._compose(ctx, ws, inputs)

        sent = await provider.send(
            inbox_id=ws.email_inbox_id if inputs.delivery_route == "agentmail" else None,
            oauth_user_id=inputs.oauth_user_id,
            to=inputs.recipient_addr,
            subject=composed.subject, text=composed.text, html=composed.html,
            reply_to=ws.email_inbox_addr if inputs.delivery_route == "agentmail" else None,
            headers={"Message-ID": _build_message_id(ws, inputs)})

        await ctx.db.write(EmailMessage(
            workspace_id=ws.id, organization_id=ws.organization_id,
            provider=inputs.delivery_route,
            provider_message_id=sent.message_id, provider_thread_id=sent.thread_id,
            trigger_kind=inputs.trigger_kind, trigger_ref_id=inputs.trigger_ref_id,
            recipient_class=inputs.recipient_class,
            recipient_addr=inputs.recipient_addr,
            sent_at=sent.timestamp, correlation_idempotency_key=idem))
        return EmailDeliveryResult(message_id=sent.message_id,
                                    thread_id=sent.thread_id, sent_at=sent.timestamp)

    async def _compose(self, ctx, ws, inputs) -> ComposedEmail:
        # Speed-variant: templates, no LLM composer skill.
        artifact = await ctx.artifacts.get(inputs.trigger_kind, inputs.trigger_ref_id)
        tpl = {"post_call_summary": "post_call_summary.j2",
               "daily_brief":        "daily_brief.j2",
               "missed_decisions":   "missed_decisions.j2"}[inputs.trigger_kind]
        return render_email_template(tpl, artifact=artifact, workspace=ws,
                                      recipient_class=inputs.recipient_class,
                                      tone=ws.config.get("email", {}).get(
                                          "outbound_email_tone", "professional"))
```

> Cut: opt-in re-check inside delivery agent (config flag at enqueue time is the only gate); recipient health pre-flight; daily cap pre-flight; idempotency_key build complexity beyond `(workspace_id, trigger_kind, trigger_ref_id, recipient_class, recipient_addr)` hash.

### Webhook + `email_reply_handler` (http)

```python
# app/api/webhooks/agentmail.py
@router.post("/agentmail/webhook")
async def agentmail_webhook(request: Request,
                             provider: EmailProvider = Depends(get_agentmail_provider),
                             registry: MiniAgentRegistry = Depends(get_miniagent_registry)):
    raw = await request.body()
    event = provider.parse_webhook(raw_body=raw)
    if not event:
        return Response(status_code=200)         # malformed → drop
    await registry.invoke_http("email_reply_handler", event)
    return Response(status_code=200)
```

> Cut: HMAC/Svix verification, Svix-ID dedupe ring in Redis. Webhook is publicly reachable; if it gets hit with garbage, we just don't act on it. AgentMail re-delivery is rare and the email_messages.correlation_idempotency_key handles dedupe at the outbound layer; for inbound, the worst case is creating a duplicate `CorrectionIntake` which a Manager can dismiss.

```python
class EmailReplyHandler(MiniAgent):
    name = "email_reply_handler"
    trigger = "http"

    async def run(self, ctx, event: AgentMailEvent) -> None:
        msg = event.message
        ws = await ctx.workspaces.get_by_inbox_id(msg.inbox_id)
        if not ws:
            ctx.log.warn("agentmail_webhook_unknown_inbox", inbox_id=msg.inbox_id)
            return
        if event.event_type != "message.received":
            return  # bounce/complaint/delivered — log only

        # Re-fetch if payload truncated
        if msg.text is None and msg.html is None:
            msg = await ctx.email_providers["agentmail"].get_full_message(
                inbox_id=ws.email_inbox_id, oauth_user_id=None, message_id=msg.message_id)

        # Correlate via in_reply_to / references
        parent = await ctx.db.find_email_message(
            provider_message_id__in=msg.in_reply_to or msg.references or [])
        if not parent:
            ctx.log.info("dropped_orphan_reply", from_=msg.from_[0])
            return

        # SIMPLE sender routing — direct email match, no skill
        from_addr = msg.from_[0].lower()
        if from_addr == ws.manager_email.lower():
            sender_role = "manager"
        else:
            fe = await field_employee_repo.get_by_email(ws.id, from_addr)
            sender_role = "rep" if fe else "unknown"

        reply_body = msg.text         # raw text; no Talon extraction

        if sender_role == "manager":
            await ctx.corrections.open(
                workspace_id=ws.id, origin="manager_email_reply",
                source_ref_id=parent.trigger_ref_id,
                target_user_id=ws.manager_user_id,
                payload={"reply_body": reply_body,
                         "from_addr": from_addr,
                         "subject": msg.subject,
                         "parent_email_message_id": str(parent.id)})
        elif sender_role == "rep":
            await ctx.intake_buffer.write(IntakeBufferItem(
                workspace_id=ws.id, organization_id=ws.organization_id,
                source="rep_email_followup", content_text=reply_body,
                submitted_by_user_id=fe.id, submitted_at=msg.timestamp,
                purpose="ongoing_update",
                metadata={"call_id": str(parent.trigger_ref_id),
                          "field_employee_id": str(fe.id), "via": "email_reply"}))
        else:
            ctx.log.info("dropped_unknown_sender", from_=from_addr)
```

> Cut: `sender_classifier` skill (replaced with two-line direct match); Talon quoted-history extraction (raw text is good enough — the LLM downstream can ignore quoted material); `EmailQuarantine` writes (orphans/unknown senders just log).

### Composition — Jinja templates (no skill)

Three templates under `app/email/templates/` rendered with the artifact + workspace + tone. **All recipients of a given send get the same content** — no role-based redaction. Templates are pure presentation; no LLM call. Edit-in-source workflow; no skill eval rig, no quality bar to maintain.

If the brief or summary needs richer natural-language framing later, swap the template for an LLM skill call at that one site — the rest of the pipeline doesn't change.

### Endpoints

| Method | Path | Purpose |
|---|---|---|
| (POST) | `/api/v1/integrations/agentmail/webhook` | Unauthenticated; parses + dispatches reply handler |
| GET | `/workspaces/{wid}/email/messages` | Audit list of sent emails |

> Cut: `/email/health` and `/email/health/{addr}/reset` (no health tracking).

Opt-in flags are written via existing `PATCH /workspaces/{wid}/config`.

### Smoke probe

`smoke/agentmail.py` — minimal:

```python
class AgentMailProbe(Probe):
    name = "agentmail"
    required_env = ["AGENTMAIL_API_KEY", "SMOKE_AGENTMAIL_TEST_INBOX_ID",
                    "SMOKE_AGENTMAIL_TEST_TO"]

    def checks_for_mode(self):
        if self.mode in ("check", "smoke", "repair"):
            self.check("auth_valid", self._auth_valid)
        if self.mode in ("smoke", "repair"):
            self.check("outbound_send", self._outbound_send)
```

> Cut: `webhook_registered`, `svix_verification_roundtrip`, `oversize_payload_fallback`, `subscribed_event_types_complete`, `thread_correlation_roundtrip`.

### Edge cases

- At-least-once delivery: `correlation_idempotency_key` unique constraint dedupes retries.
- Reply received before parent send committed: handler retries `find_email_message` once with 500ms backoff, then drops as orphan.
- Email arrives for deleted Workspace: `get_by_inbox_id` returns None → log, drop.
- Webhook payload >1MB: re-fetch via `get_full_message`.

### Tests

- `tests/integration/email/test_workspace_provisioning_creates_inbox.py`
- `tests/integration/email/test_delivery_idempotent.py`
- `tests/integration/email/test_reply_routes_manager_to_correction.py`
- `tests/integration/email/test_reply_routes_rep_to_intake.py`
- `tests/integration/email/test_oauth_personal_route_uses_user_token.py` — F3 path
- `tests/e2e/test_email_roundtrip_post_call.py` — full E2E

---

## F7. Manager Intervention — Whisper Only

Covers HLD priority #16. **Takeover (was P2 E3) deferred.**

> **Cut: TakeoverGateway, WebRTC, STUN/TURN, sticky session routing, second TelephonyProvider implementation, 25-takeover load test.** That's weeks of telecom work for a feature that whisper covers 80% of. Ship whisper; revisit takeover once you have customer pull for it.

### Endpoint

```
POST /api/v1/workspaces/{wid}/calls/{call_id}/whisper
Body: { "guidance": "..." }
```

Returns 202 with the new `ManagerIntervention.id`.

### Data model

```python
class ManagerIntervention(Base):
    id: UUID
    call_id: UUID
    workspace_id: UUID
    user_id: UUID
    mode: Literal["whisper"]                     # widening to "takeover" is a 1-line change later
    started_at: datetime
    ended_at: datetime | None
    payload: dict                                # whisper: {guidance, consumed_at_turn?}
```

> Cut: `state` column (only one mode now; whisper has no meaningful intermediate state); `granted_at` (instantaneous).

### Orchestrator integration

`CallSession` already has `manager_whispers: list[str]` from Phase 0. Wire it through:

1. `POST /whisper` writes `ManagerIntervention`, publishes a `SessionEvent("manager_whisper", {guidance})` on the call's session bus.
2. Orchestrator consumes before next LLM turn; appends to `session.manager_whispers`.
3. Next turn's `skills/orchestrator/turn_prompt.j2` renders an additional `## Manager Guidance` block per HLD §5.5.4.
4. After turn completes, consumed whispers moved to `session.consumed_whispers`; `ManagerIntervention.payload.consumed_at_turn` set.
5. WS frame `takeover.granted(mode=whisper)` pushed for FE confirmation.

### Endpoints additions

| Method | Path | Purpose |
|---|---|---|
| POST | `/workspaces/{wid}/calls/{call_id}/whisper` | Submit guidance |
| GET | `/workspaces/{wid}/calls/{call_id}/interventions` | List for audit |

### Post-call audit

Summary surfaces interventions: "Manager whispered at turn 7 about pushing on integration timeline; the agent's turn-8 reply incorporated the guidance." Pure display-side rendering — no new skill.

### Edge cases

- Whisper after `call.ended` → 409 `call_ended`.
- Rapid-fire whispers → all stored; all concatenated into next turn's prompt block.
- Whisper >2000 chars → 400 `whisper_too_long`.

### Tests

- `tests/integration/calls/test_whisper_persists_and_publishes.py`
- `tests/integration/orchestrator/test_whisper_alters_next_turn_prompt.py`
- `tests/integration/calls/test_whisper_audit_visible_post_call.py`

---

## F8. Dashboards — Daily Brief + Multi-Conversation Trends

Covers HLD priorities #17 (daily brief) and #19 (cross-conversation dashboards). **One nightly rollup produces brief + snapshots in one transaction.**

> **Cut: Tier-A materialized views** (`mview_refresh` worker, 5-min refresh, stale-indicator UX). For now, the overview endpoint queries the App DB directly. If it gets slow at scale, add the mview later — the endpoint contract doesn't change.

### One nightly writer

A single `dashboard_rollup` mini-agent (`trigger="cron"`) per Workspace, fired at the Workspace's `daily_brief_hour` (default 7am workspace TZ). Produces the daily brief artifact *and* writes `DashboardSnapshot` rows — sharing intermediates so we don't re-read raw call data twice.

```python
class DashboardRollup(MiniAgent):
    name = "dashboard_rollup"
    trigger = "cron"

    async def run(self, ctx, inputs: RollupInput) -> RollupResult:
        async with ctx.db.begin() as tx:
            agg = await self._compute_intermediates(tx, inputs.workspace_id, inputs.date)
            brief = await self._build_brief(agg)
            brief_artifact_id = await ctx.artifacts.save_brief(brief)
            await self._write_snapshots(tx, agg)

        ws = await ctx.workspaces.get(inputs.workspace_id)
        if ws.config.get("email", {}).get("manager_daily_brief"):
            await arq.enqueue("email_delivery", EmailDeliveryInput(
                workspace_id=inputs.workspace_id, trigger_kind="daily_brief",
                trigger_ref_id=brief_artifact_id, recipient_class="manager",
                recipient_addr=ws.manager_email))
        return RollupResult(brief_id=brief_artifact_id,
                             snapshots_written=len(agg.dimensions))
```

### Brief sections

1. **Yesterday at a glance** — call count, top topics, urgent flags.
2. **Decisions you missed** — every `DecisionRequest.status=timed_out` since last brief.
3. **Account movement** — accounts with significant brain updates yesterday.
4. **Reps in motion** — Reps who called in; stats per Rep.
5. **Stub-to-real escalations** — entities promoted to enriched pages.

### `surfaced_in_brief_at`

`DecisionRequest` gains `surfaced_in_brief_at: datetime | None`. Brief queries `status=timed_out AND surfaced_in_brief_at IS NULL`, surfaces them, sets timestamp. One brief per decision.

### Data model

```python
class DashboardSnapshot(Base):
    id: UUID
    workspace_id: UUID
    snapshot_date: date
    dimension: Literal["overview", "rep", "account", "theme", "decision"]
    key: str | None                # field_employee_id / slug
    metrics: dict
    computed_at: datetime

class SavedDashboardQuery(Base):
    id: UUID
    workspace_id: UUID
    user_id: UUID
    name: str
    dimension: str
    filters: dict
    pinned: bool                   # cap: 10 pinned
```

### Endpoints

| Method | Path | Purpose |
|---|---|---|
| GET | `/workspaces/{wid}/dashboards/daily_brief?date=YYYY-MM-DD` | Current or historical brief |
| POST | `/workspaces/{wid}/decisions/{id}/resolve_now` | The "Resolve now" CTA |
| GET | `/workspaces/{wid}/dashboards/overview` | Top-level KPIs (direct query — no mview) |
| GET | `/workspaces/{wid}/dashboards/reps?range=30d` | Per-Rep activity |
| GET | `/workspaces/{wid}/dashboards/accounts?range=30d` | Per-account movement |
| GET | `/workspaces/{wid}/dashboards/themes?range=30d` | Trending themes |
| GET | `/workspaces/{wid}/dashboards/decisions?range=30d` | Decision-loop stats |
| GET | `/workspaces/{wid}/dashboards/queries` | List saved queries |
| POST | `/workspaces/{wid}/dashboards/queries` | Save |
| GET | `/workspaces/{wid}/dashboards/queries/{id}` | Run |
| DELETE | `/workspaces/{wid}/dashboards/queries/{id}` | |

"Resolve now": `DecisionRequest.status` transitions `timed_out → answered_late`; if a gated action item exists, it auto-approves (which executes via F3's dispatcher since there's no preview step).

### Optional skill

`skills/dashboard_rollup_writer/` — produces natural-language framing for each section. Manual eval. (Optional; the FE can render structured data directly if you want to skip this.)

### Edge cases

- Snapshot row missing for a date in range → backfill on-demand from raw data (slow path); log.
- Manager pins >10 → cap at 10.
- Workspace has no calls yesterday → brief still generated, sections show "no activity."
- Workspace TZ invalid → fallback UTC, surface banner.
- Brief generation fails mid-run → state `partial`; next run retries.

### Tests

- `tests/integration/dashboards/test_brief_surfaces_missed_decisions_once.py`
- `tests/integration/dashboards/test_resolve_now_transitions_status.py`
- `tests/integration/dashboards/test_brief_skeleton_when_no_activity.py`
- `tests/integration/dashboards/test_snapshot_creation.py`
- `tests/integration/dashboards/test_saved_query_roundtrip.py`
- `tests/integration/dashboards/test_brief_and_snapshots_in_one_transaction.py`

---

## F9. Google Workspace Connector + OAuth (Plaintext)

Covers HLD priority #18's OAuth side. **Single connector vendor. Plaintext tokens. No KMS. No scope minimization.**

> **Cut:** Microsoft 365 connector, Slack connector, KMS envelope encryption, `smoke/kms.py`, `smoke/microsoft_365.py`, per-handler scope minimization, "this is the first phase taking actions on the Manager's behalf" guardrails section.

### One connector

`app/connectors/google_workspace.py` — OAuth dance + token refresh. **Broad scopes requested at consent time** (`gmail.send`, `gmail.readonly`, `calendar.events`) so the same OAuth covers both handlers without re-consent prompts.

### Data model

```python
class WorkspaceOAuthCredentials(Base):
    id: UUID
    workspace_id: UUID
    provider: Literal["google_workspace"]
    scopes: list[str]
    refresh_token: str                            # plaintext TEXT column
    access_token: str | None                      # plaintext
    access_token_expires_at: datetime | None
    connected_by_user_id: UUID
    connected_at: datetime
    revoked: bool = False
    revoked_at: datetime | None
```

> No `encrypted_refresh_token: bytes` + KMS envelope. Plaintext. If this becomes a compliance concern later, add encryption then.

### Endpoints

| Method | Path | Purpose |
|---|---|---|
| GET | `/workspaces/{wid}/integrations/google/auth_url` | Begin OAuth |
| GET | `/workspaces/{wid}/integrations/google/callback` | OAuth callback |
| GET | `/workspaces/{wid}/integrations` | List connected integrations |
| DELETE | `/workspaces/{wid}/integrations/{integration_id}` | Disconnect |

### How F3 + F6 use this

- F3's `scheduler` and `email_drafter` read credentials via `ctx.connectors.oauth_creds_for(ws.id, user_id)`.
- F6's `email_delivery` uses the same lookup when `delivery_route="oauth_personal"`.
- Token refresh centralized in `app/connectors/base.py:refresh_if_needed()`. Hard failure → `revoked=True`; downstream consumers surface `needs_reconnect` to FE.

### Smoke probe

`smoke/google_workspace.py` — OAuth refresh works; one calendar event create; one gmail send to sink address.

### Audit trail

Every executed action records `executed_at`, provider-side IDs, and the draft body. Lives on `CallArtifact(kind="action_item_handler_outcome")` referenced from `ActionItem.handler_outcome_artifact_id` (F3).

---

## Cross-Cutting Concerns

### One model everywhere

**`claude-sonnet-4-6`** for every skill listed in this document. Already in use as Phase 0's orchestrator default and the `llm_default_model` fallback. No per-skill model pinning, no haiku/sonnet decision per skill, no `skill_models_reachable` probe over multiple models (Phase 0's existing probe still walks `skills/*/SKILL.md` and now finds one model everywhere). This removes a class of CI failures and operational decisions.

### Combined registry table (one lifespan pass)

| Registry | Items added |
|---|---|
| `MiniAgentRegistry` | `brain_updater`, `dashboard_rollup` (cron), `action_item_dispatcher` (cron), `web_verifier`, `email_delivery`, `email_reply_handler` (http), `scheduler`, `email_drafter` |
| `SkillRegistry` | **Only two NEW skills: `web_verifier`, `dashboard_rollup_writer`.** Plus version bumps to existing Phase 0 skills: `summarizer` → v0.2 (extended output + raised bar) and `classifier` → v0.4 (`verifiable_against_web`). |
| `EmailProviderRegistry` (NEW) | `agentmail`, `oauth_personal` |
| `ConnectorRegistry` | `google_workspace` |

> Cut from the secured variant: `brain_maintenance`, `contradiction_reporter`, `web_verifier_planner`, `web_verifier_adjudicator`, `post_call_email_composer`, `daily_brief_email_composer`, `email_sender_classifier`, `microsoft_365`, `slack`.
>
> Cut from the prior speed-variant: `action_item_extractor` (replaced by heuristic regex extractor), `email_composer` (replaced by Jinja templates), `scheduler` *skill* (replaced by Jinja template; the mini-agent still exists), `email_drafter` *skill* (replaced by Jinja template; the mini-agent still exists). The mini-agents `scheduler` and `email_drafter` remain in `MiniAgentRegistry` because they execute provider calls — they just no longer wrap an LLM skill.

All registered in `app/lifespan.py` in one block.

### `MiniAgent` base-class extension

```python
class MiniAgent(ABC):
    name: str
    trigger: Literal["queue", "http", "cron"]
    @abstractmethod
    async def run(self, ctx, inputs: BaseModel) -> BaseModel: ...
```

Dispatch: `queue` → arq enqueue, `http` → invoked synchronously by FastAPI webhook handler, `cron` → arq cron scheduler.

### New env vars

| Var | Purpose |
|---|---|
| `AGENTMAIL_API_KEY` | AgentMail SDK auth |
| `EMAIL_DOMAIN` | Optional custom domain for `<slug>@<EMAIL_DOMAIN>` |
| `BROWSER_USE_API_KEY` | Browser harness for web verification |
| `GOOGLE_OAUTH_CLIENT_ID` / `GOOGLE_OAUTH_CLIENT_SECRET` | Google Workspace OAuth |
| `SMOKE_AGENTMAIL_TEST_INBOX_ID` / `SMOKE_AGENTMAIL_TEST_TO` | AgentMail smoke probe |
| `SMOKE_VERIFIER_FIXTURE_CLAIM` | Verifier smoke probe |

> Cut: `AGENTMAIL_WEBHOOK_SECRET`, `MS_OAUTH_CLIENT_ID` / `MS_OAUTH_CLIENT_SECRET`, `KMS_KEY_ARN`, `TURN_SERVER_URL` / `TURN_SERVER_USERNAME` / `TURN_SERVER_CREDENTIAL`.

### Migrations (consolidated)

App DB (in dependency order):

1. `call_artifacts` table with `kind` enum incl. `action_item_handler_outcome`.
2. `action_items` extended (single migration: `extracted_by`, `confidence`, `handler`, `handler_outcome`, `handler_outcome_artifact_id`, `handler_executed_at`, `handler_attempts`, `handler_error`).
3. `manager_interventions` table (whisper-only `mode` enum).
4. `decision_requests.surfaced_in_brief_at` column.
5. `claim_verifications` table.
6. **Enum migration A** — `correction_intakes.origin` adds `system_web_verifier` + `manager_email_reply` together.
7. **Enum migration B** — `intake_buffer_items.source` adds `rep_email_followup`.
8. `manager_workspaces` adds `email_inbox_id`, `email_inbox_addr`, `email_domain`.
9. `email_messages` table with `provider` column + unique index on `correlation_idempotency_key`.
10. `workspace_oauth_credentials` table (plaintext columns).
11. `dashboard_snapshots` table.
12. `saved_dashboard_queries` table.

Brain DB:
- `brain_edges` indexes for typed-graph traversal.

> Cut: `email_health` column, `email_quarantine` table, `merge_proposals` table, Tier-A materialized views.

### CI additions

- `skills_eval` step gates **only the two NEW skills**: `web_verifier`, `dashboard_rollup_writer`. Plus existing skills' version bumps: `summarizer` v0.2, `classifier` v0.4.
- Integration test stage `phase_12_e2e` runs: post-call full fan-out (with verifier branch), whisper E2E, daily-brief → snapshot → trend query, email round-trip, action-item full loop (extract → approve → done).
- Smoke probes registered with §B9 runner: `agentmail`, `web_verifier`, `google_workspace`. All in `--smoke` and `--check` modes.

> Cut: privacy-filter security gate, adversarial near-miss fixtures, manager-classification precision gate, `kms`/`turn`/`microsoft_365` smoke probes.

### Infrastructure additions

- AgentMail account + webhook URL registered (no signing secret).
- Browser Use Cloud account + API key.
- Google Cloud project with OAuth consent screen + client credentials.

> Cut: TakeoverGateway service, STUN/TURN, KMS, second telephony provider, Microsoft Azure app registration, Slack app.

### Observability additions

| Metric | Type | Source |
|---|---|---|
| `votf_post_call_duration_ms` | histogram | post_call worker |
| `votf_brain_pages_created_total` | counter | brain_updater |
| `votf_action_items_extracted_total` | counter (labels: status) | action_item_extractor |
| `votf_action_item_handler_duration_ms` | histogram (labels: handler, outcome) | scheduler / email_drafter |
| `votf_whisper_to_turn_latency_ms` | histogram | orchestrator |
| `votf_brief_generation_duration_ms` | histogram | dashboard_rollup |
| `votf_verifier_claims_total` | counter (labels: verdict) | web_verifier |
| `votf_verifier_browser_session_ms` | histogram | browser_client |
| `votf_emails_sent_total` | counter (labels: trigger_kind, recipient_class, provider) | email_delivery |
| `votf_email_inbound_total` | counter (labels: route) | email_reply_handler |
| `votf_oauth_refresh_total` | counter (labels: outcome) | F9 OAuth refresh path |

> Cut: `votf_verifier_claims_capped_total`, `votf_verifier_error_rate`, `votf_email_addr_unhealthy_total`, `votf_email_workspace_daily_count`, `votf_takeover_*`, `votf_dashboard_snapshot_lag_minutes` (the rollup either succeeds or fails — lag is moot for a daily job).

---

## Combined Exit Criteria

1. `post_call` worker reliably produces a canonical summary + action items for every call, runs the verifier branch for org-wide verifiable claims, fans out emails to opted-in recipients.
2. The brain compounds: pages created from new calls are searchable in subsequent calls; entity escalation runs on write.
3. A Manager can whisper into a live call; the next turn incorporates the guidance; an audit row exists.
4. A missed decision from yesterday appears in today's brief; "Resolve now" CTA works; the same nightly invocation writes `DashboardSnapshot` rows that power 30-day and 90-day trend queries in <500ms P95.
5. The `web_verifier` runs on every post-call fan-out for org-wide verifiable claims; each verified brain page carries one of `web_corroborated` / `unverified_web` / `contradicts_web_source`; contradictions land as `CorrectionIntake(origin=system_web_verifier)` in the Manager's review queue; a browser-harness outage degrades to `unverified_web` instead of blocking writes.
6. The email surface delivers daily brief by email to opted-in Managers, delivers per-call summaries only where opted in, turns Manager email replies into `CorrectionIntake(origin=manager_email_reply)` and Rep replies into `IntakeBuffer(source=rep_email_followup)` within seconds.
7. A Manager can approve an action item; the handler executes immediately; the outcome (provider event ID or sent email ID) is recorded in `CallArtifact(kind="action_item_handler_outcome")` and on the `ActionItem` row. Google Workspace OAuth flow works; revoked refresh tokens surface `needs_reconnect`.
8. All Phase 0 smoke probes still pass; the new probes (`agentmail`, `web_verifier`, `google_workspace`) pass in CI; all new skills pass their evals in CI (standard quality bars, no security gates).
9. Every LLM call across the system uses `claude-sonnet-4-6`.
