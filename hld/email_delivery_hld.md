# Email Delivery & Reply Handling — High-Level Design

**Version:** 0.1 (Draft — companion to Voice of the Field HLD v0.6)
**Status:** Design Review
**Owners:** Engineering
**Depends on:** VotF HLD §2 (Hierarchy), §7 (Key Flows), §8.2 (MiniAgent), §8.7 (Skills), §9 (Correction & Provenance), §11 (Third-Party Integration Contracts), §12 (Smoke Tests), §14.3 (Privacy Tiers — deferred work this HLD partially activates)

> **What this is.** Two MiniAgents on the §8.2 extension point that give VotF an email channel: one outbound (`email_delivery`) that delivers post-call summaries and daily briefs, and one inbound (`email_reply_handler`) that turns Manager and Rep replies into §9 corrections or new IntakeBuffer items. Backed by AgentMail. Per-Workspace inboxes, recipient-role-filtered content, full Svix webhook verification, idempotent creation, and the §11.1 SDK-not-MCP discipline. Defaults are conservative: Manager opt-in for digests, Rep opt-in per Rep — no surveillance-by-default.

---

## 1. Need for This HLD

The parent VotF HLD v0.6 has three load-bearing surfaces that touch this work and one explicit deferral:

1. **Phase Map item 14** specifies the post-call fan-out: `summarizer`, `action_item_extractor`, and (per the verifier HLD companion) `web_verifier` all run on call completion. The outputs land in the Workspace Brain and the Manager's dashboard but **have no delivery channel outside the FE**. A Manager not at their desk and a Rep not at their desk both miss the artifact entirely until they log in.
2. **Phase Map item 17** introduces a daily brief but routes it only through the FE dashboard. Most operators expect a daily brief in their inbox.
3. **Phase Map item 18 (Phase 2)** plans for "scheduling / emailing with approval" but does not pin the underlying email transport, does not specify a reply path, and does not pin the privacy posture for emailing Reps content from a Workspace where they don't yet have FE access.
4. **§14.3 explicitly defers privacy tiers** (`workspace_private` / `team` / `org`). But the moment you email a Rep a per-call summary, the de-facto first privacy tier ships with that summary — the composer must decide what a Rep is and isn't allowed to see. Email is the first feature that forces this decision to be made.

This HLD addresses all four. It pins the transport (AgentMail), specifies the two MiniAgents, fixes the security and idempotency story, and resolves the privacy-tier question for the email surface specifically (without prejudicing the broader §14.3 resolution).

The HLD exists because email is **not** a bolt-on. It crosses §2 (recipient identity), §8.2 (MiniAgent contract), §8.7 (composer is a skill), §9 (replies become corrections), §11 (third-party contract), §12 (smoke probe), and §14.3 (privacy tiers). Getting any of those wrong individually is recoverable; getting them wrong together is not. Pinning the design first is cheaper than retrofitting.

---

## 2. Overview

Every Manager Workspace gets one AgentMail inbox at signup. Phase 1's post-call worker, in addition to running the summarizer and action-item extractor, optionally enqueues an `email_delivery` job per configured recipient class. The delivery agent loads the composer skill, which renders content **filtered by recipient role**, and sends via AgentMail. Replies land on a single signed webhook endpoint; the reply handler routes them: Manager replies → `CorrectionIntake` with `origin=manager_email_reply`; Rep replies → IntakeBuffer with `source=rep_email_followup`; anything else → quarantine queue.

The agent has no opinion about *what* should be emailed when. That's per-Workspace config (`workspace.config.email.*`), with conservative defaults: Manager daily digest opt-in, Rep per-call opt-in per Rep, no auto-blast.

---

## 3. Goals and Non-Goals

### 3.1 Goals

1. Manager and (opt-in) Rep can receive post-call summaries and daily briefs by email without any FE access.
2. Replies to those emails become first-class signals in the system: Manager corrections, Rep follow-up intake, with provenance back to the originating call/brief.
3. Per-Workspace inbox, per-recipient content filter, signed inbound, all under the §11 contract pattern (SDK on the backend, not MCP).
4. Default posture is conservative: no email goes out without explicit per-Workspace + per-recipient-class opt-in.
5. The email surface is **versioned and eval-gated** through §8.7 — composer prompts are first-class artifacts, not strings buried in the delivery agent.

