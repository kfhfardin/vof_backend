import { NextRequest, NextResponse } from "next/server";

export const runtime = "nodejs";

const SUPERMEMORY_BASE = "https://api.supermemory.ai";

type DeclinePayload = {
  intakeId: string;
  caller: string;
  caseType: string;
  carrier?: string | null;
  valueRange: string;
  statute?: string | null;
  summary: string;
  reason?: string;
  transcript?: string;
};

async function writeDeclineToSupermemory(p: DeclinePayload) {
  const key = process.env.SUPERMEMORY_API_KEY;
  if (!key) throw new Error("SUPERMEMORY_API_KEY not set");

  const content = [
    `Case declined: ${p.caller}.`,
    `Mechanism: ${p.caseType}.`,
    p.carrier ? `Carrier: ${p.carrier}.` : "",
    `Estimated value: ${p.valueRange}.`,
    p.statute ? `Statute clock: ${p.statute}.` : "",
    "",
    `Decline reason: ${p.reason ?? "Outside firm's case acceptance criteria (low value / weak liability / outside practice area)."}`,
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
      containerTags: ["reyes-associates", `intake:${p.intakeId}`, "declined"],
      metadata: {
        intake_id: p.intakeId,
        caller: p.caller,
        case_type: p.caseType,
        carrier: p.carrier ?? "",
        value_range: p.valueRange,
        outcome: "declined",
        declined_at: new Date().toISOString(),
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

export async function POST(req: NextRequest) {
  const payload = (await req.json()) as DeclinePayload;
  if (!payload?.intakeId || !payload?.caller) {
    return NextResponse.json(
      { error: "intakeId and caller are required" },
      { status: 400 },
    );
  }

  const [supermemory] = await Promise.allSettled([
    writeDeclineToSupermemory(payload),
  ]);

  return NextResponse.json({
    supermemory:
      supermemory.status === "fulfilled"
        ? supermemory.value
        : { ok: false, error: String(supermemory.reason) },
  });
}
