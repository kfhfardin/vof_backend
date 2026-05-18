/**
 * Moss-powered semantic search over the firm's brain.
 *
 * Two operations behind one route:
 *   POST { op: "seed" }   → indexes the firm's precedent set into Moss
 *   POST { op: "query", q, topK? } → semantic search, returns matches
 *
 * Moss retrieval runs locally in Node after loadIndex() — sub-10ms once warm.
 */

import { NextRequest, NextResponse } from "next/server";

export const runtime = "nodejs";

// Lazy-imported so a missing/bad key doesn't crash the whole API surface.
async function getClient() {
  const id = process.env.MOSS_PROJECT_ID;
  const key = process.env.MOSS_PROJECT_KEY;
  if (!id || !key) {
    throw new Error(
      "MOSS_PROJECT_ID + MOSS_PROJECT_KEY required (sign up at https://portal.moss.dev)",
    );
  }
  const mod = (await import("@moss-dev/moss")) as unknown as {
    MossClient: new (id: string, key: string) => MossClient;
  };
  return new mod.MossClient(id, key);
}

type MossClient = {
  createIndex: (
    name: string,
    docs: { id: string; text: string; metadata?: Record<string, unknown> }[],
    opts?: { modelId?: string },
  ) => Promise<unknown>;
  loadIndex: (name: string) => Promise<unknown>;
  query: (
    name: string,
    q: string,
    opts?: { topK?: number },
  ) => Promise<{ docs: Array<{ id: string; score: number; text: string; metadata?: Record<string, unknown> }> }>;
};

const INDEX = process.env.MOSS_INDEX || "reyes-brain";

const FIRM_BRAIN_SEED = [
  {
    id: "p_t_nguyen_2025",
    text:
      "T. Nguyen (2025). Rear-end collision on the 405 in San Mateo. ER visit, soft tissue neck/back. Carrier: State Farm. Settled pre-suit at $52,000 in 7 months. No prior injury, clean liability — adjuster (Janet S.) opened claim within 48 hours.",
    metadata: { client: "T. Nguyen", year: 2025, mechanism: "rear_end", carrier: "State Farm", amount_usd: 52000, months_to_settle: 7, suit_filed: false },
  },
  {
    id: "p_d_alvarez_2025",
    text:
      "D. Alvarez (2025). Rear-end on 880 N. ER visit plus 4 PT visits. Carrier: State Farm. Soft tissue, no surgery. Settled pre-suit at $41,500 in 5 months. Clean prior history.",
    metadata: { client: "D. Alvarez", year: 2025, mechanism: "rear_end", carrier: "State Farm", amount_usd: 41500, months_to_settle: 5, suit_filed: false },
  },
  {
    id: "p_s_park_2024",
    text:
      "S. Park (2024). Rear-end on the 405 in West LA. ER, MRI showing disc bulge L4-L5, lumbar injection completed. Carrier: State Farm. Filed suit, settled at $78,000 in 11 months. Prior back tweak from gym (2021) — disclosed early, did not affect causation.",
    metadata: { client: "S. Park", year: 2024, mechanism: "rear_end", carrier: "State Farm", amount_usd: 78000, months_to_settle: 11, suit_filed: true },
  },
  {
    id: "p_k_liu_2024",
    text:
      "K. Liu (2024). Rear-end on the Bay Bridge approach. No ER, only PT (12 sessions). Carrier: State Farm. Settled pre-suit at $22,000 in 3 months. No imaging, no prior injuries.",
    metadata: { client: "K. Liu", year: 2024, mechanism: "rear_end", carrier: "State Farm", amount_usd: 22000, months_to_settle: 3, suit_filed: false },
  },
  {
    id: "p_a_chen_2025",
    text:
      "A. Chen (2025). Motorcycle crash on PCH near Pacifica. Hospital 4 nights, scheduled hip surgery. Pre-existing knee strain complicates causation. Carrier: GEICO. Currently in records collection, expected value $120K-$220K.",
    metadata: { client: "A. Chen", year: 2025, mechanism: "motorcycle", carrier: "GEICO", expected_value_min: 120000, expected_value_max: 220000, status: "open" },
  },
  {
    id: "p_r_kim_2025",
    text:
      "R. Kim (2025). Pedestrian hit-and-run at Sloat crosswalk. CHP recovered plate. Broken tibia, surgery completed. UM/UIM coverage. Currently awaiting CHP report. Expected value $60K-$110K.",
    metadata: { client: "R. Kim", year: 2025, mechanism: "pedestrian", carrier: "UM/UIM", expected_value_min: 60000, expected_value_max: 110000, status: "open" },
  },
  {
    id: "p_t_garcia_2025",
    text:
      "T. García (2025). Rear-end on Folsom St in SF. PT in progress. Carrier: Allstate. Soft tissue, no imaging yet. Expected value $25K-$45K.",
    metadata: { client: "T. García", year: 2025, mechanism: "rear_end", carrier: "Allstate", expected_value_min: 25000, expected_value_max: 45000, status: "open" },
  },
  {
    id: "playbook_state_farm_priors",
    text:
      "PLAYBOOK · State Farm adjusters frequently use prior injury disclosures to argue pre-existing condition and reduce settlement. Mitigation: probe scope of any prior on the intake call (imaging? PT? claim filed?) before the adjuster does. Document that the prior fully resolved.",
    metadata: { type: "playbook", carrier: "State Farm" },
  },
  {
    id: "playbook_geico_motorcycle",
    text:
      "PLAYBOOK · GEICO settles motorcycle cases with clear documentation in ~9 months pre-suit when surgeries are completed and police report is clean. Push for treatment completion before opening negotiation.",
    metadata: { type: "playbook", carrier: "GEICO" },
  },
  {
    id: "playbook_ca_statute",
    text:
      "PLAYBOOK · California personal injury statute of limitations is 2 years from the date of incident under CCP §335.1. Send retainer and HIPAA authorization within 7 days of intake to lock representation before carrier outreach.",
    metadata: { type: "playbook", jurisdiction: "California" },
  },
];