### 3.2 Non-Goals

- Outbound email *campaigns* (newsletters, marketing). VotF is not a marketing tool.
- An IMAP/SMTP bridge to a Manager's existing inbox (Gmail/O365). The Workspace inbox is the source of truth; Manager's personal inbox is a recipient.
- Approval-gated outbound actions. That's Phase 2 (Phase Map item 18) — separate MiniAgent, separate HLD.
- Real-time mid-call email. Hot-path latency (§15) forbids it; SMS via AgentPhone is the right channel for mid-call.
- A general-purpose "agent has its own inbox to send arbitrary mail" surface. The two MiniAgents here are scoped to known event types.

---

## 4. Glossary Additions

| Term | Definition |
|---|---|
| **Workspace Inbox** | The single AgentMail inbox provisioned at Workspace signup. Stored on `ManagerWorkspace.email_inbox_id`. Address shape: `notes@<workspace-slug>.<your-domain>` on a custom domain, or `<workspace-slug>@agentmail.to` on free tier. |
| **Recipient class** | One of `manager` / `rep` / `org_admin` (future). Drives the composer's content filter. |
| **Composer recipient filter** | The §8.7 skill rule that determines which brain content, caller-memory content, and action items appear in an outbound email given the recipient class. The de-facto first privacy tier. |
| **Reply route** | The mapping from inbound `message.received` event to internal handler: Manager-reply → CorrectionIntake; Rep-reply → IntakeBuffer; sender-unrecognized → quarantine. |
| **Talon-extracted reply** | The clean reply body without quoted history. AgentMail exposes this as `extracted_text` / `extracted_html` on received messages — load-bearing for clean intake. |

---

## 5. Where It Sits in the Pipeline

### 5.1 Outbound (post-call fan-out)

```
Call completes
  ├─→ summarizer                       (existing — Phase 1)
  ├─→ action_item_extractor            (existing — Phase 1)
  ├─→ entity_extractor + web_verifier  (existing + companion HLD)
  └─→ email_delivery  ◄──── NEW
         │   (one job per configured recipient class; gated on opt-in)
         ├─→ skills/post_call_email_composer  ← filtered by recipient_role
         └─→ AgentMail SDK: inboxes.messages.send(...)
                (thread_key encodes call_id for reply routing)
```

### 5.2 Outbound (daily brief)

```
Daily brief cron
  └─→ dashboard_rollup                 (existing — Phase 1)
        └─→ email_delivery             (one job per Workspace where Manager opted in)
              └─→ skills/daily_brief_email_composer
                    └─→ AgentMail SDK
```

### 5.3 Inbound (replies)

```
AgentMail   →  Svix-signed POST  →  /api/v1/integrations/agentmail/webhook
                                       │
                                       ├─ verify (svix.Webhook.verify)
                                       ├─ dedupe on event_id (Redis SETNX, 7d TTL)
                                       └─ enqueue email_reply_handler

email_reply_handler:
  resolve workspace from inbox_id
  resolve sender role from from_ + Workspace roster + Manager email
  load thread_metadata from in_reply_to / references / our stored Message row
  route:
    manager_reply   → CorrectionIntake (origin=manager_email_reply)
    rep_reply       → IntakeBuffer (source=rep_email_followup, target_caller_id)
    unrecognized    → quarantine queue (operator review)
    bounce/complaint→ Workspace.email_health update; pause future sends to that addr
```

---

## 6. The Two MiniAgents

### 6.1 `email_delivery` (trigger=`queue`)

