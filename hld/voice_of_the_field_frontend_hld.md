# Voice of the Field — Front-End High-Level Design

**Version:** 0.1 (Draft — companion to Backend HLD v0.6)
**Status:** Design Review
**Owners:** Engineering (Front-End)

> **Relationship to the Backend HLD.** This document is the FE-side twin of the Backend HLD. Section numbers and structure mirror it intentionally: §5 Core Components on the BE side has a corresponding §5 on the FE side, and so on. Where this document references a BE section (e.g., "§11.2.3 of the BE HLD"), it means the section in the backend document, not this one. The principle is that every FE design decision is **grounded in a specific backend contract** — an API endpoint, a WebSocket frame, a data model. Nothing is invented FE-side that isn't also nailed down on the BE side.

> **What's intentionally *not* in this document:** visual design (typography, color palettes, illustration), copy/microcopy specifics, marketing pages. Those belong in design files and copy docs. This is engineering structure: how the FE is organized, what consumes what, how state moves, what ships in which phase.

---

## 1. Overview

The Front-End is a **web application for the Manager** who owns one Workspace. It exposes the four jobs the Manager does:

1. **Set up** the Workspace (onboarding wizard, data source connections, roster).
2. **Watch** live calls happening in their team (multi-call live view, decision prompts, whisper interventions).
3. **Review** past calls and the compounding Workspace Brain (transcripts, summaries, action items, brain pages).
4. **Correct** anything in the brain that's wrong (the §9 Correction & Provenance UX from the BE HLD).

Phase 0 ships the minimum to make the BE-side MVP usable: signup → onboarding → live call view (single call) → decision pane → basic brain read. Phase 1 adds the multi-call hub, the canonical-summary review UI, the action-items inbox, the whisper-mode intervention, and the brain editor. Phase 2 adds dashboards, scheduling/email approvals, and the deferred Rep-side FE.

**Core stack:** Next.js 15 (App Router), React 19, TypeScript, TanStack Query (server state), Zustand (client state), shadcn/ui + Tailwind v4 (components + styling), TanStack Virtual (long transcript lists), native WebSocket with reconnection middleware, OpenAPI-generated typed API client. Tested with Vitest + Storybook + Playwright.

---

## 2. Glossary, Mapping to Backend Concepts

The Front-End uses the same vocabulary as the BE HLD §2; this glossary clarifies what each concept *looks like* from the FE perspective.

| BE concept | FE manifestation |
|---|---|
| Organization | Implicit. Auto-created at signup, invisible in Phase 0 UI. Reserved as a namespace in routes and types. |
| Manager Workspace | The active scope of every screen. Workspace ID is in the URL path (`/w/{workspace_id}/...`) and in the auth context. |
| Manager | The signed-in user in Phase 0. Always sees their own Workspace. |
| Field Rep (`FieldEmployee`) | A row in the Roster screen; a card in the Live Call Hub when on a call; an avatar with name in transcripts. |
| Customer / Account | A brain page (`accounts/{slug}`) — viewable in the Brain Explorer. Never an authenticated user. |
| Orchestrator | Invisible to the FE. Its outputs (transcripts, decision requests, whispers acknowledged) arrive via WS. |
| Mini Agent | Mostly invisible. Two FE-visible touchpoints: the canonical summary (`summarizer` output) and the daily brief (`dashboard_rollup` output). |
| Workspace Brain | Browsable as a graph of pages in the Brain Explorer. Editable via the Brain Editor. |
| Caller Memory | Surfaces inside the Field Rep profile view as "What we know about Sarah." Not directly editable in Phase 0. |
| Decision Loop | The Decision Pane (live during a call) + the Missed Decisions section of the Daily Brief. |
| Privacy posture (Phase 0) | All views are scoped to the signed-in Manager. No tier filters in the UI yet. |

---

## 3. Goals and Non-Goals

### 3.1 Goals

1. Every BE contract has exactly one FE consumer (no duplicated state, no two screens that fetch the same data differently).
2. Real-time correctness: the Live Call Hub reflects BE state within ~100ms of WS frame arrival.
3. Optimistic where it makes sense (corrections, action-item approvals); pessimistic where state must converge (decision responses, brain writes that cascade).
4. Mobile-tolerant for the Manager's two highest-frequency mobile flows: receiving and answering a decision prompt; reading the daily brief.
5. Modular: a new screen, a new widget, or a new action-handler is one file in the right place.
6. Type-safe end to end: backend Pydantic → OpenAPI → TypeScript types → React components. No hand-rolled API types.
7. Designed for Rep-side FE (Phase 2+) without painting into a corner: route namespace `/rep/...` is reserved, role-aware components handle `role=rep` even when rep accounts don't exist yet.

### 3.2 Non-Goals (initial release)

- Native mobile apps. Mobile experience is responsive web in Phase 0–1.
- Offline mode for live call viewing. Connectivity loss = "reconnecting" toast + cached transcript replay on reconnect.
- Real-time collaboration on the same screen by multiple Managers (no Org-level UX in Phase 0).
- A custom WYSIWYG for brain pages. Brain Editor is markdown with a structured-fields side panel.
- Internationalization. English-only in Phase 0.

---

## 4. System Architecture (FE)

```
                       ┌───────────────────────────────────────────────┐
                       │                  BROWSER                       │
                       │                                                │
                       │  ┌─────────────────────────────────────────┐  │
                       │  │              Next.js App                 │  │
                       │  │  ┌──────────┐  ┌──────────┐  ┌────────┐ │  │
                       │  │  │  Pages   │  │ Widgets  │  │ Hooks  │ │  │
                       │  │  │ (routes) │  │(reusable)│  │(state) │ │  │
                       │  │  └────┬─────┘  └────┬─────┘  └───┬────┘ │  │
                       │  │       └─────────────┴────────────┘      │  │
                       │  │                     │                    │  │
                       │  │              ┌──────▼───────┐            │  │
                       │  │              │ State Layer  │            │  │
                       │  │              │              │            │  │
                       │  │              │ TanStack Q   │  Zustand   │  │
                       │  │              │ (server)     │  (client)  │  │
                       │  │              │              │            │  │
                       │  │              │   WS Bridge  │            │  │
                       │  │              └──────┬───────┘            │  │
                       │  └─────────────────────┼────────────────────┘  │
                       │                        │                       │
                       │  ┌─────────────────────▼───────────────────┐  │
                       │  │       Typed API Client (generated)       │  │
                       │  │   from backend OpenAPI spec; one fn      │  │
                       │  │   per endpoint; JWT auth interceptor      │  │
                       │  └─────────────────────┬───────────────────┘  │
                       └────────────────────────┼──────────────────────┘
                                                │
                       ┌────────────────────────▼──────────────────────┐
                       │       HTTPS (REST) + WSS (WebSocket)           │
                       └────────────────────────┬──────────────────────┘
                                                │
                       ┌────────────────────────▼──────────────────────┐
                       │      BACKEND FastAPI Gateway (BE §5.6)         │
                       │                                                │
                       │  /api/v1/auth/...                              │
                       │  /api/v1/me/...                                │
                       │  /api/v1/workspaces/{workspace_id}/...         │
                       │  /api/v1/organizations/{org_id}/...  (Phase 1+)│
                       │  /api/v1/rep/...                     (Phase 2+)│
                       └────────────────────────────────────────────────┘

   Cross-cutting:
   - OpenAPI spec consumed at build time → TypeScript types + API client
   - WS reconnection middleware with exponential backoff + queue replay
   - Sentry (error tracking) + PostHog or LogRocket (product analytics, optional)
   - Storybook (component dev) + Playwright (E2E) + Vitest (unit)
```

---

## 5. Core Components

### 5.1 Authentication & Session

Mirrors BE §5.2. Phase 0 BE endpoints (LLD §A7): `POST /api/v1/auth/signup`, `POST /api/v1/auth/login` (OAuth2 password grant — **`application/x-www-form-urlencoded` with `username`+`password`**, not JSON), `POST /api/v1/auth/refresh`, `POST /api/v1/auth/logout`, `GET /api/v1/me`. Signup body is `{email, password, workspace_name}` and creates Org + Workspace + User + provisions an AgentPhone number + creates the brain schema in one flow.

The JWT carries short-keyed claims per BE LLD §A7: `{sub, org, ws, role, iat, exp, jti}` — `sub` is the user id, `org` the organization id, `ws` the workspace id (nullable for `org_admin`). Refresh tokens are rotated server-side; reuse of a rotated refresh token revokes the chain.

The FE:

- **Attaches the access token as `Authorization: Bearer <jwt>`** on every REST and WebSocket-handshake request. BE Phase 0 §A7 uses OAuth2 Bearer via `oauth2_scheme`; cookie-based auth is **not** implemented BE-side today (see §11 — cookie-vs-bearer is the auth-posture question to resolve before launch if we want the XSS-mitigation cookie storage).
- **Decodes the JWT client-side** (without trusting it for security — security is server-side) only to know the active scope so the UI can render scope-aware navigation. Decode the short keys: `sub → userId`, `org → organizationId`, `ws → workspaceId`, `role`.
- **Auto-redirects** unauthenticated users to `/auth/signin` and back to the requested URL after sign-in.
- **Role-aware components.** Every navigation entry and route guard checks `role`. Phase 0 only `role=manager` exists; `role=rep` route guards are written and tested via Playwright fixtures (the §C10 guard test of the Phase 0 LLD) but never reached by a real user.

**Auth screens in Phase 0:**

| Route | Purpose | BE endpoint |
|---|---|---|
| `/auth/signin` | Email + password (form-urlencoded body to BE). | `POST /api/v1/auth/login` |
| `/auth/signup` | Manager signup → creates Organization + Workspace + User row. Funnels into onboarding. May return with `provisioning_state="number_pending"` if AgentPhone is slow — wizard shows a "your number is on its way" banner until the workspace settles to `ready` (poll `GET /workspaces/{wid}/config`). | `POST /api/v1/auth/signup` |
| `/auth/refresh` (silent) | Background token refresh; rotates the refresh token. Failure surfaces a "session expired" modal. | `POST /api/v1/auth/refresh` |
| `/auth/reset` | Password reset flow. **Not yet implemented BE-side in Phase 0** — see §11. Screen is built and shows "coming soon" until the BE endpoint lands. | (Phase 1+) |