export async function POST(req: NextRequest) {
  let body: Record<string, unknown> = {};
  try {
    body = await req.json();
  } catch {
    body = {};
  }
  const op = (body.op as string) || "query";

  let client: MossClient;
  try {
    client = await getClient();
  } catch (e) {
    return NextResponse.json(
      { ok: false, error: String((e as Error).message || e) },
      { status: 200 },
    );
  }

  if (op === "seed") {
    try {
      await client.createIndex(INDEX, FIRM_BRAIN_SEED, { modelId: "moss-minilm" });
      await client.loadIndex(INDEX);
      return NextResponse.json({
        ok: true,
        index: INDEX,
        docs: FIRM_BRAIN_SEED.length,
      });
    } catch (e) {
      return NextResponse.json(
        { ok: false, error: String((e as Error).message || e), index: INDEX },
        { status: 200 },
      );
    }
  }

  // op === "query"
  const q = (body.q as string) || (body.query as string) || "";
  const topK = (body.topK as number) || 4;
  if (!q.trim()) {
    return NextResponse.json({ ok: false, error: "q is required" }, { status: 400 });
  }

  const t0 = Date.now();
  try {
    try {
      await client.loadIndex(INDEX);
    } catch {
      // Index may not exist yet — try to seed it on the fly, then retry.
      await client.createIndex(INDEX, FIRM_BRAIN_SEED, { modelId: "moss-minilm" });
      await client.loadIndex(INDEX);
    }
    const results = await client.query(INDEX, q.trim(), { topK });
    const elapsed = Date.now() - t0;
    return NextResponse.json({
      ok: true,
      elapsedMs: elapsed,
      index: INDEX,
      q: q.trim(),
      results: results.docs.map((d) => ({
        id: d.id,
        score: d.score,
        text: d.text,
        metadata: d.metadata ?? null,
      })),
    });
  } catch (e) {
    return NextResponse.json(
      { ok: false, error: String((e as Error).message || e), index: INDEX },
      { status: 200 },
    );
  }
}