```python
class EmailDeliveryInput(BaseModel):
    workspace_id: UUID
    trigger_kind: Literal["post_call_summary", "daily_brief", "missed_decisions"]
    trigger_ref_id: UUID                # call_id or brief_id
    recipient_class: Literal["manager", "rep", "org_admin"]
    recipient_addr: EmailStr
    recipient_user_id: UUID | None      # FieldEmployee.id when recipient_class="rep"

class EmailDeliveryResult(BaseModel):
    message_id: str                     # AgentMail message_id
    thread_id: str                      # AgentMail thread_id (for reply correlation)
    sent_at: datetime
    delivered: bool | None              # filled later by message.delivered webhook

class EmailDeliveryAgent(MiniAgent):
    name = "email_delivery"
    trigger = "queue"

    async def run(self, ctx: AgentContext, inputs: EmailDeliveryInput) -> EmailDeliveryResult:
        ws = await ctx.workspaces.get(inputs.workspace_id)
        if not ws.config.email.enabled_for(inputs.recipient_class, inputs.trigger_kind):
            return EmailDeliveryResult(skipped=True, reason="opt_in_not_set")

        # Pull existing artifact — DO NOT re-summarize. Email is a delivery channel,
        # not a second extraction pass.
        artifact = await ctx.artifacts.get(inputs.trigger_kind, inputs.trigger_ref_id)

        composer = Skill.load(
            "post_call_email_composer" if inputs.trigger_kind == "post_call_summary"
            else "daily_brief_email_composer",
            workspace_id=inputs.workspace_id,
        )
        composed = await composer.run(
            artifact=artifact,
            recipient_role=inputs.recipient_class,
            recipient_user_id=inputs.recipient_user_id,
        )

        sent = await ctx.email_provider.send(
            inbox_id=ws.email_inbox_id,
            to=inputs.recipient_addr,
            subject=composed.subject,
            text=composed.text,
            html=composed.html,
            reply_to=ws.email_inbox_addr,        # replies come back to us
            headers={
                # we encode routing into a custom message-id pattern so replies'
                # in_reply_to / references give us free correlation
                "Message-ID": f"<{inputs.trigger_kind}-{inputs.trigger_ref_id}-"
                              f"{inputs.recipient_class}@{ws.email_domain}>",
            },
        )

        # Persist for reply correlation
        await ctx.db.write(EmailMessage(
            workspace_id=inputs.workspace_id,
            agentmail_message_id=sent.message_id,
            agentmail_thread_id=sent.thread_id,
            trigger_kind=inputs.trigger_kind,
            trigger_ref_id=inputs.trigger_ref_id,
            recipient_class=inputs.recipient_class,
            recipient_addr=inputs.recipient_addr,
            sent_at=sent.timestamp,
        ))
        return EmailDeliveryResult(
            message_id=sent.message_id,
            thread_id=sent.thread_id,
            sent_at=sent.timestamp,
        )
```

### 6.2 `email_reply_handler` (trigger=`http`)

```python
class InboundEmailEvent(BaseModel):
    event_id: str
    event_type: Literal["message.received", "message.bounced", "message.complained",
                        "message.delivered", "message.rejected"]
    message: AgentMailMessage           # full payload per §11.7.3

class EmailReplyHandler(MiniAgent):
    name = "email_reply_handler"
    trigger = "http"

    async def run(self, ctx, inputs: InboundEmailEvent):
        msg = inputs.message
        workspace = await ctx.workspaces.get_by_inbox_id(msg.inbox_id)
        if not workspace:
            return  # not one of ours; quietly drop after logging

        # Bounce / complaint paths short-circuit
        if inputs.event_type in ("message.bounced", "message.complained", "message.rejected"):
            await ctx.workspaces.mark_email_unhealthy(
                workspace.id, addr=msg.to[0], reason=inputs.event_type,
            )
            return
        if inputs.event_type == "message.delivered":
            await ctx.db.update_email_message_delivered(msg.message_id)
            return

        # message.received → correlate via in_reply_to / references
        parent = await ctx.db.find_email_message(
            agentmail_message_id__in=msg.in_reply_to or msg.references or [],
        )
        if not parent:
            return await ctx.quarantine.enqueue(msg, reason="no_parent_thread")

        sender_role = await self._resolve_sender_role(workspace, msg.from_[0])
        # Use Talon-extracted body, not raw — drops quoted history cleanly
        reply_body = msg.extracted_text or msg.text

        if sender_role == "manager":
            await ctx.corrections.open(
                workspace_id=workspace.id,
                origin="manager_email_reply",
                source_ref=parent.trigger_ref_id,        # the call_id
                content=reply_body,
                target_user_id=workspace.manager_id,
            )
        elif sender_role == "rep":
            await ctx.intake_buffer.write(IntakeBufferItem(
                workspace_id=workspace.id,
                source="rep_email_followup",
                content=reply_body,
                metadata={
                    "call_id": parent.trigger_ref_id,
                    "field_employee_id": parent.recipient_user_id,
                    "via": "email_reply",
                },
            ))
        else:
            await ctx.quarantine.enqueue(msg, reason="unrecognized_sender")
```

