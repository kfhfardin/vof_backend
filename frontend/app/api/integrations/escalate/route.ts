import { NextRequest, NextResponse } from "next/server";

export const runtime = "nodejs";

const AGENTPHONE_BASE = "https://api.agentphone.ai/v1";
const AGENTMAIL_BASE = "https://api.agentmail.to/v0";

type EscalatePayload = {
  intakeId: string;
  caller: string;
  caseType: string;
  carrier?: string | null;
  valueRange: string;
  statute?: string | null;
  approvalLink?: string;
};

function summary(p: EscalatePayload, link: string) {
  return [
    `Lien · new intake needs your approval`,
    `${p.caller} · ${p.caseType}${p.carrier ? " · " + p.carrier : ""}`,
    `Est. value: ${p.valueRange}${p.statute ? " · " + p.statute : ""}`,
    `Tap to decide: ${link}`,
  ].join("\n");
}

async function tryAgentPhoneSMS(text: string) {
  const apiKey = process.env.AGENTPHONE_API_KEY;
  const agentId = process.env.AGENTPHONE_AGENT_ID;
  const to =
    process.env.AGENTPHONE_MARGARITA_TO ||
    process.env.SMOKE_AGENTPHONE_TEST_TO_NUMBER ||
    "+14783304859";
  if (!apiKey || !agentId) return { ok: false as const };

  const r = await fetch(`${AGENTPHONE_BASE}/messages`, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${apiKey}`,
      "Content-Type": "application/json",
      Accept: "application/json",
      "User-Agent":
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15",
    },
    body: JSON.stringify({ agent_id: agentId, to_number: to, body: text }),
  });
  const t = await r.text();
  let body: unknown = t;
  try {
    body = JSON.parse(t);
  } catch {}
  return { ok: r.ok, status: r.status, body, to };
}

async function tryAgentMail(p: EscalatePayload, link: string) {
  const apiKey = process.env.AGENTMAIL_API_KEY;
  const inbox = process.env.AGENTMAIL_INBOX;
  const to = process.env.DEMO_PARTNER_EMAIL || process.env.DEMO_CLIENT_EMAIL;
  if (!apiKey || !inbox || !to) return { ok: false as const };

  const r = await fetch(
    `${AGENTMAIL_BASE}/inboxes/${encodeURIComponent(inbox)}/messages/send`,
    {
      method: "POST",
      headers: {
        authorization: `Bearer ${apiKey}`,
        "content-type": "application/json",
        accept: "application/json",
      },
      body: JSON.stringify({
        to: [to],
        subject: `Lien · approve ${p.caller} · ${p.caseType}`,
        text: summary(p, link),
        html: `<div style="font-family:-apple-system,system-ui,sans-serif;color:#111;max-width:520px;">
  <div style="text-transform:uppercase;letter-spacing:.08em;font-size:11px;color:#666;">Lien · approval needed</div>
  <h2 style="margin:8px 0 4px 0;">${p.caller}</h2>
  <div style="color:#555;font-size:14px;">${p.caseType}${p.carrier ? " · " + p.carrier : ""}</div>
  <table style="border-collapse:collapse;margin:16px 0;font-size:14px;">
    <tr><td style="padding:4px 12px 4px 0;color:#666;">Est. value</td><td style="padding:4px 0;">${p.valueRange}</td></tr>
    <tr><td style="padding:4px 12px 4px 0;color:#666;">Statute</td><td style="padding:4px 0;">${p.statute ?? "CA 2y"}</td></tr>
  </table>
  <a href="${link}" style="display:inline-block;background:#0a0a0a;color:#fff;padding:10px 16px;border-radius:8px;text-decoration:none;font-weight:500;">Open one-tap approval →</a>
</div>`,
      }),
    },
  );
  const t = await r.text();
  let body: unknown = t;
  try {
    body = JSON.parse(t);
  } catch {}
  return { ok: r.ok, status: r.status, body, to };
}

export async function POST(req: NextRequest) {
  const p = (await req.json()) as EscalatePayload;
  if (!p?.intakeId || !p?.caller) {
    return NextResponse.json(
      { ok: false, error: "intakeId + caller required" },
      { status: 400 },
    );
  }
  const origin = req.nextUrl.origin;
  const link = p.approvalLink || `${origin}/approve/${p.intakeId}`;
  const text = summary(p, link);

  const sms = await tryAgentPhoneSMS(text);
  if (sms.ok) {
    return NextResponse.json({
      ok: true,
      channel: "agentphone",
      to: sms.to,
      link,
    });
  }
  const mail = await tryAgentMail(p, link);
  if (mail.ok) {
    return NextResponse.json({
      ok: true,
      channel: "agentmail",
      to: mail.to,
      link,
      sms_status: sms.status,
    });
  }
  return NextResponse.json({ ok: false, sms, mail, link });
}