**Session middleware:** every Next.js route under `/w/{workspace_id}/...` validates the access token, decodes it, verifies the path's `workspace_id` matches the JWT's `ws` claim, and 403s on mismatch. This is the FE-side analog to BE's `require_workspace_access` dependency.

### 5.2 Routing & Scope

The route structure **mirrors the BE API path structure** so URL → API mapping is 1:1:

```
/                                       → redirect to /w/{workspace_id}/home or /auth/signin
/auth/signin
/auth/signup
/auth/reset

/w/{workspace_id}/                      → workspace home (= daily brief in Phase 1; redirect in Phase 0)
  home                                  → Daily Brief (Phase 1; BE: GET /workspaces/{wid}/dashboards/daily_brief)
  calls/                                → Call History list (BE Phase 1: GET /workspaces/{wid}/calls)
    active                              → Live Call Hub (multi-call view; data comes from the WS snapshot frame, not a separate REST call)
    {call_id}                           → Single Call View (live if active, review if ended; BE Phase 1: GET /workspaces/{wid}/calls/{call_id})
  decisions                             → Decisions inbox (BE: GET /workspaces/{wid}/decisions)
  action-items                          → Action Items inbox (BE Phase 1 path is /workspaces/{wid}/action_items — note underscore on the API path, hyphen in the UI route)
  brain/                                → Brain Explorer (root: graph or list)
    {slug...}                           → Brain Page View (BE: GET /workspaces/{wid}/brain/pages/{slug} with path-shaped slug)
  roster/                               → Field Rep roster (list)
    {field_employee_id}                 → Field Rep profile (Caller Brain view)
  data-sources/                         → Connected sources (Phase 0: manual_upload only via /workspaces/{wid}/intake/upload; real OAuth connectors are Phase 1+ per BE HLD §11.6)
  settings/                             → Workspace config (BE: GET/PATCH /workspaces/{wid}/config)
  onboarding/                           → 5-stage onboarding wizard. FE route only; API calls all go to /workspaces/{wid}/intake/* (BE LLD §C2) — there is no /onboarding/ API namespace.

/org/{org_id}/...                       → Phase 1+, FE namespace reserved (BE API namespace is /api/v1/organizations/{org_id}/... — note the rename; the FE shortens for URL brevity)
/rep/...                                → Phase 2+, namespace reserved (BE API: /api/v1/rep/...)
```

**Implementation:** Next.js App Router. Folder-based routes. Layout files enforce scope checks. Catch-all (`[...slug]`) handles brain page paths.

**Reserved namespaces.** Empty page files exist for `/org/` and `/rep/` returning 404 in Phase 0. This mirrors the BE's empty router modules and is the FE side of the §C10 hierarchy guard test (Phase 0 LLD): a Playwright test asserts that a token forged with `role=rep` reaches `/rep/...` (showing a placeholder page) but is rejected with 403 from `/w/{workspace_id}/...`. The corresponding BE-side assertion is that `/api/v1/organizations/...` and `/api/v1/rep/...` return 404 to roles that match those scopes in Phase 0 (the routers are registered but empty).

### 5.3 State Management

Three categories with different tools:

| Category | Tool | Why |
|---|---|---|
| **Server state** (data fetched from BE) | TanStack Query v5 | Caching, deduplication, background refetch, optimistic updates. One query key per endpoint, mirroring the BE API path. |
| **Client state** (UI-only: open modals, pane focus, draft text) | Zustand | Lightweight, no boilerplate, persistable per-component scope. |
| **Real-time state** (WS-driven: live transcripts, decision-opened frames) | TanStack Query cache + WS bridge | WS frames invalidate or directly patch the relevant TanStack queries. See §5.5. |

**Query key convention:** path-shaped, mirroring the BE URL.

```ts
// One query per endpoint, key shape = path segments
useQuery({
  queryKey: ['workspaces', workspaceId, 'calls', callId, 'transcripts'],
  queryFn: () => api.workspaces.calls.transcripts.list(workspaceId, callId),
});
```

This makes it trivial to invalidate everything below a path: `queryClient.invalidateQueries({ queryKey: ['workspaces', workspaceId, 'calls'] })` blows away all call-related caches when a major event happens.

**Optimistic update policy:**

| Operation | Policy | Reason |
|---|---|---|
| Mark action item approved | Optimistic | Mutation is fast, rollback is acceptable |
| Submit a correction (`CorrectionIntake`) | **Optimistic with explicit "cascading…" indicator** | Cascade can take seconds (§9.4 BE), but the UI shouldn't feel laggy |
| Respond to a decision request | Pessimistic | Wrong response is worse than slow feedback |
| Approve an outbound email draft | Pessimistic | Send-once semantics |
| Edit brain page free-text | Optimistic | Standard text editor expectation |

### 5.4 Real-Time Layer (WebSocket Bridge)

This is the most distinctive FE piece. It powers the Live Call Hub (§7.2.2) and the Decision Pane (§7.3).

**Single WS connection per Manager session.** Matches BE §5.5.2 + Phase 0 LLD §C5 (`/api/v1/workspaces/{workspace_id}/ws/live`). One connection multiplexes all of the Workspace's active calls plus decision events. The FE never opens additional WS connections.

**WS handshake auth.** Browsers can't set headers on the WebSocket handshake, so BE Phase 0 §C5 issues a **short-lived single-use token via `POST /workspaces/{wid}/ws/token`** (TTL 30s) that the FE appends as a query param: `wss://<host>/api/v1/workspaces/{wid}/ws/live?token=<short-lived-jwt>`. The token-mint endpoint requires a normal authenticated Bearer request, so it inherits the session's auth. The FE re-mints on every (re)connect.

**Initial state arrives as a `snapshot` frame, not a REST call.** On connect, the BE WS hub immediately sends a `snapshot` frame containing the current list of in-progress calls for the Workspace (Phase 0 §C5 explicit decision — this replaces an initial `GET /calls?status=in_progress`). The FE seeds its Active Calls list from this frame and then patches it as `call.started` / `call.ended` frames arrive.

**Heartbeat.** Server sends a ping every 20s; FE must pong within 10s or the connection is closed (Phase 0 §C5). The bridge handles the pong transparently.

**WS Bridge architecture:**

```
                  ┌─────────────────────────────────────────────┐
                  │             Browser tab                      │
                  │                                              │
                  │  ┌───────────────────────────────────────┐  │
                  │  │  WSBridge (singleton, per Workspace)  │  │
                  │  │                                       │  │
                  │  │  - native WebSocket                   │  │
                  │  │  - exponential backoff reconnection   │  │
                  │  │  - in-flight frame queue (replay on   │  │
                  │  │    reconnect via sequence numbers)    │  │
                  │  │  - frame dispatcher (type → handler)  │  │
                  │  └─────────────┬─────────────────────────┘  │
                  │                │                             │
                  │      ┌─────────┴─────────┐                  │
                  │      │ frame handlers    │                  │
                  │      │ (per frame type)  │                  │
                  │      └─────────┬─────────┘                  │
                  │                │ patches TanStack cache     │
                  │                ▼                             │
                  │  ┌───────────────────────────────────────┐  │
                  │  │  TanStack Query cache (server state)  │  │
                  │  └─────────────┬─────────────────────────┘  │
                  │                │ subscriptions               │
                  │                ▼                             │
                  │  ┌───────────────────────────────────────┐  │
                  │  │  React components (auto re-render)    │  │
                  │  └───────────────────────────────────────┘  │
                  └─────────────────────────────────────────────┘
```

**Frame handlers** (one per BE frame type from §5.5.2 + Phase 0 §C5 / Phase 1 §D2 / §D4):

```ts
const handlers: Record<FrameType, FrameHandler> = {
  // Phase 0 (BE LLD §C5)
  'snapshot':             frame => seedActiveCalls(queryClient, frame),
  'call.started':         frame => addActiveCall(queryClient, frame),
  'transcript.fragment':  frame => appendTranscriptFragment(queryClient, frame),
  'decision.opened':      frame => openDecisionPrompt(queryClient, frame),
  'decision.resolved':    frame => closeDecisionPrompt(queryClient, frame),
  'call.ended':           frame => endActiveCall(queryClient, frame),
  // Phase 1
  'summary_ready':        frame => onSummaryReady(queryClient, frame),         // BE §C11 → §D2
  'action_items_ready':   frame => onActionItemsReady(queryClient, frame),     // BE §D2
  'takeover.granted':     frame => markCallWhispered(queryClient, frame),      // BE §D4
  'takeover.released':    frame => unmarkCallWhispered(queryClient, frame),    // BE §D4
};
```

Each handler patches the relevant TanStack Query cache entry rather than triggering a refetch — keeps the live view smooth and avoids extra HTTP round trips.

**Reconnection.** WebSocket connections die: browser tab backgrounded, network blip, server redeploy. The BE explicitly **does not** replay live transcript frames on reconnect (Phase 0 §C5: "no replay of transcript fragments — the REST `GET /calls/{id}/transcript` is the durable source"). On disconnect:

1. UI shows a subtle "reconnecting…" banner (not a blocking modal — Manager may still be on a call).
2. Bridge attempts reconnect with exponential backoff (1s, 2s, 4s, 8s, 15s, 30s cap). Before reconnecting, the bridge re-mints a new short-lived WS token via `POST /workspaces/{wid}/ws/token` (the prior token is single-use and almost certainly expired anyway).
3. On reconnect, the BE sends a fresh `snapshot` frame. The bridge:
    - Reseeds the Active Calls list from the snapshot.
    - For each call the FE thinks is in progress, refetches its transcript via `GET /workspaces/{wid}/calls/{call_id}/transcript` (Phase 1 §D1) to backfill any fragments missed during the outage. Phase 0 fallback before that endpoint exists: leave the transcript pane with a "transcript caught up via reconnect — recent fragments may be missing until call ends" notice.
