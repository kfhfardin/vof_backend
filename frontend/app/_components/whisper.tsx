"use client";

import { useState } from "react";
import { Button, SectionLabel } from "./ui";

type Suggestion = { id: string; reason: string; text: string };

type WhisperResult =
  | { ok: true; to: string; sent: string; channel?: string }
  | { ok: false; error: string };

export function WhisperPanel({
  agentName,
  suggestions,
  intakeId,
}: {
  agentName: string;
  suggestions: Suggestion[];
  intakeId?: string;
}) {
  const [custom, setCustom] = useState("");
  const [sending, setSending] = useState(false);
  const [result, setResult] = useState<WhisperResult | null>(null);

  const send = async (text: string, source: "auto" | "custom") => {
    if (!text.trim()) return;
    setSending(true);
    setResult(null);
    try {
      const r = await fetch("/api/integrations/whisper", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          intakeId: intakeId ?? "",
          agentName,
          text,
          source,
        }),
      });
      const data = await r.json();
      if (data.ok) {
        setResult({
          ok: true,
          to: data.to,
          sent: text.trim(),
          channel: data.channel,
        });
        if (source === "custom") setCustom("");
      } else {
        setResult({
          ok: false,
          error:
            (data.error as string) ||
            (typeof data.body === "string"
              ? data.body
              : JSON.stringify(data.body)?.slice(0, 200)) ||
            `status ${data.status ?? "?"}`,
        });
      }
    } catch (e) {
      setResult({ ok: false, error: String(e) });
    } finally {
      setSending(false);
      setTimeout(() => setResult(null), 6000);
    }
  };

  return (
    <div className="px-5 py-5">
      <div className="flex items-baseline justify-between">
        <SectionLabel>Whisper {agentName}</SectionLabel>
        <span className="text-[11px] text-muted">via SMS</span>
      </div>

      <p className="mt-1.5 text-[11.5px] text-muted leading-snug">
        Auto-generated from the call + firm history. Tap one, or write your own.
      </p>

      <ul className="mt-3 space-y-2">
        {suggestions.map((s) => (
          <li key={s.id} className="rounded-md glass-inset p-3">
            <div className="text-[10.5px] text-muted uppercase tracking-[0.06em]">
              {s.reason}
            </div>
            <p className="mt-1 text-[12.5px] leading-snug italic">
              &ldquo;{s.text}&rdquo;
            </p>
            <button
              onClick={() => send(s.text, "auto")}
              disabled={sending}
              className="mt-2 text-[11px] font-medium text-white hover:underline disabled:opacity-50"
            >
              {sending ? "Sending…" : `Send to ${agentName} →`}
            </button>
          </li>
        ))}
      </ul>

      <div className="mt-4">
        <div className="text-[11px] text-muted mb-1.5">Or write your own</div>
        <textarea
          value={custom}
          onChange={(e) => setCustom(e.target.value)}
          placeholder={`Type a whisper to ${agentName}…`}
          rows={3}
          className="w-full text-[13px] leading-snug rounded-md glass-inset p-3 outline-none text-white placeholder:text-soft resize-none focus:ring-2 focus:ring-white/20"
        />
        <Button
          variant="primary"
          onClick={() => send(custom, "custom")}
          disabled={sending || !custom.trim()}
          className="mt-2 w-full"
        >
          {sending ? "Sending SMS…" : `Send to ${agentName}`}
        </Button>
      </div>

      {result?.ok && (
        <div className="mt-3 text-[11.5px] text-live leading-snug">
          ✓ Delivered to {result.to}
          {result.channel && (
            <span className="text-muted"> · via {result.channel}</span>
          )}
          <div className="text-muted italic mt-0.5">&ldquo;{result.sent}&rdquo;</div>
        </div>
      )}
      {result && !result.ok && (
        <div className="mt-3 text-[11.5px] text-warn leading-snug">
          ✗ Failed: {result.error}</div>
      )}
    </div>
  );
}
