import { NextRequest, NextResponse } from "next/server";

export const runtime = "nodejs";

const SUPERMEMORY_BASE = "https://api.supermemory.ai";
const AGENTMAIL_BASE = "https://api.agentmail.to/v0";
// Browser Use's live API is /api/v2/tasks with the X-Browser-Use-API-Key
// header. The /api/v1/run-task path with Bearer auth that the older docs
// describe returns 404 in production, so we use the v2 surface here.
const BROWSER_USE_BASE = "https://api.browser-use.com/api/v2";

type AcceptPayload = {
  intakeId: string;
  caller: string;
  caseType: string;
  carrier?: string | null;
  valueRange: string;
  statute?: string | null;
  summary: string;
  transcript?: string;
  clientEmail?: string;
};

async function writeToSupermemory(p: AcceptPayload) {
  const key = process.env.SUPERMEMORY_API_KEY;
  if (!key) throw new Error("SUPERMEMORY_API_KEY not set");

  const content = [
    `New case accepted: ${p.caller}.`,
    `Mechanism: ${p.caseType}.`,
    p.carrier ? `Carrier: ${p.carrier}.` : "",
    `Estimated value: ${p.valueRange}.`,
    p.statute ? `Statute clock: ${p.statute}.` : "",
    "",
    `Intake summary: ${p.summary}`,
    p.transcript ? `\nFull transcript:\n${p.transcript}` : "",
  ]
    .filter(Boolean)
    .join("\n");

  const r = await fetch(`${SUPERMEMORY_BASE}/v3/memories`, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${key}`,
      "Content-Type": "application/json",
      Accept: "application/json",
    },
    body: JSON.stringify({
      content,
      containerTags: ["reyes-associates", `intake:${p.intakeId}`, "demo"],
      metadata: {
        intake_id: p.intakeId,
        caller: p.caller,
        case_type: p.caseType,
        carrier: p.carrier ?? "",
        value_range: p.valueRange,
        accepted_at: new Date().toISOString(),
      },
    }),
  });

  const text = await r.text();
  let body: unknown = null;
  try {
    body = JSON.parse(text);
  } catch {
    body = text;
  }
  if (!r.ok) {
    return { ok: false as const, status: r.status, body };
  }
  return { ok: true as const, status: r.status, body };
}

async function sendEngagementLetter(p: AcceptPayload) {
  const key = process.env.AGENTMAIL_API_KEY;
  const inbox = process.env.AGENTMAIL_INBOX;
  const to = p.clientEmail || process.env.DEMO_CLIENT_EMAIL;
  if (!key) throw new Error("AGENTMAIL_API_KEY not set");
  if (!inbox) throw new Error("AGENTMAIL_INBOX not set");
  if (!to) throw new Error("client email not configured");

  const subject = `Engagement letter — Reyes & Associates · ${p.caseType}`;
  const text = `Hello ${p.caller},

Thanks so much for calling Reyes & Associates today. As discussed, our managing partner Margarita Reyes has authorized us to represent you on this matter (${p.caseType}, ${p.carrier ?? "carrier TBD"}).

Two documents are attached / linked below — please review and e-sign at your earliest convenience:

1. Engagement letter (contingency fee agreement)
2. HIPAA medical records authorization

Important reminders:
• Please do not return any calls from ${p.carrier ?? "the at-fault carrier"} until we have your retainer back on file.
• Focus on your recovery. Keep all medical appointments and document any work missed.
• Statute of limitations: ${p.statute ?? "California PI 2 years"}.

We will be in touch within 48 hours to walk you through next steps.

— Sue, on behalf of Margarita Reyes
Reyes & Associates · Personal Injury Law
`;

  const html = `
<div style="font-family: -apple-system, system-ui, sans-serif; max-width: 600px; color: #111;">
  <h2 style="margin: 0 0 8px 0;">Engagement letter — Reyes &amp; Associates</h2>
  <p>Hello <strong>${p.caller}</strong>,</p>
  <p>Thanks so much for calling Reyes &amp; Associates today. Our managing partner Margarita Reyes has authorized us to represent you on this matter.</p>
  <table style="border-collapse: collapse; margin: 16px 0; font-size: 14px;">
    <tr><td style="padding: 4px 12px 4px 0; color: #666;">Case type</td><td style="padding: 4px 0;">${p.caseType}</td></tr>
    <tr><td style="padding: 4px 12px 4px 0; color: #666;">Carrier</td><td style="padding: 4px 0;">${p.carrier ?? "TBD"}</td></tr>
    <tr><td style="padding: 4px 12px 4px 0; color: #666;">Est. value</td><td style="padding: 4px 0;">${p.valueRange}</td></tr>
    <tr><td style="padding: 4px 12px 4px 0; color: #666;">Statute</td><td style="padding: 4px 0;">${p.statute ?? "California PI 2 years"}</td></tr>
  </table>
  <p>Two documents to e-sign:</p>
  <ol>
    <li>Engagement letter (contingency fee agreement)</li>
    <li>HIPAA medical records authorization</li>
  </ol>
  <p style="background: #fffceb; padding: 12px 16px; border-radius: 8px; font-size: 14px;">
    <strong>Important:</strong> Please do not return any calls from ${p.carrier ?? "the at-fault carrier"} until we have your retainer back on file.
  </p>
  <p style="color: #666; font-size: 13px; margin-top: 24px;">— Sue, on behalf of Margarita Reyes<br/>Reyes &amp; Associates · Personal Injury Law</p>
</div>
`.trim();

  const r = await fetch(`${AGENTMAIL_BASE}/inboxes/${encodeURIComponent(inbox)}/messages/send`, {
    method: "POST",
    headers: {
      authorization: `Bearer ${key}`,
      "content-type": "application/json",
      accept: "application/json",
    },
    body: JSON.stringify({
      to: [to],
      subject,
      text,
      html,
    }),
  });

  const respText = await r.text();
  let body: unknown = null;
  try {
    body = JSON.parse(respText);
  } catch {
    body = respText;
  }
  if (!r.ok) {
    return { ok: false as const, status: r.status, body };
  }
  return { ok: true as const, status: r.status, body, to };
}

async function createMatterViaBrowserUse(p: AcceptPayload) {
  const key = process.env.BROWSER_USE_API_KEY;
  if (!key) throw new Error("BROWSER_USE_API_KEY not set");

  const task = `Open https://www.google.com and search for '${p.caller} ${p.caseType} ${p.carrier ?? ""} personal injury case'. Return the first 3 result titles.`;

  const r = await fetch(`${BROWSER_USE_BASE}/tasks`, {
    method: "POST",
    headers: {
      "X-Browser-Use-API-Key": key,
      Authorization: `Bearer ${key}`,
      "Content-Type": "application/json",
      Accept: "application/json",
    },
    body: JSON.stringify({ task }),
  });

  const text = await r.text();
  let body: unknown = null;
  try {
    body = JSON.parse(text);
  } catch {
    body = text;
  }

  if (!r.ok) {
    return { ok: false as const, status: r.status, body };
  }

  // Be defensive about envelope shape — Browser Use v2 returns
  // `{ id, sessionId }` (202), but other variants might nest under `task`,
  // `data`, or use `task_id`.
  let taskId: string | undefined;
  if (body && typeof body === "object") {
    const obj = body as Record<string, unknown>;
    const candidate =
      (typeof obj.id === "string" && obj.id) ||
      (typeof obj.task_id === "string" && obj.task_id) ||
      (obj.task && typeof (obj.task as Record<string, unknown>).id === "string"
        ? ((obj.task as Record<string, unknown>).id as string)
        : undefined) ||
      (obj.data && typeof (obj.data as Record<string, unknown>).id === "string"
        ? ((obj.data as Record<string, unknown>).id as string)
        : undefined);
    if (candidate) taskId = candidate;
  }

  return {
    ok: true as const,
    status: r.status,
    taskId,
    statusLabel: "queued",
    body,
  };
}

export async function POST(req: NextRequest) {
  const payload = (await req.json()) as AcceptPayload;
  if (!payload?.intakeId || !payload?.caller) {
    return NextResponse.json(
      { error: "intakeId and caller are required" },
      { status: 400 },
    );
  }

  // Fire all three in parallel — let them succeed or fail independently
  const [supermemory, email, browserUse] = await Promise.allSettled([
    writeToSupermemory(payload),
    sendEngagementLetter(payload),
    createMatterViaBrowserUse(payload),
  ]);

  return NextResponse.json({
    supermemory:
      supermemory.status === "fulfilled"
        ? supermemory.value
        : { ok: false, error: String(supermemory.reason) },
    email:
      email.status === "fulfilled"
        ? email.value
        : { ok: false, error: String(email.reason) },
    browserUse:
      browserUse.status === "fulfilled"
        ? browserUse.value
        : { ok: false, error: String(browserUse.reason) },
  });
}