4. Visual hint: a small "(reconnected, caught up)" toast clears the banner.

**Cross-tab coordination.** If the Manager opens two browser tabs, both establish their own WS connection (each mints its own short-lived token). The BE allows this. Each tab maintains independent state, so a decision-opened frame appears in both tabs and either can answer. Whichever tab fires the response first wins (BE Phase 0 §C6 enforces this with `SELECT … FOR UPDATE` on the DecisionRequest row); the loser receives a 409 `decision_already_resolved` and its pane closes via the subsequent `decision.resolved` frame.

### 5.5 API Client (Typed, Generated)

The FE consumes one source of truth for API shapes: the **OpenAPI spec emitted by FastAPI**. At build time:

```
backend/openapi.json   (committed to repo, regenerated on BE schema change)
       │
       ▼  openapi-typescript generates types
frontend/src/api/types.ts
       │
       ▼  ts-rest or similar generates client
frontend/src/api/client.ts
       │
       ▼  imported throughout the app
```

This means a backend schema change that's incompatible with the FE produces a **TypeScript compile error**, not a runtime surprise. CI blocks merges where `openapi.json` updates and `frontend/src/api/types.ts` wasn't regenerated.

**Authentication.** The client attaches the access token as `Authorization: Bearer <jwt>` on every request (BE Phase 0 §A7 uses OAuth2 Bearer; the cookie posture noted in §5.1 is not yet supported BE-side — see §11). On 401 response: silent refresh attempt via `POST /api/v1/auth/refresh` → retry once → if still 401, redirect to `/auth/signin`. Refresh-token rotation means the FE must always use the most recently issued refresh token; the bridge stores it in memory plus a single localStorage key per tab session.

**Path-typed routes.** Workspace-scoped endpoints carry `workspace_id` in their function signature; calling `client.workspaces.calls.list(callId)` without the workspace ID is a compile error.

**Login is form-urlencoded, not JSON.** The OAuth2 password grant on `POST /api/v1/auth/login` expects `application/x-www-form-urlencoded` with `username` + `password`. The generated client honors this for the login function specifically; everywhere else is JSON.

### 5.6 Component System

**Foundation:** shadcn/ui (Radix primitives + Tailwind v4) gives accessible components without lock-in. Components live in our repo, not as a dependency, so customization is editing source.

**Design tokens** in Tailwind v4 (`@theme` block in `globals.css`): a single semantic token layer (`color-text-default`, `color-text-muted`, `space-call-pane`, etc.) so a future theme change is editing the token layer, not finding every hard-coded class.

**Layered component organization:**

```
src/components/
  primitives/                 # shadcn/ui-derived, lowest level
    Button.tsx
    Dialog.tsx
    Toast.tsx
    Avatar.tsx
    ...
  patterns/                   # generic, reused across screens
    DataTable.tsx
    ConfirmationDialog.tsx
    EmptyState.tsx
    ErrorState.tsx
    StreamingTextBlock.tsx    # for live-streaming transcript chunks
    OptimisticPatch.tsx       # wrapper for optimistic mutation UI
  features/                   # screen-specific, named for the BE concept
    call/
      LiveCallPane.tsx
      CallTranscript.tsx
      DecisionPrompt.tsx
      WhisperInput.tsx
      CallSummary.tsx
    brain/
      BrainGraphView.tsx
      BrainPageView.tsx
      BrainPageEditor.tsx
      CorrectionDialog.tsx
      ProvenanceTooltip.tsx
    onboarding/
      OnboardingWizard.tsx
      IntakeForm.tsx
      DocumentUpload.tsx
      VoiceIntakeCallTrigger.tsx
      VerificationView.tsx     # Stage 5
    decisions/
      DecisionsInbox.tsx
      MissedDecisionsBriefSection.tsx
    action_items/
      ActionItemsList.tsx
      ActionItemApproval.tsx
    rep/
      RepRosterList.tsx
      RepProfileView.tsx
```

**Naming rule:** feature components are named after the BE concept they consume. A FE developer looking at `BrainPageEditor.tsx` immediately knows the corresponding BE section is §9 of the Backend HLD.

### 5.7 Performance Considerations

The two perf-sensitive surfaces:

**Multi-call live view.** Up to ~20 active calls visible at once. Each call pane streams transcript fragments at ~1 per turn. Strategy:

- **Pane virtualization** via TanStack Virtual: only DOM-mount panes currently in viewport.
- **Transcript virtualization** within each pane: long transcripts (5-min call = ~80 turns) virtualized so scrolling stays smooth.
- **Frame-rate throttle on heavy panes:** if 10+ panes are receiving streaming chunks simultaneously, batch incoming frames into rAF (requestAnimationFrame) ticks so React doesn't render-storm.

**Brain Explorer.** The brain graph for a mature Workspace is 1k–10k nodes. Strategy:

- **Lazy graph rendering** with d3-force or sigma.js — only render the neighborhood of the current focus node (depth 2 default, configurable).
- **List view as primary, graph view as overlay.** Most Manager use is "find a page" not "explore the graph." Graph is for visual orientation, not the main interface.
- **Server-side search.** Brain search must hit a BE hybrid-search endpoint (BE HLD §5.3 + Phase 1 §D3 `hybrid_search`); FE never tries to filter 10k pages in memory. **Gap:** the Phase 0/1 LLDs implement `hybrid_search` as an internal function but do not expose a `GET /workspaces/{wid}/brain/search?q=…` endpoint. Until that endpoint lands the Brain Explorer falls back to client-side filtering of the paginated `/brain/pages` list (acceptable while page counts are small in early Workspaces, breaks at >~500 pages). Flagged in §11.

### 5.8 Accessibility

The Live Call Hub is essentially live closed-captioning of a phone conversation, which puts it in WCAG-meaningful territory.

- **All transcript fragments labeled** with speaker (Rep / agent) and timestamp; reading order matches conversation order; ARIA live region with `aria-live="polite"` so screen readers announce new fragments without interrupting.
- **Decision prompts use `role="alertdialog"`** with focus management — a new decision moves keyboard focus to the prompt; closing returns focus to whatever the user was doing.
- **Color contrast** meets WCAG AA at minimum on text + UI controls; emphasis (urgent decisions) uses pattern + color, not color alone.
- **Keyboard navigation** for every interactive surface: every call pane is reachable by Tab, decision options are radio-buttons-with-arrow-keys, whisper input has a dedicated shortcut (`Cmd+W` or `Ctrl+W` on the active call pane).
- **Mobile gestures** are progressive enhancement: every tap target has a keyboard equivalent for desktop and assistive tech.

---

## 6. Data Models (TypeScript)

Generated from the BE Pydantic models via OpenAPI. Showing the essentials and where they shape the FE.

```ts
// Generated from backend/openapi.json — DO NOT EDIT BY HAND

export type UUID = string;

export interface Organization { id: UUID; name: string; created_at: string; }

export interface ManagerWorkspace {
  id: UUID;
  organization_id: UUID;
  manager_user_id: UUID;
  name: string;
  primary_number: string;                        // empty string while provisioning_state != 'ready'
  created_at: string;
  config: WorkspaceConfig;                       // free-form dict BE-side; FE narrows via WorkspaceConfig
  // BE Phase 0 §C1 additions (not in HLD §6 model sketch)
  provisioning_state: 'pending' | 'number_pending' | 'ready' | 'failed';
  agentphone_agent_id: string | null;            // AP persona id
  agentphone_number_id: string | null;           // AP number id (for later deprovisioning)
}

export interface User {
  id: UUID;
  organization_id: UUID;
  workspace_id: UUID | null;
  field_employee_id: UUID | null;
  email: string;
  role: 'manager' | 'org_admin' | 'rep' | 'viewer';
}

export interface FieldEmployee {
  id: UUID;
  workspace_id: UUID;
  organization_id: UUID;
  user_id: UUID | null;
  name: string;
  phone: string;
  role: string | null;
  team: string | null;
  profiled: boolean;
  supermemory_user_id: string;
}

export interface Call {
  id: UUID;
  workspace_id: UUID;
  organization_id: UUID;
  field_employee_id: UUID | null;
  agentphone_call_id: string;
  started_at: string;
  ended_at: string | null;
  status: 'ringing' | 'in_progress' | 'ended' | 'failed';
  recording_uri: string | null;
  transcript_uri: string | null;
  provider_summary?: string;          // from agent.call_ended (BE §11.2.3)
}

export interface DecisionRequest {
  id: UUID;
  call_id: UUID;
  workspace_id: UUID;
  target_user_id: UUID;
  prompt: string;
  options: string[];
  decision_class: 'inline' | 'bridged' | 'async';
  timeout_at: string;
  status: 'open' | 'answered' | 'timed_out' | 'cancelled';
  response: string | null;
  responded_at: string | null;
  responded_by_user_id: UUID | null;
  responded_via: 'websocket' | 'sms' | null;
}

export interface BrainPage {
  slug: string;
  type: string;
  title: string;
  compiled_truth: string;
  timeline: TimelineEntry[];
  tags: string[];
  updated_at: string;
  provenance?: Provenance;            // present on every claim per BE §9.1
}

export type WSFrame =
  // Phase 0 (BE LLD §C5)
  | { type: 'snapshot'; calls: Call[] }                                           // sent on every (re)connect; seeds Active Calls
  | { type: 'call.started'; call_id: UUID; field_employee_id: UUID; started_at: string }
  | { type: 'transcript.fragment'; call_id: UUID; speaker: 'caller' | 'agent'; text: string; ts: string }
  | { type: 'decision.opened'; call_id: UUID; decision_id: UUID; prompt: string; options: string[]; decision_class: 'inline' | 'bridged' | 'async'; timeout_at: string }
  | { type: 'decision.resolved'; call_id: UUID; decision_id: UUID; response: string | null; responded_via: 'websocket' | 'sms' | 'timeout' }
  | { type: 'call.ended'; call_id: UUID; ended_at: string }
  // Phase 1
  | { type: 'summary_ready'; call_id: UUID }                                      // BE §C11 / §D2 — FE refetches GET /calls/{id}/summary
  | { type: 'action_items_ready'; call_id: UUID }                                 // BE §D2 — FE refetches GET /action_items?call_id=…
  | { type: 'takeover.granted'; call_id: UUID; taken_over_by_user_id: UUID; mode: 'whisper' | 'takeover' }
  | { type: 'takeover.released'; call_id: UUID };
```