---

## 7. Data Model Additions

Four additions, no schema reshapes.

### 7.1 `ManagerWorkspace` columns

```python
class ManagerWorkspace(Base):
    # ... existing fields ...
    email_inbox_id: str | None              # AgentMail inbox_id (e.g. "inbox_def456...")
    email_inbox_addr: str | None            # the actual email address
    email_domain: str | None                # if custom domain configured
    # config.email lives in the existing JSON config blob:
    #   { "enabled": bool,
    #     "manager": { "post_call_summary": bool, "daily_brief": bool, "missed_decisions": bool },
    #     "rep_default": { "post_call_summary": bool },     # default per Workspace
    #     "rep_overrides": { "<field_employee_id>": { "post_call_summary": bool } } }
```

### 7.2 `EmailMessage` table

```python
class EmailMessage(Base):
    id: UUID
    workspace_id: UUID
    agentmail_message_id: str               # for reply correlation via in_reply_to
    agentmail_thread_id: str
    trigger_kind: Literal["post_call_summary", "daily_brief", "missed_decisions"]
    trigger_ref_id: UUID                    # call_id or brief_id
    recipient_class: Literal["manager", "rep", "org_admin"]
    recipient_user_id: UUID | None
    recipient_addr: str
    sent_at: datetime
    delivered_at: datetime | None           # filled by message.delivered webhook
    bounced_at: datetime | None
```

### 7.3 `CorrectionIntake.origin` extension

Per the §9 contract and consistent with the verifier HLD's `system_web_verifier` addition:

```
origin: Literal["manager", "rep_callback", "manager_email_reply",
                "system_web_verifier"]
```

### 7.4 `IntakeBuffer.source` extension

Adds `"rep_email_followup"`. The classifier (§8.7) handles it the same as any other intake source — no special-case routing.

---

## 8. AgentMail API Mapping (§11.7)

A new §11.7 subsection on the parent doc, following the AgentPhone/Supermemory template.

### 8.1 Capabilities we use

| Capability | Used for | Phase |
|---|---|---|
| Create inbox per Workspace | Workspace provisioning at signup | 1 |
| `inboxes.messages.send` | Outbound delivery agent | 1 |
| Webhooks: `message.received` | Reply handler (Manager corrections + Rep intake) | 1 |
| Webhooks: `message.bounced`, `.complained`, `.rejected` | Workspace email-health updates; auto-pause to dead addresses | 1 |
| Webhooks: `message.delivered` | Telemetry only (mark `EmailMessage.delivered_at`) | 1 |
| Talon `extracted_text` / `extracted_html` | Clean reply-body parsing for intake | 1 |
| Threads (`thread_id`, `in_reply_to`, `references`) | Reply-to-parent correlation | 1 |
| Custom domain | `notes@<slug>.<your-domain>` instead of `@agentmail.to` | 1 (paid plan) |
| WebSocket inbound (alt to webhook) | Local dev convenience; not used in prod | — |
| MCP server | **Not used.** §11.1 rule applies. | — |

### 8.2 REST/SDK we consume

- **Base URL:** managed by SDK
- **Auth:** `AGENTMAIL_API_KEY` env var (key prefix `am_...`)
- **Python SDK:** `pip install agentmail` → `from agentmail import AgentMail; client = AgentMail()`

