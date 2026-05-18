"use client";

import { useState } from "react";

type Intake = {
  id: string;
  caller: string;
  caseType: string;
  carrier: string | null;
  valueRange: string;
  statute: { date: string; label: string } | null;
  summary: string;
};

type AcceptResult = {
  supermemory: { ok: boolean; status?: number; body?: unknown; error?: string };
  email: { ok: boolean; status?: number; body?: unknown; to?: string; error?: string };
  browserUse: {
    ok: boolean;
    status?: number;
    body?: unknown;
    taskId?: string;
    statusLabel?: string;
    error?: string;
  };
};

type DeclineResult = {
  supermemory: { ok: boolean; status?: number; body?: unknown; error?: string };
};

type MoreInfoResult = {
  email: { ok: boolean; status?: number; body?: unknown; to?: string; error?: string };
};

type Mode = "accept" | "more-info" | "decline";
type Phase = "idle" | "sending" | "done" | "error";

export function AcceptActions({ intake }: { intake: Intake }) {
  const [mode, setMode] = useState<Mode | null>(null);
  const [phase, setPhase] = useState<Phase>("idle");
  const [acceptResult, setAcceptResult] = useState<AcceptResult | null>(null);
  const [declineResult, setDeclineResult] = useState<DeclineResult | null>(null);
  const [moreInfoResult, setMoreInfoResult] = useState<MoreInfoResult | null>(null);

  const basePayload = {
    intakeId: intake.id,
    caller: intake.caller,
    caseType: intake.caseType,
    carrier: intake.carrier,
    valueRange: intake.valueRange,
    statute: intake.statute?.label ?? null,
    summary: intake.summary,
  };

  const sending = phase === "sending";
  const accept = async () => {
    setMode("accept");
    setPhase("sending");
    try {
      const r = await fetch("/api/integrations/accept-case", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(basePayload),
      });
      const data = (await r.json()) as AcceptResult;
      setAcceptResult(data);
      setPhase(
        data.supermemory.ok || data.email.ok || data.browserUse.ok
          ? "done"
          : "error",
      );
    } catch (err) {
      setAcceptResult({
        supermemory: { ok: false, error: String(err) },
        email: { ok: false, error: String(err) },
        browserUse: { ok: false, error: String(err) },
      });
      setPhase("error");
    }
  };

  const needMoreInfo = async () => {
    setMode("more-info");
    setPhase("sending");
    try {
      const r = await fetch("/api/integrations/need-more-info", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(basePayload),
      });
      const data = (await r.json()) as MoreInfoResult;
      setMoreInfoResult(data);
      setPhase(data.email.ok ? "done" : "error");
    } catch (err) {
      setMoreInfoResult({ email: { ok: false, error: String(err) } });
      setPhase("error");
    }
  };

  const decline = async () => {
    setMode("decline");
    setPhase("sending");
    try {
      const r = await fetch("/api/integrations/decline-case", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(basePayload),
      });
      const data = (await r.json()) as DeclineResult;
      setDeclineResult(data);
      setPhase(data.supermemory.ok ? "done" : "error");
    } catch (err) {
      setDeclineResult({ supermemory: { ok: false, error: String(err) } });
      setPhase("error");
    }
  };

  const acceptDone = mode === "accept" && phase === "done";
  const acceptSending = mode === "accept" && sending;
  const acceptError = mode === "accept" && phase === "error";

  const moreInfoDone = mode === "more-info" && phase === "done";
  const moreInfoSending = mode === "more-info" && sending;
  const moreInfoError = mode === "more-info" && phase === "error";

  const declineDone = mode === "decline" && phase === "done";
  const declineSending = mode === "decline" && sending;
  const declineError = mode === "decline" && phase === "error";

  // Lock all buttons whenever any flow is in-flight or terminal-done on accept
  const anyLock = sending || acceptDone;

  return (
    <div className="space-y-3">
      <button
        onClick={accept}
        disabled={anyLock}
        className={`w-full px-5 py-4 rounded-xl text-left transition active:scale-[0.99] ${
          acceptDone
            ? "bg-live text-white"
            : "bg-white text-black hover:bg-white/90 disabled:opacity-60"
        }`}
      >
        <div className="text-[16px] font-medium">
          {!acceptSending && !acceptDone && !acceptError && "Accept"}
          {acceptSending && "Accepting…"}
          {acceptDone && "✓ Accepted"}
          {acceptError && "Accepted with errors"}
        </div>
        <div
          className={`text-[12px] mt-0.5 ${
            acceptDone ? "text-white/80" : "text-black/60"
          }`}
        >
          {!acceptSending && !acceptDone && !acceptError &&
            "Writes Supermemory + AgentMail engagement letter + Browser Use matter"}
          {acceptSending && "Firing Supermemory + AgentMail + Browser Use…"}
          {acceptDone && "Brain updated. Letter sent. Matter task queued."}
          {acceptError && "Some integrations failed — see status below"}
        </div>
      </button>

      <button
        onClick={needMoreInfo}
        disabled={anyLock || moreInfoDone}
        className={`w-full px-5 py-4 rounded-xl text-left backdrop-blur-md transition active:scale-[0.99] ${
          moreInfoDone
            ? "bg-live/80 text-white"
            : "bg-white/10 text-white hover:bg-white/14 disabled:opacity-60"
        }`}
      >
        <div className="text-[16px] font-medium">
          {!moreInfoSending && !moreInfoDone && !moreInfoError && "Need more info"}
          {moreInfoSending && "Sending follow-up…"}
          {moreInfoDone && "✓ Follow-up sent"}
          {moreInfoError && "Follow-up failed"}
        </div>
        <div className="text-[12px] mt-0.5 text-white/60">
          {!moreInfoSending && !moreInfoDone && !moreInfoError &&
            "Sends AgentMail follow-up with photo/ER request"}
          {moreInfoSending && "Composing email via AgentMail…"}
          {moreInfoDone && "Client asked for ER papers, photos, witnesses."}
          {moreInfoError && "AgentMail rejected the send — see below"}
        </div>
      </button>

      <button
        onClick={decline}
        disabled={anyLock || declineDone}
        className={`w-full px-5 py-4 rounded-xl text-left transition active:scale-[0.99] ${
          declineDone
            ? "bg-live/80 text-white"
            : "text-white/60 hover:text-white hover:bg-white/8 disabled:opacity-60"
        }`}
      >
        <div className="text-[16px] font-medium">
          {!declineSending && !declineDone && !declineError && "Decline"}
          {declineSending && "Logging decline…"}
          {declineDone && "✓ Declined"}
          {declineError && "Decline log failed"}
        </div>
        <div className={`text-[12px] mt-0.5 ${declineDone ? "text-white/80" : ""}`}>
          {!declineSending && !declineDone && !declineError &&
            "Logs decline + reason to Supermemory"}
          {declineSending && "Writing to Supermemory…"}
          {declineDone && "Reason filed. Brain knows why we said no."}
          {declineError && "Supermemory rejected the write — see below"}
        </div>
      </button>

      {mode === "accept" && (phase === "done" || phase === "error") && acceptResult && (
        <div className="mt-2 space-y-1.5 text-[12px]">
          <StatusRow
            label="Supermemory"
            ok={acceptResult.supermemory.ok}
            detail={
              acceptResult.supermemory.ok
                ? "Memory written to brain"
                : acceptResult.supermemory.error ||
                  `status ${acceptResult.supermemory.status ?? "?"}`
            }
          />
          <StatusRow
            label="AgentMail"
            ok={acceptResult.email.ok}
            detail={
              acceptResult.email.ok
                ? `Engagement letter sent to ${acceptResult.email.to ?? "client"}`
                : acceptResult.email.error ||
                  `status ${acceptResult.email.status ?? "?"}`
            }
          />
          <StatusRow
            label="Browser Use"
            ok={acceptResult.browserUse.ok}
            detail={
              acceptResult.browserUse.ok
                ? `Matter task ${acceptResult.browserUse.statusLabel ?? "queued"}${
                    acceptResult.browserUse.taskId
                      ? ` · ${acceptResult.browserUse.taskId.slice(0, 12)}`
                      : ""
                  }`
                : acceptResult.browserUse.error ||
                  `status ${acceptResult.browserUse.status ?? "?"}`
            }
          />
        </div>
      )}

      {mode === "more-info" && (phase === "done" || phase === "error") && moreInfoResult && (
        <div className="mt-2 space-y-1.5 text-[12px]">
          <StatusRow
            label="AgentMail"
            ok={moreInfoResult.email.ok}
            detail={
              moreInfoResult.email.ok
                ? `Follow-up sent to ${moreInfoResult.email.to ?? "client"}`
                : moreInfoResult.email.error ||
                  `status ${moreInfoResult.email.status ?? "?"}`
            }
          />
        </div>
      )}

      {mode === "decline" && (phase === "done" || phase === "error") && declineResult && (
        <div className="mt-2 space-y-1.5 text-[12px]">
          <StatusRow
            label="Supermemory"
            ok={declineResult.supermemory.ok}
            detail={
              declineResult.supermemory.ok
                ? "Decline reason logged"
                : declineResult.supermemory.error ||
                  `status ${declineResult.supermemory.status ?? "?"}`
            }
          />
        </div>
      )}
    </div>
  );
}

function StatusRow({
  label,
  ok,
  detail,
}: {
  label: string;
  ok: boolean;
  detail: string;
}) {
  return (
    <div className="flex items-center justify-between px-3 py-2 rounded-md bg-black/30">
      <div className="flex items-center gap-2">
        <span className={ok ? "text-live" : "text-warn"}>{ok ? "✓" : "!"}</span>
        <span className="text-white/80">{label}</span>
      </div>
      <span className="text-white/50 text-[11px] truncate ml-3">{detail}</span>
    </div>
  );
}