**Two design notes worth flagging on these frames:**

1. **No `seq` field.** An earlier draft of this document proposed `seq` on every frame so the FE could request a replay window on reconnect. Phase 0 §C5 chose a different mechanism: the BE sends a fresh `snapshot` frame on every (re)connect, and the durable record for transcript fragments lives in `GET /workspaces/{wid}/calls/{call_id}/transcript` (Phase 1 §D1). The FE reconciles via snapshot + REST refetch (see §5.4), not via gap-fill replay. The `seq` field was removed.
2. **`decision.opened` payload is flat.** BE §C5 sends `{call_id, decision_id, prompt, options, decision_class, timeout_at}` rather than embedding the full `DecisionRequest` object. The FE constructs a local `DecisionRequest`-shape from these fields plus a derived `status='open'`; the canonical record is fetched via `GET /workspaces/{wid}/decisions/{decision_id}` if needed.

---

## 7. Key Screens & Flows

The FE has nine screen families. Each maps to one or more BE flows.

### 7.1 F1 — Onboarding Wizard (Phase 0)

**Backend flow:** BE §7.1 (Manager Onboarding & Initial Brain Seeding). All wizard-side API calls go to the **intake** namespace — there is no `/onboarding/*` BE API. Phase 0 intake endpoints (BE LLD §C2):

| FE wizard step uses | BE endpoint |
|---|---|
| Form-field submit | `POST /workspaces/{wid}/intake/text` |
| Document upload | `POST /workspaces/{wid}/intake/upload` (multipart, **single-shot, ≤25 MB**; chunked-resumable is an open contract gap — §11) |
| Voice intake call | inbound voice handled by AP webhook → flows through the same intake pipeline |
| Re-trigger processing | `POST /workspaces/{wid}/intake/process` (idempotent; usually fires automatically) |
| Inspect what we ingested | `GET /workspaces/{wid}/intake/items?purpose=…&kind=…` |
| Item detail / download | `GET /workspaces/{wid}/intake/items/{id}` and `/download` |
| Supersede a prior upload | `POST /workspaces/{wid}/intake/items/{id}/supersede` |
| Soft-delete | `DELETE /workspaces/{wid}/intake/items/{id}` |
| Stage 5 "What we learned" | `GET /workspaces/{wid}/intake/review` |
| Confirm/correct a classification | `POST /workspaces/{wid}/intake/review/{id}` |

The wizard implements all five stages from the BE side. Single-page application (within the broader app), no early exit — but state is persisted server-side after each stage (as `IntakeBufferItem` rows + classification + handler results) so a Manager can resume.

```
/w/{wid}/onboarding (auto-redirect target after signup)
  Stage 1: WelcomeScreen
           - "We've created your Workspace and provisioned a number"
           - Display the AgentPhone number prominently
           - "Next: tell us about your team"

  Stage 2: GuidedIntake (three sub-tabs, can do in any order, persists between)
    /onboarding/intake/forms        - Workspace + per-rep forms (BE §7.1.2)
    /onboarding/intake/documents    - DocumentUpload (chunked, resumable)
    /onboarding/intake/voice        - Voice intake call — shows the number,
                                       instructs to dial it, awaits call

  Stage 3-4: BackendProcessing (no FE work; FE polls intake items list)
    /onboarding/processing          - Progress bar driven by polling
                                       GET /workspaces/{wid}/intake/items
                                       and aggregating per-item status
                                       (queued → extracting → classified → ingested |
                                        needs_review | failed). No dedicated job-status
                                       endpoint exists in Phase 0; this polling
                                       approach is the BE-supported path.

  Stage 5: VerificationView         - "What we learned"
    /onboarding/verify              - Tabular surface of created entities,
                                       NeedsReview queue, per-rep brain summary,
                                       inline edit for any correction
                                       (corrections fan to BE per §9.2)

  Final: OnboardingComplete
    Redirect to /w/{wid}/home or /w/{wid}/calls/active
```

**Key UX decisions:**

- **The voice intake call is optional but recommended.** The screen shows it as the "high-signal path" with a tip: "20 minutes of you talking to the agent produces better results than 2 hours of forms."
- **Stage 2 is non-blocking.** A Manager can leave and come back; the IntakeBuffer persists server-side.
- **Stage 5 is the most-clickable screen.** Every entity card has an "Edit" affordance. Every correction is `POST /workspaces/{wid}/intake/review/{id}` (or `POST /workspaces/{wid}/brain/corrections` for corrections that target an existing Brain page directly per BE Phase 0 §C8).
- **Document upload is single-shot multipart in Phase 0.** `POST /workspaces/{wid}/intake/upload` with the file in a `multipart/form-data` body. BE caps at 25 MB and returns 413 above that with a `fix_hint` to split. SHA-256-based dedupe on (workspace_id, sha256) means accidental double-clicks return the original `intake_item_id`. **Chunked + resumable uploads** for large CRM exports are an open BE contract gap (§11); until that ships, the FE pre-checks file size and tells the Manager to split inputs >25 MB.

### 7.2 F2 — Live Call Hub (Phase 0 single call; Phase 1 multi-call)

**Backend flows:** BE §5.5.2 (Multi-Call Live View), §7.2 (Inbound Call hot path).

**Phase 0:** single call view. When a call comes in, the FE shows one pane with the live transcript and decision prompts.

**Phase 1:** the **Live Call Hub** — the multi-call view. The most distinctive FE surface in the product.

#### 7.2.1 Phase 0 — Single Call View

```
/w/{wid}/calls/{call_id}                    (when call.status = 'in_progress')

  ┌────────────────────────────────────────────────────┐
  │  [Sarah] 📞 in progress · started 2 min ago        │
  │  ─────────────────────────────────────────────────│
  │  TRANSCRIPT (live)                                  │
  │                                                     │
  │  agent (00:02) "Hey Sarah, how'd the Acme meeting…"│
  │  Sarah (00:08) "Went well, they're excited about…" │
  │  agent (00:14) "What did they say about pricing?"  │
  │  Sarah (00:21) "They want a 20% discount…"         │
  │  [streaming]                                        │
  │                                                     │
  │  ─────────────────────────────────────────────────│
  │  DECISION PROMPT (if active)                        │
  │  → Slides in when 'decision.opened' frame arrives  │
  └────────────────────────────────────────────────────┘
```

**Behavior:**

- On page load the FE establishes the single Workspace WS (§5.4) and reads the `snapshot` frame to find the call (no separate REST list call needed in Phase 0). If the page is deep-linked to a specific `call_id` and the snapshot doesn't include it (call ended before snapshot), the FE falls back to `GET /workspaces/{wid}/calls/{call_id}` (Phase 1 §D1) for review-mode rendering.
- Transcripts append as `transcript.fragment` WS frames arrive. ARIA live region; ~100ms perceived latency from BE delivery.
- The pane auto-scrolls to the latest fragment unless the user has scrolled up (sticky-bottom pattern).
- Decision prompts slide in from below; do not steal scroll position; do steal keyboard focus per A11y.

#### 7.2.2 Phase 1 — Multi-Call Live Hub

```
/w/{wid}/calls/active

  ┌─────────────────────────────────────────────────────────────────┐
  │  ACTIVE CALLS (3)                                       [▾ Sort] │
  │ ─────────────────────────────────────────────────────────────── │
  │                                                                  │
  │  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐          │
  │  │ Sarah · 2:14 │  │ Bob · 0:47   │  │ Maya · 4:32  │          │
  │  │ Acme         │  │ Initech      │  │ Globex (new!)│          │
  │  │              │  │              │  │              │          │
  │  │ [transcript] │  │ [transcript] │  │ [transcript] │          │
  │  │ scrolling    │  │ scrolling    │  │ scrolling    │          │
  │  │              │  │              │  │              │          │
  │  │ 🔔 DECISION  │  │              │  │              │          │
  │  └──────────────┘  └──────────────┘  └──────────────┘          │
  │                                                                  │
  │  ─────────────────────────────────────────────────────────────── │
  │  RECENTLY ENDED (last 30 min)                                    │
  │  - Sarah · Acme · 4:21 · "Discount approved" → 1 action item     │
  └─────────────────────────────────────────────────────────────────┘
```

**Behavior:**

- One WS connection drives all panes (§5.4 / BE §5.5.2).
- New calls fade in via `call.started`; ended calls move to "Recently ended" via `call.ended`.
- Decision prompts within a pane bring focus to that pane (Cmd-click to navigate without losing context).
- Whisper shortcut (`Cmd+W` on focused pane) opens the whisper input inline.
- Mobile: panes stack vertically; horizontal-swipe between them.
- Performance: TanStack Virtual mounts only visible panes (§5.7).

**The "watch a specific call" deep-link** is `/w/{wid}/calls/{call_id}` and works whether the call is live or ended (the same component switches between live and review modes based on `call.status`).

### 7.3 F3 — Decision Pane (Phase 0)

**Backend flow:** BE §5.5.3 (Decision Loop), §7.3 (Manager Decision Request).

The decision pane appears inside the Live Call View. Three states matching the three classes from BE:

| Class | Visual treatment | Time-to-respond UX |
|---|---|---|
| `inline` (45s) | Prominent, large buttons, countdown ring at 30s/15s/5s | Pulsing border at 5s; high urgency |
| `bridged` (2 min) | Standard, sub-header in pane | Countdown text, low pulse |
| `async` | Adds to Decisions inbox; no live pane component | Daily-brief surface; no urgency |

**Decision pane component:**