Key operations:

| Operation | SDK call | Used by |
|---|---|---|
| Create inbox | `client.inboxes.create(username=workspace_slug, domain=..., client_id=f"votf-ws-{workspace_id}")` | Workspace provisioning |
| Send message | `client.inboxes.messages.send(inbox_id, to, subject, text, html, reply_to, headers)` | `email_delivery` agent |
| List messages | `client.inboxes.messages.list(inbox_id, limit, page_token, labels)` | Diagnostics / replay |
| Get message (full) | `client.inboxes.messages.get(inbox_id, message_id)` | When webhook payload exceeds 1MB cap and `text`/`html` are omitted |
| Create webhook | `client.webhooks.create(url, event_types=[...], client_id="votf-prod-v1")` | One-time deploy setup |
| Get webhook (secret) | `client.webhooks.get(webhook_id).secret` | Bootstrap |

**Idempotency.** Pass `client_id="votf-ws-{workspace_id}"` to `inboxes.create()`. The HLD §11 idempotency story (already encoded for AgentPhone via `X-Webhook-ID` dedupe) extends here naturally.

### 8.3 Webhook contract (AgentMail calls us)

| Header | Purpose |
|---|---|
| `svix-id` | Unique delivery ID; we dedupe in Redis (`SETNX seen_agentmail_webhooks:{svix-id} 1 EX 604800`) |
| `svix-timestamp` | Unix seconds; tolerance 5 min (Svix default); we reject older |
| `svix-signature` | Space-delimited `v1,<base64>` signatures; verified via `svix.webhooks.Webhook(secret).verify(payload, headers)` |

**Adapter pseudocode:**

```python
async def handle_agentmail_webhook(request):
    raw = await request.body()
    try:
        msg = svix_webhook.verify(raw, request.headers)   # raises on bad sig
    except WebhookVerificationError:
        return Response(status=400)

    svix_id = request.headers["svix-id"]
    if not await redis.set(f"seen_agentmail_webhooks:{svix_id}", 1, nx=True, ex=604800):
        return Response(status=200)                       # already processed

    payload = AgentMailEvent.parse_obj(msg)
    if payload.event_type in BOUNCE_EVENTS:
        await arq.enqueue("email_reply_handler", payload, priority="high")
    elif payload.event_type == "message.received":
        # Note: payload.message.text / .html may be omitted if >1MB.
        # Reply handler fetches full message via SDK in that case.
        await arq.enqueue("email_reply_handler", payload)
    return Response(status=200)
```

**Payload size limit (1 MB).** Per AgentMail docs, when a received message exceeds 1 MB the webhook drops `text` and `html` from the payload. Our reply handler must detect this (`payload.message.text is None`) and re-fetch via `client.inboxes.messages.get(inbox_id, message_id)`. Belt-and-braces for long forwarded threads.

### 8.4 SDK ↔ MCP

AgentMail publishes an MCP server. **We do not call it from the backend** — same §11.1 rule that excluded the AgentPhone and Supermemory MCP servers. If a Manager wants to point Claude Desktop at their Workspace's AgentMail inbox directly someday, that's their MCP client to configure; it's out of scope for VotF backend.

### 8.5 Operator Setup Checklist (AgentMail)

1. Create an AgentMail account at https://console.agentmail.to.
2. (Optional, paid) Configure a custom domain (`notes.<yourdomain>`) so Workspace inboxes are addressed as `<slug>@notes.<yourdomain>` rather than `@agentmail.to`. Verify the domain; await `domain.verified` webhook.
3. Generate an API key from the Console dashboard. Store as `AGENTMAIL_API_KEY` in the secret manager.
4. Create one production webhook pointing at `https://<your-host>/api/v1/integrations/agentmail/webhook`. Subscribe to: `message.received`, `message.bounced`, `message.complained`, `message.rejected`, `message.delivered`. (Skip `message.received.spam` / `.blocked` / `.unauthenticated` unless explicitly enabling spam handling — they require additional permissions and silently bypass `message.received`.)
5. Copy the webhook secret (prefix `whsec_...`). Store as `AGENTMAIL_WEBHOOK_SECRET`.
6. Verify connectivity from a deploy shell:
   ```bash
   python -c "from agentmail import AgentMail; \
              print(AgentMail().inboxes.list(limit=1))"
   ```
   Expect an empty list or a sample inbox — not an auth error.
