import { NextRequest, NextResponse } from "next/server";

export const runtime = "nodejs";

const AGENTPHONE_BASE = "https://api.agentphone.ai/v1";
const AGENTMAIL_BASE = "https://api.agentmail.to/v0";

type WhisperPayload = {
  intakeId: string;
  agentName: string;
  text: string;
  source?: "auto" | "custom";
};

async function tryAgentPhoneSMS(text: string): Promise<{
  ok: boolean;
  status?: number;
  body?: unknown;
  to?: string;
}> {
  const apiKey = process.env.AGENTPHONE_API_KEY;
  const agentId = process.env.AGENTPHONE_AGENT_ID;
  const toNumber =
    process.env.AGENTPHONE_WHISPER_TO ||
    process.env.SMOKE_AGENTPHONE_TEST_TO_NUMBER ||
    "+14783304859";

  if (!apiKey || !agentId) return { ok: false };

  const body = `From Margarita (Lien whisper):\n${text}`;
  const r = await fetch(`${AGENTPHONE_BASE}/messages`, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${apiKey}`,
      "Content-Type": "application/json",
      Accept: "application/json",
      "User-Agent":
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15",
    },
    body: JSON.stringify({
      agent_id: agentId,
      to_number: toNumber,
      body,
    }),
  });

  const text2 = await r.text();
  let parsed: unknown = null;
  try {
    parsed = JSON.parse(text2);
  } catch {
    parsed = text2;
  }
  return {
    ok: r.ok,
    status: r.status,
    body: parsed,
    to: toNumber,
  };
}

async function tryAgentMail(
  text: string,
  agentName: string,
  intakeId: string,
): Promise<{
  ok: boolean;
  status?: number;
  body?: unknown;
  to?: string;
}> {
  const apiKey = process.env.AGENTMAIL_API_KEY;
  const inbox = process.env.AGENTMAIL_INBOX;
  // The whisper goes to the "rep's inbox" — for the demo we route it to the
  // same address as the client engagement letter so it lands in a visible inbox.
  const to = process.env.DEMO_REP_EMAIL || process.env.DEMO_CLIENT_EMAIL;
  if (!apiKey || !inbox || !to) return { ok: false };

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
        subject: `Whisper · ${intakeId} · partner guidance`,
        text: `Hi ${agentName.split(" ")[0]},\n\nMargarita sent the following guidance for this call:\n\n${text}\n\n— Lien`,
        html: `<div style="font-family:-apple-system,system-ui,sans-serif;color:#111;max-width:560px;">
  <div style="text-transform:uppercase;letter-spacing:.06em;font-size:11px;color:#666;">Lien whisper · partner guidance</div>
  <h3 style="margin:6px 0 12px 0;">For ${agentName}</h3>
  <p style="background:#f3f4f6;padding:12px 16px;border-radius:8px;font-size:15px;line-height:1.5;">${text.replace(/&/g, "&amp;").replace(/</g, "&lt;")}</p>
  <p style="color:#666;font-size:12px;margin-top:16px;">Sent by Margarita Reyes mid-call · intake ${intakeId}</p>
</div>`,
      }),
    },
  );

  const respText = await r.text();
  let parsed: unknown = null;
  try {
    parsed = JSON.parse(respText);
  } catch {
    parsed = respText;
  }
  return { ok: r.ok, status: r.status, body: parsed, to };
}

export async function POST(req: NextRequest) {
  const payload = (await req.json()) as WhisperPayload;

  if (!payload?.text?.trim()) {
    return NextResponse.json(
      { ok: false, error: "text is required" },
      { status: 400 },
    );
  }

  const text = payload.text.trim();

  // 1) Try AgentPhone SMS/iMessage first.
  const sms = await tryAgentPhoneSMS(text);
  if (sms.ok) {
    return NextResponse.json({
      ok: true,
      channel: "agentphone",
      to: sms.to,
      sent: text,
    });
  }

  // 2) Fall back to AgentMail so the whisper still delivers.
  const mail = await tryAgentMail(text, payload.agentName, payload.intakeId);
  if (mail.ok) {
    return NextResponse.json({
      ok: true,
      channel: "agentmail",
      to: mail.to,
      sent: text,
      sms_status: sms.status,
      sms_error:
        typeof sms.body === "object" && sms.body && "detail" in (sms.body as Record<string, unknown>)
          ? (sms.body as Record<string, unknown>).detail
          : undefined,
    });
  }

  return NextResponse.json({
    ok: false,
    channel: "none",
    sms: sms,
    mail: mail,
  });
}