```
┌─────────────────────────────────────────────────────────┐
│  DECISION NEEDED                          ⏱ 28s         │
│  ─────────────────────────────────────────────────────  │
│  Sarah's call · Acme                                     │
│  "Acme wants 20% discount. Approve a counter at 10%?"   │
│                                                          │
│  ◯ Approve 10%                                    [Tap] │
│  ◯ Hold firm at list                              [Tap] │
│  ◯ Defer to me later                              [Tap] │
│                                                          │
│  [Whisper to agent instead ↗]                            │
└─────────────────────────────────────────────────────────┘
```

**Mobile (the critical mode — Manager between meetings):** the decision pane is a full-screen sheet with large touch targets; same SMS fallback fires server-side regardless of which surface the Manager taps. SMS-tap and FE-tap race; first-responder-wins server-side per BE §5.5.3.

**The Decisions inbox** (`/w/{wid}/decisions`):
- Open decisions (countdown still running, with timer)
- Async decisions (open, no countdown)
- Recent (last 7 days, with answer + outcome)
- **Missed (timed out)** — the prominent section flagged from BE §5.5.3 timeout behavior. One-click "Resolve now" CTA per item.

### 7.4 F4 — Call Review (Phase 1)

**Backend flow:** BE §7.4 (Post-Call Processing); BE LLD Phase 1 §D1 (transcripts + call history) + §D2 (action items).

**Endpoints consumed:**

| Surface | BE endpoint |
|---|---|
| Call detail (metadata + summary + decisions + action items) | `GET /workspaces/{wid}/calls/{call_id}` (Phase 1 §D1) |
| Canonical summary alone | `GET /workspaces/{wid}/calls/{call_id}/summary` (Phase 0 §C11 — minimum) |
| Full transcript | `GET /workspaces/{wid}/calls/{call_id}/transcript` (JSON; `?format=text` for gzipped plaintext per `Accept-Encoding`) |
| Recording (audio) | `GET /workspaces/{wid}/calls/{call_id}/recording` → 302 to a signed URL (15 min TTL); returns **`425 recording_not_ready_yet`** until AP delivers the recording webhook some seconds after `call.ended` — FE polls or shows "audio coming…" until 302 |
| Replay (QA / training) | `GET /workspaces/{wid}/calls/{call_id}/replay` — WebSocket that replays original transcript + decision frames at original cadence |
| Action items for this call | `GET /workspaces/{wid}/action_items?call_id=…` (Phase 1 §D2 — note underscore in API path) |
| Interventions (whispers) | `GET /workspaces/{wid}/calls/{call_id}/interventions` (Phase 1 §D4) |

A call enters "review" state when `agent.call_ended` is processed and the `post_call` job finishes. The FE knows it's ready via the `summary_ready` and `action_items_ready` WS frames (BE Phase 1 §D2), at which point it refetches the relevant query.

```
/w/{wid}/calls/{call_id}              (when call.status = 'ended' + summary ready)

  ┌─────────────────────────────────────────────────────────────┐
  │  Call review · Sarah · Acme · 4:21 · 2 hours ago             │
  │  ─────────────────────────────────────────────────────────── │
  │                                                              │
  │  CANONICAL SUMMARY  (our summarizer mini-agent)             │
  │  ─────────────────                                           │
  │  Discussion: pricing pressure, integration timeline concerns │
  │  Blockers: integration team hasn't responded in 2 weeks      │
  │  In their own words: "We need certainty by end of Q3"        │
  │  Action items (3 →)                                          │
  │                                                              │
  │  ▾ Show AgentPhone's built-in summary (signal-only)          │
  │     [BE §7.4: AP provider_summary is rendered collapsed,     │
  │      diffed against the canonical so the Manager can flag    │
  │      cases where the two disagree]                           │
  │                                                              │
  │  ACTION ITEMS                                                │
  │  ┌────────────────────────────────────────────────────────┐ │
  │  │ □ Follow up with integration team by Tue [Approve][Edit]│ │
  │  │ □ Send pricing one-pager to Jane                        │ │
  │  │ □ Schedule check-in next week                           │ │
  │  └────────────────────────────────────────────────────────┘ │
  │                                                              │
  │  ENTITIES UPDATED  (BrainUpdater output)                     │
  │  → accounts/acme-corp · 2 new timeline entries [view]        │
  │  → people/jane-customer · created (stub → enriched) [view]   │
  │                                                              │
  │  ▾ Full transcript (collapsed by default)                    │
  │  ▾ Recording (audio player, scrubbable, 4:21)                │
  └─────────────────────────────────────────────────────────────┘
```

**Key UX decisions:**

- **Canonical summary is the primary surface;** AP's provider_summary is collapsed by default but available for cross-check. This matches BE §7.4's "AP summary is a signal, canonical is the truth" position.
- **Action items default to approved-not-yet-acted state** with one-click final approval. The drafted artifact (email, calendar invite) appears on approval per §7.6 of the BE HLD.
- **Entity updates link to the brain pages** so the Manager can verify what got extracted and correct it inline.
- **Transcript and recording are collapsed** but inline-expandable. Right-click a transcript line → "Correct this" opens a CorrectionIntake dialog scoped to that line.

### 7.5 F5 — Brain Explorer & Editor (Phase 0 read; Phase 1 edit)

**Backend flows:** BE §5.3.2 (Workspace Brain), §9 (Correction & Provenance).

#### 7.5.1 Brain Explorer (Phase 0)

```
/w/{wid}/brain                                Default: list view; toggle to graph

  ┌─────────────────────────────────────────────────────────────┐
  │  Brain · 1,247 pages · 3,891 edges                          │
  │  ─────────────────────────────────────────────────────────  │
  │  [search ____________________]   [Type ▾]  [Sort ▾]  [⊞⊟]  │
  │                                                              │
  │  ACCOUNTS (203)                                              │
  │    accounts/acme-corp           Last touched 2h ago          │
  │    accounts/initech             Last touched 5h ago          │
  │    ...                                                       │
  │                                                              │
  │  PEOPLE (1,341)                                              │
  │    people/jane-customer         3 calls mention her          │
  │    ...                                                       │
  │                                                              │
  │  PRODUCTS (12)                                               │
  │  THEMES (47)                                                 │
  │  PLAYBOOKS (8)                                               │
  └─────────────────────────────────────────────────────────────┘
```

Per-page reads use `GET /workspaces/{wid}/brain/pages/{slug}` (Phase 0 §C8); version history is at `GET /workspaces/{wid}/brain/pages/{slug}/versions`. **Search is the open gap** (§5.7 + §11): the BE has `hybrid_search()` as an internal function (Phase 1 §D3) but no `GET /workspaces/{wid}/brain/search` endpoint yet. Until that lands, the Brain Explorer renders the page list via a paginated list endpoint (TBD) with client-side type filters and sort; server-side hybrid search is wired the moment the endpoint exists.

#### 7.5.2 Brain Page View (Phase 0)

```
/w/{wid}/brain/accounts/acme-corp

  ┌─────────────────────────────────────────────────────────────┐
  │  accounts/acme-corp                                          │
  │  Tags: enterprise, renewal-q3, top-account                   │
  │  ─────────────────────────────────────────────────────────  │
  │  COMPILED TRUTH (current understanding)             [Edit]   │
  │  Acme is our biggest customer, currently on Pro tier,        │
  │  approaching renewal in Q3. Owned by Sarah. Pain points      │
  │  around integration latency. (i)                             │
  │  ─────────────────────────────────────────────────────────  │
  │  TIMELINE                                                    │
  │  2025-04-15  Sarah discussed pricing  → call_abc123          │
  │  2025-04-10  Sarah & Jane reviewed roadmap → call_def456     │
  │  2025-03-22  Initial discovery → manager_upload              │
  │  ...                                                         │
  │  ─────────────────────────────────────────────────────────  │
  │  CONNECTED ENTITIES (graph)                                  │
  │  → callers/sarah  [owns]                                    │
  │  → people/jane-customer  [works_at]                         │
  │  → products/pro-tier  [uses]                                │
  └─────────────────────────────────────────────────────────────┘
```

The `(i)` icon next to any claim is the **Provenance tooltip** (§5.6 patterns). Hover shows where the claim came from: source type, source ID, extraction skill version, confidence, original cite. One click → "Edit this claim" → opens the Correction Dialog. Directly maps to BE §9.1.

#### 7.5.3 Correction Dialog (Phase 1)

```
┌─────────────────────────────────────────────────────────────┐
│  Correct: "Owned by Sarah"                                   │
│  ─────────────────────────────────────────────────────────  │
│  Current value                                               │
│  → Owned by Sarah                                            │
│                                                              │
│  Replace with                                                │
│  ┌────────────────────────────────────────┐                │
│  │ Owned by Bob                            │                │
│  └────────────────────────────────────────┘                │
│                                                              │
│  Reason (optional)                                           │
│  ┌────────────────────────────────────────┐                │
│  │ Bob took over this account in March    │                │
│  └────────────────────────────────────────┘                │
│                                                              │
│  ⓘ This will update 14 dependent entries.                   │
│    The original value will be preserved in the timeline.    │
│                                                              │
│  [Cancel]                            [Apply correction]      │
└─────────────────────────────────────────────────────────────┘
```

**Submit goes to** `POST /workspaces/{wid}/brain/corrections` (Phase 0 §C8). The body is a `CorrectionIntake` shape (the same shape Stage 5 of onboarding posts).

**Optimistic update with explicit cascade indicator:**

1. On submit, the FE patches the local cache immediately (the displayed `compiled_truth` updates to "Owned by Bob").
2. A toast appears: "Cascading updates… (14 entries)" with progress indicator.
3. The BE `correction_cascade` worker runs (BE §9.4 + Phase 0 §C8).
4. **Phase 0 progress fallback:** there is no `correction.cascade.progress` WS frame yet (logged as a §11 contract gap). The FE polls `GET /workspaces/{wid}/brain/pages/{slug}/versions` (and the affected dependent slugs) every ~1s for up to 10s to detect when the new `BrainPageVersion` row's cascade is `applied` vs `partially_applied`. If/when the WS frame ships, the polling path is removed.
5. On completion: "Cascade complete · Undo (30s)" — the undo window matches the 30s timeout before the version is "settled."
6. If the cascade returns `partially_applied`: toast turns to warning, "Some updates couldn't apply — view details" link opens an audit panel with the failed targets.

