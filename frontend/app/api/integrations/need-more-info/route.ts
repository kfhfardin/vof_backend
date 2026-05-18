import { NextRequest, NextResponse } from "next/server";

export const runtime = "nodejs";

const AGENTMAIL_BASE = "https://api.agentmail.to/v0";

type NeedMoreInfoPayload = {
  intakeId: string;
  caller: string;
  caseType: string;
  carrier?: string | null;
  valueRange: string;
  statute?: string | null;
  summary: string;
  clientEmail?: string;
};

async function sendFollowUpEmail(p: NeedMoreInfoPayload) {
  const key = process.env.AGENTMAIL_API_KEY;
  const inbox = process.env.AGENTMAIL_INBOX;
  const to = p.clientEmail || process.env.DEMO_CLIENT_EMAIL;
  if (!key) throw new Error("AGENTMAIL_API_KEY not set");
  if (!inbox) throw new Error("AGENTMAIL_INBOX not set");
  if (!to) throw new Error("client email not configured");

  const subject = "Quick follow-up about your case — Reyes & Associates";
  const text = `Hello ${p.caller},

Thanks again for calling Reyes & Associates today about your ${p.caseType} matter. Before our managing partner Margarita Reyes can make a final decision on representation, we need a few more pieces of documentation from you.

Could you please reply to this email with:

1. ER discharge papers (and any urgent-care or follow-up visit summaries)
2. Photos of the damage / injury / scene (the more the better)
3. Witness contact info — names, phone numbers, and any statements they made

The sooner we have these, the sooner we can move forward. If anything is hard to track down, just let us know — we can usually help.

— Sue, on behalf of Margarita Reyes
Reyes & Associates · Personal Injury Law
`;

  const html = `
<div style="font-family: -apple-system, system-ui, sans-serif; max-width: 600px; color: #111;">
  <h2 style="margin: 0 0 8px 0;">Quick follow-up about your case</h2>
  <p>Hello <strong>${p.caller}</strong>,</p>
  <p>Thanks again for calling Reyes &amp; Associates today about your <strong>${p.caseType}</strong> matter. Before our managing partner Margarita Reyes can make a final decision on representation, we need a few more pieces of documentation from you.</p>
  <p>Please reply to this email with:</p>
  <ol style="line-height: 1.7;">
    <li><strong>ER discharge papers</strong> (and any urgent-care or follow-up visit summaries)</li>
    <li><strong>Photos of the damage</strong> / injury / scene — the more the better</li>
    <li><strong>Witness contact info</strong> — names, phone numbers, and any statements they made</li>
  </ol>
  <p style="background: #fffceb; padding: 12px 16px; border-radius: 8px; font-size: 14px;">
    The sooner we have these, the sooner we can move forward. If anything is hard to track down, just let us know — we can usually help.
  </p>
  <p style="color: #666; font-size: 13px; margin-top: 24px;">— Sue, on behalf of Margarita Reyes<br/>Reyes &amp; Associates · Personal Injury Law</p>
</div>
`.trim();

  const r = await fetch(
    `${AGENTMAIL_BASE}/inboxes/${encodeURIComponent(inbox)}/messages/send`,
    {
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
    },
  );

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

export async function POST(req: NextRequest) {
  const payload = (await req.json()) as NeedMoreInfoPayload;
  if (!payload?.intakeId || !payload?.caller) {
    return NextResponse.json(
      { error: "intakeId and caller are required" },
      { status: 400 },
    );
  }

  const [email] = await Promise.allSettled([sendFollowUpEmail(payload)]);

  return NextResponse.json({
    email:
      email.status === "fulfilled"
        ? email.value
        : { ok: false, error: String(email.reason) },
  });
}
