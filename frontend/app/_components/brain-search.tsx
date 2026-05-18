"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { SectionLabel } from "./ui";

type Chunk = { content?: string; text?: string };

type Memory = {
  id?: string;
  documentId?: string;
  content?: string;
  text?: string;
  title?: string;
  summary?: string;
  chunks?: Chunk[];
  metadata?: Record<string, unknown>;
  createdAt?: string;
  created_at?: string;
  score?: number;
};

type ApiResponse = {
  ok: boolean;
  count?: number;
  memories?: Memory[];
  error?: string;
};

function truncate(s: string, n = 140) {
  if (!s) return "";
  return s.length > n ? s.slice(0, n - 1).trimEnd() + "…" : s;
}

function pickContent(m: Memory): string {
  // Supermemory v3 returns chunks[].content with the matched snippet
  if (Array.isArray(m.chunks) && m.chunks.length > 0) {
    const c = m.chunks
      .map((ch) => ch?.content || ch?.text || "")
      .filter(Boolean)
      .join(" ");
    if (c) return c;
  }
  return (
    (typeof m.content === "string" && m.content) ||
    (typeof m.text === "string" && m.text) ||
    (typeof m.summary === "string" && m.summary) ||
    (typeof m.title === "string" && m.title) ||
    ""
  );
}

function pickCreatedAt(m: Memory): string | undefined {
  return m.createdAt || m.created_at;
}

function timeAgo(iso?: string): string {
  if (!iso) return "";
  const t = Date.parse(iso);
  if (Number.isNaN(t)) return "";
  const diff = Date.now() - t;
  const sec = Math.max(0, Math.floor(diff / 1000));
  if (sec < 60) return `${sec}s ago`;
  const min = Math.floor(sec / 60);
  if (min < 60) return `${min}m ago`;
  const hr = Math.floor(min / 60);
  if (hr < 24) return `${hr}h ago`;
  const d = Math.floor(hr / 24);
  if (d < 30) return `${d}d ago`;
  const mo = Math.floor(d / 30);
  if (mo < 12) return `${mo}mo ago`;
  const yr = Math.floor(d / 365);
  return `${yr}y ago`;
}

function metaString(m: Memory, key: string): string | undefined {
  const md = m.metadata;
  if (!md || typeof md !== "object") return undefined;
  const v = (md as Record<string, unknown>)[key];
  return typeof v === "string" ? v : undefined;
}

export default function BrainSearch({
  caseSlug,
  clientName,
}: {
  caseSlug: string;
  clientName: string;
}) {
  const [state, setState] = useState<
    | { kind: "loading" }
    | { kind: "ok"; memories: Memory[] }
    | { kind: "error"; message: string }
  >({ kind: "loading" });

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const r = await fetch("/api/integrations/brain-search", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            query: clientName,
            containerTags: [caseSlug],
          }),
        });
        const data = (await r.json()) as ApiResponse;
        if (cancelled) return;
        if (!r.ok || !data.ok) {
          setState({
            kind: "error",
            message: data.error || `HTTP ${r.status}`,
          });
          return;
        }
        setState({ kind: "ok", memories: data.memories || [] });
      } catch (err) {
        if (cancelled) return;
        setState({
          kind: "error",
          message: err instanceof Error ? err.message : "network error",
        });
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [caseSlug, clientName]);

  return (
    <div className="rounded-2xl glass text-white">
      <div className="px-5 py-4 border-b border-line flex items-center justify-between">
        <SectionLabel>Brain · matched memories</SectionLabel>
        {state.kind === "ok" && state.memories.length > 0 && (
          <span className="text-[11px] text-muted tnum">
            {state.memories.length}
          </span>
        )}
      </div>

      {state.kind === "loading" && (
        <div className="px-5 py-5 text-[12px] text-muted">
          Searching the brain…
        </div>
      )}

      {state.kind === "error" && (
        <div className="px-5 py-5 text-[12px] text-warn">
          Couldn&apos;t reach the brain · {state.message}
        </div>
      )}

      {state.kind === "ok" && state.memories.length === 0 && (
        <div className="px-5 py-5 text-[12px] text-muted leading-snug">
          No memories yet — accept a case to see them here.{" "}
          <Link href="/inbox" className="text-white hover:underline">
            Open inbox →
          </Link>
        </div>
      )}

      {state.kind === "ok" && state.memories.length > 0 && (
        <div className="divide-y divide-line">
          {state.memories.map((m, i) => {
            const content = pickContent(m);
            const caller = metaString(m, "caller");
            const caseType = metaString(m, "case_type");
            const when = timeAgo(pickCreatedAt(m));
            return (
              <div
                key={m.id || m.documentId || i}
                className="px-5 py-4 glass-inset first:rounded-none last:rounded-b-2xl"
              >
                <div className="text-[13px] leading-snug text-white">
                  {truncate(content) || (
                    <span className="text-muted italic">No content</span>
                  )}
                </div>
                <div className="mt-2 flex items-center justify-between gap-3 text-[11px]">
                  <div className="flex items-center gap-2 text-muted">
                    {caller && <span className="mono">{caller}</span>}
                    {caller && caseType && (
                      <span className="text-soft">·</span>
                    )}
                    {caseType && <span>{caseType}</span>}
                  </div>
                  {when && (
                    <span className="text-muted tnum text-[11px]">{when}</span>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