This is the most distinctive UX in the FE because it visualizes a thing that's hard to see otherwise: **a correction's blast radius**.

### 7.6 F6 — Action Items Inbox (Phase 1)

**Backend flow:** BE §7.6 (Action Item Execution).

```
/w/{wid}/action-items

  ┌─────────────────────────────────────────────────────────────┐
  │  Action items                                                │
  │  ─────────────────────────────────────────────────────────  │
  │  PENDING APPROVAL (3)                                        │
  │    □ Send pricing one-pager to Jane @ Acme       [Review]   │
  │    □ Schedule follow-up with Bob, Wed afternoon  [Review]   │
  │    □ Check in with integration team             [Review]    │
  │                                                              │
  │  IN FLIGHT (1)                                               │
  │    ⟳ Sending: Email to Jane @ Acme  (queued 12s ago)        │
  │                                                              │
  │  COMPLETED (last 7 days)                                     │
  │  ...                                                         │
  └─────────────────────────────────────────────────────────────┘
```

**[Review]** opens the drafted artifact in a modal — email body / calendar invite — editable before send. **Phase 1 BE (§D2) ships state transitions only**: `POST /workspaces/{wid}/action_items/{id}/approve` flips the row to `approved`; `POST /…/reject` flips to `rejected`; `PATCH /workspaces/{wid}/action_items/{id}` edits title/description/`due_at` before approval. The actual handler execution (send the email, write the calendar invite) is **Phase 2** — until then the "IN FLIGHT" pane simply reflects the approved-not-yet-acted state and the artifact preview is a draft, not a sent message.

### 7.7 F7 — Daily Brief (Phase 1)

**Backend flow:** BE §5.5.3 (Missed-decision flagging) + §7.5 (dashboard_rollup mini-agent).

The home screen for the Manager from Phase 1 onward. Generated nightly by `dashboard_rollup`.

```
/w/{wid}/home

  ┌─────────────────────────────────────────────────────────────┐
  │  Tuesday, April 16 · Good morning                            │
  │  ─────────────────────────────────────────────────────────  │
  │                                                              │
  │  DECISIONS YOU MISSED (2)                  ← from BE §5.5.3 │
  │    ⚠ Sarah · Acme · "Approve 10% discount?"     [Resolve →] │
  │    ⚠ Maya · Globex · "Should we bring in CSM?"  [Resolve →] │
  │                                                              │
  │  ─────────────────────────────────────────────────────────  │
  │                                                              │
  │  YESTERDAY                                                   │
  │  - 7 calls, avg 3:42                                         │
  │  - 4 action items pending your approval                      │
  │  - 2 new accounts mentioned: Stripe, Vercel                  │
  │  - 1 theme emerging: customers asking about API limits       │
  │                                                              │
  │  TODAY                                                       │
  │  - Sarah: Acme renewal call at 2pm                          │
  │  - Bob: Initech discovery at 4pm                            │
  │                                                              │
  │  [View full brief →]                                         │
  └─────────────────────────────────────────────────────────────┘
```

The "Decisions you missed" section is prominent — top of brief — because it represents action the Manager owes that didn't get done yesterday. One-click "Resolve" reopens the original decision context: the call, the prompt, the original options.

### 7.8 F8 — Roster (Phase 0)

```
/w/{wid}/roster

  ┌─────────────────────────────────────────────────────────────┐
  │  Field Reps · 12                                  [+ Add]   │
  │  ─────────────────────────────────────────────────────────  │
  │  Sarah Chen           West       +1 415 555 0142   3 calls  │
  │  Bob Martinez         East       +1 212 555 0188   1 call   │
  │  Maya Patel           Central    +1 312 555 0177   12 calls │
  │  ...                                                         │
  └─────────────────────────────────────────────────────────────┘
```

Click a rep → `/w/{wid}/roster/{field_employee_id}` — their profile (Caller Brain view, BE §5.3.3): identity, manager-noted style, owned accounts, call history, recent themes from their calls. "Edit" opens the per-rep intake form from onboarding Stage 2; corrections fan through the same pipeline.

### 7.9 F9 — Settings & Data Sources (Phase 0)

Workspace config: timeouts, retention defaults (when those land per BE §13.2), notification preferences. Reads/writes via `GET` / `PATCH /workspaces/{wid}/config` (BE Phase 0 §C1) — `config` is a free-form dict server-side, so the FE narrows it via a `WorkspaceConfig` type and validates with Zod before patching.

Data sources: **Phase 0 BE ships only the `manual_upload` connector** (Phase 0 LLD §A11 ConnectorRegistry), exposed through the intake-upload path (§7.1). Real third-party connectors (Salesforce, HubSpot, Google Workspace, Microsoft 365, Notion, Slack) are anticipated **Phase 1+** per BE HLD §11.6 — they'll plug into the `DataSourceConnector` extension point with per-connector OAuth dances. Until then, the Data Sources screen shows the manual-upload history (a thin renderer over `GET /workspaces/{wid}/intake/items?kind=upload`) and a "More connectors coming" placeholder list. The "Disconnect" UX and OAuth-callback handling are deferred to whenever the first real connector lands.

---

## 8. Modularity & Extension Points

Mirrors BE §8. FE has its own extension points; each is a one-file addition.

### 8.0 Summary Table

| # | Extension point | How you extend it | Used for |
|---|---|---|---|
| 8.1 | **Route** | Drop a file into `src/app/...` | New page |
| 8.2 | **Feature Widget** | Drop a component into `src/components/features/<feature>/` | New screen-specific widget |
| 8.3 | **WS Frame Handler** | Register in `src/realtime/handlers.ts` | New BE-side WS event |
| 8.4 | **Query Hook** | Drop a hook into `src/queries/` | New BE endpoint consumed |
| 8.5 | **Mutation Hook with Optimistic** | Drop a hook into `src/mutations/` | New BE mutation that needs UX feedback |
| 8.6 | **Toast / Notification Variant** | Register in `src/notifications/registry.ts` | New event the user should know about |
| 8.7 | **Provenance Renderer** | Register in `src/brain/provenance/renderers.ts` | New `source_type` from BE §9.1 needs distinct visual treatment |

### 8.1 Routes

Next.js App Router file conventions. Drop `src/app/w/[wid]/something/page.tsx` and the route exists. Layout files in parent directories enforce auth and scope.

### 8.2 Feature Widgets

Components are organized by BE concept (§5.6). Adding a new widget for an existing feature is dropping a `.tsx` file into the right `features/<feature>/` directory; the widget imports its data via hooks from `src/queries/`.

### 8.3 WebSocket Frame Handlers

Each WS frame type has exactly one handler (the §5.4 `FrameHandler` registry). Adding a new frame type from the BE:

1. Add the frame's TypeScript type to the `WSFrame` union (regenerated from OpenAPI, but WS frames live alongside).
2. Implement `handleNewFrameType(frame, queryClient)` in `src/realtime/handlers/`.
3. Register in `src/realtime/handlers.ts`:
   ```ts
   const handlers = {
     ...existing,
     'new.frame.type': handleNewFrameType,
   };
   ```

The bridge automatically routes incoming frames to the right handler. Untyped frames are logged and dropped.

### 8.4 Query Hooks (Server State Reads)

One hook per BE endpoint. Convention:

```ts
// src/queries/useWorkspaceCalls.ts
export function useWorkspaceCalls(workspaceId: UUID, opts?: { status?: CallStatus }) {
  return useQuery({
    queryKey: ['workspaces', workspaceId, 'calls', opts],
    queryFn: () => api.workspaces(workspaceId).calls.list(opts),
    staleTime: 30_000,
  });
}
```

Every hook returns the same shape (`{ data, isLoading, error, ... }`) so components are agnostic to where data comes from. Adding a new BE endpoint → adding a new hook file.

### 8.5 Mutation Hooks (Server State Writes)

Mutation hooks declare optimistic strategy explicitly:

```ts
// src/mutations/useApproveActionItem.ts
export function useApproveActionItem() {
  return useMutation({
    mutationFn: (id: UUID) => api.actionItems.approve(id),
    onMutate: async (id) => {
      // optimistic
      await queryClient.cancelQueries({ queryKey: ['action-items'] });
      const previous = queryClient.getQueryData(['action-items']);
      queryClient.setQueryData(['action-items'], (old) => patchStatus(old, id, 'approved'));
      return { previous };
    },
    onError: (_err, _id, ctx) => {
      // rollback
      queryClient.setQueryData(['action-items'], ctx?.previous);
      toast.error('Approval failed');
    },
    onSettled: () => {
      queryClient.invalidateQueries({ queryKey: ['action-items'] });
    },
  });
}
```

### 8.6 Toast / Notification Registry

Different events deserve different visual treatment (success toast vs warning banner vs full modal). One registry maps event type → renderer.

### 8.7 Provenance Renderers

Per BE §9.1, every claim has a `Provenance.source_type`. The FE renders the provenance tooltip differently per source:

- `manager_form` → simple "You said this on [date]"
- `manager_voice_intake` → link to the voice intake transcript line
- `field_call` → link to the call + timestamp + transcript snippet
- `automated_extraction` → "Auto-extracted from [source] by classifier@0.3.0 (87% confidence)"

Adding a new source type from BE → adding a renderer entry. Default renderer shows raw metadata if no specific renderer is registered.

---

## 9. State Sync, Offline, and Multi-Tab

### 9.1 Connection Loss Handling

The Manager is mobile. Network drops happen.

