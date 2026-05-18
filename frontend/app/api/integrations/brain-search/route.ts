import { NextRequest, NextResponse } from "next/server";

export const runtime = "nodejs";

const SUPERMEMORY_BASE = "https://api.supermemory.ai/v3";

type SearchPayload = {
  query: string;
  containerTags?: string[];
};

type Memory = {
  id?: string;
  content?: string;
  text?: string;
  title?: string;
  summary?: string;
  metadata?: Record<string, unknown>;
  createdAt?: string;
  created_at?: string;
  score?: number;
};

function extractMemories(raw: unknown): Memory[] {
  if (!raw || typeof raw !== "object") return [];
  const obj = raw as Record<string, unknown>;

  // Try common envelope shapes
  const candidates: unknown[] = [
    obj.results,
    obj.documents,
    obj.memories,
    obj.data,
    obj.hits,
    obj.matches,
  ];

  for (const c of candidates) {
    if (Array.isArray(c)) return c as Memory[];
  }

  // Fallback: response itself is an array
  if (Array.isArray(raw)) return raw as Memory[];

  return [];
}

export async function POST(req: NextRequest) {
  const apiKey = process.env.SUPERMEMORY_API_KEY;
  if (!apiKey) {
    return NextResponse.json(
      { ok: false, error: "SUPERMEMORY_API_KEY missing" },
      { status: 500 },
    );
  }

  let payload: SearchPayload;
  try {
    payload = (await req.json()) as SearchPayload;
  } catch {
    return NextResponse.json(
      { ok: false, error: "invalid JSON body" },
      { status: 400 },
    );
  }

  const query = (payload?.query || "").trim();
  if (!query) {
    return NextResponse.json(
      { ok: false, error: "query is required" },
      { status: 400 },
    );
  }

  const body = {
    q: query,
    containerTags: payload.containerTags,
    limit: 8,
  };

  let upstream: Response;
  try {
    upstream = await fetch(`${SUPERMEMORY_BASE}/search`, {
      method: "POST",
      headers: {
        Authorization: `Bearer ${apiKey}`,
        "Content-Type": "application/json",
        Accept: "application/json",
      },
      body: JSON.stringify(body),
      cache: "no-store",
    });
  } catch (err) {
    return NextResponse.json(
      {
        ok: false,
        error: "network error calling Supermemory",
        detail: err instanceof Error ? err.message : String(err),
      },
      { status: 502 },
    );
  }

  const text = await upstream.text();
  let parsed: unknown = null;
  try {
    parsed = JSON.parse(text);
  } catch {
    parsed = text;
  }

  if (!upstream.ok) {
    return NextResponse.json(
      {
        ok: false,
        status: upstream.status,
        error: "supermemory error",
        body: parsed,
      },
      { status: upstream.status },
    );
  }

  const memories = extractMemories(parsed);

  return NextResponse.json({
    ok: true,
    count: memories.length,
    memories,
    raw: parsed,
  });
}
