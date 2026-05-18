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