| Scenario | Behavior |
|---|---|
| WS disconnect during live call | "Reconnecting…" subtle banner; transcript pauses. On reconnect the bridge re-mints a short-lived WS token (`POST /workspaces/{wid}/ws/token`), reconnects, and reseeds Active Calls from the `snapshot` frame; missed transcript fragments are backfilled from `GET /workspaces/{wid}/calls/{call_id}/transcript` (Phase 1 §D1) — the BE explicitly does **not** replay live frames (Phase 0 §C5). Banner clears with "(caught up)". |
| HTTP 401 during a normal request | Silent refresh attempt via `POST /api/v1/auth/refresh` → retry → if still 401, redirect to signin preserving return URL. The rotated refresh token replaces the prior one. |
| BE down (HTTP 5xx) | Toast "Backend unreachable, retrying…" with exponential backoff on the affected query. Standard error envelope per BE LLD §A8: `{"error":{"code","message","request_id","details"}}` — surface `request_id` in the toast for support. |
| WS down but HTTP fine | Fall back to polling for live calls (`GET /workspaces/{wid}/calls?status=in_progress` every 5s); banner indicates "Limited real-time mode". |
| Both down | Full-page error overlay with retry button and a status link. |

### 9.2 Multi-Tab Coordination

Two tabs open by the same Manager:
- Each tab has its own WS connection.
- BE accepts multiple sessions per user.
- Each tab maintains independent TanStack Query cache (no shared SharedWorker in Phase 0).
- Decision prompts appear in both tabs. The first tab to submit a response wins (BE-side). The losing tab receives `decision.resolved` and closes the pane.
- A future enhancement (Phase 2+) might add SharedWorker-based cache sharing across tabs; not needed for the current scope.

### 9.3 Optimistic vs Pessimistic Recap

| Mutation | Optimistic | Pessimistic | Reason |
|---|---|---|---|
| Mark action item approved | ✓ | | Cheap to rollback |
| Submit correction | ✓ | | UX needs to feel responsive; cascade indicator handles in-flight state |
| Respond to decision | | ✓ | Wrong answer worse than slow feedback |
| Send approved email | | ✓ | Send-once semantics |
| Edit brain page text | ✓ | | Standard editor UX |
| Onboarding stage advance | | ✓ | Backend has to confirm provisioning succeeded |

---

## 10. Tech Stack Summary

### 10.1 Stack Choices

| Layer | Choice | Notes |
|---|---|---|
| Framework | Next.js 15 (App Router) | File-based routing, RSC where useful (static pages); client-heavy in /w/... |
| Language | TypeScript strict mode | Generated types from BE OpenAPI |
| Server state | TanStack Query v5 | Query keys path-shaped to mirror BE routes |
| Client state | Zustand | Lightweight; one store per feature |
| Real-time | Native WebSocket + custom bridge | Reconnect with exponential backoff; frame replay via `seq` |
| Component primitives | shadcn/ui (Radix + Tailwind) | Components in repo, not as dep |
| Styling | Tailwind v4 | Design tokens in `@theme` block |
| Forms | react-hook-form + Zod | Zod schemas can be generated from BE Pydantic via openapi-zod-client |
| Tables | TanStack Table | For roster, action items, decisions inbox |
| Virtualization | TanStack Virtual | Multi-call view + long transcripts |
| Graph viz (brain) | sigma.js or react-flow | Decided in low-level design |
| Date / time | date-fns + Temporal polyfill | Timestamps from BE are UTC ISO strings |
| Errors | Sentry | Captures unhandled + custom error boundaries |
| Analytics | PostHog (optional) | Only if product team needs it |
| Testing | Vitest + Storybook + Playwright | See §12 |

### 10.2 Deployment Profiles — Local vs Cloud

Mirrors BE §10.2. The FE has fewer infra concerns; the only "service" the FE needs locally is the backend itself.

| Component | Local | Cloud |
|---|---|---|
| Frontend build | `npm run dev` (Next.js dev server, port 3000) | Vercel / Netlify / static export to S3+CloudFront |
| Backend (consumed) | `localhost:8000` (Docker Compose from BE side) | The deployed BE URL |
| WebSocket | `ws://localhost:8000/api/v1/...` | `wss://<deployment>/api/v1/...` |
| API client base URL | `NEXT_PUBLIC_API_URL=http://localhost:8000` | `NEXT_PUBLIC_API_URL=https://api.<deployment>` |

`.env.local` and `.env.production.local` switch the base URL. No code changes between profiles.

**One local-dev nuance:** AgentPhone webhook needs to reach the BE, which means the BE needs an `ngrok` tunnel (per BE §10.2). The FE does not need a tunnel — it always points at localhost backend during dev. The tunnel is BE-side only.

---

## 11. Front-End ↔ Backend Contract Gaps

Gaps the FE has found while consuming the Phase 0 + Phase 1 backend LLDs. Some originally listed here have been resolved by the LLDs (recorded below for traceability); the remaining ones need BE work before — or as part of — the FE phase that depends on them.

### 11.1 Resolved by the Phase 0 / Phase 1 LLDs (no further BE work needed)

| Original gap | Resolution in the LLD |
|---|---|
| **WS frame `seq` for replay** | BE chose a different mechanism. Phase 0 LLD §C5 explicitly: "no replay of transcript fragments — the REST `GET /calls/{id}/transcript` is the durable source." The FE recovers via a fresh `snapshot` frame on reconnect plus a transcript REST refetch (§5.4 / §9.1). The `seq` field has been removed from §6's WSFrame union. |
| **Reconnect replay window** | Moot — see above. |
| **Recording playback signed URLs** | Phase 1 §D1 confirms 15-min TTL with `GET /workspaces/{wid}/calls/{call_id}/recording` → 302. **Newly relevant:** the endpoint returns `425 recording_not_ready_yet` until AP delivers the recording webhook some seconds after `call.ended` — FE handles this (§7.4). |

### 11.2 Still open — needs BE work before the dependent FE feature ships