7. **Replay window.** Confirm webhook deliveries are reachable from public internet (return 200 within 30s). AgentMail (via Svix) retries with exponential backoff.

### 8.6 Mapping to our internal types

```python
class AgentMailEmailProvider(EmailProvider):
    def __init__(self, api_key: str):
        self.client = AgentMail(api_key=api_key)

    async def provision_workspace_inbox(self, workspace_id: UUID, slug: str,
                                        domain: str | None) -> WorkspaceInbox:
        inbox = await self.client.inboxes.create(
            username=slug, domain=domain,
            client_id=f"votf-ws-{workspace_id}",
            display_name=f"{slug} notes",
        )
        return WorkspaceInbox(inbox_id=inbox.inbox_id, address=inbox.address)

    async def send(self, inbox_id: str, to: str, subject: str,
                   text: str, html: str | None, reply_to: str,
                   headers: dict) -> SentMessage:
        res = await self.client.inboxes.messages.send(
            inbox_id, to=to, subject=subject, text=text, html=html,
            reply_to=reply_to,
        )
        return SentMessage(message_id=res.message_id, thread_id=res.thread_id,
                           timestamp=res.created_at)
```

The rest of the codebase imports `EmailProvider`, never `AgentMail` directly. Same §11.1 discipline that hides "AP Agent" behind `TelephonyProvider.AgentPhoneAdapter`: AgentMail's "agents have inboxes" framing never leaks past this adapter into the VotF agent vocabulary.

---

## 9. Skills (§8.7 Additions)

Three new skill directories, all under §8.7 governance:

