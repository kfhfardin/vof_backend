"use client";

import { useState } from "react";

type Intake = {
  id: string;
  caller: string;
  caseType: string;
  carrier: string | null;
  valueRange: string;
  statute: { date: string; label: string } | null;
};

export function SendToMargarita({ intake }: { intake: Intake }) {
  const [state, setState] = useState<"idle" | "sending" | "done" | "error">(
    "idle",
  );
  const [info, setInfo] = useState<{ channel?: string; to?: string } | null>(
    null,
  );

  const send = async (e: React.MouseEvent) => {
    if (state === "sending") return;
    // Open the partner preview in a new tab immediately (so demo always shows it).
    window.open(`/approve/${intake.id}`, "_blank", "noopener,noreferrer");
    setState("sending");
    try {
      const r = await fetch("/api/integrations/escalate", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          intakeId: intake.id,
          caller: intake.caller,
          caseType: intake.caseType,
          carrier: intake.carrier,
          valueRange: intake.valueRange,
          statute: intake.statute?.label ?? null,
        }),
      });
      const data = await r.json();
      if (data.ok) {
        setInfo({ channel: data.channel, to: data.to });
        setState("done");
      } else {
        setState("error");
      }
    } catch {
      setState("error");
    }
    setTimeout(() => {
      setState("idle");
      setInfo(null);
    }, 6000);
    e?.preventDefault?.();
  };

  return (
    <div className="flex items-center gap-3">
      {state === "done" && info && (
        <span className="text-[11px] text-live">
          ✓ Sent to {info.to} via {info.channel}
        </span>
      )}
      {state === "error" && (
        <span className="text-[11px] text-warn">✗ Delivery failed</span>
      )}
      <button
        onClick={send}
        disabled={state === "sending"}
        className="inline-flex items-center justify-center gap-2 px-3 py-1.5 rounded-md text-[13px] font-medium transition-colors bg-white text-black hover:bg-white/90 disabled:opacity-60"
      >
        {state === "sending" ? "Sending…" : "Send to Margarita ↗"}
      </button>
    </div>
  );
}