| Gap | Detail | Proposed resolution | Blocking FE feature |
|---|---|---|---|
| **Cookie vs Bearer auth posture** | §5.1 prefers cookie-based auth for XSS mitigation; BE Phase 0 §A7 ships OAuth2 Bearer only. Production is currently Bearer-in-header. | Either (a) BE adds a cookie-mode option behind a setting, or (b) FE documents the Bearer-only posture in §5.1 and adds explicit XSS hardening elsewhere (CSP, no third-party scripts in the app shell). Pick before launch. | Auth screens (priority #1) |
| **Brain search endpoint** | Phase 1 §D3 implements `hybrid_search()` internally but exposes no `GET /workspaces/{wid}/brain/search?q=…&types=…&limit=…` route. FE Brain Explorer needs server-side search at >~500 pages. | Add the route in Phase 1 §D3; signature should return `{hits: [{slug, score, snippet, type}], total}`. | Brain Explorer search (priority #5) |
| **Brain page list endpoint** | The list view (§7.5.1) needs a paginated list — `GET /workspaces/{wid}/brain/pages?type=…&sort=…&cursor=…`. Phase 0 §C8 only exposes per-slug reads. | Add the list endpoint alongside the per-slug `GET`. | Brain Explorer list (priority #5) |
| **Chunked / resumable upload protocol** | §7.1 onboarding asks Managers to upload large CRM exports; Phase 0 §C2 caps `POST /intake/upload` at 25 MB single-shot multipart. | Add `POST /workspaces/{wid}/intake/uploads/init` → `PUT /uploads/{id}/chunks/{n}` → `POST /uploads/{id}/complete` with a `GET /uploads/{id}/status` for progress; emit a WS frame `intake.processing.update` if real-time progress is needed beyond polling. | Onboarding Stage 2 large-file path (priority #2) |
| **Cascade-progress WS frame** | §7.5.3 wants "Cascading 14 updates…" feedback. BE's `correction_cascade` worker (Phase 0 §C8) doesn't currently emit progress events. | Add `correction.cascade.progress { correction_id, page_slug, completed, total }` from BE §9.4. Until then, FE polls `GET /brain/pages/{slug}/versions` for status (§7.5.3 fallback). | Correction Dialog with cascade UX (priority #15) |
| **Password reset** | §5.1 lists `/auth/reset` as a Phase 0 screen but Phase 0 §A7 doesn't include the endpoint. | BE Phase 1+: `POST /api/v1/auth/reset/request` (sends email with token) → `POST /api/v1/auth/reset/confirm` (`{token, new_password}`). | Self-serve password reset |
| **Field-employee CRUD** | §5.6 BE module structure registers `field_employees.py` but Phase 0 LLD doesn't pin the CRUD surface; FE Roster screen (priority #6) needs at minimum `GET /workspaces/{wid}/field_employees`, `POST` (add), `GET /{id}`, `PATCH /{id}`, `DELETE /{id}`. | Pin in a Phase 0 addendum or Phase 1 §D-section. | Roster (priority #6) |

### 11.3 Process gaps (not endpoint-level)

| Gap | Detail | Proposed resolution |
|---|---|---|
| **OpenAPI spec stability commitment** | The FE depends on `openapi.json` being regenerated and committed on every BE schema change. | Add to BE §14.1 Resolved Decisions: OpenAPI spec is committed to the repo; CI blocks BE merges if the spec is stale. Pair with the FE CI gate in §12.4 (this doc). |
| **WS frame schemas in OpenAPI** | OpenAPI doesn't natively cover WS message schemas, but FE wants typed handlers (§5.4). | BE: declare frames as Pydantic models in `app/schemas/ws_frames.py` (already exists per Phase 0 §C5) and emit a separate `ws-schemas.json` artifact at build time; FE generates the `WSFrame` union from both. |

Each item is small and concrete. The remaining open ones should be folded into the BE LLD before the dependent FE phase begins.

---

## 12. Verification & Testing

Mirrors BE §12 in spirit but with FE-shaped tools. Three layers.

### 12.1 Storybook — Component Verification

Every primitive and pattern has a Storybook story. Every feature widget has at least one story per significant state. CI runs Storybook in interaction-test mode (Storybook 8 has Vitest integration).

```
stories/
  primitives/Button.stories.tsx
  features/call/LiveCallPane.stories.tsx
    - "Empty (no active call)"
    - "Active call streaming"
    - "Active call with decision prompt"
    - "Active call with whisper input open"
    - "Ended call (review mode)"
  features/brain/CorrectionDialog.stories.tsx
    - "Initial"
    - "Cascading (in flight)"
    - "Cascade complete"
    - "Cascade error"
```

Stories double as visual regression test surfaces (Chromatic or Playwright screenshot diffs).

### 12.2 Vitest — Unit + Hook Tests

Unit tests for:
- Reducers, selectors, pure utility functions
- All custom hooks (using `@testing-library/react-hooks`)
- WS frame handlers (give them a fake `queryClient`, assert cache state after)
- API client wrappers (against MSW mock server)

### 12.3 Playwright — End-to-End Flows

Playwright tests run against a real backend (typically the staging deployment, optionally a local Docker Compose stack).

| Flow | Why it's covered |
|---|---|
| Signup → onboarding → first verified state | Smoke for the whole Phase 0 happy path |
| Manager receives inbound call, sees transcript live | Verifies WS bridge end-to-end |
| Decision prompt appears, Manager taps option, Orchestrator continues | Verifies §7.3 round-trip |
| Whisper input submitted during call, post-call shows whispered turn | Verifies §5.5.4 (Phase 1) |
| Correction in brain explorer, cascade completes, audit shows version | Verifies §9 (Phase 1) |
| Hierarchy guard: forged JWT with `role=rep` rejected from `/w/{wid}/*` | Mirrors BE §13.4 guard test from the FE side |
| Network loss during call: reconnect, frame replay catches up | Verifies §9.1 (this doc) |
| Multi-tab: decision in tab 1, answered in tab 2, both reflect resolved | Verifies §9.2 |

Playwright runs are tagged by phase so Phase 0 CI only runs Phase 0 flows.

### 12.4 Contract Tests Against the BE OpenAPI Spec

CI step in the FE repo:
1. Pull the latest `openapi.json` from the BE repo (pinned commit or `main`).
2. Regenerate FE types.
3. Run TypeScript compilation.
4. Any breakage = the BE shipped a breaking change.

This is the FE-side equivalent of the BE smoke tests in spirit: catching contract drift early, mechanically.

### 12.5 What These Don't Cover

- **Visual / design fidelity** — Chromatic (or Percy) handles screenshot diffs for Storybook stories. Not part of the unit-test bundle.
- **Accessibility audits** — axe-core integrated into Storybook play functions; manual audits for the Live Call Hub specifically.
- **Performance regressions** — Lighthouse CI on key routes; the multi-call view gets a separate "10-pane streaming" budget test in Playwright.

---

## 13. Phase-by-Phase Implementation Map

| # | Priority | Phase | Component Work |
|---|---|---|---|
| 1 | Auth + scope | 0 | `/auth/*` routes; JWT cookie handling; session middleware; `useCurrentUser` hook; role-aware nav |
| 2 | Onboarding wizard (Stages 1–5) | 0 | `/w/{wid}/onboarding/*` routes; `IntakeForm`, `DocumentUpload` (chunked, resumable), voice-intake trigger; Stage 5 `VerificationView` with inline corrections |
| 3 | Single Live Call View | 0 | `/w/{wid}/calls/{call_id}` (live mode); `LiveCallPane`, `CallTranscript`; WS bridge with frame handlers; ARIA live regions |
| 4 | Decision Pane | 0 | `DecisionPrompt` component (three classes, countdown, mobile sheet); SMS fallback awareness; `/w/{wid}/decisions` inbox |
| 5 | Brain Explorer (read) | 0 | `/w/{wid}/brain/*` routes; list + page view (`GET /workspaces/{wid}/brain/pages/{slug}` + the list endpoint flagged as a §11 gap); `ProvenanceTooltip`. Server-side search depends on the §11.2 brain-search endpoint landing; client-side filtering of the page list is the Phase 0 fallback. |
| 6 | Roster + Field Rep profile | 0 | `/w/{wid}/roster/*`; per-rep edit form (reuses onboarding components) |
| 7 | Settings + Data Sources | 0 | `/w/{wid}/settings`, `/w/{wid}/data-sources`; connector OAuth flow UI |
| 8 | Hierarchy guard test (FE side) | 0 | Playwright: stub `org_admin`/`rep` JWT cannot access `/w/{wid}/*`; `/org/*` and `/rep/*` namespaces return 404 |
| 9 | OpenAPI type generation in CI | 0 | Build step regenerates `src/api/types.ts`; CI fails if drift; pinned BE schema version |
| 10 | Storybook + Vitest + Playwright | 0 | Test scaffolding for §12 layers; smoke set of stories and flows in place |
| 11 | Multi-Call Live Hub | 1 | `/w/{wid}/calls/active`; multi-pane layout; TanStack Virtual for pane mounting; frame-rate throttling |
| 12 | Call Review (with summary diff) | 1 | `/w/{wid}/calls/{call_id}` (review mode); `CallSummary` with AP `provider_summary` collapsible diff; transcript right-click → correct |
| 13 | Action Items Inbox | 1 | `/w/{wid}/action-items`; approval modal; in-flight indicator |
| 14 | Whisper Input | 1 | `WhisperInput` component on live call pane; `Cmd+W` shortcut; `takeover.granted` WS frame handler |
| 15 | Brain Editor (Correction Dialog) | 1 | `CorrectionDialog` with optimistic cascade UI; `correction.cascade.progress` WS handler |
| 16 | Daily Brief | 1 | `/w/{wid}/home` becomes Daily Brief; "Decisions you missed" section prominent |
| 17 | Scheduler / email approval | 2 | Email/calendar preview modal; one-click approve + send |
| 18 | Dashboards | 2 | `/w/{wid}/dashboards/*`; rollup widgets |
| 19 | Rep-side FE | 2+ | Light up `/rep/*` namespace; rep-scoped views |

---

## 14. Open Questions, Resolutions, Future Work

### 14.1 Resolved Decisions

- **Single WS connection per Manager session**, not per call (mirrors BE §5.5.2). See §5.4.
- **OpenAPI as the type source of truth.** No hand-rolled API types. See §5.5.
- **Optimistic strategy is per-mutation, declared explicitly.** See §9.3.
- **Reserved namespaces (`/org/`, `/rep/`) get empty pages in Phase 0** to power the FE-side hierarchy guard test. See §5.2.
- **Voice intake call is optional but recommended** in onboarding Stage 2. See §7.1.
- **Mobile is responsive web, not native, in Phase 0–1.** See §3.2.

### 14.2 Still-Open Questions

- **Graph viz library** for the brain explorer — sigma.js vs react-flow vs custom d3-force. Decide at LLD time based on the size of the 90th-percentile Workspace brain.
- **Whisper input on mobile** — virtual keyboard takes half the screen during a live call view. UX needs work.
- **Cmd+key shortcuts conflict with browser defaults** on macOS Safari for some combinations. Need an alternative key map or an in-app help overlay.
- **PostHog / analytics opt-in** — privacy posture (Phase 0 is Manager-private) means analytics defaults to off; need product input on whether to surface an opt-in.
- **Brand voice / copy** — the agent's voice is defined by BE skills (Orchestrator system prompt); the FE's copy (tooltips, labels, empty-state messages) is its own thing. Needs a copy doc.

### 14.3 Explicitly Deferred Future Work

- **Native mobile apps** (iOS, Android) — possibly Phase 3. Responsive web in Phase 0–2.
- **Rep-side FE** — Phase 2+, namespace reserved.
- **Org-level admin FE** — Phase 2+, namespace reserved.
- **Real-time multi-user collaboration on the brain** (two Managers editing the same page) — Phase 3+; requires CRDT or OT, big lift.
- **SharedWorker for cross-tab cache** — Phase 2+ if user feedback warrants.
- **PWA installability** — easy lift, postponed until product asks.

### 14.4 Risks

- **WS contract gaps (§11) shipping unresolved.** Mitigation: file BE-side issues against §11 items before Phase 0 BE work starts.
- **TanStack Query cache stampede on reconnect.** If the FE invalidates every query on WS reconnect, it can hammer the BE. Mitigation: use targeted cache patches via frame handlers (the §5.4 design), avoid blunt invalidations.
- **Correction Dialog UX complexity.** The cascade visualization is novel — users may not understand what "Cascading 14 updates" means. Mitigation: copy testing, fallback to a simpler "Applied — undo for 30s" message if the educational version doesn't resonate.
- **Multi-call performance.** A Manager with 20+ active calls is unusual but possible. Mitigation: virtualization (§5.7) and frame-rate throttling; load test the Live Hub before launch.
- **Mobile decision response.** This is the most product-critical mobile flow. Mitigation: dedicated Playwright mobile-emulation runs for the decision flow; design review specifically for one-handed thumb usage.
- **Type drift between BE and FE.** Mitigation: CI gate (§12.4) makes drift impossible to merge.

---

## 15. Appendix — Sample Sequence (Live Call Frame Flow)

End-to-end timing for a single transcript fragment arriving at the FE while the Manager is watching the live call.

```
T+0       BE telephony adapter receives agent.message:voice webhook from AgentPhone
T+50ms    BE adapter publishes transcript.fragment to Redis bus + WS hub
T+60ms    WS hub forwards frame to all Workspace subscribers
T+~70ms   Frame arrives at FE WSBridge (~10-50ms over wire, depending on network)
T+72ms    Bridge dispatches frame to handleTranscriptFragment(frame, queryClient)
T+73ms    Handler patches TanStack cache:
            queryClient.setQueryData(
              ['workspaces', wid, 'calls', frame.call_id, 'transcripts'],
              (old) => [...old, frame]
            )
T+74ms    TanStack notifies subscribers
T+75ms    Affected components re-render (React 19 concurrent, scheduled)
T+~85ms   Browser paints the new fragment in the call pane
T+86ms    ARIA live region announces (screen reader picks up on next polite check)

Total wall-clock latency from BE to visible: ~85ms (P50)
Manager-perceived: "instant"
```

The sample assumes a healthy WS connection. On a degraded connection where the FE has just reconnected, the bridge's reconciliation budget is bounded by (a) the time to re-mint a short-lived WS token (one fast REST call), (b) the `snapshot` frame the BE sends immediately on connect (Phase 0 §C5), and (c) any transcript REST refetches the bridge issues for in-progress calls (`GET /workspaces/{wid}/calls/{call_id}/transcript`, Phase 1 §D1) — typically <500ms total for a Workspace with a handful of active calls. There is no frame-replay queue (see §5.4).