- **`skills/post_call_email_composer/`** — Takes the existing `summarizer` artifact + `action_items` + `recipient_role`, returns `{subject, text, html}`. Quality bar: **recipient-role filter precision** (a Rep email never contains content the Rep shouldn't see; a Manager email never omits content the Manager needs). Fixtures must include adversarial cases: ORG_WIDE content tagged to an account the recipient Rep doesn't own; cross-Rep mentions in caller-style notes.
- **`skills/daily_brief_email_composer/`** — Takes `dashboard_rollup` artifact, renders for `recipient_role=manager` (only role currently configured). Includes the "Decisions you missed" section per Phase Map item 17. Quality bar: faithful summarization with no new claims invented at email-compose time.
- **`skills/email_sender_classifier/`** — One-shot LLM call that maps `(from_addr, workspace.roster, workspace.manager_email)` to `manager` / `rep` / `unknown`. Why a skill rather than a SQL lookup? Reps sometimes reply from personal addresses, forwards, or aliases. The skill can be primed with known aliases and decide based on signal. Quality bar: zero false-positive `manager` classifications (a misclassified Rep reply opening a fake "Manager correction" is a worst-case failure).

The §8.7 evals discipline applies: golden sets, `quality_bar` in each `SKILL.md`, CI gate blocks regressions below threshold.

---

## 10. Privacy Filter Per Recipient Role

This is where §14.3 stops being deferred for this surface.

| Content type | Manager email | Rep email (recipient's own call) | Rep email (cross-rep) |
|---|---|---|---|
| Call summary | ✓ | ✓ | — |
| Action items | All | Only assigned to this Rep | — |
| Brain pages mentioned | All | Only accounts this Rep owns + ORG_WIDE pages flagged shareable | — |
| Caller Memory snippets | All | This Rep's own only | — |
| Manager whispers / interventions (Phase 1.5) | ✓ | **Never** | — |
| Decision Loop history | ✓ | Only decisions involving this Rep's call | — |
| Verifier verdicts (per companion HLD) | All | Only on items shared with this Rep | — |

These rules live in the composer skill's `SKILL.md` and are enforced **inside the skill** (the composer receives the recipient role and decides what to include). They are not enforced by the delivery agent post-hoc — that would create two sources of truth.

**Once §14.3 ships its full privacy-tier model**, the composer's filter retires in favor of tier tags on each piece of content, and this table moves to the §14.3 spec. Until then, this is the de-facto first tier. Worth being explicit about so it doesn't quietly drift.

---

## 11. §12 Smoke Probe

Required by §12.10. New `smoke/agentmail.py`:

```python
class AgentMailProbe(Probe):
    name = "agentmail"
    required_env = [
        "AGENTMAIL_API_KEY", "AGENTMAIL_WEBHOOK_SECRET",
        "SMOKE_AGENTMAIL_TEST_INBOX_ID", "SMOKE_AGENTMAIL_TEST_TO",
    ]

    def checks_for_mode(self):
        if self.mode in ("check", "smoke", "repair"):
            self.check("auth_valid", self._auth_valid,
                       fix_hint="Verify AGENTMAIL_API_KEY in secret manager; rotate via console.agentmail.to.")
            self.check("webhook_registered", self._webhook_registered,
                       fix_hint="Run client.webhooks.create(...) for the production /webhooks endpoint.")
        if self.mode in ("smoke", "repair"):
            self.check("svix_verification_roundtrip", self._svix_roundtrip,
                       fix_hint="AGENTMAIL_WEBHOOK_SECRET may be stale; refetch from client.webhooks.get(id).secret.")
            self.check("outbound_send", self._outbound_send,
                       fix_hint="Test inbox may lack send capability; check console.")
            self.check("thread_correlation_roundtrip", self._thread_roundtrip,
                       fix_hint="Sent message_id should be retrievable via messages.get within 5s.")
            self.check("oversize_payload_fallback", self._oversize_fallback,
                       fix_hint="Confirm reply handler fetches full message when webhook payload omits text/html.")
            self.check("subscribed_event_types_complete", self._event_types,
                       fix_hint="Webhook must include message.received, .bounced, .complained, .rejected, .delivered.")
```

Cost note: each `--smoke` run sends one email to a fixture sink address. <$0.001 per run.

---

## 12. Bounds & Cost

Per-Workspace config knobs (under `workspace.config.email.*`):

| Knob | Default | Purpose |
|---|---|---|
| `enabled` | `false` | Workspace-level kill switch. Must be explicitly turned on. |
| `manager.post_call_summary` | `false` | Manager opt-in for per-call summaries. Off by default; daily brief is the recommended cadence. |
| `manager.daily_brief` | `true` *(once enabled=true)* | The expected default once the Manager enables email at all. |
| `manager.missed_decisions_alert` | `true` *(once enabled=true)* | Manager-paged for §7 decision-timeout flags. |
| `rep_default.post_call_summary` | `false` | Default for all Reps. Per-Rep override available. |
| `rep_overrides.<field_employee_id>.*` | unset | Per-Rep opt-in, set by Manager from the FE. |
| `outbound_per_workspace_per_day_cap` | `200` | Cost ceiling. Exceeding pages the operator and pauses sends. |

**Cost shape.** AgentMail pricing is per-inbox + per-message (see their pricing page). At Phase 1 scale (one inbox per Workspace, ~10 messages/day/Workspace), the dominant cost is per-Workspace fixed (the inbox), not per-message. Feeds into the per-Workspace cost telemetry §14.4 calls for. Worth pinning a cost dashboard panel from day one.

---

## 13. Phase Placement

Phase 1, alongside Phase Map items 14 (post-call) and 17 (daily brief). Five new Phase Map rows:

| # | Priority | Phase | Component Work |
|---|---|---|---|
| 14d | EmailProvider abstraction + AgentMail adapter | 1 | `EmailProvider` interface; `AgentMailEmailProvider` implementation; secret-manager wiring |
| 14e | Workspace email inbox provisioning | 1 | `ManagerWorkspace.email_inbox_id`; signup flow extension; idempotent inbox creation with `client_id` |
| 14f | `email_delivery` MiniAgent + composer skills | 1 | Two skill directories; opt-in config; per-recipient filter; integration with post-call worker |
| 14g | AgentMail webhook + `email_reply_handler` | 1 | Svix verification adapter; dedupe; reply correlation via `EmailMessage` lookup; routing to corrections / IntakeBuffer / quarantine |
| 14h | `email_sender_classifier` skill + bounce handling | 1 | Sender role resolution skill; bounce/complaint → email health state; pause-on-dead-address |

**Phase 0 ships without it.** The FE dashboard is the only delivery channel in Phase 0, which is consistent with the parent HLD's existing scope.

---

## 14. Open Questions

- **One inbox per Workspace, or one inbox per (Workspace × purpose)?** Single inbox is simpler and matches AgentMail's "agent has an inbox" framing. Multiple (e.g., `notes@`, `briefs@`, `replies@`) is more navigable for Managers who triage by inbox. Leaning single — replies are correlated by `in_reply_to`, not by inbox.
- **Should Rep replies go through the same classifier path as initial intake?** Currently yes (write to IntakeBuffer, classifier runs). But a Rep replying to their own call summary is a *correction-ish* signal, not a fresh observation. Could justify an `origin=rep_callback`-style path on CorrectionIntake instead of IntakeBuffer. Resolve before Phase 1.5.
- **Forwarded emails as intake source.** A Manager forwards a customer email to the Workspace inbox. Treat as raw source ingestion? Trigger a brain seed? Out of scope here; flag for §11.7 v2.
- **WebSocket inbound (alt to webhook) in prod?** AgentMail offers WS inbound as well. Tempting because it removes the public-URL requirement. But our infra already runs a public webhook surface for AgentPhone; one more probably easier than adding a long-lived WS connection per Workspace. Default to webhook; revisit if AP migrates.
- **`message.received.spam` handling.** Spam is excluded by default and requires extra permissions. Probably fine to leave off in Phase 1; Manager replies coming from known addresses won't be misclassified. Revisit if false-positive spam filtering swallows real replies.

---

## 15. Risks

- **Sender misclassification → fake "Manager correction."** A reply from a Rep with a Manager-shaped address (forward, alias) opening a fake `manager_email_reply` CorrectionIntake is the worst-case failure. Mitigation: `email_sender_classifier` quality bar weighted on Manager-precision; the corrections review UI surfaces the sending address verbatim; high-stakes corrections require Manager confirmation before cascading per §9.
- **Privacy-filter regression.** The composer skill's recipient filter is the de-facto first privacy tier. A regression that emails ORG_WIDE-but-not-shareable content to a Rep is a real leak. Mitigation: §8.7 eval gate with adversarial fixtures; CI blocks any composer change that drops recipient-filter precision.
- **Email-as-surveillance perception.** Reps experiencing "every call I made got auto-emailed to me and my manager" is a culture problem even if technically benign. Mitigation: conservative defaults (opt-in everywhere); custom domain so the address is `notes@<workspace>.<yourdomain>` not `<random>@agentmail.to`; Manager-controlled per-Rep override.
- **Webhook replay / dedupe drift.** Svix retries with exponential backoff; our `seen_agentmail_webhooks:{svix-id}` TTL is 7d. A replay >7d later would double-process. Mitigation: pair with `EmailMessage`-level idempotency on the reply handler (a CorrectionIntake with the same `(workspace_id, source_ref_id, sender_addr, sent_at)` is suppressed).
- **AgentMail as critical dependency.** If AgentMail is down, outbound stalls (queue backs up — acceptable) and inbound replies are buffered on their side (also acceptable per their retry policy). Mitigation: the §12 smoke probe's upstream-down exit code path covers it; deploys don't block on third-party outages.
- **Cost creep on bounce loops.** A dead-address bounce → retry → bounce loop wastes money. Mitigation: `email_reply_handler` immediately pauses sends to bounced addresses; bounce + complaint feed Workspace email health, surfaced in the operator dashboard.
- **Composer prompt drift across model upgrades.** Same risk as every §8.7 skill. The eval CI gate is the answer; the composer's golden set is the early-warning system.
